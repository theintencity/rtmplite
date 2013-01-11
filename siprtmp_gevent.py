# Copyright (c) 2011, Kundan Singh. All rights reserved. see README for details.
# CAUTION: This module is not well tested.

'''
This is higher-performance re-write of rtmp.py and siprtmp.py. 
Intead of the multitask module, it uses gevent project.
It support SIP-RTMP gateway.
It support RTMP streaming.
BUT
It does not support file recording/playback.

Please see 
http://p2p-sip.blogspot.com/2011/04/performance-of-siprtmp-multitask-vs.html
for details on the performance improvement and measurement result.

The conclusion of my measurement is as follows. The SIP-RTMP gateway software 
using gevent takes about 2/3 the CPU cycles than using multitask, and the RTMP 
server software using gevent takes about 1/2 the CPU cycles than using multitask. 
After the improvements, on a dual-core 2.13 GHz CPU machine, a single audio 
call going though gevent-based siprtmp using Speex audio codec at 8Hz sampling 
takes about 3.1% CPU, and hence in theory can support about 60 active calls 
in steady state. Another way to look at it is that the software requires CPU 
cycles of about 66 MHz per audio call.
'''

try:
    import gevent
except ImportError:
    print 'Please install gevent and its dependencies'
    import sys
    sys.exit(1)
    
from gevent import monkey, Greenlet, GreenletExit
monkey.patch_socket()
from gevent.server import StreamServer
from gevent.queue import Queue, Empty 
from gevent.coros import Semaphore

import os, sys, traceback, time, struct, socket, random, amf, hashlib, hmac, random
from struct import pack, unpack
from rtmp import Header, Message, Command, App, getfilename, Protocol, FLV as baseFLV

try:
    from std import rfc3261, rfc3264, rfc3550, rfc2396, rfc4566, rfc2833, kutil
    from app.voip import MediaSession
    from siprtmp import MediaContext
    sip = True
except:
    print 'warning: disabling SIP. To enable please include p2p-sip src directory in your PYTHONPATH before starting this application'
    sip = False
    # sys.exit(1)

try: import audiospeex, audioop
except: audiospeex = None

_debug = _debugAll = False

def truncate(data, max=100):
    return data and len(data)>max and data[:max] + '...(%d)'%(len(data),) or data
    

# -----------------------------------------------------------------------------
# Borrowed from rtmp.py after changing to multitask to asyncore/gevent
# -----------------------------------------------------------------------------

class Stream(object):
    def __init__(self):
        self.id, self.name = 0, ''
#        self.recordfile, self.playfile = None, None
        
    def close(self):
#        if self.recordfile is not None: 
#            self.recordfile.close()
#            self.recordfile = None
#        if self.playfile is not None: 
#            self.playfile.close()
#            self.playfile = None
        pass
        
class FlashClient(object):
    '''Represents a single Flash connection and client.'''
    PING_SIZE, DEFAULT_CHUNK_SIZE, HIGH_WRITE_CHUNK_SIZE, PROTOCOL_CHANNEL_ID = 1536, 128, 4096, 2 # constants
    READ_WIN_SIZE, WRITE_WIN_SIZE = 1000000L, 1073741824L
    CHANNEL_MASK = 0x3F

    
    crossdomain =  '''<!DOCTYPE cross-domain-policy SYSTEM "http://www.macromedia.com/xml/dtds/cross-domain-policy.dtd">
<cross-domain-policy>
  <allow-access-from domain="*" to-ports="1935" secure='false'/>
</cross-domain-policy>'''
    
    def __init__(self, server, sock):
        self.server, self.sock, self.state, self.buffer = server, sock, 'idle', ''
        self.bytesRead = self.bytesWritten = 0
        self.lastReadHeaders, self.incompletePackets, self.lastWriteHeaders = dict(), dict(), dict()
        self.readChunkSize = self.writeChunkSize = self.DEFAULT_CHUNK_SIZE
        self.readWinSize0, self.readWinSize, self.writeWinSize0, self.writeWinSize = 0L, self.READ_WIN_SIZE, 0L, self.WRITE_WIN_SIZE
        self.nextChannelId = self.PROTOCOL_CHANNEL_ID + 1
        self._time0 = time.time()
        self.path, self.agent, self.streams, self._nextCallId, self._nextStreamId, self.objectEncoding, self._rpc = \
          None,      None,         {},           2,                1,                  0.0,             Message.RPC
        self._write_lock = Semaphore()
        
    @property
    def relativeTime(self):
        return int(1000*(time.time() - self._time0))
    
    def send(self, data):
        if self.sock is not None and data is not None:
            self._write_lock.acquire()
            try:
                self.sock.sendall(data)
            except:
                if _debug: traceback.print_exc()
            finally:
                self._write_lock.release()
        
    def received(self, data):
        self.buffer += data
        self.bytesRead += len(data)
        while len(self.buffer) > 0:
            size, buffer = len(self.buffer), self.buffer
            if self.state == 'idle': # no handshake done yet
                if size >= 23 and buffer.startswith('<policy-file-request/>\x00'):
                    self.send(self.crossdomain)
                    raise RuntimeError, 'closed'
                if size < self.PING_SIZE+1: return
                self.buffer = buffer[self.PING_SIZE+1:]
                response = Protocol.handshakeResponse(buffer[:self.PING_SIZE+1])
                self.send(response)
                self.state = 'handshake'
            elif self.state == 'handshake':
                if size < self.PING_SIZE: return
                self.buffer = buffer[self.PING_SIZE:]
                self.state = 'active'
            elif self.state == 'active':
                if size < 1: return # at least one byte needed
                hdrsize, offset = ord(buffer[0]), 1
                channel = hdrsize & self.CHANNEL_MASK
                if channel == 0: # we need one more byte
                    if size < 2: return
                    channel, offset = 64 + ord(buffer[1:2]), 2
                elif channel == 1: # we need two more bytes
                    if size < 3: return
                    channel, offset = 64 + ord(buffer[1:2]) + 256 * ord(buffer[2:3]), 3
            
                hdrtype = hdrsize & Header.MASK   # read header type byte
                if hdrtype == Header.FULL or not self.lastReadHeaders.has_key(channel):
                    header = Header(channel)
                    self.lastReadHeaders[channel] = header
                else:
                    header = self.lastReadHeaders[channel]
            
                if hdrtype < Header.SEPARATOR: # time or delta has changed
                    if size < offset+3: return
                    header.time, offset = struct.unpack('!I', '\x00' + buffer[offset:offset+3])[0], offset+3
                
                if hdrtype < Header.TIME: # size and type also changed
                    if size < offset+4: return
                    header.size, header.type, offset = struct.unpack('!I', '\x00' + buffer[offset:offset+3])[0], ord(buffer[offset+3:offset+4]), offset+4

                if hdrtype < Header.MESSAGE: # streamId also changed
                    if size < offset+4: return
                    header.streamId, offset = struct.unpack('<I', buffer[offset:offset+4])[0], offset+4

                if header.time == 0xFFFFFF: # if we have extended timestamp, read it
                    if size < offset+4: return
                    header.extendedTime, offset = struct.unpack('!I', buffer[offset:offset+4])[0], offset+4
                    if _debug: print 'extended time stamp', '%x'%(header.extendedTime,)
                else:
                    header.extendedTime = None
            
                if hdrtype == Header.FULL:
                    header.currentTime = header.extendedTime or header.time
                    header.hdrtype = hdrtype
                elif hdrtype in (Header.MESSAGE, Header.TIME):
                    header.hdrtype = hdrtype

                # if _debug: print 'R', header, header.currentTime, header.extendedTime, '0x%x'%(hdrsize,)
             
                data = self.incompletePackets.get(channel, '') # are we continuing an incomplete packet?
            
                count = min(header.size - (len(data)), self.readChunkSize) # how much more
                
                if size < offset+count: return
                
                data, offset = data + buffer[offset:offset+count], offset+count
                if size == offset:
                    self.buffer = ''
                else:
                    self.buffer = buffer[offset:]

                # check if we need to send Ack
                if self.readWinSize is not None:
                    if self.bytesRead > (self.readWinSize0 + self.readWinSize):
                        self.readWinSize0 = self.bytesRead
                        ack = Message()
                        ack.time, ack.type, ack.data = self.relativeTime, Message.ACK, struct.pack('>L', self.readWinSize0)
                        self.writeMessage(ack)
                    
                if len(data) < header.size: # we don't have all data
                    self.incompletePackets[channel] = data
                else: # we have all data
                    if hdrtype in (Header.MESSAGE, Header.TIME):
                        header.currentTime = header.currentTime + (header.extendedTime or header.time)
                    elif hdrtype == Header.SEPARATOR:
                        if header.hdrtype in (Header.MESSAGE, Header.TIME):
                            header.currentTime = header.currentTime + (header.extendedTime or header.time)
                    if len(data) == header.size:
                        if channel in self.incompletePackets:
                            del self.incompletePackets[channel]
                    else:
                        data, self.incompletePackets[channel] = data[:header.size], data[header.size:]
                
                    hdr = Header(channel=header.channel, time=header.currentTime, size=header.size, type=header.type, streamId=header.streamId)
                    msg = Message(hdr, data)
