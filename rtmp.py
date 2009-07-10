# Copyright (c) 2007-2009, Mamta Singh. All rights reserved. see README for details.

'''
This is a simple implementation of a Flash RTMP server to accept connections and stream requests. The module is organized as follows:
1. The FlashServer class is the main class to provide the server abstraction. It uses the multitask module for co-operative multitasking.
   It also uses the App abstract class to implement the applications.
2. The Server class implements a simple server to receive new Client connections and inform the FlashServer application. The Client class
   derived from Protocol implements the RTMP client functions. The Protocol class implements the base RTMP protocol parsing. A Client contains
   various streams from the client, represented using the Stream class.
3. The Message, Header and Command represent RTMP message, header and command respectively. The FLV class implements functions to perform read
   and write of FLV file format.


Typically an application can launch this server as follows:
$ python rtmp.py

To know the command line options use the -h option:
$ python rtmp.py -h

To start the server with a different directory for recording and playing FLV files from, use the following command.
$ python rtmp.py -r some-other-directory/
Note the terminal '/' in the directory name. Without this, it is just used as a prefix in FLV file names.

A test client is available in testClient directory, and can be compiled using Flex Builder. Alternatively, you can use the SWF file to launch
from testClient/bin-debug after starting the server. Once you have launched the client in the browser, you can connect to
local host by clicking on 'connect' button. Then click on publish button to publish a stream. Open another browser with
same URL and first connect then play the same stream name. If everything works fine you should be able to see the video
from first browser to the second browser. Similar, in the first browser, if you check the record box before publishing,
it will create a new FLV file for the recorded stream. You can close the publishing stream and play the recorded stream to
see your recording. Note that due to initial delay in timestamp (in case publish was clicked much later than connect),
your played video will start appearing after some initial delay.


If an application wants to use this module as a library, it can launch the server as follows:
>>> agent = FlashServer()   # a new RTMP server instance
>>> agent.root = 'flvs/'    # set the document root to be 'flvs' directory. Default is current './' directory.
>>> agent.start()           # start the server
>>> multitask.run()         # this is needed somewhere in the application to actually start the co-operative multitasking.


If an application wants to specify a different application other than the default App, it can subclass it and supply the application by
setting the server's apps property. The following example shows how to define "myapp" which invokes a 'connected()' method on client when
the client connects to the server.

class MyApp(App):         # a new MyApp extends the default App in rtmp module.
    def __init__(self):   # constructor just invokes base class constructor
        App.__init__(self)
    def onConnect(self, client, *args):
        result = App.onConnect(self, client, *args)   # invoke base class method first
        def invokeAdded(self, client):                # define a method to invoke 'connected("some-arg")' on Flash client
            client.call('connected', 'some-arg')
            yield
        multitask.add(invokeAdded(self, client))      # need to invoke later so that connection is established before callback
...
agent.apps = dict({'myapp': MyApp, 'someapp': MyApp, '*': App})

Now the client can connect to rtmp://server/myapp or rtmp://server/someapp and will get connected to this MyApp application.
If the client doesn't define "function connected(arg:String):void" in the NetConnection.client object then the server will
throw an exception and display the error message.

'''

import os, sys, time, struct, socket, traceback, multitask, amf, threading, Queue

_debug = False

class ConnectionClosed:
    'raised when the client closed the connection'

class SockStream:
    '''A class that represents a socket as a stream'''
    def __init__(self, sock):
        self.sock, self.buffer = sock, ''
        self.bytesWritten = self.bytesRead = 0
    
    def close(self):
        self.sock.close()
        
    def read(self, count):
        try:
            while True:
                if len(self.buffer) >= count: # do not have data in buffer
                    data, self.buffer = self.buffer[:count], self.buffer[count:]
                    raise StopIteration(data)
                data = (yield multitask.recv(self.sock, 4096)) # read more from socket
                if not data: raise ConnectionClosed
                #if _debug: print 'socket.read[%d] %r'%(len(data), data)
                self.bytesRead += len(data)
                self.buffer += data
        except StopIteration: raise
        except: raise ConnectionClosed # anything else is treated as connection closed.
        
    def unread(self, data):
        self.buffer = data + self.buffer
            
    def write(self, data):
        while len(data) > 0: # write in 4K chunks each time
            chunk, data = data[:4096], data[4096:]
            self.bytesWritten += len(chunk)
            try: yield multitask.send(self.sock, chunk)
            except: raise ConnectionClosed
                                

