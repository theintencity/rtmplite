# Copyright (c) 2009-2011, Kundan Singh. All rights reserved. see README for details.
# WARNING:This is currently incomplete. Especially the quality is poor, and HTTP is not yet implemented.

'''
This is a simple implementation of a Flash RTMP client to perform remote copy similar to secure copy (scp) application.
It shares some classes with the rtmp.py module, and is based on the server implementation of that module.

The client takes two arguments, src and dest, for source and destination resources. It copies the stream from src to dest resources. 
A resource can be identified using an URL with "rtmp", "http" or "file" scheme. If no scheme is given, it is assumed to be a local file
with a "file://" prefix. An "rtmp" resource URL is of the form "rtmp://server/app?id=streamname" which represents an RTMP connection 
to server using NetConnection URL "rtmp://server/app" followed by a new NetStream (either published or played) with name "streamname". 
An "http" resource URL is of the form "http://server/something/file1.flv" and represents a web accessible FLV file.  When reading a 
local or web resource, the reading stops at the end of the file. When reading a RTMP resource, the reading stops either on connection 
termination by the server or <ctrl-C> on command line or when no stream data is received for 10 seconds. You can change this timeout 
using the "timeout" header in the "rtmp" URL, e.g., "rtmp://server/app?id=streamname&timeout=20".

Most common use of rtmpclient.py is to record a real-time stream or stream out a file to the server.

Case 1: record a real-time stream to a local file.
$ python rtmpclient.py "rtmp://server/app?id=user1" file1.flv

Case 2: stream out a local file to a real-time server stream.
$ python rtmpclient.py file2.flv "rtmp://server/app?id=user2"

The other use cases of the software such as downloading an http resource to local file or storing real-time stream to an http resource, 
are straight forward to implement, either not dependent on RTMP or use one of the above cases.

This module can be tested using the same testClient you used for testing the rtmp.py server module. In particular, when the server is 
running, you can run an instance of testClient to publish a stream named user1, and run rtmpclient.py to record that stream into file1.flv. 
Then, for second case, you can stream out file1.flv using rtmpclient.py and have testClient play that stream.

To understand the code, please see the high level method copy() and open(). Usually you can use the copy method to invoke the copier. If you 
want to work on individual resource objects, use the open method and the returned resource object.
'''

import os, sys, traceback, time, urlparse, socket, multitask
from rtmp import Protocol, Message, Command, ConnectionClosed, Stream, FLV
from amf import Object

_debug = False

#--------------------------------
# RTMP/network related classes
#--------------------------------