#                    if _debug: print 'rtmp.parseMessage msg=', msg
                    if channel == self.PROTOCOL_CHANNEL_ID:
                        self.protocolMessage(msg)
                    else: 
                        self.messageReceived(msg)
    
    def writeMessage(self, message, stream=None):
#            if _debug: print 'rtmp.writeMessage msg=', message
            if stream is not None:
                message.streamId = stream.id
            
            # get the header stored for the stream
            if self.lastWriteHeaders.has_key(message.streamId):
                header = self.lastWriteHeaders[message.streamId]
            else:
                if self.nextChannelId <= self.PROTOCOL_CHANNEL_ID: 
                    self.nextChannelId = self.PROTOCOL_CHANNEL_ID+1
                header, self.nextChannelId = Header(self.nextChannelId), self.nextChannelId + 1
                self.lastWriteHeaders[message.streamId] = header
            if message.type < Message.AUDIO:
                header = Header(self.PROTOCOL_CHANNEL_ID)
               
            # now figure out the header data bytes
            if header.streamId != message.streamId or header.time == 0 or message.time <= header.time:
                header.streamId, header.type, header.size, header.time, header.delta = message.streamId, message.type, message.size, message.time, message.time
                control = Header.FULL
            elif header.size != message.size or header.type != message.type:
                header.type, header.size, header.time, header.delta = message.type, message.size, message.time, message.time-header.time
                control = Header.MESSAGE
            else:
                header.time, header.delta = message.time, message.time-header.time
                control = Header.TIME
            
            hdr = Header(channel=header.channel, time=header.delta if control in (Header.MESSAGE, Header.TIME) else header.time, size=header.size, type=header.type, streamId=header.streamId)
            assert message.size == len(message.data)

            data = ''
            while len(message.data) > 0:
                data += hdr.toBytes(control) # gather header bytes
                count = min(self.writeChunkSize, len(message.data))
                data += message.data[:count]
                message.data = message.data[count:]
                control = Header.SEPARATOR # incomplete message continuation
            if data:
                self.send(data)
                
    def protocolMessage(self, msg):
        if msg.type == Message.ACK: # update write window size
            self.writeWinSize0 = struct.unpack('>L', msg.data)[0]
        elif msg.type == Message.CHUNK_SIZE: # update read chunk size
            self.readChunkSize = struct.unpack('>L', msg.data)[0]
        elif msg.type == Message.WIN_ACK_SIZE: # update read window size
            self.readWinSize, self.readWinSize0 = struct.unpack('>L', msg.data)[0], self.bytesRead
        elif msg.type == Message.USER_CONTROL:
            type, data = struct.unpack('>H', msg.data[:2])[0], msg.data[2:]
            if type == 3: # client expects a response when it sends set buffer length
                streamId, bufferTime = struct.unpack('>II', data)
                response = Message()
                response.time, response.type, response.data = self.relativeTime, Message.USER_CONTROL, struct.pack('>HI', 0, streamId)
                self.writeMessage(response)
        else:
            if _debug: print 'ignoring protocol message type', msg.type
            
    def messageReceived(self, msg):
        if (msg.type == Message.RPC or msg.type == Message.RPC3) and msg.streamId == 0:
            cmd = Command.fromMessage(msg)
            # if _debug: print 'rtmp.messageReceived cmd=', cmd
            if cmd.name == 'connect':
                self.agent = cmd.cmdData
                self.objectEncoding = self.agent.objectEncoding if hasattr(self.agent, 'objectEncoding') else 0.0
                self._rpc = Message.RPC
                self.onConnect(cmd.args) # new connection
            elif cmd.name == 'createStream':
                self.rpc = Message.RPC if self.objectEncoding == 0.0 else Message.RPC3
                response = Command(name='_result', id=cmd.id, tm=self.relativeTime, type=self._rpc, args=[self._nextStreamId])
                self.writeMessage(response.toMessage())
                stream = self.createStream()
                self.onCreateStream(stream) # also notify others of our new stream
            elif cmd.name == 'closeStream':
                self.rpc = Message.RPC if self.objectEncoding == 0.0 else Message.RPC3
                assert msg.streamId in self.streams
                self.onCloseStream(self.streams[msg.streamId]) # notify closing to others
                del self.streams[msg.streamId]
            else:
                # if _debug: print 'Client.messageReceived cmd=', cmd
                self.onCommand(cmd) # RPC call
        else: # this has   to be a message on the stream
            assert msg.streamId != 0
            assert msg.streamId in self.streams
            # if _debug: print self.streams[msg.streamId], 'recv'
            stream = self.streams[msg.streamId]
            if not stream.client: stream.client = self 
            if msg.type == Message.RPC or msg.type == Message.RPC3:
                cmd = Command.fromMessage(msg)
                if _debug: print 'stream received cmd=', cmd
                if cmd.name == 'publish':
                    self.onStreamPublish(stream, cmd)
                elif cmd.name == 'play':
                    self.onStreamPlay(stream, cmd)
                elif cmd.name == 'closeStream':
                    self.onCloseStream(stream)
                    # TODO: Flash Player does not send createStream again when it publish/play for same NetStream
                    # Hence do not delete the stream from our record.
                    # del self.streams[msg.streamId]
#                elif cmd.name == 'seek':
#                    self.onStreamSeek(stream, cmd) 
            else: # audio or video message
                self.onStreamMessage(stream, msg)

    def accept(self):
        '''Method to accept an incoming client.'''
        response = Command()
        response.id, response.name, response.type = 1, '_result', self._rpc
        if _debug: print 'rtmp.accept() objectEncoding=', self.objectEncoding
        arg = amf.Object(level='status', code='NetConnection.Connect.Success',
                         description='Connection succeeded.', fmsVer='rtmplite/8,2')
        if hasattr(self.agent, 'objectEncoding'):
            arg.objectEncoding = self.objectEncoding
        response.setArg(arg)
        self.writeMessage(response.toMessage())
            
    def rejectConnection(self, reason=''):
        '''Method to reject an incoming client.'''
        response = Command()
        response.id, response.name, response.type = 1, '_error', self._rpc
        response.setArg(amf.Object(level='status', code='NetConnection.Connect.Rejected',
                        description=reason, fmsVer='rtmplite/8,2', details=None))
        self.writeMessage(response.toMessage())
            
    def redirectConnection(self, url, reason='Connection failed'):
        '''Method to redirect an incoming client to the given url.'''
        response = Command()
        response.id, response.name, response.type = 1, '_error', self._rpc
        extra = dict(code=302, redirect=url)
        response.setArg(amf.Object(level='status', code='NetConnection.Connect.Rejected',
                        description=reason, fmsVer='rtmplite/8,2', details=None, ex=extra))
        self.writeMessage(response.toMessage())

    def call(self, method, *args):
        '''Call a (callback) method on the client.'''
        cmd = Command()
        cmd.id, cmd.time, cmd.name, cmd.type = self._nextCallId, self.relativeTime, method, self._rpc
        cmd.args, cmd.cmdData = args, None
        self._nextCallId += 1
        if _debug: print 'rtmp.call method=', method, 'args=', args, ' msg=', cmd.toMessage()
        self.writeMessage(cmd.toMessage())
            
    def createStream(self):
        ''' Create a stream on the server side'''
        stream = Stream()
        stream.client = self
        stream.id = self._nextStreamId
        self.streams[stream.id] = stream
        self._nextStreamId += 1
        return stream

    def onConnect(self, args):
        if _debug: print 'client connection received', args
        if self.objectEncoding != 0 and self.objectEncoding != 3:
            self.rejectConnection(reason='Unsupported encoding ' + str(self.objectEncoding) + '. Please use NetConnection.defaultObjectEncoding=ObjectEncoding.AMF0')
            return
        self.path = str(self.agent.app) if hasattr(self.agent, 'app') else str(self.agent['app']) if isinstance(self.agent, dict) else None
        if not self.path:
            self.rejectConnection(reason='Missing app path')
            return
        name, ignore, scope = self.path.partition('/')
        if '*' not in self.server.apps and name not in self.server.apps:
            self.rejectConnection(reason='Application not found: ' + name)
            return
        # create application instance as needed and add in our list
        if _debug: print 'name=', name, 'name in apps', str(name in self.server.apps)
        app = self.server.apps[name] if name in self.server.apps else self.server.apps['*'] # application class
        if self.path in self.server.clients: inst = self.server.clients[self.path][0]
        else: inst = app()
        
        win_ack = Message()
        win_ack.time, win_ack.type, win_ack.data = self.relativeTime, Message.WIN_ACK_SIZE, struct.pack('>L', self.writeWinSize)
        self.writeMessage(win_ack)
        
