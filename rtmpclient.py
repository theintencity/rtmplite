# Copyright (c) 2009, Mamta Singh. All rights reserved. see README for details.

# WARNING:This is currently incomplete. Especially the quality is poor, and HTTP is not implemented.

'''
This is a simple implementation of a Flash RTMP client to perform remote copy similar to secure copy (scp) application.
It shares some classes with the rtmp.py module, and is based on the server implementation of that module.

The client takes two arguments, src and dest, for source and destination resources. It copies the stream from src to dest. 
The resource can be identified using an URL with "rtmp", "http" or "file" scheme. If no scheme is given, it is assumed to be
a local file with a "file://" prefix. An "rtmp" resource URL is of the form "rtmp://server/app?id=streamname" which represents
an RTMP connection to server using NetConnection URL "rtmp://server/app" followed by a new NetStream (either published or played)
with name "streamname". An "http" resource URL is of the form "http://server/something/file1.flv" and represents a web accessible
FLV file. A "file" resource URL is of the form "file://somedir/file2.flv" representing local relative file "somedir/file2.flv" or
"file:///top-dir/file3.flv" representing local absolute file path "/top-dir/file3.flv". When reading a local or web resource, the
reading stops at the end of the file. When reading a RTMP resource, the reading stops either on connection termination by the 
server or <ctrl-C> on command line or when no stream data is received for 10 seconds. You can change this timeout using the "timeout"
header in the "rtmp" URL, e.g., "rtmp://server/app?id=streamname&timeout=20".

Most common use of rtmpclient.py is to record a real-time stream or stream out a file to the server.

Case 1: record a real-time stream to a local file.
$ python rtmpclient.py rtmp://server/app?id=user1 file1.flv

Case 2: stream out a local file to a real-time server stream.
$ python rtmpclient.py file2.flv rtmp://server/app?id=user2

The other use cases of the software such as downloading an http resource to local file or storing real-time stream to an http
resource, are straight forward to implement, either not dependent on RTMP or use one of the above cases.

This module can be tested using the same testClient you used for testing the rtmp.py server module. In particular, when the
server is running, you can run an instance of testClient to publish a stream named user1, and run rtmpclient.py to record
that stream into file1.flv. Then, for second case, you can stream out file1.flv using rtmpclient.py and have testClient play
that stream.

'''

import os, sys, traceback, time, urlparse, socket, multitask, amf
from rtmp import Protocol, Message, Command, ConnectionClosed, Stream, FLV

_debug = False

_usage = '''usage: python rtmpclient.py [-d] src dest
  -d: verbose mode prints trace statements
  src and dest: are resource URLs with "rtmp", "http" or "file" scheme. 
  For "rtmp" use a header named "id" to specify the stream name.
  This software depends on Python 2.5 (won't work with 2.4, 2.6 or 3.0)'''