class Client(Protocol):
    '''Internal class to interface with the RTMP parser from the rtmp.py module. The other classes such as NetConnection and NetStream use this
    class to do handshake() and send() RPC commands to the server. The send method itself receives the RPC response.'''
    def __init__(self, sock): # similar to the Client class of rtmp.py
        Protocol.__init__(self, sock)
        self.streams, self.objectEncoding, self._nextCallId, self.queue, self.close_queue = {}, 0.0, 1, multitask.SmartQueue(), multitask.Queue()
            
    def handshake(self): # Implement the client side of the handshake. Must be invoked by caller after TCP connection completes.
        yield self.stream.write('\x03' + '\x00'*(Protocol.PING_SIZE)) # send first handshake
        data = (yield self.stream.read(Protocol.PING_SIZE + 1))
        yield self.stream.write(data[1:]) # send second handshake
        data = (yield self.stream.read(Protocol.PING_SIZE))
        multitask.add(self.parse()); multitask.add(self.write()) # launch the reader and writer tasks
        raise StopIteration, self
    
    def parse(self): # started by handshake, to parse incoming messages.
        try: yield self.parseMessages()   # parse messages
        except ConnectionClosed: yield self.connectionClosed()
        
    def connectionClosed(self): # called by base class framework when server drops the TCP connections
        if _debug: print 'Client.connectionClosed'
        yield self.writeMessage(None)
        for stream in self.streams.values(): yield stream.queue.put(None)
        yield self.queue.put(None)
        yield self.close_queue.put(None)
        self.streams.clear()
    
    def send(self, cmd, timeout=None): # Call a RPC method on the server. This is used for connect, createStream, publish, etc. 
        # Returns (result, fault) with either result or fault as valid Command object, and other as None.'''
        cmd.id, cmd.type = float(self._nextCallId), (self.objectEncoding == 0.0 and Message.RPC or Message.RPC3)
        callId = self._nextCallId; self._nextCallId += 1
        if _debug: print 'Client.send cmd=', cmd, 'name=', cmd.name, 'args=', cmd.args, ' msg=', cmd.toMessage()
        yield self.writeMessage(cmd.toMessage())
        try: # wait for response if received within timeout.
            res = yield self.queue.get(timeout=timeout, criteria=lambda x: x is None or x.id == callId)
            result = res if res is not None and res.name == '_result' else None
            fault  = res if res is None or res.name == '_error' else None
            raise StopIteration, (result, fault)
        except multitask.Timeout:
            if _debug: print 'Client.send timed out'
            raise StopIteration, (None, None)
    
    def messageReceived(self, msg): # invoked by base class framework to handle a receive message.
        if (msg.type == Message.RPC or msg.type == Message.RPC3) and msg.streamId == 0:
            cmd = Command.fromMessage(msg)
            yield self.queue.put(cmd, timeout=5) # RPC call, must be processed by application within 5 seconds, or will be discarded.
        elif msg.streamId in self.streams: # this has to be a message on the stream
            stream = self.streams[msg.streamId]
            if not stream.client: stream.client = self 
            yield stream.queue.put(msg) # give it to stream
        elif _debug: print 'ignoring stream message for streamId=', msg.streamId
            
class NetConnection(object):
    '''This is similar to the NetConnection object of ActionScript 3.0, and represents a client-server connection. The application usually
    invokes the connect() method to initiate the connection, create one or more NetStream, and finally close() method to disconnect.'''
    def __init__(self):
        self.client = self.path = None
        self.data = Object(videoCodecs=252.0, audioCodecs=3191.0, flashVer='WIN 10,0,32,18', swfUrl=None, videoFunction=1.0, capabilities=15.0, fpad=False, objectEncoding=0.0)
    
    def connect(self, url, timeout=None, *args): # Generator to connect to the given url, and return True or False.
        if url[:7].lower() != 'rtmp://': raise ValueError('Invalid URL scheme. Must be rtmp://')
        path, ignore, ignore = url[7:].partition('?')
        hostport, ignore, path = path.partition('/')
        host, port = (hostport.split(':', 1) + ['1935'])[:2]
        self.data.tcUrl, self.data.app = url, path
        sock = socket.socket(type=socket.SOCK_STREAM)
        if _debug: print 'NetConnection.connect url=', url, 'host=', host, 'port=', port
        try: sock.connect((host, int(port)))
        except: raise StopIteration, False
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1) # make it non-block
        self.client = yield Client(sock).handshake()
        result, fault = yield self.client.send(Command(name='connect', cmdData=self.data, args=args), timeout=timeout)
        if _debug: print 'NetConnection.connect result=', result, 'fault=', fault
        raise StopIteration, (result is not None)
    
    def close(self): # disconnect the connection with the server
        if self.client is not None: 
            yield self.client.connectionClosed()
            # TODO: for some reason, the socket is not closed with multitask. Need to explicitly close the file descriptor.
            try: os.close(self.client.stream.sock.fileno())
            except: pass # ignore the error
            self.client = None
            