#        set_peer_bw = Message()
#        set_peer_bw.time, set_peer_bw.type, set_peer_bw.data = self.relativeTime, Message.SET_PEER_BW, struct.pack('>LB', client.writeWinSize, 1)
#        self.writeMessage(set_peer_bw)
        
        try: 
            result = inst.onConnect(self, *args)
        except: 
            if _debug: print sys.exc_info()
            self.rejectConnection(reason='Exception on onConnect'); 
            return
        
        if not (result is True or result is None):
            self.rejectConnection(reason='Rejected in onConnect')
            return
        
        if self.path not in self.server.clients: 
            self.server.clients[self.path] = [inst]; inst._clients=self.server.clients[self.path]
        self.server.clients[self.path].append(self)
        if result is True:
            self.accept()
            self.connected = True
           
    def onCommand(self, cmd):
        inst = self.server.clients[self.path][0]
        if inst:
            if cmd.name == '_error':
                if hasattr(inst, 'onStatus'):
                    inst.onStatus(self, cmd.args[0])
            elif cmd.name == '_result':
                if hasattr(inst, 'onResult'):
                    inst.onResult(self, cmd.args[0])
            else:
                res, code, result = Command(), '_result', None
                try:
                    result = inst.onCommand(self, cmd.name, *cmd.args)
                except:
                    if _debug: print 'Client.call exception', (sys and sys.exc_info() or None) 
                    code = '_error'
                args = (result,) if result is not None else dict()
                res.id, res.time, res.name, res.type = cmd.id, self.relativeTime, code, self._rpc
                res.args, res.cmdData = args, None
                if _debug: print 'rtmp.call method=', code, 'args=', args, ' msg=', res.toMessage()
                self.writeMessage(res.toMessage())
        
    def closed(self): # client disconnected
        # client is disconnected, clear our state for application instance.
        if _debug: print 'cleaning up client', self.path
        if self.path in self.server.clients:
            inst = self.server.clients[self.path][0]
            self.server.clients[self.path].remove(self)
        for stream in self.streams.values(): # for all streams of this client
            self.onCloseStream(stream)
        self.streams.clear() # and clear the collection of streams
        inst = None
        if self.path in self.server.clients and len(self.server.clients[self.path]) == 1: # no more clients left, delete the instance.
            if _debug: print 'removing the application instance'
            inst = self.server.clients[self.path][0]
            inst._clients = None
            del self.server.clients[self.path]
        if inst is not None: 
            inst.onDisconnect(self)
            
    def onCreateStream(self, stream):
        pass
    
    def onCloseStream(self, stream):
        '''A stream is closed explicitly when a closeStream command is received from given client.'''
        inst = self.server.clients[self.path][0]
        if inst:
            if stream.name in inst.publishers and inst.publishers[stream.name] == stream: # clear the published stream
                inst.onClose(self, stream)
                del inst.publishers[stream.name]
            if stream.name in inst.players and stream in inst.players[stream.name]:
                inst.onStop(self, stream)
                inst.players[stream.name].remove(stream)
                if len(inst.players[stream.name]) == 0:
                    del inst.players[stream.name]
        stream.close()
    
    def onStreamPublish(self, stream, cmd):
        '''A new stream is published. Store the information in the application instance.'''
        try:
            stream.mode = 'live' if len(cmd.args) < 2 else cmd.args[1] # live, record, append
            stream.name = cmd.args[0]
            if _debug: print 'publishing stream=', stream.name, 'mode=', stream.mode
            inst = self.server.clients[self.path][0]
            if (stream.name in inst.publishers):
                raise ValueError, 'Stream name already in use'
            inst.publishers[stream.name] = stream # store the client for publisher
            inst.onPublish(self, stream)
#            path = getfilename(self.path, stream.name, self.server.root)
#            if stream.mode in ('record', 'append'): 
#                stream.recordfile = FLV().open(path, stream.mode)
            if stream.mode in ('record', 'append'): 
                raise ValueError, 'Recording not implemented'
            # elif stream.mode == 'live': FLV().delete(path) # TODO: this is commented out to avoid accidental delete
            response = Command(name='onStatus', id=cmd.id, tm=self.relativeTime, args=[amf.Object(level='status', code='NetStream.Publish.Start', description='', details=None)])
            self.writeMessage(response.toMessage(), stream)
        except ValueError, E: # some error occurred. inform the app.
            if _debug: print 'error in publishing stream', str(E)
            response = Command(name='onStatus', id=cmd.id, tm=self.relativeTime, args=[amf.Object(level='error',code='NetStream.Publish.BadName',description=str(E),details=None)])
            self.writeMessage(response.toMessage(), stream)

    def onStreamPlay(self, stream, cmd):
        '''A new stream is being played. Just updated the players list with this stream.'''
        try:
            inst = self.server.clients[self.path][0]
            name = stream.name = cmd.args[0]  # store the stream's name
            start = cmd.args[1] if len(cmd.args) >= 2 else -2
            if name not in inst.players:
                inst.players[name] = [] # initialize the players for this stream name
            if stream not in inst.players[name]: # store the stream as players of this name
                inst.players[name].append(stream)
#            if start >= 0 or start == -2 and name not in inst.publishers:
#                path = getfilename(self.path, stream.name, self.server.root)
#                if os.path.exists(path):
#                    stream.playfile = FLV().open(path)
#                    if start > 0: stream.playfile.seek(start)
#                    stream.playfile.reader(stream)
#                elif start >= 0: raise ValueError, 'Stream name not found'
            if start >= 0: raise ValueError, 'Stream name not found'
            if _debug: print 'playing stream=', name, 'start=', start
            inst.onPlay(self, stream)

            # Default chunk size is 128. It is pretty small when we stream high audio and video quality.
            # So, send the choosen chunk size to flash client.
            self.writeChunkSize = self.HIGH_WRITE_CHUNK_SIZE
            m0 = Message() # SetChunkSize
            m0.time, m0.type, m0.data = self.relativeTime, Message.CHUNK_SIZE, struct.pack('>L', self.writeChunkSize)
            self.writeMessage(m0)
            
#            m1 = Message() # UserControl/StreamIsRecorded
#            m1.time, m1.type, m1.data = self.relativeTime, Message.USER_CONTROL, struct.pack('>HI', 4, stream.id)
#            self.writeMessage(m1)
            
            m2 = Message() # UserControl/StreamBegin
            m2.time, m2.type, m2.data = self.relativeTime, Message.USER_CONTROL, struct.pack('>HI', 0, stream.id)
            self.writeMessage(m2)
            
            #self.writeMessage(Message(hdr=Header(time=self.relativeTime, type=Message.USER_CONTROL), data=struct.pack('>HI', 0, stream.id)));
            response = Command(name='onStatus', id=cmd.id, tm=self.relativeTime, args=[amf.Object(level='status',code='NetStream.Play.Start', description=stream.name, details=None)])
            self.writeMessage(response.toMessage(), stream)
        except ValueError, E: # some error occurred. inform the app.
            if _debug: print 'error in playing stream', str(E)
            response = Command(name='onStatus', id=cmd.id, tm=self.relativeTime, args=[amf.Object(level='error',code='NetStream.Play.StreamNotFound',description=str(E),details=None)])
            self.writeMessage(response.toMessage(), stream)
            
