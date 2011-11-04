# Copyright (c) 2011, Kundan Singh. All rights reserved. see README for details.

'''
This is a simple tunnel application that receives connection on RTMPT and forwards on RTMP.

I have tested this with Flash VideoIO on Flash Player 11 and rtmplite's rtmp.py server. To test it yourself, first start an RTMP server, e.g.,
  $ python rtmp.py -d
This listens on default TCP port 1935. The -d option enabled debug trace during development.
Now start this tunnel in debug mode listening on port 8080 (RTMPT/HTTP) and forwarding to localhost:1935 (RTMP).
  $ python rtmpt.py -l 0.0.0.0:8080 -t 127.0.0.1:1935 -d
By default rtmpt.py listens on port 8080 on RTMPT and forward to localhost:1935 on RTMP, so the -l and -t options above are unnecessary.
Now point your browser to http://myprojectguide.org/p/flash-videoio/test.html for the Flash videoIO test page.
Set the "src" property to rtmpt://localhost:8080/myapp?publish=live to start publishing using RTMPT.
To play the stream, open another browser instance or tab to the same test page, and set the "src"
property to rtmpt://localhost:8080/myapp?play=live
Note that the RTMP server is doing actual media conferencing, whereas this tunnel application just forwards between RTMPT/HTTP and RTMP.
You can have some participants on "rtmp" and others on "rtmpt" as long as both connect to the same back end RTMP server under the same
connection scope.

Known issues: this tunnel software is in alpha with known issues:
1. Disconnection of publisher when player disconencts.
'''

import random, socket, traceback, SocketServer

_debug = False

class Session(object):
    def __init__(self):
        self.id = str(random.randint(1000000000, 9999999999))
        self._sock, self._timeout, self._pending, self._next = None, 0.020, [], 0
    
    def connect(self, target_address):
        sock = self._sock = socket.socket(family=socket.AF_INET, type=socket.SOCK_STREAM)
        sock.connect(target_address)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1) # make it non-block
        sock.settimeout(self._timeout)
        
    def close(self):
        if self._sock is not None:
            self._sock.close()
            self._sock = None
    
    def sendrecv(self, seq, data):
        if seq == self._next:
            self._next += 1
            if _debug: print '=>%r=>   (%s)'%(seq, self.id)
            if data: self._sock.send(data)
            while self._pending:
                found = [(i, x[0], x[1]) for i, x in enumerate(self._pending) if x[0] == self._next]
                if not found: break
                index, seq, data = found[0]
                del self._pending[index]
                self._next += 1
                if _debug: print '  %r=>   (%s)'%(seq, self.id)
                if data: self._sock.send(data)
            try: response = self._sock.recv(8192)
            except socket.timeout: response = ''
        else:
            if _debug: print '=>%r     (%s)'%(seq, self.id)
            self._pending.append((seq, data))
            response = '' # no need to respond with data in this case
        return response
        
class tunnel(SocketServer.ThreadingMixIn, SocketServer.TCPServer):
    allow_reuse_address = True 