class Header:
    FULL, MESSAGE, TIME, SEPARATOR, MASK = 0x00, 0x40, 0x80, 0xC0, 0xC0
    
    def __init__(self, channel=0, time=0, size=None, type=None, streamId=0):
        self.channel, self.time, self.size, self.type, self.streamId = channel, time, size, type, streamId
        self.extendedtime = 0
        if channel<64: self.hdrdata = chr(channel)
        elif channel<(64+256): self.hdrdata = '\x00'+chr(channel-64)
        else: self.hdrdata = '\x01'+chr((channel-64)%256)+chr((channel-64)/256) 
    
    def _appendExtendedTimestamp(self, data):
        if self.time == 0xFFFFFF:
            data += struct.pack('>I', self.extendedtime)
        return data
                    
    def toBytes(self, control):
        data = chr(ord(self.hdrdata[0]) | control) + self.hdrdata[1:]
        if control == Header.SEPARATOR: return self._appendExtendedTimestamp(data)
        
        data += struct.pack('>I', self.time & 0xFFFFFF)[1:]  # add time
        if control == Header.TIME: return self._appendExtendedTimestamp(data)
        
        data += struct.pack('>I', self.size)[1:]  # size
        data += chr(self.type)                    # type
        if control == Header.MESSAGE: return self._appendExtendedTimestamp(data)
        
        data += struct.pack('<I', self.streamId)  # add streamId
        return self._appendExtendedTimestamp(data)

    def __repr__(self):
        return ("<Header channel=%r time=%r size=%r type=%r (0x%02x) streamId=%r>"
            % (self.channel, self.time, self.size, self.type, self.type or 0, self.streamId))

class Message:
    # message types: RPC3, DATA3,and SHAREDOBJECT3 are used with AMF3
    RPC,  RPC3, DATA, DATA3, SHAREDOBJ, SHAREDOBJ3, AUDIO, VIDEO, ACK,  CHUNK_SIZE = \
    0x14, 0x11, 0x12, 0x0F,  0x13,      0x10,       0x08,  0x09,  0x03, 0x01
    
    def __init__(self, hdr=Header(), data=''):
        self.header, self.data = hdr, data
    
    # define properties type, streamId and time to access self.header.(property)
    for p in ['type', 'streamId', 'time']:
        exec 'def _g%s(self): return self.header.%s'%(p, p)
        exec 'def _s%s(self, %s): self.header.%s = %s'%(p, p, p, p)
        exec '%s = property(fget=_g%s, fset=_s%s)'%(p, p, p)
    @property
    def size(self): return len(self.data)
            
    def __repr__(self):
        return ("<Message header=%r data=%r>"% (self.header, self.data))
                