class NetStream(object):
    '''This is similar to the NetStream class of ActionScript 3.0, and represents a client-server media stream for play or publish. The application
    creates a NetStream, first invokes create(), then either publish() or play() but not both, and finally close() to terminate.'''
    def __init__(self):
        self.nc = self.stream = None
        
    def create(self, nc, timeout=None):
        self.nc = nc
        result, fault = yield self.nc.client.send(Command(name='createStream'), timeout=timeout)
        if _debug: print 'createStream result=', result, 'fault=', fault
        if result:
            stream = self.stream = Stream(self.nc.client)
            stream.queue, stream.id = multitask.SmartQueue(), int(result.args[0]) # replace with SmartQueue
            self.nc.client.streams[stream.id] = stream
            raise StopIteration, self
        else: raise StopIteration, None
        
    def publish(self, name, mode='live', timeout=None):
        yield self.send(Command(name='publish', args=[name, mode]))
        msg = yield self.stream.recv()
        if _debug: print 'publish result=', msg
        raise StopIteration, True
    
    def play(self, name, timeout=None):
        yield self.send(Command(name='play', args=[name]))
        msg = yield self.stream.recv()
        if _debug: print 'play response=', msg
        raise StopIteration, True
    
    def close(self):
        yield self.send(Command(name='closeStream'))
        msg = yield self.stream.recv()
        if _debug: print 'closeStream response=', msg

    def send(self, cmd):
        cmd.id, cmd.type = float(self.nc.client._nextCallId), (self.nc.client.objectEncoding == 0.0 and Message.RPC or Message.RPC3)
        self.nc.client._nextCallId += 1
        msg = cmd.toMessage()
        msg.streamId = self.stream.id
        if _debug: print 'Stream.send cmd=', cmd, 'name=', cmd.name, 'args=', cmd.args, ' msg=', msg
        yield self.nc.client.writeMessage(msg)
    
#--------------------------------
# Resources implementation
#--------------------------------

# The implementation uses Resource base class to identify all types of resources. Individual sub-classes such as RTMPReader or FLVWriter
# implement the specific functiosn, e.g., RTMP play and FLV write, respectively. 

class Result(Exception): pass # a result class is used to send result of copy operation from within a nested control flow.

class Resource(object): # base class for different types of resources. Just defines an internal queue to get and put messages.
    __slots__ = ['url', 'type', 'mode']
    def __init__(self): self.url = self.type = self.mode = None; self.queue = multitask.SmartQueue()
    def get(self, timeout=None, criteria=None): result = yield self.queue.get(timeout=timeout, criteria=criteria); raise StopIteration, result
    def put(self, item, timeout=None): result = yield self.queue.put(item, timeout=timeout); raise StopIteration, result
        
class RTMPReader(Resource): # connect to RTMP URL and play the stream identified by id in URL.
    def __init__(self):
        Resource.__init__(self)
        self.type, self.mode, self._gen, self.timeout, self.stream = 'rtmp', 'r', None, None, ''
        
    def open(self, url):
        self.url, options = url, dict(map(lambda x: tuple(x.split('=', 1)+[''])[:2], url[7:].partition('?')[2].split('&')))
        self.timeout, self.stream = int(options['timeout']) if 'timeout' in options else 10, options['id'] if 'id' in options else None
        if not self.stream: raise StopIteration, None # id property is MUST in rtmp URL.
        if _debug: print 'RTMPReader.open timeout=', self.timeout, 'stream=', self.stream, 'url=', self.url
        self.nc = NetConnection(); result = yield self.nc.connect(self.url, timeout=self.timeout)
        if not result: raise StopIteration, None
        if self.stream:
            self.ns = yield NetStream().create(self.nc, timeout=self.timeout)
            result = yield self.ns.play(self.stream, timeout=self.timeout)
            if not result: raise StopIteration, None
        self._gen = self.run(); multitask.add(self._gen)
        raise StopIteration, self
    
    def close(self):
        if self.nc is not None: yield self.nc.close(); self.nc = None
        if self._gen is not None: self._gen.close()
        
    def run(self):
        try:
            while True:
                msg = yield self.ns.stream.queue.get(timeout=self.timeout, criteria=lambda x: x is None or x.type in (Message.AUDIO, Message.VIDEO))
                yield self.queue.put(msg)
        except multitask.Timeout:
            if _debug: print 'RTMPReader.run() timedout'
            yield self.queue.put(False)
            