#    def onStreamSeek(self, stream, cmd):
#        '''A stream is seeked to a new position. This is allowed only for play from a file.'''
#        try:
#            offset = cmd.args[0]
#            if stream.playfile is None or stream.playfile.type != 'read': 
#                raise ValueError, 'Stream is not seekable'
#            stream.playfile.seek(offset)
#            response = Command(name='onStatus', id=cmd.id, tm=self.relativeTime, args=[amf.Object(level='status',code='NetStream.Seek.Notify', description=stream.name, details=None)])
#            self.writeMessage(response, stream)
#        except ValueError, E: # some error occurred. inform the app.
#            if _debug: print 'error in seeking stream', str(E)
#            response = Command(name='onStatus', id=cmd.id, tm=self.relativeTime, args=[amf.Object(level='error',code='NetStream.Seek.Failed',description=str(E),details=None)])
#            self.writeMessage(response, stream)
            
    def onStreamMessage(self, stream, message):
        '''Handle incoming media on the stream, by sending to other stream in this application instance.'''
        if stream.client is not None:
            inst = self.server.clients[self.path][0]
            result = inst.onPublishData(self, stream, message)
            if result:
                for s in (inst.players.get(stream.name, [])):
                    #if _debug: print 'D', stream.name, s.name
                    m = message.dup()
                    result = inst.onPlayData(s.client, s, m)
                    if result:
                        s.client.writeMessage(m, s)
#                if stream.recordfile is not None:
#                    stream.recordfile.write(message)


class FLV(baseFLV):
    '''Only the reader() task is changed to gevent instead of multitask from base class rtmp.FLV'''
    def __init__(self):
        baseFLV.__init__(self)
    
    def reader(self, client, stream):
        '''A gevent task that periodically reads the file and sends media in the stream to this client.'''
        if _debug: print 'reader started'
        try:
            while self.fp is not None:
                bytes = self.fp.read(11)
                if len(bytes) == 0:
                    response = Command(name='onStatus', id=stream.id, tm=client.relativeTime, args=[amf.Object(level='status',code='NetStream.Play.Stop', description='File ended', details=None)])
                    client.writeMessage(response.toMessage(), stream)
                    break
                type, len0, len1, ts0, ts1, ts2, sid0, sid1 = struct.unpack('>BBHBHBBH', bytes)
                length = (len0 << 16) | len1; ts = (ts0 << 16) | (ts1 & 0x0ffff) | (ts2 << 24)
                body = self.fp.read(length); ptagsize, = struct.unpack('>I', self.fp.read(4))
                if ptagsize != (length+11): 
                    if _debug: print 'invalid previous tag-size found:', ptagsize, '!=', (length+11),'ignored.'
                if stream is None or stream.client is None: break # if it is closed
                #hdr = Header(3 if type == Message.AUDIO else 4, ts if ts < 0xffffff else 0xffffff, length, type, stream.id)
                hdr = Header(0, ts, length, type, stream.id)
                msg = Message(hdr, body)
                # if _debug: print 'FLV.read() length=', length, 'hdr=', hdr
                # if hdr.type == Message.AUDIO: print 'r', hdr.type, hdr.time
                if type == Message.DATA: # metadata
                    amfReader = amf.AMF0(body) # TODO: use AMF3 if needed
                    name = amfReader.read()
                    obj = amfReader.read()
                    if _debug: print 'FLV.read()', name, repr(obj)
                client.writeMessage(msg, stream)
                if ts > self.tsp: 
                    diff, self.tsp = ts - self.tsp, ts
                    if _debug: print 'FLV.read() sleep', diff
                    gevent.sleep(diff / 1000.0)
        except gevent.GreenletExit:
            if _debug: print 'closing the reader'
        except: 
            if _debug: print 'closing the reader', (sys and sys.exc_info() or None)
        if self.fp is not None: 
            try: self.fp.close()
            except: pass
            self.fp = None
            

class Timer(object):
    '''Timer object used by SIP (rfc3261.Stack) and RTP (rfc3550.Session) among others.'''
    def __init__(self, app):
        self.app = app
        self.delay, self.running, self.gen = 0, False, None 
    def start(self, delay=None):
        if self.running: self.stop() # stop previous one first.
        if delay is not None: 
            self.delay = delay # set the new delay
        self.running = True
        self.gen = gevent.spawn_later(self.delay / 1000.0, self.app.timedout, self)
    def stop(self):
        if self.running: 
            self.running = False
        if self.gen: 
            try: self.gen.kill()
            except: pass
            self.gen = None


# -----------------------------------------------------------------------------
# Borrowed from voip.py after changing multitask to gevent
# -----------------------------------------------------------------------------