class Protocol:
    # constants
    PING_SIZE           = 1536
    DEFAULT_CHUNK_SIZE  = 128
    MIN_CHANNEL_ID      = 3
    PROTOCOL_CHANNEL_ID = 2
    
    def __init__(self, sock):
        self.stream = SockStream(sock)
        self.lastReadHeaders = dict() # indexed by channelId
        self.incompletePackets = dict() #indexed by channelId
        self.readChunkSize = self.writeChunkSize = Protocol.DEFAULT_CHUNK_SIZE
        self.lastWriteHeaders = dict() # indexed by streamId
        self.nextChannelId = Protocol.MIN_CHANNEL_ID
        self.writeLock = threading.Lock()
        self.writeQueue = Queue.Queue()
            
    def messageReceived(self, msg):
        yield
            
    def protocolMessage(self, msg):
        if msg.type == Message.ACK: # respond to ACK requests
            response = Message()
            response.type, response.data = msg.type, msg.data
            self.writeMessage(response)
        elif msg.type == Message.CHUNK_SIZE:
            self.readChunkSize = struct.unpack('>L', msg.data)[0]
            
    def connectionClosed(self):
        yield
                            
    def parse(self):
        try:
            yield self.parseCrossDomainPolicyRequest() # check for cross domain policy
            yield self.parseHandshake()  # parse rtmp handshake
            yield self.parseMessages()   # parse messages
        except ConnectionClosed:
            yield self.connectionClosed()
            if _debug: print 'parse connection closed'
                    
    def writeMessage(self, message):
        self.writeQueue.put(message)
            
    def parseCrossDomainPolicyRequest(self):
        # read the request
        REQUEST = '<policy-file-request/>\x00'
        data = (yield self.stream.read(len(REQUEST)))
        if data == REQUEST:
            if _debug: print data
            data = '''<!DOCTYPE cross-domain-policy SYSTEM "http://www.macromedia.com/xml/dtds/cross-domain-policy.dtd">
                    <!-- Policy file for xmlsocket://socks.mysite.com -->
                    <cross-domain-policy>
                      <allow-access-from domain="*" to-ports="1935" secure='false'/>
                    </cross-domain-policy>'''
            yield self.stream.write(data)
            raise ConnectionClosed
        else:
            yield self.stream.unread(data)
                    
    def parseHandshake(self):
        '''Parses the rtmp handshake'''
        data = (yield self.stream.read(Protocol.PING_SIZE + 1)) # bound version and first ping
        yield self.stream.write(data)
        data = (yield self.stream.read(Protocol.PING_SIZE)) # bound second ping
        yield self.stream.write(data)
    
    def parseMessages(self):
        '''Parses complete messages until connection closed. Raises ConnectionLost exception.'''
        CHANNEL_MASK = 0x3F
        while True:
            hdrsize = ord((yield self.stream.read(1))[0])  # read header size byte
            channel = hdrsize & CHANNEL_MASK
            if channel == 0: # we need one more byte
                # if _debug: print 'need one more bytes'
                channel = 64 + ord((yield self.stream.read(1))[0])
            elif channel == 1: # we need two more bytes
                # if _debug: print 'need two more bytes'
                data = (yield self.stream.read(2))
                channel = 64 + ord(data[0]) + 256 * ord(data[1])

            hdrtype = hdrsize & Header.MASK   # read header type byte
            #if hdrtype is zero than we read a complete header
            if hdrtype == 0 or not self.lastReadHeaders.has_key(channel):
                header = Header(channel)
            else:
                header = self.lastReadHeaders[channel]

            if hdrtype < Header.SEPARATOR: # only time has changed
                data = (yield self.stream.read(3))
                header.time = struct.unpack('!I', '\x00' + data)[0] # TODO: kundan - fixed a bug here, change += to =

            if hdrtype < Header.TIME: # time, size and type has changed
                data = (yield self.stream.read(3))
                header.size = struct.unpack('!I', '\x00' + data)[0]
                header.type = ord((yield self.stream.read(1))[0])

            if hdrtype < Header.MESSAGE: # time, size, type and streamId has changed
                data = (yield self.stream.read(4))
                header.streamId = struct.unpack('<I', data)[0]

            if header.time == 0xFFFFFF: # if we have extended timestamp, read it
                if _debug: print 'extended time stamp'
                data = (yield self.stream.read(4))
                header.extendedtime = struct.unpack('!I', data)[0]

            self.lastReadHeaders[channel] = header # save the header for following packets
            data = self.incompletePackets.get(channel, "") # are we continuing an incomplete packet?
            
            count = min(header.size - (len(data)), self.readChunkSize) # how much more
            # print 'count=', count, 'hdrsize=', hdrsize, 'len(data)=', len(data), 'hdrtype=', hdrtype, 'channel=', channel, 'header=', header
            # count = header.size - (len(data)) # how much more
            data += (yield self.stream.read(count))

            if len(data) < header.size: # we don't have all data
                # if _debug: print 'Protocol.parseMessage incomplete', len(data), '<', header.size
                self.incompletePackets[channel] = data
            else: # we have all data
                if len(data) == header.size:
                    if channel in self.incompletePackets:
                        # if _debug: print 'Protocol.parseMessage del old incomplete'
                        del self.incompletePackets[channel]
                else:
                    # if _debug: print 'Protocol.parseMessage updated old incomplete'
                    data, self.incompletePackets[channel] = data[:header.size], data[header.size:]
                msg = Message(header, data)
                if _debug: print 'Protocol.parseMessage msg=', msg
                try:
                    if channel == Protocol.PROTOCOL_CHANNEL_ID:
                        # if _debug: print 'Protocol.parseMessage protocol msg'
                        self.protocolMessage(msg)
                    else: 
                        # if _debug: print 'Protocol.parseMessage messageReceived'
                        yield self.messageReceived(msg)
                except:
                    if _debug: print 'Protocol.parseMessages exception', (traceback and traceback.print_exc() or None)

    def write(self):
        '''Writes messages to stream'''
        while True:
            while self.writeQueue.empty(): (yield multitask.sleep(0.01))
            message = self.writeQueue.get() # TODO this should be used using multitask.Queue and remove previous wait.
            if _debug: print 'response', message
            if message is None: 
                try: self.stream.close()  # just in case TCP socket is not closed, close it.
                except: pass
                break
            
            # get the header stored for the stream
            if self.lastWriteHeaders.has_key(message.streamId):
                header = self.lastWriteHeaders[message.streamId]
            else:
                if self.nextChannelId < Protocol.MIN_CHANNEL_ID: self.nextChannelId = Protocol.MIN_CHANNEL_ID
                header, self.nextChannelId = Header(self.nextChannelId), self.nextChannelId + 1
                self.lastWriteHeaders[message.streamId] = header
            # special header for protocol messages
            if message.type < Message.AUDIO:
                header = Header(Protocol.PROTOCOL_CHANNEL_ID)
                    
            # now figure out the header data bytes
            if header.streamId != message.streamId or header.time == 0:
                header.streamId, header.type, header.size, header.time = message.streamId, message.type, message.size, message.time
                control = Header.FULL
            elif header.size != message.size or header.type != message.type:
                header.type, header.size, header.time = message.type, message.size, message.time
                control = Header.MESSAGE
            elif header.time != message.time:
                # if _debug: print '------- time changed'
                header.time = message.time
                control = Header.TIME
            else:
                control = Header.SEPARATOR

            assert message.size == len(message.data)

            data = ''
            while len(message.data) > 0:
                data += header.toBytes(control) # gather header bytes
                count = min(self.writeChunkSize, len(message.data))
                data += message.data[:count]
                message.data = message.data[count:]
                control = Header.SEPARATOR # incomplete message continuation
            try:
                yield self.stream.write(data)
            except ConnectionClosed:
                yield self.connectionClosed()
            except:
                print traceback.print_exc()