class RTMPWriter(Resource): # Connect to RTMP URL and publish the stream identified by id in URL.
    def __init__(self):
        Resource.__init__(self)
        self.type, self.mode, self.timeout, self.stream = 'rtmp', 'w', None, ''
        
    def open(self, url):
        self.url, options = url, dict(map(lambda x: tuple(x.split('=', 1)+[''])[:2], url[7:].partition('?')[2].split('&')))
        self.timeout, self.stream = int(options['timeout']) if 'timeout' in options else 10, options['id'] if 'id' in options else None
        if not self.stream: raise StopIteration, None # The id parameter is a MUST
        if _debug: print 'RTMPWriter.open timeout=', self.timeout, 'stream=', self.stream, 'url=', self.url
        self.nc = NetConnection(); result = yield self.nc.connect(self.url, timeout=self.timeout)
        if not result: raise StopIteration, None
        if self.stream:
            self.ns = yield NetStream().create(self.nc, timeout=self.timeout)
            result = yield self.ns.publish(self.stream, timeout=self.timeout)
            if not result: raise StopIteration, None
        raise StopIteration, self
    
    def close(self):
        if self.nc is not None: yield self.nc.close(); self.nc = None
        
    def put(self, item):
        if self.ns is not None: yield self.ns.stream.send(item)
        yield # yield is needed since there is no other blocking operation
            
class HTTPReader(Resource): # Fetch a FLV file from a web URL. TODO: implement this
    def open(self, url): raise StopIteration, False
    
class HTTPWriter(Resource): # Put a FLV file to a web URL. TODO: implement this
    def open(self, url): raise StopIteration, False
    
class FLVReader(Resource): # Read a local FLV file, one message at a time, and implement inter-message wait.
    def __init__(self):
        Resource.__init__(self)
        self.type, self.mode, self._gen, self.id, self.client = 'file', 'r', None, 1, True
        
    def open(self, url):
        if _debug: print 'FLVReader.open', url
        yield # needed at least one yield in a generator
        self.url, u = url, urlparse.urlparse(url, 'file')
        self.fp = FLV().open(u.path)
        if self.fp:
            self._gen = self.fp.reader(self); multitask.add(self._gen) 
            raise StopIteration, self
        else: raise StopIteration, None
        
    def close(self):
        if self.fp: self.fp.close(); self.fp = None
        if self._gen is not None: self._gen.close()
        yield # yield is needed since there is no other blocking operation

    def send(self, msg):
        def sendInternal(self, msg): yield self.queue.put(msg)
        if msg.type in (Message.RPC, Message.RPC3):
            cmd = Command.fromMessage(msg)
            if cmd.name == 'onStatus' and len(cmd.args) > 0 and hasattr(cmd.args[0], 'code') and cmd.args[0].code == 'NetStream.Play.Stop': msg = False # indicates end of file
        multitask.add(sendInternal(self, msg))
    
class FLVWriter(Resource): # Write a local FLV file.
    def __init__(self):
        Resource.__init__(self)
        self.type, self.mode = 'file', 'w'
        
    def open(self, url):
        if _debug: print 'FLVWrite.open', url
        self.url, u = url, urlparse.urlparse(url, 'file')
        self.fp = FLV().open(u.path, 'record'); yield # yield is needed since there is no other blocking operation.
        raise StopIteration, self if self.fp else None
    
    def close(self):
        if self.fp is not None: self.fp.close(); self.fp = None
        yield # yield is needed since there is no other blocking operation
    
    def put(self, item):
        if self.fp is not None: self.fp.write(item)
        yield # yield is needed since there is no other blocking operation
    
#--------------------------------
# Global methods
#--------------------------------

def open(url, mode='r'):
    '''Open the given resource for read "r" or write "w" mode. Returns an object that has generator methods such as put(), get() and close().'''
    type = 'rtmp' if str(url).startswith('rtmp://') else 'http' if str(url).startswith('http://') else 'file'
    types = {'rtmp-r': RTMPReader, 'rtmp-w': RTMPWriter, 'http-r': HTTPReader, 'http-w': HTTPWriter, 'file-r': FLVReader, 'file-w': FLVWriter }
    r = yield types[type + '-' + mode]().open(url=url)
    raise StopIteration, r
    