class User(object):
    '''The User object provides a layer between the application and the SIP stack.'''
    def __init__(self, sock, start=False):
        '''Construct a new User on given bound socket for SIP signaling. Starts listening for messages if start is set.
        '''
        self.sock, self.sockaddr = sock, kutil.getlocaladdr(sock)
        self._userListenerTask = self._userQueue = None
        self.address = self.username = self.password = self.proxy = None
        self.transport = rfc3261.TransportInfo(self.sock)
        self.stack = rfc3261.Stack(self, self.transport) # create a SIP stack instance
        self.reg = None   # registration UAC
        
        if _debug: print 'User created on listening=', sock.getsockname(), 'advertised=', self.sockaddr
        if start:
            self.start()
            
    def __del__(self):
        '''Destroy other internal references to Stack, etc.'''
        self.stop()
        self.reg = None
        if self.stack: self.stack.app = None # TODO: since self.stack has a reference to this, __del__will never get called. 
        self.sock = self.stack = None
    
    def start(self):
        '''Start the listener, if not already started.'''
        if self._userListenerTask is None:
            self._userListenerTask  = gevent.spawn(self._listener)
        return self
    
    def stop(self):
        '''Stop the listener, if already present'''
        if self._userListenerTask is not None:
            self._userListenerTask.kill()
        self._userListenerTask = None
        return self
    
    def _listener(self, maxsize=1500):
        '''Listen for transport messages on the signaling socket. The default maximum 
        packet size to receive is 1500 bytes.'''
        try:
            while self.sock and self.stack:
                data, remote = self.sock.recvfrom(maxsize)
                if _debug: print 'received[%d] from %s\n%s'%(len(data),remote,data)
                self.stack.received(data, remote)
        except GreenletExit: pass
        except: print 'User._listener exception', (sys and sys.exc_info() or None); traceback.print_exc(); raise
        if _debug: print 'terminating User._listener()'
        self._userListenerTask = None
    
    #-------------------- binding related ---------------------------------
    
    def bind(self, address, username=None, password=None, interval=180, refresh=False, update=False): 
        '''Register the local address with the server to receive incoming requests.
        This is a generator function, and returns either ('success', None) for successful
        registration or ('failed', 'reason') for a failure. The username and password 
        arguments are used to authenticate the registration. The interval argument 
        controls how long the registration is valid, and refresh if set to True causes 
        automatic refresh of registration before it expires. 
        If update is set to True then also update the self.transport.host with local address.uri.host.'''
        
        if self.reg: 
            return ('failed', 'Already bound')
        
        address = self.address = rfc2396.Address(str(address))
        if not address.uri.scheme: address.uri.scheme = 'sip' # default scheme
        self.username, self.password = username or self.username or address.uri.user, password or self.password

        if update: self.transport.host = kutil.getintfaddr(address.uri.host)
        reg = self.reg = self.createClient()
        reg.queue = Queue()
        result, reason = self._bind(interval=interval, refresh=refresh, wait=False)
        if _debug: print 'received response', result
        if result == 'failed': self.reg = None
        return (result, reason)
                    
    def close(self):
        '''Close the binding by unregistering with the SIP server.'''
        if not self.reg:
            return ('failed', 'not bound')
        reg = self.reg
        if reg.gen: reg.gen.kill(); reg.gen = None
        result, reason = self._bind(interval=0, refresh=False, wait=False)
        return (result, reason)
            
    def _bind(self, interval, refresh, wait):
        '''Internal function to perform bind and wait for response, and schedule refresh.'''
        try:
            if wait:
                gevent.sleep(interval - min(interval*0.05, 5)) # refresh about 5 seconds before expiry
            reg = self.reg
            reg.sendRequest(self._createRegister(interval))
            while True:
                response = reg.queue.get()
                if response.CSeq.method == 'REGISTER':
                    if response.is2xx:   # success
                        if refresh:        # install automatic refresh
                            if response.Expires:
                                interval = int(response.Expires.value)
                            if interval > 0:
                                reg.gen = gevent.spawn(self._bind, interval, refresh, True) # generator for refresh
                        return ('success', None)
                    elif response.isfinal: # failed
                        self.reg.gen = None; self.reg = None
                        return ('failed', str(response.response) + ' ' + response.responsetext)
        except GreenletExit:
            return ('failed', 'Greenlet closed')

    def _createRegister(self, interval):
        '''Create a REGISTER Message and populate the Expires and Contact headers. It assumes
        that self.reg is valid.'''
        if self.reg:
            ua = self.reg
            m = ua.createRegister(ua.localParty)
            m.Contact = rfc3261.Header(str(self.stack.uri), 'Contact')
            m.Contact.value.uri.user = ua.localParty.uri.user
            m.Expires = rfc3261.Header(str(interval), 'Expires')
            return m
        else: return None
    
    #-------------------------- Session related methods -------------------
    def connect(self, dest, sdp=None, provisional=False):
        '''Invite a remote destination to a session. This is a generator function, which 
        returns a (session, None) for successful connection and (None, reason) for failure.
        Either mediasock or sdp must be present. If mediasock is present, then session is negotiated 
        for that mediasock socket, without SDP. Otherwise, the given sdp (rfc4566.SDP) is used 
        to negotiate the session. On success the returned Session object has mysdp and yoursdp
        properties storing rfc4566.SDP objects in the offer and answer, respectively.'''
        dest = rfc2396.Address(str(dest))
        if not dest.uri:
            return (None, 'invalid dest URI')
        ua = self.createClient(dest)
        ua.queue = Queue() # to receive responses
        m = ua.createRequest('INVITE')
        
        if sdp is not None:
            m.body, local = str(sdp), None
            m['Content-Type'] = rfc3261.Header('application/sdp', 'Content-Type')
        else:
            return (None, 'sdp must be supplied')

        ua.sendRequest(m)
        session, reason = self.continueConnect((ua, dest, sdp), provisional=provisional)
        return (session, reason)
        
    def continueConnect(self, context, provisional):
        ua, dest, sdp = context
        while True:
            try:
                response = ua.queue.get()
            except GreenletExit: # connect was cancelled
                ua.sendCancel()
                raise
            if response.response == 180 or response.response == 183:
                context = (ua, dest, sdp)
                return (context, "%d %s"%(response.response, response.responsetext))
            if response.is2xx: # success
                session = Session(user=self, dest=dest)
                session.ua = hasattr(ua, 'dialog') and ua.dialog or ua
                session.mysdp, session.yoursdp = sdp, None
                
                if response.body and response['Content-Type'] and response['Content-Type'].value.lower() == 'application/sdp':
                    session.yoursdp = rfc4566.SDP(response.body)
                
                session.start(True)
                return (session, None)
            elif response.isfinal: # some failure
                return (None, str(response.response) + ' ' + response.responsetext)
    
    def accept(self, arg, sdp=None):
        '''Accept a incoming connection from given arg (dest, ua). The arg is what is supplied
        in the 'connect' notification from recv() method's return value.'''
        dest, ua = arg
        m = ua.createResponse(200, 'OK')
        ua.queue = Queue()
        
        if sdp is not None:
            m.body, local = str(sdp), None
            m['Content-Type'] = rfc3261.Header('application/sdp', 'Content-Type')
        else:
            return (None, 'sdp must be supplied')
            
        ua.sendResponse(m)
        
        try:
            while True:
                request = ua.queue.get(timeout=5) # wait for 5 seconds for ACK
                if request.method == 'ACK':
                    session, incoming = Session(user=self, dest=dest), ua.request
                    session.ua = hasattr(ua, 'dialog') and ua.dialog or ua
                    session.mysdp, session.yoursdp, session.local = sdp, None, local
                    session.remote= [(x.value.split(':')[0], int(x.value.split(':')[1])) for x in incoming.all('Candidate')] # store remote candidates 
                    
                    if incoming.body and incoming['Content-Type'] and incoming['Content-Type'].value.lower() == 'application/sdp':
                        session.yoursdp = rfc4566.SDP(incoming.body)
                    
                    session.start(False)
                    return (session, None)
        except Empty: pass
        except GreenletExit: pass
        
        return (None, 'didnot receive ACK')
    
    def reject(self, arg, reason='486 Busy here'):
        dest, ua = arg
        code, sep, phrase = reason.partition(' ')
        if code: 
            try: code = int(code)
            except: pass
        if not isinstance(code, int): 
            code = 603 # decline
            phrase = reason
        ua.sendResponse(ua.createResponse(code, phrase))
        
    def sendIM(self, dest, message):
        '''Send a paging-mode instant message to the destination and return ('success', None)
        or ('failed', 'reason')'''
        ua = self.createClient(dest)
        ua.queue = Queue() # to receive responses
        m = ua.createRequest('MESSAGE')
        m['Content-Type'] = rfc3261.Header('text/plain', 'Content-Type')
        m.body = str(message)
        ua.sendRequest(m)
        while True:
            response = ua.queue.get()
            if response.is2xx:
                return ('success', None)
            elif response.isfinal:
                return ('failed', str(response.response) + ' ' + response.responsetext)
    
    #-------------------------- generic event receive ---------------------
    def recv(self, timeout=None):
        if self._userQueue is None: self._userQueue = Queue()
        return self._userQueue.get(timeout=timeout)
    
    #-------------------------- Interaction with SIP stack ----------------
    # Callbacks invoked by SIP Stack
    def createServer(self, request, uri, stack): 
        '''Create a UAS if the method is acceptable. If yes, it also adds additional attributes
        queue and gen in the UAS.'''
        ua = request.method in ['INVITE', 'BYE', 'ACK', 'MESSAGE'] and rfc3261.UserAgent(self.stack, request) or None
        if ua: ua.queue = ua.gen = None
        if _debug: print 'createServer', ua
        return ua
    
    def createClient(self, dest=None):
        '''Create a UAC and add additional attributes: queue and gen.'''
        ua = rfc3261.UserAgent(self.stack)
        ua.queue = ua.gen = None
        ua.localParty  = self.address and self.address.dup() or None
        ua.remoteParty = dest and dest.dup() or self.address and self.address.dup() or None
        ua.remoteTarget= dest and dest.uri.dup() or self.address and self.address.uri.dup() or None
        ua.routeSet    = self.proxy and [rfc3261.Header(str(self.proxy), 'Route')] or None
        if ua.routeSet and not ua.routeSet[0].value.uri.user: ua.routeSet[0].value.uri.user = ua.remoteParty.uri.user
        if _debug: print 'createClient', ua
        return ua

    def sending(self, ua, message, stack): 
        pass
    
    def receivedRequest(self, ua, request, stack):
        '''Callback when received an incoming request.'''
        if _debug: print 'receivedRequest method=', request.method, 'ua=', ua, ' for ua', (ua.queue is not None and 'with queue' or 'without queue') 
        if hasattr(ua, 'queue') and ua.queue is not None:
            ua.queue.put(request)
        elif request.method == 'INVITE':    # a new invitation
            if self._userQueue is not None:
                self._userQueue.put(('connect', (str(request.From.value), ua)))
            else:
                ua.sendResponse(405, 'Method not allowed')
        elif request.method == 'MESSAGE':   # a paging-mode instant message
            if request.body and self._userQueue:
                ua.sendResponse(200, 'OK')      # blindly accept the message
                self._userQueue.put(('send', (str(request.From.value), request.body)))
            else:
                ua.sendResponse(405, 'Method not allowed')
        elif request.method == 'CANCEL':
            # TODO: non-dialog CANCEL comes here. need to fix rfc3261 so that it goes to cancelled() callback.
            if ua.request.method == 'INVITE': # only INVITE is allowed to be cancelled.
                self._userQueue.put(('close', (str(request.From.value), ua)))
        else:
            ua.sendResponse(405, 'Method not allowed')

    def receivedResponse(self, ua, response, stack):
        '''Callback when received an incoming response.'''
        if _debug: print 'receivedResponse response=', response.response, ' for ua', (ua.queue is not None and 'with queue' or 'without queue') 
        if hasattr(ua, 'queue') and ua.queue is not None: # enqueue it to the ua's queue
            ua.queue.put(response)
            if _debug: print 'response put in the ua queue'
        else:
            if _debug: print 'ignoring response', response.response
        
    def cancelled(self, ua, request, stack): 
        '''Callback when given original request has been cancelled by remote.'''
        if hasattr(ua, 'queue') and ua.queue is not None:
            ua.queue.put(request)
        elif self._userQueue is not None and ua.request.method == 'INVITE': # only INVITE is allowed to be cancelled.
            self._userQueue.put(('close', (str(request.From.value), ua)))
        
    def dialogCreated(self, dialog, ua, stack):
        dialog.queue = ua.queue
        dialog.gen   = ua.gen 
        ua.dialog = dialog
        if _debug: print 'dialogCreated from', ua, 'to', dialog
        # else ignore this since I don't manage any dialog related ua in user
        
    def authenticate(self, ua, obj, stack):
        '''Provide authentication information to the UAC or Dialog.'''
        obj.username, obj.password = self.username, self.password 
        return bool(obj.username and obj.password)

    def createTimer(self, app, stack):
        '''Callback to create a timer object.'''
        return Timer(app)
    
    # rfc3261.Transport related methods
    def send(self, data, addr, stack):
        '''Send data to the remote addr.'''
        if _debug: print 'sending[%d] to %s\n%s'%(len(data), addr, data)
        if self.sock:
            try: self.sock.sendto(data, addr)
            except socket.error:
                if _debug: print 'socket error in sending' 


