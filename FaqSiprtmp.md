# Frequently Asked Questions (SIP-RTMP gateway) #

### My gateway does not work. What do I do? ###

Please start your gateway with "-d" command line option, so that it prints detailed trace information including the SIP messages. Then capture the trace, e.g., using Unix "script" command. Finally, send your error report and the trace to [support group](http://groups.google.com/group/myprojectguide). You can post a message from web or via email after joining the group.

### Does it work with other SIP servers or clients? ###

Depends on what the other SIP client or server is. If there are interoperability bugs, we will be happy to resolve those.

### Can I directly connect from Flash client to SIP server? ###

No. You need to go through the siprtmp.py (SIP-RTMP gateway). The path is Flash client connect to SIP-RTMP gateway, which in turn registers and communicates with the SIP server. But you can communicate with any existing SIP server, as long as there are no interoperability bugs, between the gateway and the SIP server.

### How do I test a SIP registration and call? ###

Using the builtin videoPhone.swf applictaion (which is also hosted at http://myprojectguide.org/p/siprtmp). Support you want to register with gateway running on gateway.host.com and SIP server of iptel.org with username myname, password mypass, use the following input text when prompted to register.
Gateway URL: rtmp://gateway.host.com/sip
SIP URL: myname@iptel.org
Auth username: myname
Auth password: mypass
Display name: My Name
Once registered, use the SIP URL of target to make call, e.g., yourname@iptel.org

### Can I run the gateway on Amazon EC2 cloud? ###

Yes, but you will need to use the latest sources of rtmplite and p2p-sip projects from SVN. Both rtmplite ([r61](https://code.google.com/p/rtmplite/source/detail?r=61)) and p2p-sip ([r29](https://code.google.com/p/rtmplite/source/detail?r=29)) were modified to allow specifying an IP address to advertise in SIP/SDP, which can be different than the local IP address. This is useful for EC2, because the node gets local IP address in range 10.x.x.x but can be reached from public IP address which is different. For example, if your EC2 node's private IP is 10.245.221.44 and public IP is 50.17.154.98, then you should start SIP-RTMP gateway with -e option as follows.
```
$ python siprtmp.py -d -e 50.17.154.98
```
You can know your public IP from the public DNS name of your node, e.g., host name of ec2-50-17-154-98.compute-1.amazonaws.com means IP is 50.17.154.98. I have tested siprtmp.py on EC2 using a call between VideoPhone.swf example and X-Lite via the SIP proxy running on iptel.org.

There may be issues if you run your own SIP proxy server on another EC2 node since siprtmp.py and your SIP server should now connect using private IP instead of public IP. Please let us know if you have problems.

### Why does it pick 127.0.0.1 as the listening IP? ###

When the Flash side connects to siprtmp, it prints the listening/advertised IP of the corresponding SIP User Agent. If you see local IP address here, then you won't be able to communicate with SIP phones/servers on other machines. The most common reason for this is that your 'hostname' points to local IP in your /etc/hosts file. The siprtmp code uses gethostbyname(gethostname()) to find the listening/advertised IP.

To work around this, you can supply the -l option with your correct IP address, e.g.,
```
$ python siprtmp.py -d -l 192.168.0.3
```
By default if -l (listening IP) is supplied, but -e (advertised IP) is not, then it uses the same -l value for advertised IP.

### Can I run the gateway or server on Google App Engine? ###

No. The existing API of Google App Engine does not support long lived general purpose TCP connection that can be used for RTMP. The channel API uses another protocol, XMPP, and cannot be used as long-lived connection to your GAE application. A long-lived TCP connection is needed for RTMP media server implementation.

### How do I build my own Flash application to connect to the gateway? ###

The necessary API is documented in the http://code.google.com/p/rtmplite/source/browse/trunk/siprtmp.py source code itself. In particular, you use NetConnection's connect and supply the appropriate parameters.

### When dialing out from web client, should I dial phone number or SIP address? ###

You must dial a SIP address of the form "user@domain" or "user@ip-address". If you have PSTN dialing available via your gateway, then use the "phone-number@ip-address-of-pstn-gateway", e.g., "7140@192.1.2.3" instead of just "7140".

### When I call from X-lite it responds with "488 Incompatible SDP". Why? ###

By default X-lite has only PCMU and PCMA codec enabled. You will need to go to audio options of X-lite and enable the Speex/16000 (wideband codec).

### How I do enable Speex to G.711 transcoding ###

In siprtmp.py (and siprtmp\_gevent.py), we have added support for transcoding between speex and pcmu/pcma voice codecs using the py-audio project. Just follow [py-audio](http://code.google.com/p/py-audio) build instructions only for audiospeex module (ignoring the instructions for audiodev and audiotts) and place the generated audiospeex.so in your PYTHONPATH before starting siprtmp.py. Make sure you have the latest version of rtmplite and p2p-sip from SVN. More details of the codecs related enahancement are in [siprtmp.py](http://code.google.com/p/rtmplite/source/browse/trunk/siprtmp.py) under top level file comments heading "Major Updates".

### Does it work with Ekiga? ###

Yes. Please make sure you use the latest p2p-sip sources from SVN, specially [r39](https://code.google.com/p/rtmplite/source/detail?r=39) or later, which works around the lack of RTP padding support in Ekiga.

### Does it work with Asterisk? ###

Depends on what codec Asterisk supports. The siprtmp gateway supports speex/16000 ~~or 8000 (audio)~~ and x-flv/90000 (video). From what I understand, the Asterisk codec does not support speex. You can compile Asterisk to support speex using speex/8000 and not speex/16000. ~~The VideoPhone and siprtmp gateway now have support to dynamically switch from default 16000 (wideband) to 8000 (narrowband). Please see the next question on how to make siprtmp work with 8000 Hz sampling.~~

In short it will not work with Asterisk unless Asterisk supports speex/16000.

**Update:** We found a bug in Asterisk 1.6.2 (may also be on other 1.6.x) that it sends incorrect Content-Length in 200 OK response (answer) to INVITE if the the INVITE request (offer) has video in SDP, but unsupported by target. To work around this you can comment out the following line in p2p-sip's [src/std/rfc3261.py](http://code.google.com/p/p2p-sip/source/browse/trunk/src/std/rfc3261.py). (on or near line 217)
```
if self.body != None and bodyLen != len(body): raise ValueError, ...
```

### How can I use Speex/8000 (narrowband) instead of Speex/16000 (wideband)? ###

~~Flash Player by default uses 16000 Hz sampling for Speex. The new version of siprtmp and rtmplite (version 6.0 and above) support both 8000 and 16000 Hz sampling for Speex. In the VideoPhone Flash application, you can select the narrowband (8000) Speex in the right click menu. The right click menu allows you to switch between narrowband and wideband. The selection must be done before registration, but is saved along with you other registration data if you select "Remember me" option. The selection is supplied to the siprtmp.py gateway in the NetConnection.connect method as the rate attribute, and is used for audio format sampling rate.~~

I realized the hard way that even if I change Microphone's rate to 8, the Flash Player still uses 16 kHz for speex encoded stream from Microphone. So in the current form a flash application (e.g., VideoPhone.swf or VideoIO.swf) does not support speex/8000 (narrowband) even though the siprtmp.py gateway can handle it. On the other hand, a flash application can play speex/8000 (narrowband). I am working on modifying the speex wideband payload to narrowband in siprtmp.py if needed.

### How to send DTMF touch tone? ###

I have added a patch sent by another person to both VideoPhone and siprtmp.py. During a call, you can click on the button in the top-left corner of VideoPhone Flash application to show a dial-pad. The dial-pad will allow you to enter digits during a call. It invokes "sendDTMF" method on siprtmp.py, which in turn uses the rfc2833.py module to send out the digits if the remote end had sent "telephone-event" in SDP during session initiation. Please use the latest code from SVN/[r34](https://code.google.com/p/rtmplite/source/detail?r=34) or later to get this patch.

The following text describes how to use RFC 2198 along with RFC 2833 to send digits, and how to use SIP INFO method to send digits:

Using RFC2833 is preferred way to send DTMF touch tones. You can use the rfc2833.py and rfc2198.py modules of p2p-sip/39peers project as mentioned in http://39peers.net/download/doc/report.html (search for "Touch-tone interface" towards the end). Since siprtmp.py already has the RTP session, you can use the existing RTP session to
send out the digits. For example if you sending digits "1234" first create the RFC 2833 payloads as:
```
dtmfs = rfc2833.createDTMFs("1234")
```
This will return a list of DTMF objects. Then use RFC 2198 to create redundant payloads. Suppose your timestamp is 10000, interval of 1600 between digits and negotiated payload-type is 97, then as follows:
```
t0, td, pt = 10000, 1600, 97
input = []
for dtmf in dtmfs:
    dtmf = repr(dtmf)    # convert DTMF to str
    input.append((pt, t0, dtmf))
    t0 += td
payload = rfc2198.createRedundant(input)
```
You can now use the payload as the RTP's payload to send out in the existing RTP session. See siprtmp.py's rtmpdata method. Something like the following should work, where fmt should be set to your audio format for touch-tone.
```
self.session.media.send(payload=payload, ts=10000, marker=False, fmt=...)
```
We will try to add this feature to siprtmp.py soon, in the next version.

On the other hand, if you do want to use the SIP INFO method, you can use the following example. In siprtmp.py, the Context's self.session represents the voip.Session object of the existing session. Session has a ua object representing the Dialog which has createRequest and sendRequest methods. You can use them as follows.
```
ua = self.session.ua
m = ua.createRequest("INFO")
m['Content-Type'] = rfc3261.Header('application/dtmf-relay', 'Content-Type')
m.body = 'Signal=5\nDuration=160'
ua.sendRequest(m)
```
This will send out the SIP INFO request in the current dialog/session with Content-Type of "application/dtmf-relay" and content of
```
Signal=5
Duration=160
```
The Content-Length will automatically be added correctly to the request.

### How to send SIP MESSAGE for instant message? ###

You can send SIP MESSAGE in an established call in siprtmp.py using Context's self.session (which is voip.Session object) as follows. In class Context add the following:
```
    def rtmp_sendMessage(self, message):
        try:  yield self.session.send(message)
        except: pass
```
The Session class uses Content-Type of text/plain to send a SIP MESSAGE with given message as content.
Now you can call "sendMessage" with argument "message" from your Flash application using NetConnection's call method.

To receive incoming SIP MESSAGE, in Context's `_sessionhandler` method, similar to the check for "close" add the following check.
```
                if cmd == 'send': self.client.call('receivedMessage', arg)
```
Then add a public function of receivedMessage(text:String) in your ActionScript class for NetConnection.client. If you are using Flash-VideoIO, define receivedMessage in your HTML/Javascript page that embeds VideoIO.swf.

If you want to send a out-of-dialog paging-mode SIP MESSAGE, you need to use sendIM of user object itself.
```
    def rtmp_sendPagingMessage(self, dest, message):
        try: result, reason = yield self.user.sendIM(dest, message)
        except: pass
```
On incoming side, you will need to modify Context's `_incominghandler` parallel to close as follows:
```
                elif cmd == 'send': # incoming paging SIP MESSAGE
                    source, body = arg # arg is actually a tuple
                    self.client.call("receivedPagingMessage", str(source), str(body))
```
And define public function receivedPagingMessage(src:String, body:String) in your ActionScript.

We will try to add instant message send/receive in the code, if there are huge demand for this. Please send a request on the support group to demand this feature.

### How to use RTMPS on the server? ###

(contributed by Dmitry) There are no changes needed in rtmplite source code. You need to
  1. install [stunnel](http://www.stunnel.org)
  1. add the following in `stunnel.conf`
```
[rtmps]
accept = 443
connect = 1935
```
  1. In `NetConnection` object in your Flash application, set the `proxyType` to "best" before doing a connect
```
 nc.proxyType = "best"
```
  1. In `NetConnection` object's `connect()` method use the URL with "rtmps" scheme, e.g., "rtmps://your-server/sip".

If you want use non-443 port, for example 8443, change `stunnel.conf` and use port number in your URL, e.g., "rtmps://your-server:8443/sip".

For Flash Player's RTMPS to work the following applies.
  1. The certificate must be signed by a popular CA (not self signed). I believe there are CAs that can sign your certificate for free, but haven't tried them. I haven't been able to get a self signed certificate to work with RTMPS from Flash Player.
  1. Pre-loading a self-signed certificate/CA in browser settings does not work for Flash Player's RTMPS.
  1. The common name (CN) of the certificate must be the host name that you are connecting to. For example, if your certificate is for CN of `server.com` and you are connecting to `rtmps://xyz.server.com` or `rtmps://192.1.2.3` (which is the IP address) then it will **not** work. Alternatively, you can get the CN in your certificate as wildcard `*.server.com`

### How do I have multiple clients registered with same SIP address? ###

Currently the Gateway class in siprtmp.py (in rtmplite project) disconnects other clients with same scope when a new client connects. This prevents multiple registrations for the same SIP address. For example, if first client connects with `rtmp://localhost/sip/alice@iptel.org` and then second client also connects to `rtmp://localhost/sip/alice@iptel.org` then the first client is disconnected. There are two approaches to solving this problem:

1) do not disconnect other clients. This can be done by modifying `siprtmp.py::Gateway::onConnect` method. Just comment out one line as shown below.
```
   def onConnect(self, client, *args):
       App.onConnect(self, client, args)
-      for c in self.clients: multitask.add(c.connectionClosed())
       client.context = Context(self, client)
       ...
```
There may be potential problems in audio path, but not sure, since audio path is maintained using named streams within the scope, i.e., `/sip/alice@iptel.org`.

2) let the clients connect with random scope, e.g., `rtmp://localhost/sip/alice@iptel.org/72812` where 72812 is some random number uniquely generated for each client. This avoids any audio path problem since each client has separate named streams now. Also, it avoids disconnection of other clients since each client will have potentially different random number. However, `siprtmp.py::Context::rtmp_register` method needs to be modified to extract the SIP address correctly as shown below.
```
   def rtmp_register(self, login=None, passwd='', display=None, rate='wideband'):
       global agent
       scheme, ignore, aor = self.client.path.partition('/')
+      aor = aor.split('/', 1)[0]   # ignore /random in /aor/random if present
       if rate == 'narrowband': self._audio.rate = 8000
       ...
```
I think 2 is a better approach but requires changes both in client (`VideoPhone`) and server (`rtmplite`), whereas 1 requires a change only in server.

### Why cannot play media published using wirecast to rtmplite? ###

You can, but will need to use the Wirecast application instead of default App, and is accessible at `rtmp://your-server/wirecast` when using rtmp.py or siprtmp\_gevent.py as your RTMP server. If you want it to be available at another URL just change the URL-app to application class mapping (look for apps property in both files).

The problem is that Wirecast sends the AVC seq message only once in the beginning and then does not send it again. Hence if a Flash Player joins the stream after publishing has already started, then the Flash Player never receives the AVC seq message which is crucial in decoding the video. On the other hand Flash Player (11+) with H264Avc video codec mode sends the AVC seq message periodically, before every intra frame. To work around the limitation of Wirecast, I created a sub-class of App to store the published AVC seq messages, and send it to any player who join afterwards if no explicit AVC seq message was sent before intra frame. The sub-class also drops any non-infra frame after a player joins before an AVC seq and an intra frame are sent to the player.

### The second call with Asterisk does not work? ###

Thanks to Roman Tsymbalyuk, we found a problem in the SIP ACK generated by Asterisk. It uses the same branch parameter in the top-via header resulting in incorrect branch (and transaction) matching in my SIP library. Thus, the ACK from Asterisk for the second call is matched with the transaction of the previous ACK, and treated as a retransmission instead of completing the second call. A quick work-around to fix this is as follows (This will be checked in soon). In p2p-sip's src/std/rfc3261.py file's Stack class' `_`receivedRequest method, locate a call to app.createTransaction(r). Modify to add the following change.
```
            if app:
                t = app.createTransaction(r)
+               if r.method == 'ACK' and t.id in self.transactions:
+                   del self.transactions[t.id]  # no need to store the ACK transaction.
            elif r.method != 'ACK':
                self.send(Message.createResponse(404, "Not found", None, None, r))
```