def copy(src, dest):
    '''Copy from given src url (str) to dest url (str).'''
    s  = yield open(src, 'r')
    if not s: raise Result, (False, 'Cannot open source %r'%(src))
    d = yield open(dest, 'w')
    if not d: yield s.close(); raise Result, (False, 'Cannot open destination %r'%(dest))
    result = (True, 'Completed') # initialize the result
    try:
        while True:
            msg = yield s.get()
            if not msg: break;
            yield d.put(msg)
    except Result, e: result = e
    except KeyboardInterrupt: result = (True, 'Keyboard Interrupt')
    yield s.close()
    yield d.close()
    raise Result, result
    

def _copy_loop(filename, ns, enableAudio, enableVideo):
    '''Local function used by connect() to stream from file to NetStream in a loop.'''
    reader = yield FLVReader().open(filename)
    if not reader: raise StopIteration('Failed to open file %r'%(filename,))
    try:
        while True:
            msg = yield reader.get()
            if not msg: 
                if _debug: print 'Reached end, re-opening the file', filename
                reader.close()
                reader = yield FLVReader().open(filename)
            elif enableAudio and msg.type == Message.AUDIO or enableVideo and msg.type == Message.VIDEO:
                yield ns.stream.send(msg)
    except Result, e:
        if _debug: print filename, 'result=', e
    except GeneratorExit: pass
    except: 
        if _debug: traceback.print_exc()
    reader.close()

def connect(url, params=None, timeout=10, duration=60, publishStream='publish', playStream='play', publishFile=None, enableAudio=True, enableVideo=True):
    '''Connect to the RTMP url with supplied parameters in NetConnection.connect. Once connected it publishes and plays the supplied
    streams, and if publish file is supplied uses that to publish to the stream. The connection is kept up for the duration seconds.
    Any attempt to connect, open streams or file is with supplied timeout. It returns an error string on failure or None on success.
    Example to publish audio-only with three parameters from 'file1.flv':
       result = yield connect("rtmp://server/app", ['str-param', None, 20], publish_file='file1.flv', enableVideo=False) 
    '''
    if _debug: print 'connect url=%r params=%r timeout=%r duration=%r publishStream=%r playStream=%r publishFile=%r enableAudio=%r enableVideo=%r'%(url, params, timeout, duration, publishStream, playStream, publishFile, enableAudio, enableVideo)

    nc = NetConnection()
    result = yield nc.connect(url, timeout, *params)
    if not result: raise StopIteration, 'Failed to connect %r'%(url,)
        
    if publishStream:
        ns1 = yield NetStream().create(nc, timeout=timeout)
        if not ns1: raise StopIteration, 'Failed to create publish stream'
        result = yield ns1.publish(publishStream, timeout=timeout)
        if not result: yield nc.close(); raise StopIteration, 'Failed to create publish stream %r'%(publishStream,)

    if playStream:
        ns2 = yield NetStream().create(nc, timeout=timeout)
        if not ns2: raise StopIteration, 'Failed to create play stream'
        result = yield ns2.play(playStream, timeout=timeout)
        if not result: yield nc.close(); raise StopIteration, 'Failed to create play stream %r'%(playStream,)
        
    if publishFile and publishStream: # copy from file to stream
        gen = _copy_loop(publishFile, ns1, enableAudio, enableVideo)
        multitask.add(gen)

    try: # if the remote side terminates before duration, 
        print 'timeout=', duration
        yield nc.client.close_queue.get(timeout=duration)
        if _debug: print 'received connection close'
        if publishFile and publishStream: gen.close()
    except (multitask.Timeout, GeneratorExit): # else wait until duration
        print 'timedout'
        if _debug: print 'duration completed, connect closing'
        if publishFile and publishStream: gen.close()
        yield nc.close()

    raise StopIteration(None)
    
    
#--------------------------------
# Module's main
#--------------------------------

_usage = '''usage: python rtmpclient.py [-d] src dest
  -d: verbose mode prints trace statements
  src and dest: either "rtmp" URL or a file name. Use "id" to specify stream name, e.g., rtmp://localhost/myapp?id=user1
  This software depends on Python 2.6 (won't work with 2.4 or 3.0)'''

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