class Session(object):
    '''The Session object represents a single session or call between local User and remote
    dest (Address).'''
    def __init__(self, user, dest):
        self.user, self.dest = user, dest
        self.ua = self.local = self.remote = self._sessionRunTask = self.remotemediaaddr = None
        self._sessionQueue = Queue()
        
    def start(self, outgoing):
        '''A generator function to initiate the connectivity check and then start the run
        method to receive messages on this ua.'''
        self._sessionRunTask = gevent.spawn(self._run)
        
    def send(self, message):
        if self.ua:
            ua = self.ua
            m = ua.createRequest('MESSAGE')
            m['Content-Type'] = rfc3261.Header('text/plain', 'Content-Type')
            m.body = str(message)
            ua.sendRequest(m)
    
    def recv(self, timeout=None):
        return self._sessionQueue.get(timeout=timeout)
    
    def close(self, outgoing=True):
        '''Close the call and terminate any generators.'''
        self.local = self.remote = None
        if self._sessionRunTask is not None: # close the generator
            try:
                self._sessionRunTask.kill()
            except GreenletExit:
                pass
            self._sessionRunTask = None
        if self.ua:
            ua = self.ua
            if outgoing:
                ua.sendRequest(ua.createRequest('BYE'))
                try: response = ua.queue.get(timeout=5) # wait for atmost 5 seconds for BYE response
                except Empty: pass # ignore the no response for BYE
            self.ua.queue = None
            self.ua.close()  # this will remove dialog if needed
            self.ua = None
    
    def _run(self):
        '''Thread method for this task.'''
        try:
            while True:
                try: message = self.ua.queue.get()
                except AttributeError: break # when self.ua is closed, and set to null
                if message.method: # request
                    self._receivedRequest(message)
                else: # response
                    self._receivedResponse(message)
        except GreenletExit: pass
        except: 
            if _debug: traceback.print_exc()
        self._sessionRunTask = None
           
    def _receivedRequest(self, request):
        '''Callback when received an incoming request.'''
        if _debug: print 'session receivedRequest', request.method, 'ua=', self.ua
        ua = self.ua
        if request.method == 'INVITE': self._receivedReInvite(request)
        elif request.method == 'BYE': # remote terminated the session
            ua.sendResponse(200, 'OK')
            self.close(outgoing=False)
            self._sessionQueue.put(('close', None))
        elif request.method == 'MESSAGE': # session based instant message
            ua.sendResponse(200, 'OK')
            message = request.body
            self._sessionQueue.put(('send', message))
        elif request.method not in ['ACK', 'CANCEL']:
            m = ua.createResponse(405, 'Method not allowed in session')
            m.Allow = rfc3261.Header('INVITE, ACK, CANCEL, BYE', 'Allow')
            ua.sendResponse(m)
    
    def _receivedResponse(self, response):
        '''Callback when received an incoming response.'''
        if _debug: print 'session receivedResponse', response.response, 'ua=', self.ua
        method = response.CSeq.method
        if _debug: print 'Ignoring response ', response.response, 'of', method
    
    def _receivedReInvite(self, request): # only accept re-invite if no new media stream.
        if not (hasattr(self, 'media') and isinstance(self.media, MediaSession)):
            self.ua.sendResponse(501, 'Re-INVITE Not Supported')
        if not (request.body and request['Content-Type'] and request['Content-Type'].value.lower() == 'application/sdp'):
            self.ua.sendResponse(488, 'Must Supply SDP in Request Body')
        else:
            oldsdp, newsdp = self.yoursdp, rfc4566.SDP(request.body)
            if oldsdp and newsdp and len(oldsdp['m']) != len(newsdp['m']): # don't accept change in m= lines count
                self.ua.sendResponse(488, 'Change Not Acceptable Here')
            else:
                self.media.setRemote(newsdp)
                self.mysdp, self.yoursdp, m = self.media.mysdp, self.media.yoursdp, self.ua.createResponse(200, 'OK')
                m.body, m['Content-Type'] = str(self.mysdp), rfc3261.Header('application/sdp', 'Content-Type')
                self.ua.sendResponse(m)
                self._sessionQueue.put(('change', self.yoursdp))

    def hold(self, value): # send re-INVITE with SDP ip=0.0.0.0
        if hasattr(self, 'media') and isinstance(self.media, MediaSession):
            self.media.hold(value);
            self.change(self.media.mysdp)
        else: raise ValueError('No media attribute found')

    def change(self, mysdp):
        if self.ua:
            ua, self.mysdp = self.ua, mysdp; m = ua.createRequest('INVITE')
            m['Content-Type'] = rfc3261.Header('application/sdp', 'Content-Type')
            m.body = str(mysdp)
            ua.sendRequest(m)
            self._sessionQueue.put(('change', self.media.mysdp));


# -----------------------------------------------------------------------------
# Borrowed from siprtmp.py after changing multitask to gevent
# -----------------------------------------------------------------------------