class Command:
    ''' Class for command / data messages'''
    def __init__(self, type=Message.RPC, name=None, id=None, cmdData=None, args=[]):
        '''Create a new command with given type, name, id, cmdData and args list.'''
        self.type, self.name, self.id, self.cmdData, self.args = type, name, id, cmdData, args[:]
        
    def __repr__(self):
        return ("<Command type=%r name=%r id=%r data=%r args=%r>" % (self.type, self.name, self.id, self.cmdData, self.args))
    
    def setArg(self, arg):
        self.args.append(arg)
    
    def getArg(self, index):
        return self.args[index]
    
    @classmethod
    def fromMessage(cls, message):
        ''' initialize from a parsed RTMP message'''
        assert (message.type in [Message.RPC, Message.RPC3, Message.DATA, Message.DATA3])

        length = len(message.data)
        if length == 0: raise InvalidMessage
        
        if message.type == Message.RPC3 or message.type == Message.DATA3:
            assert message.data[0] == '\x00' # must be 0 in AMD3
            data = message.data[1:]
        else:
            data = message.data
        
        amfReader = amf.AMF0(data)

        inst = cls()
        inst.name = amfReader.read() # first field is command name

        try:
            if message.type == Message.RPC:
                inst.id = amfReader.read() # second field *may* be message id
                inst.cmdData = amfReader.read() # third is command data
            else:
                inst.id = 0
            inst.args = [] # others are optional
            while True:
                inst.args.append(amfReader.read())
        except EOFError:
            pass
        return inst
    
    def toMessage(self):
        msg = Message()
        assert self.type
        msg.type = self.type
        output = amf.BytesIO()
        amfWriter = amf.AMF0(output)
        amfWriter.write(self.name)
        if msg.type == Message.RPC or msg.type == Message.RPC3:
            amfWriter.write(self.id)
            amfWriter.write(self.cmdData)
        for arg in self.args:
            amfWriter.write(arg)
        output.seek(0)
        #hexdump.hexdump(output)
        #output.seek(0)
        if msg.type == Message.RPC3 or msg.type == Message.DATA3:
            data = '\x00' + output.read()
        else:
            data = output.read()
        msg.data = data
        output.close()
        return msg

class FLV(object):
    '''An FLV file which converts between RTMP message and FLV tags.'''
    def __init__(self, root):
        self.fname = self.fp = None
        self.tsa = self.tsv = 0
        self.root = root
    
    @staticmethod
    def getfilename(stream, root):
        '''return the file name for the given stream'''
        ignore, ignore, scope = stream.client.path.partition('/')
        if scope: scope = scope + '/'
        result = root + scope + stream.name + '.flv'
        if _debug: print 'filename=', result
        return result
    
    def open(self, stream, mode=0775):
        '''Open the file for reading or writing.'''
        fname = FLV.getfilename(stream, self.root)
        if str(fname).find('/../') >= 0: raise ValueError('Must not contain .. in name')
        if _debug: print 'opening file', fname
        self.tsa = self.tsv = 0
        if hasattr(stream, 'mode') and stream.mode in ('record', 'append'):
            try: os.makedirs(os.path.dirname(fname), mode)
            except: pass
            self.fp = open(fname, 'w' if stream.mode == 'record' else 'a')
            if stream.mode == 'record':
                self.fp.write('FLV\x01\x05\x00\x00\x00\x09\x00\x00\x00\x00') # the header and first previousTagSize
        else: 
            self.fp = open(fname, 'r')
            hdr = self.fp.read(13)
            if hdr[:3] != 'FLV': raise ValueError('This is not a FLV file')
        return self 
    
    def close(self):
        '''Close the underlying file for this object.'''
        if _debug: print 'closing flv file'
        if self.fp is not None: self.fp.close(); self.fp = None
    
    def write(self, message):
        '''Write a message to the file, assuming it was opened for writing or appending.'''
        if message.type == Message.AUDIO or message.type == Message.VIDEO:
            length = len(message.data)
            ts = (message.time if message.time != 0xffffff else message.extendedtime)
            if message.type == Message.AUDIO: self.tsa += ts; tsx = self.tsa
            else: self.tsv += ts; tsx = self.tsv
            # if _debug: print 'writing self.tsa/v=', self.tsa, self.tsv, 'tsx=', tsx, 'message.time=', message.time, 'type=', message.type
            data = struct.pack('>BBHBHB', message.type, (length >> 16) & 0xff, length & 0x0ffff, (tsx >> 16) & 0xff, tsx & 0x0ffff, (tsx >> 24) & 0xff) + '\x00\x00\x00' +  message.data
            data += struct.pack('>I', len(data))
            self.fp.write(data)
    
    def reader(self, stream):
        '''A generator to periodically read the file and dispatch them to the stream.'''
        if _debug: print 'reader started'
        try:
            while True:
                bytes = self.fp.read(11)
                if len(bytes) == 0:
                    response = Command(name='onStatus', id=stream.id, args=[dict(level='status',code='NetStream.Play.Stop', description='File ended', details=None)])
                    stream.send(response.toMessage())
                    break
                type, len0, len1, ts0, ts1, ts2, sid0, sid1 = struct.unpack('>BBHBHBBH', bytes)
                length = (len0 << 16) | len1; ts = (ts0 << 16) | (ts1 & 0x0ffff) | (ts2 << 24)
                body = self.fp.read(length); ptagsize, = struct.unpack('>I', self.fp.read(4))
                if ptagsize != (length+11): 
                    if _debug: print 'invalid previous tag-size found:', ptagsize, '!=', (length+11),'ignored.'
                if type == Message.AUDIO: self.tsa, ts = ts, ts - max(self.tsa, self.tsv)
                else: self.tsv, ts = ts, ts - max(self.tsa, self.tsv)
                # if _debug: print 'ts=', ts
                if ts < 0: ts = 0
                if ts > 0: yield multitask.sleep(ts / 1000.0)
                if stream is None or stream.client is None: break # if it is closed
                hdr = Header(0, ts if ts < 0xffffff else 0xffffff, length, type, stream.id)
                if ts >= 0xffffff: hdr.extendedtime = ts
                msg = Message(hdr, body)
                # if _debug: print 'sending length=', length, 'hdr=', hdr
                stream.send(msg)
        except StopIteration: pass
        except: 
            if _debug: print 'closing the reader', (sys and sys.exc_info() or None)
            traceback.print_exc()
            if self.fp is not None: self.fp.close(); self.fp = None
            