class handler(SocketServer.StreamRequestHandler):
    intervals = ('\x01', '\x03', '\x05', '\x09', '\x11', '\x21')
    
    def handle(self):
        if _debug: print 'created new handler for ', self.request
        interval, failed = self.intervals[0], 0
        try:
            while True:
                firstline = body = response = None
                headers = {}
                firstline = self.readline()
                if firstline is None: raise ValueError, 'connection closed in reading first line'
                if _debug: print firstline
                method, path, protocol = firstline.split(' ')
                if method != 'POST': raise ValueError, 'invalid method ' + method
                while True:
                    line = self.readline()
                    if line is None: raise ValueError, 'connection closed in reading headers'
                    if _debug: print line
                    if not line: break
                    name, value = line.split(':', 1)
                    headers[name.lower().strip()] = value.strip()
                ctype, clen, conn = [headers.get(name.lower(), None) for name in ('content-type', 'content-length', 'connection')]
                if ctype != 'application/x-fcs': raise ValueError, 'invalid content-type ' + ctype
                if clen: clen = int(clen)
                if clen > 0: body = self.read(clen)
                if path == '/fcs/ident2':
                    self.send_error(404, 'Not Found')
                elif path == '/open/1':
                    while True:
                        session = Session()
                        if session.id not in self.server.sessions:
                            break
                        session.close()
                    try:
                        session.connect(self.server.target_address)
                        self.server.sessions[session.id] = session
                        self.send_response(session.id + '\n')
                    except socket.error:
                        session.close()
                        self.send_error(500, 'Cannot Connect to Server')
                else:
                    parts = path.split('/')
                    if len(parts) == 4 and parts[1] in ('idle', 'send', 'close'):
                        ignore, command, sessionId, seq = parts
                        session, seq = self.server.sessions.get(sessionId, None), int(seq)
                        if not session:
                            self.send_error(500, 'Invalid session ' + sessionId)
                        elif command == 'idle' or command == 'send':
                            response = session.sendrecv(seq, body if command == 'send' else None)
                            if response:
                                interval, failed = self.intervals[0], 0
                            else:
                                failed += 1
                                if failed >= 10:
                                    index = self.intervals.index(interval)
                                    if index < len(self.intervals) - 1: index += 1
                                    interval, failed = self.intervals[index], 0
                                    if _debug: print 'changed interval to 0x%x'%(ord(interval),)
                            self.send_response(interval + response)
                        elif command == 'close':
                            del self.server.sessions[session.id]
                            session.close()
                            self.send_response('\x00')
                    else:
                        raise ValueError, 'invalid path ' + path
                if conn == 'close':
                    self.wfile.close()
                    break
        except:
            if _debug: traceback.print_exc()
            self.wfile.close()
    
    def send_error(self, code, reason):
        self.write('HTTP/1.1 %d %s'%(code, reason), 'Content-Length: 0')
        
    def send_response(self, body):
        self.write('HTTP/1.1 200 OK', 'Content-Type: application/x-fcs', 'Content-Length: %d'%(len(body) if body else 0), body=body)
        
    def write(self, *args, **kwargs):
        data = '\r\n'.join(args) + '\r\n\r\n'
        if _debug: print data[:-2]
        if 'body' in kwargs and kwargs.get('body'): data += kwargs.get('body')
        self.wfile.write(data)
        
    def read(self, length):
        return self.rfile.read(length)
        
    def readline(self):
        value = self.rfile.readline()
        return None if not value else value.rstrip() if value[-1] == '\n' else value

def run(server_address = ('0.0.0.0', 8080), target_address = ('127.0.0.1', 1935),
        server_class=tunnel, handler_class=handler):
    if _debug: print 'starting HTTP server on', server_address, 'target', target_address
    server = server_class(server_address, handler_class)
    server.target_address = target_address
    server.sessions = {} # map from session.id to session
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        if _debug: print '\ninterrupted'
    server.server_close()


# The main routine to start, run and stop the service
if __name__ == '__main__':
    from optparse import OptionParser
    parser = OptionParser(version='SVN $Revision$, $Date$'.replace('$', ''))
    parser.add_option('-l', '--listen',  dest='listen',  default='0.0.0.0:8080', help="listening transport address. Default '0.0.0.0:8080'")
    parser.add_option('-t', '--target',  dest='target',  default="127.0.0.1:1935", help="target server address. Default is '127.0.0.1:1935'")
    parser.add_option('-d', '--verbose', dest='verbose', default=False, action='store_true', help='enable debug trace')
    (options, args) = parser.parse_args()
    
    _debug = options.verbose
    listen, target = [(x.partition(':')[0], int(x.partition(':')[2])) for x in (options.listen, options.target)]
    run(server_address=listen, target_address=target)