class Context(object):
    '''Context stores state needed for gateway. The client.context property holds an instance of this class. The methods invoked
    by RTMP side are prefixed with rtmp_ and those invoked by SIP side are prefixed sip_. All such methods are actually generators.
    '''
    def __init__(self, app, client):
        self.app, self.client = app, client
        self.user = self.session = self._connectTask = self.incoming = None # SIP User and session for this connection
        self.publish_stream = self.play_stream = self.media = self._preferred = None # streams on RTMP side, media context and preferred rate
        self._incomingHandlerTask = self._sessionHandlerTask = None  # generators that needs to be closed on unregister
        if not hasattr(self.app, '_ports'): self.app._ports = {}     # used to persist SIP port wrt registering URI. map: uri=>port
        
    def rtmp_register(self, login=None, passwd='', display=None, rate='wideband'):
        scheme, ignore, aor = self.client.path.partition('/')
        self._preferred = rate
        if _debug: print 'rtmp-register scheme=', scheme, 'aor=', aor, 'login=', login, 'passwd=', '*'*(len(passwd) if passwd else 0), 'display=', display
        addr = '"%s" <sip:%s>'%(display, aor) if display else 'sip:%s'%(aor)
        sock = socket.socket(type=socket.SOCK_DGRAM) # signaling socket for SIP
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        port = self.app._ports.get(aor, 0)
        try: sock.bind((self.client.server.int_ip, port)); port = sock.getsockname()[1] 
        except: 
            if _debug: print '  exception in register', (sys and sys.exc_info() or None)
            self.client.rejectConnection(reason='Cannot bind socket port')
            return
        #self.ports[name] = sock.getsockname()[1] # store the port number
        # TODO: storing and keeping the persistent port per user doesn't work well if the app is re-loaded in brief interval.
        try:
            user = self.user = User(sock).start() # create SIP user. Ownership of sock is moved to User.
            user.context, user.username, user.password = self, login, passwd
            if user.password:
                if _debug: print '  registering addr=', addr, 'port=', port
                result, reason = user.bind(addr, refresh=True)
                if _debug: print '  registration returned', result, reason
                if result == 'failed': 
                    self.client.rejectConnection(reason=reason)
                    return
                self._incomingHandlerTask = gevent.spawn(self._incomingHandler) # incoming SIP messages handler
            else: user.address = rfc2396.Address(addr)
            if _debug: print '  register successful'
            self.client.accept()
        except: 
            if _debug: print '  exception in register', (sys and sys.exc_info() or None)
            self.client.rejectConnection(reason=sys and str(sys.exc_info()[1]) or 'Server Error')
        
    def rtmp_unregister(self):
        try:
            if self.user is not None:
                if _debug: print 'rtmp-unregister', (self.client and self.client.path or None)
                self._cleanup()    # close the call first, if any
                self.user.close()
                self.user.stop()
                if self.user.sock:
                    try: self.user.sock.close()
                    except: pass
                    self.user.sock = None
                self.user.context = None; self.user = None
                if self._incomingHandlerTask is not None: self._incomingHandlerTask.kill(); self._incomingHandlerTask = None
                if self._sessionHandlerTask is not None: self._sessionHandlerTask.kill(); self._sessionHandlerTask = None
            if self.media:
                self.media.close(); self.media = None
        except:
            if _debug: print '  exception in unregister', (sys and sys.exc_info() or None)
    
    def rtmp_invite(self, dest, *args):
        try:
            if _debug: print 'rtmp-invite %r %r'%(dest, args)
            if self.user: # already a registered user exists
                if not self.session: # not already in a session, so create one
                    try: dest = rfc2396.Address(dest) # first try the default scheme supplied by application
                    except: dest = rfc2396.Address(self.user.address.uri.scheme + ':' + dest) # otherwise scheme is picked from registered URI
                    if _debug: print '  create media context'
                    media = MediaContext(self, None, self.client.server.int_ip, self._preferred, rfc3550.gevent_Network, *args) # create a media context for the call
                    try:
                        self._connectTask = gevent.spawn(self.user.connect, dest, sdp=media.session.mysdp, provisional=True)
                        session, reason = self._connectTask.get()
                        if _debug: print '  session=', session, 'reason=', reason
                        while reason is not None and reason.partition(" ")[0] in ('180', '183'):
                            self.client.call('ringing', reason)
                            self._connectTask = gevent.spawn(self.user.continueConnect, session, provisional=True)
                            session, reason = self._connectTask.get()
                    except:
                        media.close()
                        if self._connectTask is not None: raise
                        else: return # else call was cancelled in another task
                    self._connectTask = None # because the generator returned, and no more pending outgoing call
                    if session: # call connected
                        self.media, self.session, session.media = media, session, media.session
                        self.media.session.setRemote(session.yoursdp)
                        self._sessionHandlerTask = gevent.spawn(self._sessionHandler) # receive more requests from SIP
                        codecs = self.media.accepting()
                        if _debug: print 'sip-accepted %r'%(codecs,)
                        self.client.call('accepted', *codecs)
                    else: # connection failed, close media socket
                        media.close()
                        self.client.call('rejected', reason)
                else: self.client.call('rejected', 'Already in an active or pending call')
            else: self.client.call('rejected', 'Registration required before making a call')
        except:
            if _debug: print '  exception in invite', (sys and sys.exc_info() or None)
            self.client.call('rejected', 'Internal server error')

    def rtmp_accept(self, *args):
        if _debug: print 'rtmp-accept %r'%(args,)
        incoming = self.incoming; self.incoming = reason = media = None # clear self.incoming, and store value in incoming
        try:
            if self.user is not None and incoming is not None:
                self.media = MediaContext(self, incoming[1].request, self.client.server.int_ip, self._preferred, rfc3550.gevent_Network, *args) # create a media context for the call
                if self.media.session.mysdp is None: reason = '488 Incompatible SDP'
                else:
                    session, reason = self.user.accept(incoming, sdp=self.media.session.mysdp)
                    if session: # call connected
                        self.session, session.media = session, self.media.session
                        self._sessionHandlerTask = gevent.spawn(self._sessionHandler) # receive more requests from SIP
                        codecs = self.media.accepting()
                        if _debug: print 'sip-accepted %r'%(codecs,)
                        self.client.call('accepted', *codecs)
                    elif not reason: reason = '500 Internal Server Error in Accepting'
            else:
                if _debug: print '  no incoming call. ignored.'
        except:
            if _debug: print '  exception in rtmp_accept', (sys and sys.exc_info()) 
            reason = '500 Internat Server Exception'
        if reason:
            if self.media:
                self.media.close(); self.media = None
            if self.user: self.user.reject(incoming, reason) # TODO: a better way would be to reject in _incominghandler
            if self.client: self.client.call('byed')
            
    def rtmp_reject(self, reason='Decline'):
        try:
            if _debug: print 'rtmp-reject'
            if self.user is not None and self.incoming is not None:
                self.user.reject(self.incoming, reason)
                self.incoming = None # no more pending incoming call
            elif _debug: print '  no incoming call. ignored'
        except:
            if _debug: print '  exception in reject', (sys and sys.exc_info() or None)
        
    def rtmp_bye(self):
        try:
            if _debug: print 'rtmp-bye'
            if self.session is None and self._connectTask is not None: # pending outgoing invite
                if _debug: print '  cancel outbound invite'
                self._connectTask.kill()
                self._connectTask = None
            elif self.session:
                self._cleanup()
        except:
            if _debug: print '  exception in bye', (sys and sys.exc_info() or None)
            traceback.print_exc()

    def sip_invite(self, dest):
        try:
            if _debug: print 'sip-invite' 
            self.client.call('invited', str(dest), str(self.user.address))
        except:
            if _debug: print '  exception in sip_invite', (sys and sys.exc_info() or None)
        
    def sip_cancel(self, dest):
        try: 
            if _debug: print 'sip-cancel' 
            self.client.call('cancelled', str(dest), str(self.user.address))
        except:
            if _debug: print '  exception in sip_cancel', (sys and sys.exc_info() or None)
        
    def sip_bye(self):
        try: 
            if _debug: print 'sip-bye' 
            self.client.call('byed')
        except:
            if _debug: print '  exception in sip_bye', (sys and sys.exc_info() or None)
        
    def sip_hold(self, value):
        try: 
            if _debug: print 'sip-hold', value 
            self.client.call('holded', value)
        except:
            if _debug: print '  exception in sip_hold', (sys and sys.exc_info() or None)
        
    def _incomingHandler(self): # Handle incoming SIP messages
        try:
            user = self.user
            while True:
                cmd, arg = user.recv()
                if _debug: print 'incominghandler', cmd
                if cmd == 'connect': # incoming invitation, inform RTMP side
                    self.incoming = arg
                    self.sip_invite(str(rfc2396.Address(arg[0])))
                elif cmd == 'close': # incoming call cancelled
                    self.incoming = None
                    self.sip_cancel(str(rfc2396.Address(arg[0])))
        except GreenletExit: pass
        except: 
            if _debug: print 'incominghandler exiting', (sys and sys.exc_info() or None)
        self._incomingHandlerTask = None
            
    def _sessionHandler(self): # Handle SIP session messages
        try:
            session = self.session
            while True:
                cmd, arg = session.recv()
                if cmd == 'close': self.sip_bye(); break # exit from session handler
                if cmd == 'change': # new SDP received from SIP side
                    self.sip_hold(bool(arg and arg['c'] and arg['c'].address == '0.0.0.0'))
            self._cleanup()
        except GreenletExit: pass
        except:
            if _debug: print 'exception in sessionhandler', (sys and sys.exc_info() or None)
        self._sessionHandlerTask = None
        if _debug: print 'sessionhandler exiting'
        
    def _cleanup(self): # cleanup a session
        if self.session:
            self.session.close()    # close the session
            self.session = None
        if self.media:
            self.media.close()
            self.media = None
        if self._sessionHandlerTask is not None: self._sessionHandlerTask.kill(); self._sessionHandlerTask = None

    def received(self, media, fmt, packet): # an RTP packet is received. Hand over to sip_data.
        if fmt is not None:
            self.sip_data(fmt, packet)

    def sip_data(self, fmt, data): # handle media stream received from SIP
        try:
            p = rfc3550.RTP(data) if not isinstance(data, rfc3550.RTP) else data
            if _debugAll: print ' <-s pt=%r seq=%r ts=%r ssrc=%r marker=%r len=%d'%(p.pt, p.seq, p.ts, p.ssrc, p.marker, len(p.payload))
            if self.media:
                messages = self.media.rtp2rtmp(fmt, p)
                if self.play_stream and messages:
                    for message in messages:
                        if _debugAll: print 'f<-  type=%r len=%r codec=0x%02x'%(message.type, message.size, message.data and ord(message.data[0]) or -1)
                        self.client.writeMessage(message, self.play_stream)
        except (ValueError, AttributeError), E:
            if _debug: print '  exception in sip_data', E; traceback.print_exc()

    def rtmp_data(self, stream, message): # handle media data message received from RTMP
        try:
            if _debugAll: print 'f->  type=%x len=%d codec=0x%02x'%(message.header.type, message.size, message.data and ord(message.data[0]) or -1)
            if self.media:
                messages = self.media.rtmp2rtp(stream, message)
                if self.session and self.media.session and messages:
                    for payload, ts, marker, fmt in messages:
                        if _debugAll: print ' ->s fmt=%r %r/%r ts=%r marker=%r len=%d'%(fmt.pt, fmt.name, fmt.rate, ts, marker, len(payload))
                        self.media.session.send(payload=payload, ts=ts, marker=marker, fmt=fmt)
        except:
            if _debug: print '  exception in rtmp_data'; traceback.print_exc()

    def rtmp_sendDTMF(self, digit):
        try:
            if _debug: print 'rtmp-sendDTMF', digit
            if self.media:
                messages = self.media.dtmf2rtp(digit)
                if self.session and self.media.session and messages is not None:
                    for payload, ts, marker, fmt in messages:
                        self.media.session.send(payload=payload, ts=ts, marker=marker, fmt=fmt)
        except:
            if _debug: print '  exception in rtmp_sendDTMF'; traceback.print_exc()
            
    def rtmp_hold(self, value):
        try:
            if _debug: print 'rtmp-hold', value
            self.session.hold(value)
        except:
            if _debug: print '  exception in rtmp_hold'; traceback.print_exc()

    def requestFIR(self):
        # TODO: merge with siprtmp.Context
        # TODO: this should be sent if we received INFO for FIR from remote.
        if self.session and self.session.ua:
            ua = self.session.ua
            m = ua.createRequest('INFO')
            m['Content-Type'] = rfc3261.Header('application/media_control+xml', 'Content-Type')
            m.body = '''<?xml version="1.0" encoding="utf-8" ?>
<media_control>
    <vc_primitive>
        <to_encoder>
            <picture_fast_update></picture_fast_update>
        </to_encoder>
    </vc_primitive>
</media_control>
'''
            ua.sendRequest(m)