class Client(Protocol):
    '''Internal class to interface with the RTMP parser.'''
    def __init__(self, sock):
        Protocol.__init__(self, sock)
        self.streams, self.objectEncoding, self._nextCallId = {}, 0.0, 1
        self.queue = multitask.SmartQueue() # receive queue used by various commands
        
    def parse(self):
        try: yield self.parseMessages()   # parse messages
        except ConnectionClosed: yield self.connectionClosed()
        if _debug: print 'Client.parse connection closed'
        
    def connectionClosed(self):
        '''Called when the client drops the connection'''
        if _debug: 'Client.connectionClosed'
        self.writeMessage(None)
        for stream in self.streams.values():
            yield stream.queue.put(None)
        yield self.queue.put(None)
        self.streams.clear()
            
    def handshake(self):
        '''Implement the client side of the handshake.'''
        yield self.stream.write('\x03' + '\x00'*(Protocol.PING_SIZE))
        data = (yield self.stream.read(Protocol.PING_SIZE + 1)) # bound version and first ping
        yield self.stream.write(data[1:])
        data = (yield self.stream.read(Protocol.PING_SIZE))
        multitask.add(self.parse()); multitask.add(self.write())
        raise StopIteration, self
    
    def send(self, cmd, timeout=None):
        '''Call a method on the server. This is used for connect, createStream, publish, etc.'''
        cmd.id, cmd.type = float(self._nextCallId), (self.objectEncoding == 0.0 and Message.RPC or Message.RPC3)
        callId = self._nextCallId; self._nextCallId += 1
        if _debug: print 'Client.send cmd=', cmd, 'name=', cmd.name, 'args=', cmd.args, ' msg=', cmd.toMessage()
        self.writeMessage(cmd.toMessage())
        try:
            res = yield self.queue.get(timeout=timeout, criteria=lambda x: x is None or x.id == callId)
            result = res if res is not None and res.name == '_result' else None
            fault  = res if res is None or res.name == '_error' else None
            raise StopIteration, (result, fault)
        except multitask.Timeout:
            if _debug: print 'Client.send timed out'
            raise StopIteration, (None, None)
    
    def messageReceived(self, msg):
        # if _debug: print 'Client.messageReceived msg=', msg
        if (msg.type == Message.RPC or msg.type == Message.RPC3) and msg.streamId == 0:
            cmd = Command.fromMessage(msg)
            # if _debug: print 'Client.messageReceived cmd=', cmd
            yield self.queue.put(cmd, timeout=5) # RPC call
        elif msg.streamId in self.streams: # this has to be a message on the stream
            # if _debug: print self.streams[msg.streamId], 'recv'
            stream = self.streams[msg.streamId]
            if not stream.client: stream.client = self 
            yield stream.queue.put(msg) # give it to stream
        else:
            if _debug: print 'ignoring stream message for streamId=', msg.streamId
            
class NetConnection(object):
    '''This is similar to the NetConnection object of ActionScript 3.0'''
    def __init__(self):
        self.client = self.path = None
        self.data = dict(videoCodecs=252.0, audioCodecs=3191.0, flashVer='WIN 10,0,32,18', swfUrl=None, videoFunction=1.0, capabilities=15.0, fpad=False, objectEncoding=0.0)
    
    def connect(self, url, timeout=None):
        if url[:7].lower() != 'rtmp://': raise ValueError('Invalid URL scheme. Must be rtmp://')
        path, ignore, ignore = url[7:].partition('?')
        hostport, ignore, path = path.partition('/')
        host, port = (hostport.split(':', 1) + ['1935'])[:2]
        self.data.update(tcUrl=url, app=path.partition('/')[0])
        
        sock = socket.socket(type=socket.SOCK_STREAM)
        if _debug: print 'connect ', host, port
        try: sock.connect((host, int(port)))
        except: raise StopIteration, False
        if _debug: print 'connect completed'
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1) # make it non-block
        
        self.client = yield Client(sock).handshake()
        result, fault = yield self.client.send(Command(name='connect', cmdData=self.data), timeout=timeout)
        if _debug: print 'connect result=', result, 'fault=', fault
        raise StopIteration, (result is not None)
    
    def close(self):
        if self.client is not None:
            yield self.client.connectionClosed()

class NetStream(object):
    '''This is similar to the NetStream class of ActionScript 3.0'''
    def __init__(self):
        self.nc = self.stream = None
        
    def create(self, nc, timeout=None):
        self.nc = nc
        result, fault = yield self.nc.client.send(Command(name='createStream'), timeout=timeout)
        if _debug: print 'createStream result=', result, 'fault=', fault
        if result:
            stream = self.stream = Stream(self.nc.client)
            stream.queue = multitask.SmartQueue() # replace with SmartQueue
            stream.id = int(result.args[0])
            self.nc.client.streams[stream.id] = stream
            raise StopIteration, self
        else:
            raise StopIteration, None
        
    def publish(self, name, timeout=None):
        self.stream.send(Command(name='publish', args=[name]))
        msg = yield self.stream.recv()
        if _debug: print 'publish result=', msg
        raise StopIteration, True
    
    def play(self, name, timeout=None):
        self.stream.send(Command(name='play', args=[name]))
        msg = yield self.stream.recv()
        if _debug: print 'play response=', msg
        raise StopIteration, True
    
    def close(self):
        self.stream.send(Command(name='closeStream'))
        msg = yield self.stream.recv()
        if _debug: print 'closeStream response=', msg
    