class Stream:
    count = 0;
    def __init__(self, client):
        self.client, self.id, self.name = client, 0, ''
        self.recordfile = self.playfile = None # so that it doesn't complain about missing attribute
        self.queue = multitask.Queue()
        self._name = 'Stream[' + str(Stream.count) + ']'; Stream.count += 1
        if _debug: print self, 'created'
        
    def close(self):
        if _debug: print self, 'closing'
        if self.recordfile is not None: self.recordfile.close(); self.recordfile = None
        if self.playfile is not None: self.playfile.close(); self.playfile = None
        self.client = None # to clear the reference
        pass
    
    def __repr__(self):
        return self._name;
    
    def recv(self):
        '''Generator to receive new Message on this stream, or None if stream is closed.'''
        return self.queue.get()
    
    def send(self, msg):
        '''Method to send a Message or Command on this stream.'''
        if isinstance(msg, Command):
            msg = msg.toMessage()
        msg.streamId = self.id
        # if _debug: print self,'send'
        if self.client is not None: self.client.writeMessage(msg)
        
class Client(Protocol):
    def __init__(self, sock, server):
        Protocol.__init__(self, sock)
        self.server, self.agent, self.streams, self._nextCallId, self._nextStreamId, self.objectEncoding = \
          server,      {},         {},           2,                1,                  0.0
        self.queue = multitask.Queue() # receive queue used by application
        multitask.add(self.parse()); multitask.add(self.write())

    def recv(self):
        '''Generator to receive new Message (msg, arg) on this stream, or (None,None) if stream is closed.'''
        return self.queue.get()
    
    def connectionClosed(self):
        '''Called when the client drops the connection'''
        if _debug: 'Client.connectionClosed'
        self.writeMessage(None)
        yield self.queue.put((None,None))
            
    def messageReceived(self, msg):
        if (msg.type == Message.RPC or msg.type == Message.RPC3) and msg.streamId == 0:
            cmd = Command.fromMessage(msg)
            # if _debug: print 'rtmp.Client.messageReceived cmd=', cmd
            if cmd.name == 'connect':
                self.agent = cmd.cmdData
                self.objectEncoding = self.agent['objectEncoding']
                yield self.server.queue.put((self, cmd.args)) # new connection
                return
            elif cmd.name == 'createStream':
                response = Command(name='_result', id=cmd.id, type=(self.objectEncoding == 0.0 and Message.RPC or Message.RPC3), \
                                   args=[self._nextStreamId])
                self.writeMessage(response.toMessage())
                
                stream = Stream(self) # create a stream object
                stream.id = self._nextStreamId
                self.streams[self._nextStreamId] = stream
                self._nextStreamId += 1

                yield self.queue.put(('stream', stream)) # also notify others of our new stream
                return
            elif cmd.name == 'closeStream':
                assert msg.streamId in self.streams
                yield self.streams[msg.streamId].queue.put(None) # notify closing to others
                del self.streams[msg.streamId]
                return
            else:
                # if _debug: print 'Client.messageReceived cmd=', cmd
                yield self.queue.put(('command', cmd)) # RPC call
        else: # this has to be a message on the stream
            assert msg.streamId != 0
            assert msg.streamId in self.streams
            # if _debug: print self.streams[msg.streamId], 'recv'
            stream = self.streams[msg.streamId]
            if not stream.client: stream.client = self 
            yield stream.queue.put(msg) # give it to stream

    def accept(self):
        '''Method to accept an incoming client.'''
        response = Command()
        response.id, response.name, response.type = 1, '_result', Message.RPC
        if _debug: print 'Client.accept() objectEncoding=', self.objectEncoding
        response.setArg(dict(level='status', code='NetConnection.Connect.Success',
                        description='Connection succeeded.', details=None,
                        objectEncoding=self.objectEncoding))
        self.writeMessage(response.toMessage())
            
    def rejectConnection(self, reason=''):
        '''Method to reject an incoming client.'''
        response = Command()
        response.id, response.name, response.type = 1, '_error', Message.RPC
        response.setArg(dict(level='status', code='NetConnection.Connect.Rejected',
                        description=reason, details=None))
        self.writeMessage(response.toMessage())
            
    def call(self, method, *args):
        '''Call a (callback) method on the client.'''
        cmd = Command()
        cmd.id, cmd.name, cmd.type = self._nextCallId, method, (self.objectEncoding == 0.0 and Message.RPC or Message.RPC3)
        cmd.args, cmd.cmdData = args, None
        self._nextCallId += 1
        if _debug: print 'Client.call method=', method, 'args=', args, ' msg=', cmd.toMessage()
        self.writeMessage(cmd.toMessage())
            
    def createStream(self):
        ''' Create a stream on the server side'''
        stream = Stream(self)
        stream.id = self._nextStreamId
        self.streams[stream.id] = stream
        self._nextStreamId += 1
        return stream