class Gateway(App):
    '''The SIP-RTMP gateway implemented as RTMP server application.'''
    def __init__(self):
        App.__init__(self)
    def onConnect(self, client, *args):
        App.onConnect(self, client, args)
        # if you want to allow multiple registrations for same SIP user, comment following two lines
        for c in self.clients: 
            c.closed()
        client.context = Context(self, client)
        client.context.rtmp_register(*args)
        return None
    def onDisconnect(self, client):
        App.onDisconnect(self, client)
        client.context.rtmp_unregister()
    def onCommand(self, client, cmd, *args):
        App.onCommand(self, client, cmd, args)
        if hasattr(client.context, 'rtmp_%s'%(cmd,)) and callable(eval('client.context.rtmp_%s'%(cmd,))): 
            gevent.spawn(eval('client.context.rtmp_%s'%(cmd,)), *args)
        elif _debug: print 'invalid command', cmd
    def onPublish(self, client, stream):
        if _debug: print self.name, 'onPublish', client.path, stream.name
        client.context.publish_stream = stream
    def onClose(self, client, stream):
        if _debug: print self.name, 'onClose', client.path, stream.name
        client.context.publish_stream = None
    def onPlay(self, client, stream):
        if _debug: print self.name, 'onPlay', client.path, stream.name
        client.context.play_stream = stream
        client.context.media._au2_ts0 = client.context.media._au2_tm = 0
    def onStop(self, client, stream):
        if _debug: print self.name, 'onStop', client.path, stream.name
        client.context.play_stream = None
    def onStatus(self, client, info):
        if _debug: print self.name, 'onStatus', info
    def onResult(self, client, result):
        if _debug: print self.name, 'onResult', result
    def onPublishData(self, client, stream, message):
        client.context.rtmp_data(stream, message)
        return False

class Wirecast(App):
    '''Similar to rtmp module's class except this uses gevent.'''
    def __init__(self):
        App.__init__(self)

    def onPublish(self, client, stream):
        App.onPublish(self, client, stream)
        if not hasattr(stream, 'metaData'): stream.metaData = None
        if not hasattr(stream, 'avcSeq'): stream.avcSeq = None
        
    def onPlay(self, client, stream):
        App.onPlay(self, client, stream)
        if not hasattr(stream, 'avcIntra'): stream.avcIntra = False
        publisher = self.publishers.get(stream.name, None)
        if publisher and publisher.metaData: # send published meta data to this player joining late
            client.writeMessage(publisher.metaData.dup(), stream)
    
    def onPublishData(self, client, stream, message):
        if message.type == Message.DATA and not stream.metaData: # store the first meta data on this published stream for late joining players
            stream.metaData = message.dup()
        if message.type == Message.VIDEO and message.data[:2] == '\x17\x00': # H264Avc intra + seq, store it
            stream.avcSeq = message.dup()
        return True

    def onPlayData(self, client, stream, message):
        if message.type == Message.VIDEO: # only video packets need special handling
            if message.data[:2] == '\x17\x00': # intra+seq is being sent, possibly by Flash Player publisher.
                stream.avcIntra = True
            elif not stream.avcIntra:  # intra frame hasn't been sent yet.
                if message.data[:2] == '\x17\x01': # intra+nalu is being sent, possibly by wirecast publisher.
                    publisher = self.publishers.get(stream.name, None)
                    if publisher and publisher.avcSeq: # if a publisher exists
                        stream.avcIntra = True
                        client.writeMessage(publisher.avcSeq.dup(), stream)
                        return True # so that the caller sends message
                return False # drop until next intra video is sent
        return True

class FlashServer(StreamServer):
    def __init__(self, options):
        global sip
        def handle(socket, address):
            if _debug: print 'connection[%r] received from %r'%(socket, address)
            client = FlashClient(self, socket)
            try:
                while True:
                    data = socket.recv(8192)
                    if not data:
                        break
#                    if _debug: print 'received[%d] %r'%(len(data), truncate(data))
                    client.received(data)
            except: traceback.print_exc()
            if _debug: print 'connection[%r] closed from %r'%(socket, address)
            try: client.closed()
            except: pass
            try: socket.close()
            except: pass
    
        StreamServer.__init__(self, (options.host, options.port), handle)
        self.int_ip, self.ext_ip, self.root = options.int_ip, options.ext_ip, options.root
        self.apps, self.clients = dict({'*': App, 'sip': Gateway if sip else App, 'wirecast': Wirecast}), dict()


# The main routine to start, run and stop the service
if __name__ == '__main__':
    from optparse import OptionParser
    parser = OptionParser(version='SVN $Revision$, $Date$'.replace('$', ''))
    parser.add_option('-i', '--host',    dest='host',    default='0.0.0.0', help="listening IP address for RTMP. Default '0.0.0.0'")
    parser.add_option('-p', '--port',    dest='port',    default=1935, type="int", help='listening port number for RTMP. Default 1935')
    parser.add_option('-r', '--root',    dest='root',    default='./',       help="document path prefix. Directory must end with /. Default './'")
    parser.add_option('-l', '--int-ip',  dest='int_ip',  default='0.0.0.0', help="listening IP address for SIP and RTP. Default '0.0.0.0'")
    parser.add_option('-e', '--ext-ip',  dest='ext_ip',  default=None,      help='IP address to advertise in SIP/SDP. Default is to use "--int-ip" or any local interface')
    parser.add_option('-f', '--fork',    dest='fork',    default=1, type="int", help='Number of processes to use for concurrency. Default is 1.')
    parser.add_option('-d', '--verbose', dest='verbose', default=False, action='store_true', help='enable debug trace')
    parser.add_option('-D', '--verbose-all', dest='verbose_all', default=False, action='store_true', help='enable full debug trace for all modules')
    (options, args) = parser.parse_args()
    
    import rtmp
    rtmp._debug = options.verbose_all
    if sip:
        import siprtmp, app.voip, std.rfc3550, std.rfc3261
        siprtmp._debug = std.rfc3261._debug = options.verbose_all
        app.voip._debug = options.verbose or options.verbose_all
    _debug = options.verbose or options.verbose_all
    _debugAll = options.verbose_all
    
    if _debug and not audiospeex:
        print 'warning: audiospeex module not found; disabling transcoding to/from speex'
    
    if options.ext_ip: 
        kutil.setlocaladdr(options.ext_ip)
    elif options.int_ip != '0.0.0.0': 
        kutil.setlocaladdr(options.int_ip)
        
    try:
        if _debug: print time.asctime(), 'Fast SIP-RTMP Gateway Starts - %s:%d' % (options.host, options.port)
        server = FlashServer(options)
        server.start()
        for i in range(options.fork-1):
            if not gevent.fork():
                break
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    if _debug: print time.asctime(), 'Fast SIP-RTMP Gateway Stops'