class Result(Exception):
    pass

def parseurl(url):
    return urlparse.urlparse(url, 'file')
    
class Resource(object):
    __slots__ = ['url', 'type', 'mode']
    def __init__(self):
        self.url = self.type = self.mode = None
        self.queue = multitask.SmartQueue()
    def get(self, timeout=None, criteria=None):
        result = yield self.queue.get(timeout=timeout, criteria=criteria)
        raise StopIteration, result
    def put(self, item, timeout=None):
        result = yield self.queue.put(item, timeout=timeout)
        raise StopIteration, result
        
class RTMPReader(Resource):
    def __init__(self):
        Resource.__init__(self)
        self.type, self.mode, self._gen, self.timeout, self.stream = 'rtmp', 'r', None, None, ''
    def open(self, url):
        self.url = url
        options = dict(map(lambda x: tuple(x.split('=', 1)+[''])[:2], url[7:].partition('?')[2].split('&')))
        self.timeout = int(options['timeout']) if 'timeout' in options else None
        self.stream = options['id'] if 'id' in options else None
        if not self.stream: 
            if _debug: print 'No id in url.'
            raise StopIteration, None
        if _debug: print 'RTMPReader.open timeout=', self.timeout, 'stream=', self.stream, 'url=', self.url
        
        self.nc = NetConnection()
        result = yield self.nc.connect(self.url, timeout=self.timeout)
        if _debug: print 'connect result=', result
        if not result: raise StopIteration, None
        if self.stream:
            self.ns = yield NetStream().create(self.nc, timeout=self.timeout)
            result = yield self.ns.play(self.stream, timeout=self.timeout)
            if _debug: print 'play result=', result
            if not result: raise StopIteration, None
        self._gen = self.run()
        multitask.add(self._gen)
        raise StopIteration, self
    
    def close(self):
        if self.nc:
            yield self.nc.close()
        if self._gen is not None:
            self._gen.close()
        
    def run(self):
        try:
            while True:
                msg = yield self.ns.stream.queue.get(timeout=self.timeout, criteria=lambda x: x is None or x.type in (Message.AUDIO, Message.VIDEO))
                if _debug: print 'got msg'
                yield self.queue.put(msg)
        except multitask.Timeout:
            if _debug: print 'RTMPReader.run() timedout'
            yield self.queue.put(False)
            
class RTMPWriter(Resource):
    def __init__(self):
        Resource.__init__(self)
        self.type, self.mode, self.timeout, self.stream = 'rtmp', 'w', None, ''
    def open(self, url):
        self.url = url
        options = dict(map(lambda x: tuple(x.split('=', 1)+[''])[:2], url[7:].partition('?')[2].split('&')))
        self.timeout = int(options['timeout']) if 'timeout' in options else None
        self.stream = options['id'] if 'id' in options else None
        if not self.stream: 
            if _debug: print 'No id in url.'
            raise StopIteration, None
        if _debug: print 'RTMPWriter.open timeout=', self.timeout, 'stream=', self.stream, 'url=', self.url
        
        self.nc = NetConnection()
        result = yield self.nc.connect(self.url, timeout=self.timeout)
        if _debug: print 'connect result=', result
        if not result: raise StopIteration, None
        if self.stream:
            self.ns = yield NetStream().create(self.nc, timeout=self.timeout)
            result = yield self.ns.publish(self.stream, timeout=self.timeout)
            if _debug: print 'publish result=', result
            if not result: raise StopIteration, None
        raise StopIteration, self
    
    def close(self):
        if self.nc:
            yield self.nc.close()
        
    def put(self, item):
        if self.ns is not None:
            self.ns.stream.send(item)
            