class Server:
    '''A RTMP server listens for incoming connections and informs the app.'''
    def __init__(self, sock):
        '''Create an RTMP server on the given bound TCP socket. The server will terminate
        when the socket is disconnected, or some other error occurs in listening.'''
        self.sock = sock
        self.queue = multitask.Queue()  # queue to receive incoming client connections
        multitask.add(self.run())

    def recv(self):
        '''Generator to wait for incoming client connections on this server and return
        (client, args) or (None, None) if the socket is closed or some error.'''
        return self.queue.get()
        
    def run(self):
        try:
            while True:
                sock, remote = (yield multitask.accept(self.sock))  # receive client TCP
                if sock == None:
                    if _debug: print 'rtmp.Server accept(sock) returned None.' 
                    break
                if _debug: print 'connection received from', remote
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1) # make it non-block
                client = Client(sock, self)
        except: 
            if _debug: print 'rtmp.Server exception ', (sys and sys.exc_info() or None)
        
        if (self.sock):
            try: self.sock.close(); self.sock = None
            except: pass
        if (self.queue):
            yield self.queue.put((None, None))
            self.queue = None

class App(object):
    '''An application instance containing any number of streams. Except for constructor all methods are generators.'''
    count = 0
    def __init__(self):
        self.name = str(self.__class__.__name__) + '[' + str(App.count) + ']'; App.count += 1
        self.players, self.publishers, self._clients = {}, {}, [] # Streams indexed by stream name, and list of clients
        if _debug: print self.name, 'created'
    def __del__(self):
        if _debug: print self.name, 'destroyed'
    @property
    def clients(self):
        '''everytime this property is accessed it returns a new list of clients connected to this instance.'''
        return self._clients[1:] if self._clients is not None else []
    def onConnect(self, client, *args):
        if _debug: print self.name, 'onConnect', client.path
        return True
    def onDisconnect(self, client):
        if _debug: print self.name, 'onDisconnect', client.path
    def onPublish(self, client, stream):
        if _debug: print self.name, 'onPublish', client.path, stream.name
    def onClose(self, client, stream):
        if _debug: print self.name, 'onClose', client.path, stream.name
    def onPlay(self, client, stream):
        if _debug: print self.name, 'onPlay', client.path, stream.name
    def onStop(self, client, stream):
        if _debug: print self.name, 'onStop', client.path, stream.name
    def onCommand(self, client, cmd, *args):
        if _debug: print self.name, 'onCommand', cmd, args
    def onStatus(self, client, info):
        if _debug: print self.name, 'onStatus', info
    def onResult(self, client, result):
        if _debug: print self.name, 'onResult', result
    def onPublishData(self, client, stream, message): # this is invoked every time some media packet is received from published stream. 
        return True # should return True so that the data is actually published in that stream
    def onPlayData(self, client, stream, message):
        return True # should return True so that data will be actually played in that stream
    