class HTTPReader(Resource):
    def open(self, url):
        raise StopIteration, False
        s_url, d_url = parseurl(self.src), parseurl(self.dest) # URL elements
        
    
class HTTPWriter(Resource):
    def open(self, url):
        raise StopIteration, False
    
class FLVReader(Resource):
    def __init__(self):
        Resource.__init__(self)
        self.type, self.mode, self._gen, self.id, self.client = 'file', 'r', None, 1, True
    def open(self, url):
        if _debug: print 'FLVReader.open', url
        self.url = url
        u = urlparse.urlparse(url, 'file')
        self.fp = FLV().open(u.path, 'live')
        if self.fp:
            self._gen = self.fp.reader(self)
            multitask.add(self._gen) 
            raise StopIteration, self
        else: 
            raise StopIteration, None
    def close(self):
        if self.fp:
            self.fp.close()
            self.fp = None
        if self._gen is not None:
            self._gen.close()
    def send(self, msg):
        def sendInternal(self, msg):
            yield self.queue.put(msg)
        if msg.type in (Message.RPC, Message.RPC3):
            cmd = Command.fromMessage(msg)
            if cmd.name == 'onStatus' and len(cmd.args) > 0 and cmd.args[0].get('code', '') == 'NetStream.Play.Stop':
                msg = False # indicates end of file
        multitask.add(sendInternal(self, msg))
    
class FLVWriter(Resource):
    def __init__(self):
        Resource.__init__(self)
        self.type, self.mode = 'file', 'w'
    def open(self, url):
        if _debug: print 'FLVWrite.open', url
        self.url = url
        u = urlparse.urlparse(url, 'file')
        self.fp = FLV().open(u.path, 'record')
        yield
        if self.fp: raise StopIteration, self
        else: raise StopIteration, None
    def close(self):
        if self.fp is not None:
            self.fp.close()
            self.fp = None
        yield
    def put(self, item):
        if self.fp is not None:
            self.fp.write(item)
        yield
    
def open(url, mode='r'):
    '''Open the given resource for read "r" or write "w" in binary mode. Returns an object.'''
    type = 'rtmp' if str(url).startswith('rtmp://') else 'http' if str(url).startswith('http://') else 'file'
    types = {'rtmp-r': RTMPReader, 'rtmp-w': RTMPWriter, 'http-r': HTTPReader, 'http-w': HTTPWriter, 'file-r': FLVReader, 'file-w': FLVWriter }
    r = yield types[type + '-' + mode]().open(url=url)
    raise StopIteration, r
    
def copy(src, dest):
    '''Copy from given src (url str) to dest (url str).'''
    s  = yield open(src, 'r')
    if not s: 
        raise Result, (False, 'Cannot open source %r'%(src))
    
    d = yield open(dest, 'w')
    if not d:
        yield s.close() 
        raise Result, (False, 'Cannot open destination %r'%(dest))
    
    result = (True, 'Completed')
    try:
        while True:
            msg = yield s.get()
            if _debug: print 'copy msg=', msg
            if not msg:
                if _debug: print 'copy exiting as s.get() returned None'
                break
            yield d.put(msg)
    except Result, e:
        result = e
    except KeyboardInterrupt:
        result = (True, 'Keyboard Interrupt')
    yield s.close()
    yield d.close()
    raise Result, result
    
# The main routine to invoke the copy method
if __name__ == '__main__':
    if len(sys.argv) < 3: print _usage; sys.exit(-1)
    _debug = sys.argv[1] == '-d'
    
    try:
        multitask.add(copy(sys.argv[-2], sys.argv[-1]))
        multitask.run()
    except Result, e:
        print 'result', e
    except KeyboardInterrupt:
        if _debug: print 'keyboard interrupt'