class FlashServer(object):
    '''A RTMP server to record and stream Flash video.'''
    def __init__(self):
        '''Construct a new FlashServer. It initializes the local members.'''
        self.sock = self.server = None;
        self.apps = dict({'*': App}) # supported applications: * means any as in {'*': App}
        self.clients = dict()  # list of clients indexed by scope. First item in list is app instance.
        self.root = '';
        
    def start(self, host='0.0.0.0', port=1935):
        '''This should be used to start listening for RTMP connections on the given port, which defaults to 1935.'''
        if not self.server:
            sock = self.sock = socket.socket(type=socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((host, port))
            if _debug: print 'listening on ', sock.getsockname()
            sock.listen(5)
            server = self.server = Server(sock) # start rtmp server on that socket
            multitask.add(self.serverlistener())
    
    def stop(self):
        if _debug: print 'stopping Flash server'
        if self.server and self.sock:
            try: self.sock.close(); self.sock = None
            except: pass
        self.server = None
        
    def serverlistener(self):
        '''Server listener (generator). It accepts all connections and invokes client listener'''
        try:
            while True:  # main loop to receive new connections on the server
                client, args = (yield self.server.recv()) # receive an incoming client connection.
                # TODO: we should reject non-localhost client connections.
                if not client:                # if the server aborted abnormally,
                    break                     #    hence close the listener.
                if _debug: print 'client connection received', client, args
                # if client.objectEncoding != 0 and client.objectEncoding != 3:
                if client.objectEncoding != 0:
                    yield client.rejectConnection(reason='Unsupported encoding ' + str(client.objectEncoding) + '. Please use NetConnection.defaultObjectEncoding=ObjectEncoding.AMF0')
                    yield client.connectionClosed()
                else:
                    client.path = str(client.agent['app']); name, ignore, scope = client.path.partition('/')
                    if '*' not in self.apps and name not in self.apps:
                        yield client.rejectConnection(reason='Application not found: ' + name)
                    else: # create application instance as needed and add in our list
                        if _debug: print 'name=', name, 'name in apps', str(name in self.apps)
                        app = self.apps[name] if name in self.apps else self.apps['*'] # application class
                        if client.path in self.clients: inst = self.clients[client.path][0]
                        else: inst = app()
                        try: 
                            result = inst.onConnect(client, *args)
                        except: 
                            if _debug: print sys.exc_info()
                            yield client.rejectConnection(reason='Exception on onConnect'); 
                            continue
                        if result is True or result is None:
                            if client.path not in self.clients: 
                                self.clients[client.path] = [inst]; inst._clients=self.clients[client.path]
                            self.clients[client.path].append(client)
                            if result is True:
                                yield client.accept() # TODO: else how to kill this task when rejectConnection() later
                            multitask.add(self.clientlistener(client)) # receive messages from client.
                        else: 
                            yield client.rejectConnection(reason='Rejected in onConnect')
        except StopIteration: raise
        except: 
            if _debug: print 'serverlistener exception', (sys and sys.exc_info() or None)
            
    def clientlistener(self, client):
        '''Client listener (generator). It receives a command and invokes client handler, or receives a new stream and invokes streamlistener.'''
        try:
            while True:
                msg, arg = (yield client.recv())   # receive new message from client
                if not msg:                   # if the client disconnected,
                    if _debug: print 'connection closed from client'
                    break                     #    come out of listening loop.
                if msg == 'command':          # handle a new command
                    multitask.add(self.clienthandler(client, arg))
                elif msg == 'stream':         # a new stream is created, handle the stream.
                    arg.client = client
                    multitask.add(self.streamlistener(arg))
        except StopIteration: raise
        except:
            if _debug: print 'clientlistener exception', (sys and sys.exc_info() or None)
            traceback.print_exc()
            
        # client is disconnected, clear our state for application instance.
        if _debug: print 'cleaning up client', client.path
        inst = None
        if client.path in self.clients:
            inst = self.clients[client.path][0]
            self.clients[client.path].remove(client)
        for stream in client.streams.values(): # for all streams of this client
            self.closehandler(stream)
        client.streams.clear() # and clear the collection of streams
        if client.path in self.clients and len(self.clients[client.path]) == 1: # no more clients left, delete the instance.
            if _debug: print 'removing the application instance'
            inst = self.clients[client.path][0]
            inst._clients = None
            del self.clients[client.path]
        if inst is not None: inst.onDisconnect(client)
        
    def closehandler(self, stream):
        '''A stream is closed explicitly when a closeStream command is received from given client.'''
        if stream.client is not None:
            inst = self.clients[stream.client.path][0]
            if stream.name in inst.publishers and inst.publishers[stream.name] == stream: # clear the published stream
                inst.onClose(stream.client, stream)
                del inst.publishers[stream.name]
            if stream.name in inst.players and stream in inst.players[stream.name]:
                inst.onStop(stream.client, stream)
                inst.players[stream.name].remove(stream)
                if len(inst.players[stream.name]) == 0:
                    del inst.players[stream.name]
            stream.close()
        
    def clienthandler(self, client, cmd):
        '''A generator to handle a single command on the client.'''
        inst = self.clients[client.path][0]
        if inst:
            if cmd.name == '_error':
                if hasattr(inst, 'onStatus'):
                    result = inst.onStatus(client, cmd.args[0])
            elif cmd.name == '_result':
                if hasattr(inst, 'onResult'):
                    result = inst.onResult(client, cmd.args[0])
            else:
                res, code, args = Command(), '_result', dict()
                try: result = inst.onCommand(client, cmd.name, *cmd.args)
                except:
                    if _debug: print 'Client.call exception', (sys and sys.exc_info() or None) 
                    code, args = '_error', dict()
                res.id, res.name, res.type = cmd.id, code, (client.objectEncoding == 0.0 and Message.RPC or Message.RPC3)
                res.args, res.cmdData = args, None
                if _debug: print 'Client.call method=', code, 'args=', args, ' msg=', res.toMessage()
                client.writeMessage(res.toMessage())
                # TODO return result to caller
        yield
        
    def streamlistener(self, stream):
        '''Stream listener (generator). It receives stream message and invokes streamhandler.'''
        stream.recordfile = None # so that it doesn't complain about missing attribute
        while True:
            msg = (yield stream.recv())
            if not msg:
                if _debug: print 'stream closed'
                self.closehandler(stream)
                break
            # if _debug: msg
            multitask.add(self.streamhandler(stream, msg))
            
    def streamhandler(self, stream, message):
        '''A generator to handle a single message on the stream.'''
        try:
            if message.type == Message.RPC:
                cmd = Command.fromMessage(message)
                if _debug: print 'streamhandler received cmd=', cmd
                if cmd.name == 'publish':
                    yield self.publishhandler(stream, cmd)
                elif cmd.name == 'play':
                    yield self.playhandler(stream, cmd)
                elif cmd.name == 'closeStream':
                    self.closehandler(stream)
            else: # audio or video message
                yield self.mediahandler(stream, message)
        except GeneratorExit: pass
        except StopIteration: pass
        except: 
            if _debug: print 'exception in streamhandler', (sys and sys.exc_info())
    
    def publishhandler(self, stream, cmd):
        '''A new stream is published. Store the information in the application instance.'''
        try:
            stream.mode = 'live' if len(cmd.args) < 2 else cmd.args[1] # live, record, append
            stream.name = cmd.args[0]
            if _debug: print 'publishing stream=', stream.name, 'mode=', stream.mode
            inst = self.clients[stream.client.path][0]
            if (stream.name in inst.publishers):
                raise ValueError, 'Stream name already in use'
            inst.publishers[stream.name] = stream # store the client for publisher
            result = inst.onPublish(stream.client, stream)
            
            if stream.mode == 'record' or stream.mode == 'append':
                stream.recordfile = FLV(self.root).open(stream)
            response = Command(name='onStatus', id=cmd.id, args=[dict(level='status', code='NetStream.Publish.Start', description='', details=None)])
            yield stream.send(response)
        except ValueError, E: # some error occurred. inform the app.
            if _debug: print 'error in publishing stream', str(E)
            response = Command(name='onStatus', id=cmd.id, args=[dict(level='error',code='NetStream.Publish.BadName',description=str(E),details=None)])
            yield stream.send(response)

    def playhandler(self, stream, cmd):
        '''A new stream is being played. Just updated the players list with this stream.'''
        inst = self.clients[stream.client.path][0]
        name = stream.name = cmd.args[0]  # store the stream's name
        start = cmd.args[1] if len(cmd.args) >= 2 else -2
        if name not in inst.players:
            inst.players[name] = [] # initialize the players for this stream name
        if stream not in inst.players[name]: # store the stream as players of this name
            inst.players[name].append(stream)
        if os.path.exists(FLV.getfilename(stream, self.root)):
            stream.playfile = FLV(self.root).open(stream)
            multitask.add(stream.playfile.reader(stream))
        if _debug: print 'playing stream=', name, 'start=', start
        result = inst.onPlay(stream.client, stream)
        response = Command(name='onStatus', id=cmd.id, args=[dict(level='status',code='NetStream.Play.Start', description=stream.name, details=None)])
        yield stream.send(response)
            
    def mediahandler(self, stream, message):
        '''Handle incoming media on the stream, by sending to other stream in this application instance.'''
        if stream.client is not None:
            inst = self.clients[stream.client.path][0]
            result = inst.onPublishData(stream.client, stream, message)
            if result:
                client = stream.client
                for s in (inst.players.get(stream.name, [])):
                    # if _debug: print 'D', stream.name, s.name
                    result = inst.onPlayData(s.client, s, message)
                    if result:
                        yield s.send(message)
                if stream.recordfile is not None:
                    stream.recordfile.write(message)

# The main routine to start, run and stop the service
if __name__ == '__main__':
    from optparse import OptionParser
    parser = OptionParser()
    parser.add_option('-i', '--host',    dest='host',    default='0.0.0.0', help="listening IP address. Default '0.0.0.0'")
    parser.add_option('-p', '--port',    dest='port',    default=1935, type="int", help='listening port number. Default 1935')
    parser.add_option('-r', '--root',    dest='root',    default='./',       help="document root directory. Default './'")
    parser.add_option('-d', '--verbose', dest='verbose', default=False, action='store_true', help='enable debug trace')
    (options, args) = parser.parse_args()
    
    _debug = options.verbose
    try:
        agent = FlashServer()
        agent.root = options.root
        agent.start(options.host, options.port)
        if _debug: print time.asctime(), 'Flash Server Starts - %s:%d' % (options.host, options.port)
        multitask.run()
    except KeyboardInterrupt:
        pass
    if _debug: time.asctime(), 'Flash Server Stops'
