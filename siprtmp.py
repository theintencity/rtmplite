# Copyright (c) 2007-2009, Mamta Singh. All rights reserved. See LICENSING for details.

'''
Introduction
------------
The goal of this project is to allow multimedia calls from Flash Player to SIP network and vice-versa. This allows either a
web browser or a standalone AIR-based application to call to and receive call from a SIP phone. The SIP-RTMP gateway implements
translation of signaling as well as media to support audio, video and text with the SIP user agent. The client side ActionScript
library allows any third-party to build user interface for the web-based soft-phone. The Gateway can run either as a server hosted
by the provider, or as a local application on the client's host.

For other Flash-SIP projects see:
  1. http://www.gtalk2voip.com/sipper/
  2. http://www.flaphone.com/ (formerly Flashphone.ru)
  3. http://code.google.com/p/red5phone/

Design choices
--------------
Two design alternatives: dedicated server vs. server app. The advantages of a dedicated server that implements SIP-RTMP gateway
is that management is easier, and the application does just one thing. On the other hand implementing the gateway as a RTMP server
application is more extensible, and the same server can be used to implement other applications. I outline the implementations
using both alternatives, and finally pick the second alternative in this implementation.

In the dedicated server case, the FlashServer class of rtmp.py module is extended into a Gateway class. This subclass then
overrides the various methods such as publishhandler and playhandler to map to similar operations using the SIP library such as
register, invite or accept. One advantage of this approach is that the Gateway class can be used as a component in other 
applications without having to run a separate Server.

In the server application case, the Gateway class extends the App class of rtmp.py to implement the SIP-RTMP gateway application,
and installs itself as application named 'sip'. The Gateway class overrides the methods such as onConnect, onPublish, etc., to
map to the SIP library methods such as register, invite or accept. One advantage of this approach is that the same Server can
be used to perform other RTMP server functions besides hosting a SIP gateway.

There are several API alternatives from the Flash client point of view as well:
  1. The RTMP NetConnection is just used as RPC layer to control the SIP library.
  2. Have 1-to-1 mapping between a RTMP NetConnection and a SIP user agent. (choosen one) 
  3. Have 1-to-1 mapping between a RTMP connection's scope and a SIP multi-party conference.

In the first approach, the application connects to the gateway using NetConnection URL of the form 'rtmp://server/sip'. Once
connected, the application uses various RPC commands and indications to register, invite, accept or bye a SIP session. Each
command has a full set of arguments needed to execute that command. For example, NetConnection.call('invite',..., 'alice','bob')
will make a call from local user 'alice' to remote user 'bob'. One major problem with this approach is that there is no
information hiding or abstraction in the API. Hence, any connected application can alter the state of any user or call in the
library. One could use cookies to store state information, but nevertheless the API is pretty rudimentary.

In the second approach, a single SIP user agent is associated with a NetConnection. The application connects to the URL of the
form 'rtmp://server/sip/alice@example.net' and supplies additional connection arguments such as display name and password.
The gateway associates this connection with the user address-of-record (AOR) 'sip:alice@example.net'. In particular, it sends
SIP REGISTER on behalf of this user, and keeps refreshing the registration as long as the NetConnection is connected. Thus, this
NetConnection represents an abstraction of the SIP user agent for this user. The application uses RPC commands and indications
to invite, accept or bye a SIP session in this user agent. In the simple implementation, a single user agent is capable of a 
single SIP session at any instance. The API for multi-line SIP user agent will be more complex. When the application calls
NetConnection.call('invite', ..., 'bob@home.com') the gateway sends a SIP INVITE request to the AOR sip:bob@home.com. When a 
call is successful, the application can use the NetStream named 'local' and 'remote' to send and receive audio/video with the
remote user. In this approach a multi-party call is implemented entirely in the application by having two different NetConnection
objects in two different calls, or by making a call to a separate multi-point conference server. Additional commands and 
indications are used to represent text messages and presence information. Alternatively, a SharedObject named 'contacts' could
represent the local user's contact list with presence information accessible from the Flash application. Since the SharedObject
is scoped to the NetConnection's URL, it represents that particular user's contact list.

In the third approach, the Flash application connects a NetConnection to a conference URL of the form 'rtmp://server/sip/abc1'. 
In this case the conference is identified by name 'abc1'. Each connection to this URL creates a new conference leg from an
RTMP user. Then the application uses NetConnection RPC commands such as 'invite', 'accept' and indications such as 'invited',
'accepted', to inform the gateway to change the membership of the conference, either by inviting a new user or by accepting an
incoming invitation. The gateway can be distributed such that the conference context is maintained in a gateway-farm. The 
membership information can be stored using a SharedObject accessible from the Flash application. One major advantage of this 
approach is that it maps the URL to a conference context and supports built-in multi-party conferencing. Whenever a new participant
joins the conference, the gateway informs the application about the stream name for that participant. The application opens 
a new NetStream for that stream name to play, and receives media from that participant on that stream. There is at most one 
published stream in a NetConnection, which represents the local participant's media.

The third approach seems most logical and complete, however requires implementation of a distributed conference state in the
gateway farm, and multi-party conference server logic. We do not want to mix media going to the Flash application, because
not all media (e.g., video) can be mixed and audio mixing incurs additional CPU load on the server. For example, a typical
mixer employs a decode-add-encode cycle. However, existing SIP clients do not usually handle multiple media streams well.
Hence the conference server logic becomes more complex where it mixes some audio going to SIP user agents, and does not mix
audio going to the RTMP clients. Secondly, maintaining a consistent conference membership information among the distributed
gateway farm is a challenge which requires implementing various XCON extensions to server. Thirdly, a centralized conference model
doesn't mend well with a P2P-SIP network. More details about centralized, distributed and P2P-SIP conferencing can be found
in the work of http://kundansingh.com. Because of all these issues I have decided to implement the second approach instead.
The second approach is described in much detail next.

Design description
------------------
This module defines two classes: Gateway and Context. The Gateway class extends the rtmp.App class to implement the SIP-RTMP
gateway application in the RTMP server. The Context class implements the translator context for each user or connection from
the RTMP side. The main routine is similar to that in rtmp.py, in that it launches the server additionally with the "sip" gateway
application service. 

Since there is a one-to-one mapping between a RTMP connection and a SIP user, a single Context behaves as a single line SIP
user agent, which can be in at most one SIP registration and at most one SIP call state at any time. I think implementing
multiple lines can be easily done in the Flash application by creating additional connections to the server. 

The Gateway class overrides these methods of the App class: onConnect causes a SIP registration, onDisconnect causes a SIP
unregistration, onCommand invokes various commands such as 'invite', 'bye', 'accept', 'reject' from the RTMP side to the
SIP side, onPublish and onClose update the published stream information, onPlay and onStop update the played stream information
and onPublishData handle the media data from RTMP to SIP side. A new context is created in onConnect and destroyed in 
onDisconnect. The Client (RTMP) as well as User (SIP) objects store a reference to the context. I use the SIP stack from the
p2p-sip (39 Peers) project at http://39peers.net.

The Context class maintains a mapping between RTMP client and SIP user (single line phone). It also maintains state regarding
the media sesion, incoming and outgoing pending call, and published and played streams. One unique feature of the translator
is that it tries to re-use the same port for the given SIP URL when registering with the SIP server. This way we avoid 
registering multiple contacts in the SIP server for the same SIP URL.

As you will see in the later section, a connection from the RTMP client supplies a SIP URL of the registering user. The context
maps this request to a SIP REGISTER request using the local contact address for that SIP URL. This allows the gateway to
receive incoming SIP calls for this SIP URL. When the RTMP client invokes commands such as "invite", they get mapped to the
SIP side using the methods defined on the User class. Similarly, when the User class invokes callback, they get mapped to the
RTMP callbacks such as "invited". 

The RTMP client MUST create at most one published NetStream and at most one played NetStream for the given connection. 
The published stream supplies the client's audio and video to the context. The context maps this audio and video data to the
appropriate SIP side using the RTP module available in the SIP stack. Similarly the audio and video data from the SIP side
coming in RTP are mapped to the audio and video data given to the played stream to the RTMP client.

Interoperability with SIP/SDP/RTP
---------------------------------
The Flash application must be version 10 or higher so that it can support Speex audio codec.  We can only interoperate with 
SIP user agents that support Speex/16000 or Speex/8000. The reason is that Flash Player supports only limited set of codecs for 
audio captured from Microphone. Flash Player 9 and earlier supported only proprietary NellyMoser codec, which are not understood 
or supported beyond Flash platform. Flash Player 10 incorporated Speex audio codec which is an open source and open specification, 
and are available in several SIP applications such as X-Lite. The support of Speex audio codec is not as widely available in PSTN 
gateways though. Note that we support wideband (16000 Hz) and narrowband (8000 Hz) variant of Speex audio codec. The selection
can be done from Flash application during NetConnection.connect. 

This section describes other interoperability issues with a SIP or Flash client. When the client issues an outbound
"invite" request, the mapped SIP INVITE advertises the session using SDP module of the SIP stack. This session contains 
media stream offer for both audio and video. The audio stream has only Speex/16000 format whereas the video stream has RTMP
specific proprietary x-flv format (more about this later). An example SDP offer is shown below:

    v=0
    o=- 1247290948 1247290948 IN IP4 Macintosh-2.local
    s=-
    c=IN IP4 192.168.1.3
    t=0 0
    m=audio 22700 RTP/AVP 96
    a=rtpmap:96 speex/16000
    m=video 26498 RTP/AVP 97
    a=rtpmap:97 x-flv/90000

If the response contains a both valid audio and video answer streams, then we assume that the remote side is also our own Flash
application, as it can support the proprietary x-flv video format. If the answer contains port=0 for video stream, that means
the remote party does not support our proprietary video format, then we assume that the remote side is standard SIP user agent.
Similar SDP negotiation happens for incoming call. In particular, if incoming SDP offer does not have speex audio codec, then
we disable the audio stream. Similarly if the incoming SDP offer does not have a x-flv video codec, then we disable the video
stream.

One caveat in the implementation is that the media matching is done when the Flash application accepts the incoming call. Thus,
it is possible that for an incoming call, the Flash application gets alerted even when there is no matching media session.
And when the Flash application tries it accept the incoming call, the gateway performs media matching and rejects the incoming
SIP call, and informs the Flash application that call got disconnected. I need to fix this by doing media matching as soon as
incoming SIP invitation is received.

If the remote party does not support x-flv video but supports speex/16000 audio, then we only send audio data from RTMP to
SIP side. Similarly, only audio data will be mapped from SIP to RTMP side, hence the Flash application will not see remote 
party's video. Standard RTP and RTCP formatting is used for sending/receiving data to/from the SIP side. The timestamp
of RTP is deirived from the RTMP message's time stamp property. In particular, RTMP message uses 'millisecond' unit where as
RTP header uses 'clock rate' unit. Since we support only 16000 Hz clock rate, each millisecond unit is equivalent to
16 clock rate unit, and each speex frame of typically 20 ms is equivalent to 320 clock rate.

If the remote party supports x-flv, then we disable the speex/16000 audio. Even though the remote side is SIP, we assume that
it is backed by a Flash application with a similar gateway as this. Since x-flv format includes both audio and video, we
do not need another audio only stream in the session. Next I describe the x-flv format.

The x-flv video format is basically a modification of the RTMP media messages, so that it works with RTP. It includes interleaved
audio and video packets. One problem with RTMP media message is that there is no sequence number which makes it hard to detect
and correct packet losses over RTP/UDP transport. Another problem is that video packet size can be huge, which causes problem
with UDP transport -- certain NATs may drop large packets. For these reasons, the RTMP media message is broken down into smaller
chunks such that each chunk can be sent in a single RTP message. 

The timestamp of RTP is derived from the RTMP message's time stamp property. The payload type reflect 'x-flv/90000' media type
as negotiated in SDP. In particular for outgoing call, it will use payload type of 97 and for incoming call, it will use the 
payload type that was advertised by the remote party's SDP. If remote party is also using our gateway, then it will be 97.
The sequence number, SSRC and other fields in the RTMP message are taken care by the RTP module of the SIP stack and are 
independent of the RTMP side, as long as the sequence number keeps incrementing for each RTP packet sent, and SSRC is 
randomly generated for the session and remains constant in the session. 

The RTP paylaod is constructed as follows. First the RTMP message is constructed in its entirety. The Message object in rtmp
module has type, size and time properties. These are added in that order using big endian 32-bit number each as the header,
followed by the data part of the message. Note that the data part of the media message actually has one byte type information
containing codec type (e.g., 0xb2 for speex/16000), but we treat the whole data part including the type together to simplify
the translation. Thus the assembled media message looks as follows:

        0                   1                   2                   3
        0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
       +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
type   |          RTMP message type                                    |
       +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
size   |          RTMP message body size                               |
       +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
time   |          RTMP message time stamp                              |
       +=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+
body   |          RTMP message body ...                                |
time   |            The size of this body is                           |
time   |            in the second field above                          |
       +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
        
Now the assembled media message is broken down in smaller chunks such that each chunk has at most 1000 bytes. Typically for
audio media message the size is smaller than that already hence it generates only one chunk. On the other hand a large video
media message may generate several chunks. Each chunk is treated as opaque data for the rest of the formatting. Thus, the
receiving side must re-assemble the full message as described above from the received chunks before acting of the message.
Note that if a message is split into chunks, all the chunks must be received before the whole message can be constructed.
Even if a single chunk is missing due to packet loss, the whole message needs to be discarded. The chunks idea is part of
the RTMP specification itself, however is not useful as it is, because of lack of proper sequence numbering to detect packet
losses. Hence this chunk algorithm is different than what RTMP specification uses.

Each chunk is prepended with a chunk header to form the complete RTP payload. Each chunk header starts with four bytes of
magic word 'RTMP' which is actually a big-endian 32-bit number 0x52544d50. This magic word allows detecting corrupted or
incorrect x-flv payload type. There are two sequence numbers: the message sequence number (seq) and chunk number (cseq).
Each assembed message as described before gets a unique auto-incremented message sequence number. If a message is broken
into 5 chunks, say, then the chunk will get chunk numbers as 0, 1, 2, 3, 4 in that order. Thus the first chunk of a message
always as chunk number of 0. In the chunk header, next 32-bits contain the big-endian message sequence number. Note that 
this sequence number is different than the RTP sequence number, because the RTP sequence number is based on the lower layer's
actual message sent count, whereas this message sequence number is based on RTMP's message count. This is followed by a 
big-endian 16-bit chunk number. Next 16-bit field is an optional size of the assembled message and is present if-and-only-if
the chunk number is 0, i.e., this is the first chunk of the message. This field is not present for subsequent chunks of the 
message. This field is useful to know the full size of the assembled message, so that a receiver can know when to finish
the chunks and re-assemble the full message. I could have used the body size present in the full message, but that looked
more complicated to me in parsing on the receiver, hence I added this optional field. The complete chunk is shown below.

        0                   1                   2                   3
        0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
       +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
magic  |          magic word 'RTMP' 0x52544d50                         |
       +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
seq    |          message sequence number (seq)                        |
       +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
rest   |     chunk number (cseq)       |  (optional) message size      |
       +=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+
body   |          chunk data ...                                       |
time   |            lower layer (UDP) provides size information        |
time   |            of the full packet                                 |
       +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
        
The sender is expected to send all the messages in the correct sequence number order, and all the chunks of the message 
again in the correct chunk number order. 

The receiver processing is described below. First the payload type is matched to identify it as x-flv packet as per the 
SDP negotiation. The other fields such as timestamp can be ignored because they appear in the actual assembed message anyway.
The payload of the RTP packet is parsed using the chunk format described above. The receiver verifies the magic word of 'RTMP'
and if failed it ignores the packet. The message sequence number is extracted as seq. If the seq is 0, then message size is 
extracted. Remaining data is assumed to be chunk data. The receiver maintains the last seq received so far, and also all the
chunk data in the last seq received so far. The receiver may maintain more than one seq data, if it wants to handle out-of-
order packets. For each received packet, the receiver checks if all the chunks are received or not? if the total size of 
all the chunk data received so far becomes equal to the message size found in the first chunk, then we have received all the
chunks. When all the chunks are received, all the chunk data are concatenated in the order of chunk number, to for the
complete assembled message. This message is than used to contruct the rtmp module's Message object by extracted the type,
body size, time stamp and body data as mentioned before. Note that the receiver may detect lost chunks if there is a missing
chunk number and may discard all the chunks in this message seq. The receiver may also detect missing first chunk if the
the new seq number is more than the last seq but the chunk number is not 0. In this case it may discard all future chunks
in this message seq. 

Once a message is assembled, it is given to the RTMP side using the played NetStream.

Client API in ActionScript
--------------------------
This section described the client side API needed to use this SIP-RTMP gateway service. The first step for the client is to
create a connection to the gateway. It is assumed that the client is written in ActionScript with appropriate Flex SDK that 
supports Flash Player 10 or layer features such as Speex audio codec. Note also that since the rtmp.py module currently supports
only AMF0, the client must specify this as the object encoding format. First the client creates a new NetConnection as follows:

  var nc:NetConnection = new NetConnection();
  nc.objectEncoding = ObjectEncoding.AMF0;

Then to receive various callbacks such as "invited", and to receive various events such as "NetConnection.Connect.Success" it
installs the listeners as follows. This assumes that the callbacks will be invoked on the current (this) object.

  nc.client = this;
  nc.addEventListener(NetStatusEvent.NET_STATUS, netStatusHandler);
  nc.addEventListener(SecurityErrorEvent.SECURITY_ERROR, errorHandler);
  nc.addEventListener(IOErrorEvent.IO_ERROR, errorHandler);
  
Finally to establish the connection, it invokes the 'connect' method on the NetConnection using a RTMP URL pointing to this
gateway service. In particular if the gateway is running on your local host, then use "rtmp://localhost/sip/...". If the
gateway is running on the "server" host, then use "rtmp://server/sip/...". The connection must also be scoped to the given
SIP user's address. For exacmple if the client's SIP user name is "alice@example.com" then the URL will be 
"rtmp://server/sip/alice@example.com". 

  nc.connect('rtmp://server/sip/alice@iptel.org', 'alice', 'mypass', 'Alice Smith');
  

For your testing purpose, if you are running the SIP server such as sipd.py locally, and your local IP address is
'192.168.1.3' then the URL to connect becomes "rtmp://localhost/sip/alice@192.168.1.3".  The connect method takes additional
arguments for authentication and registration: authentication name, authentication password, and display name. Note that
you must supply authentication name, authentication password and display name to perform SIP registration even if there is no
authentication requested by your SIP server. However, you must set authentication password to empty string '' if you do not 
want to do SIP registration, and just want to make outbound SIP calls (assuming that your SIP server allows outbound calls without
SIP registration).

  nc.connect('rtmp://localhost/sip/alice@192.168.1.3', 'alice', 'mypass', 'Alice Smith');
  
Internally, a call such as one mentioned before causes the gateway to send SIP registration for local SIP URL of the form
"Alice Smith" <sip:alice@192.168.1.3> and authenticate if needed using username 'alice' and password 'mypass'. The netStatus
event with code 'NetConnection.Connect.Success' is dispatched when connection and registration are successful, and with code
'NetConnection.Connect.Rejected' or 'NetConnection.Connect.Failed' if the connection or registration failed for some reason.
Typically a registration or authentication fail results in rejected message whereas a RTMP connection failure due to incorrect
server name results in failed message. The client will typically treat both message as same. Once the NetConnection is connected
the client is in connected state and can make or receive calls via the gateway.

For a call, the Flash application needs to set up its devices correctly. I recommend the following set up. In particular, you
should set the Microphone codec to use Speex audio codec, and Camera to operate in reasonable dimension and frame rate. Note that
this requires Flash Player 10 if your want to run the code, and associated Flex SDK if you want to compile your code. 

  var mic:Microphone = Microphone.getMicrophone(-1); // little known fact that -1 gives default microphone.
  mic.setUseEchoSuppression(true);
  mic.setLoopback(false);
  mic.setSilenceLevel(0);
  mic.codec = 'Speex';
  mic.gain = 80;

  var cam:Camera = Camera.getCamera(); // on Mac OS, use Flash Player settings to set default camera
  cam.setLoopback(false);              // so that local video is not compressed in the view 
  cam.setMode(320, 240, 12);           // tune this based on your needs 
  cam.setQuality(0, 70);               // tune this based on your needs
  localVideo.attachCamera(cam);

To place an outbound call, the client invokes the RPC method "invite" on the NetConnection and supplies the remote party's SIP
address. This SIP address must be a fully qualified SIP URL or SIP address, which includes optional display name. Examples are
"Bob Jones" <sip:bob@home.com> and sip:bob@office.net. 

  nc.call('invite', null, '"Bob Jones" <sip:bob@home.com>');

If you registered using "Alice Smith" <sip:alice@192.168.1.3> from another browser instance, then you can use that URL in 
the "invite" method to call that user. Note however that calling a user on a NetConnection who was registered using the same
instance of the NetConnection may result in unexpected behavior, as this means you are using your phone to call your own
number in a single like SIP user agent. The expected behavior is that you will receive 'busy' response in this case.
   
  nc.call('invite', null, 'sip:alice@192.168.1.3');

An incoming call is indicated using a callback method "invited" on the NetConnection.client property. The remote party's
SIP address and your SIP address are both supplied as arguments, along with a unique invitation identifier. The invitation
identifier is useful for multiple call case, if you received multiple incoming calls and want to respond differently to
them.  

  public function invited(inviteId:String, yourName:String, myName:String):void { ... }

The client should display some kind of alert to the user on incoming call. If the user accepts the call, the client invokes
the "accept" RPC method to accept the incoming invitation using the same invitation identifier that was received in "invited".  

  nc.call('accept', null, inviteId);

If the user wants to reject an incoming call, the client invokes the "reject" RPC method and also supplies the original 
invitation identifier and an optional reason for rejecting the call. The reason to reject is of the format "code text" where
code is a three digit reject code such as 486 for busy, and 603 for decline. The text is a human readable text phrase 
indicating the reason for rejection. The numeric code is optional, if not supplied, then the gateway uses a pre-configured
reject code of 603.

  nc.call('reject', null, inviteId, '486 Busy Here');
  nc.call('reject', null, inviteId);  // uses "603 Decline" as default

Once a call is established, either an outbound or inbound, the client will need to create two streams to exchange audio and
video with the remote party. The "local" stream is used to publish the local audio and video, and the "remote" stream is used to
play the remote's audio and video. As mentioned earlier the current implementation allows only two streams in the NetConnection,
one in each direction. If the client opens more than one published stream or more than one played stream, then the gateway will
only use the latest stream and ignore the previous one. Once the Camera and Microphone are attached to the local stream and
the stream is published, the gateway starts getting audio video data from local user and sends them to the remote party. Once 
the remote stream is attached to a Video display object and is played, the gateway streams remote party's audio and video
data to this client, and the video gets displayed in the Video object and the audio gets played out by the Flash Player.
  
  var local:NetStream = new NetStream(nc), remote:NetStream = new NetStream(nc);
  local.attachAudio(mic);
  local.attachCamera(cam);
  local.publish('local');
  remote.play('remote');
  remoteVideo.attachStream(remote);

The client may terminate an active call or a pending outbound call using the "bye" RPC method as follows. 

  nc.call('bye');
  
Note that the client must also close the two streams when the call is terminated either by local or remote user.

  local.close();
  remote.close();
  
The gateway invokes several callbacks on the client besides the "invited" callback which was discussed earlier.
In particular the "byed" callback indicates that the remote party terminated an active call, "accepted"
callback indicates that the remote party accepted our call invitation,"rejected" callback indicates that the remote party
rejected our call invitation, and "cancelled' callback indicates that the remote party cancelled its call invitation to
us. The "rejected" and "cancelled" callbacks take some arguments. These functions must be defined in the client to handle
the approrpiate events.

  public function accepted():void { ... }
  public function rejected(reason:String):void { ... }
  public function cancelled(frm:String, to:String):void { ... }
  public function byed():void { ... }

If the user wants to make a SIP call to a phone number, he can use the standard SIP URL typically supported by the phone 
providers. For example, if the user has an account for save 'phoneprovider.com' VoIP provider with user name of 
'12125551234' and password of '5678', and want to make call to another number 18001234567, the client can do the following.
 
  nc.connect("rtmp://server/sip/12125551234@phoneprovider.com", "12125551234", "5678")
  nc.call("invite", null, "sip:18001234567@phoneprovider.com");

If your VoIP provider does not require a SIP registration to make outbound calls, you will need to supply the authentication
credentials in the "invite" call. TODO: this is for future work.
  
  nc.connect("rtmp://server/sip/alice@iptel.org", "alice", "", "Alice Smith");
  nc.call("invite", null, "sip:18001234567@phone.iptel.org", "alice", "mypass");

If you want to use the default preconfigured VoIP provider of the gateway service, you can use the "tel:" URL to make a call.
TODO: this is for future work.

  nc.call('invite', null, 'tel:12125551234');

If you want to remain anonymous in your outbound call, the recommended way is to use the SIP address of <sip:anonymous@invalid>
If you supply your password as "" then no SIP registration will be done.

  nc.connect("rtmp://server/sip/anonymous@invalid", "anonymous", "", "Anonymous User");
 
To use a secure connection replace sip with sips and rtmp with rtmps. TODO: this is for future work.
In particuar, a rtmps URL uses secure TLS connection from Flash Player to the gateway server and sips URL uses secure TLS 
hop-by-hop connection from gateway server to your SIP destination. A NetConnection that uses sips will only be able to receive
secure connections from remote party. Thus, the application may need two netconnections to support both secure and regular
SIP signaling. Note that the URL in connect method is "rtmps://.../sips/...".   

  nc.connect('rtmps://server/sips/...',...);
  nc.call("invite", null, "sips:bob@home.com");

Note, however, that security using this method is not end-to-end secure even for media. In particular, the gateway server has
access to your media stream. You should use both rtmps and sips together. If your gateway server is running on local host, you
may not need rtmps though. Note also that signaling security does not guarantee media encryption and privacy. My implementation
will make sure that SRTP is required when using sips.
  
Limitations
-----------
 1. The URI schemes 'sips' and 'rtmps' are not yet implemented.
 2. Audio interoperability requires that the SIP user agent support Speex codec, and that the Flash Player is version 10 or later.
    The older version of Flash Player included a proprietary Nellymoser codec which is not interoperable with other SIP phones.
 3. Video communication is transported using a proprietary packetization format, and will work only between two Flash clients
    connected via a gateway following the packetization protocol defined in this file.
 4. Multi-party conferencing is not implemented. If at all, the logic should be implemented in the application or external
    third-party conference server in this design approach. 
 5. NAT/firewall traversal is not implemented. Thus, the gateway should run in public Internet, a third-party solution such as
    RTP proxy be used to connect to SIP side, the PSTN gateway should be in public Internet and the Flash client network should
    allow outbound RTMP traffic to the gateway. In future I will add support for STUN and TURN in the gateway so that it can be
    run behind NAT or on user's local computer, and can be used to connect to SIP clients behind NAT.

An example SIP user agent component is available in the videoPhone directory. To build use Flex builder or mxmlc compiler. A
pre-compiled SWF is included in that project directory's bin-release sub-directory for you to try out the user agent.
'''

from __future__ import with_statement
import os, sys, socket, time, traceback, random, multitask
from struct import pack, unpack
from rtmp import App, Header, Message, FlashServer

try:
    from app.voip import User, Session, MediaSession
    from std.rfc3550 import RTP
    from std.rfc2396 import Address
    from std.rfc4566 import SDP, attrs as format
except:
    print 'Please include p2p-sip src directory in your PYTHONPATH'
    exit(1)
    
_debug = False

class Context(object):
    '''Context stores state needed for gateway. The client.context property holds an instance of this class. The methods invoked
    by RTMP side are prefixed with rtmp_ and those invoked by SIP side are prefixed sip_. All such methods are actually generators.
    '''
    def __init__(self, app, client):
        self.app, self.client = app, client
        self.user = self.session = self.outgoing = self.incoming = None # SIP User and session for this connection
        self.publish_stream = self.play_stream = None # streams on RTMP side.
        self._gin = self._gss = None  # generators that needs to be closed on unregister
        self._ts = self._txseq = self._rxseq = self._rxlen = 0
        self._time, self._rxchunks = time.time(), []
        self._audio, self._video = format(pt=-1, name='speex', rate=16000), format(pt=-1, name='x-flv', rate=90000)
        if not hasattr(self.app, '_ports'): self.app._ports = {}     # used to persist SIP port wrt registering URI. map: uri=>port
        
    def rtmp_register(self, login=None, passwd='', display=None, rate='wideband'):
        scheme, ignore, aor = self.client.path.partition('/')
        if rate == 'narrowband': self._audio.rate = 8000
        if _debug: print 'rtmp-register scheme=', scheme, 'aor=', aor, 'login=', login, 'passwd=', '*'*(len(passwd)), 'display=', display
        addr = '"%s" <sip:%s>'%(display, aor) if display else 'sip:%s'%(aor)
        sock = socket.socket(type=socket.SOCK_DGRAM) # signaling socket for SIP
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        port = self.app._ports.get(aor, 0)
        try: sock.bind(('0.0.0.0', port)); port = sock.getsockname()[1] 
        except: 
            if _debug: print '  exception in register', (sys and sys.exc_info() or None)
            self.client.rejectConnection(reason='Cannot bind socket port')
            raise StopIteration(None)
        #self.ports[name] = sock.getsockname()[1] # store the port number
        # TODO: storing and keeping the persistent port per user doesn't work well if the app is re-loaded in brief interval.
        user = self.user = User(sock, nat=False).start() # create SIP user. Ownership of sock is moved to User.
        user.context, user.username, user.password = self, login, passwd
        if user.password:
            if _debug: print '  registering addr=', addr, 'port=', port
            result, reason = yield user.bind(addr, refresh=True)
            if _debug: print '  registration returned', result, reason
            if result == 'failed': 
                self.client.rejectConnection(reason=reason)
                raise StopIteration(None)
            self._gin = self._incominghandler(); multitask.add(self._gin) # incoming SIP messages handler
        if _debug: print '  register successful'
        self.client.accept()
        
    def rtmp_unregister(self):
        if self.user is not None:
            if _debug: print 'rtmp-unregister', (self.client and self.client.path or None)
            yield self._cleanup()    # close the call first, if any
            yield self.user.close()
            yield self.user.stop()
            if self.user.sock:
                try: self.user.sock.close()
                except: pass
                self.user.sock = None
            self.user.context = None; self.user = None
            if self._gin is not None: self._gin.close(); self._gin = None
            if self._gss is not None: self._gss.close(); self._gss = None
    
    def _get_sdp_streams(self): # returns a list of audio and video streams.
        audio, video = SDP.media(media='audio'), SDP.media(media='video')
        audio.fmt, video.fmt = [format(pt=96, name=self._audio.name, rate=self._audio.rate)], [format(pt=97, name=self._video.name, rate=self._video.rate)]
        return [audio, video]
    
    def rtmp_invite(self, dest):
        try:
            if _debug: print 'rtmp-invite', dest
            if self.user: # already a registered user exists
                if not self.session: # not already in a session, so create one
                    try: dest = Address(dest) # first try the default scheme supplied by application
                    except: dest = Address(self.user.address.uri.scheme + ':' + dest) # otherwise scheme is picked from registered URI
                    media = MediaSession(app=self, streams=self._get_sdp_streams())
                    self.outgoing = self.user.connect(dest, sdp=media.mysdp)
                    session, reason = yield self.outgoing
                    self.outgoing = None # because the generator returned, and no more pending outgoing call
                    if _debug: print '  session=', session, 'reason=', reason
                    if session: # call connected
                        media.setRemote(session.yoursdp); session.media = media; self.session = session
                        self._gss = self._sessionhandler(); multitask.add(self._gss) # receive more requests from SIP
                        self.client.call('accepted')
                    else: # connection failed, close media socket
                        media.close()
                        self.client.call('rejected', reason)
                else: self.client.call('rejected', 'Already in an active or pending call')
            else: self.client.call('rejected', 'Registration required before making a call')
        except:
            if _debug: print 'exception in invite', (sys and sys.exc_info() or None)
            self.client.call('rejected', 'Internal server error')

    def rtmp_accept(self):
        if _debug: print 'rtmp-accept'
        incoming = self.incoming; self.incoming = reason = media = None # clear self.incoming, and store value in incoming
        try:
            if self.user is not None and incoming is not None:
                media = MediaSession(app=self, streams=self._get_sdp_streams(), request=incoming[1].request) # create local media session
                if media.mysdp is None: reason = '488 Incompatible SDP'
                else:
                    session, reason = yield self.user.accept(incoming, sdp=media.mysdp)
                    if session: # call connected
                        session.media = media; self.session = session
                        self._gss = self._sessionhandler(); multitask.add(self._gss) # receive more requests from SIP
                        self.client.call('accepted')
                    elif not reason: reason = '500 Internal Server Error in Accepting'
            else:
                if _debug: print '  no incoming call. ignored.'
        except:
            if _debug: print 'exception in rtmp_accept', (sys and sys.exc_info()) 
            reason = '500 Internat Server Exception'
        if reason:
            if media: media.close()
            if self.user: yield self.user.reject(incoming, reason) # TODO: a better way would be to reject in _incominghandler
            if self.client: self.client.call('byed')
            pass
            
    def rtmp_reject(self, reason='Decline'):
        if _debug: print 'rtmp-accept'
        if self.user is not None and self.incoming is not None:
            yield self.user.reject(self.incoming, reason)
            self.incoming = None # no more pending incoming call
        elif _debug: print '  no incoming call. ignored'
        
    def rtmp_bye(self):
        if _debug: print 'rtmp-bye'
        try:
            if self.session is None and self.outgoing is not None: # pending outgoing invite
                if _debug: print '  cancel outbound invite'
                self.outgoing.close()
            elif self.session:
                yield self._cleanup()
        except:
            if _debug: print '  exception in bye', (sys and sys.exc_info() or None)

    def sip_invite(self, dest):
        self.client.call('invited', str(dest), str(self.user.address))
        yield
        
    def sip_cancel(self, dest):
        self.client.call('cancelled', str(dest), str(self.user.address))
        yield
        
    def sip_bye(self):
        self.client.call('byed')
        yield
        
    def _incominghandler(self): # Handle incoming SIP messages
        try:
            user = self.user
            while True:
                cmd, arg = (yield user.recv())
                if _debug: print 'incominghandler', cmd
                if cmd == 'connect': # incoming invitation, inform RTMP side
                    self.incoming = arg
                    multitask.add(self.sip_invite(str(Address(arg[0]))))
                elif cmd == 'close': # incoming call cancelled
                    self.incoming = None
                    multitask.add(self.sip_cancel(str(Address(arg[0]))))
        except StopIteration: raise
        except: 
            if _debug: print 'incominghandler exiting', (sys and sys.exc_info() or None)
        self._gin = None
            
    def _sessionhandler(self): # Handle SIP session messages
        session = self.session
        while True:
            cmd, arg = (yield session.recv())
            if cmd == 'close': multitask.add(self.sip_bye()); break # exit from session handler
        yield self._cleanup()
        self._gss = None
        if _debug: print 'sessionhandler exiting'
        
    def _cleanup(self): # cleanup a session
        if self.session:
            yield self.session.close()    # close the session
            if self.session.media: self.session.media.close(); self.session.media = None # clear the reference
            self.session = None
        if self._gss is not None: self._gss.close(); self._gss = None

    def received(self, media, fmt, packet): # an RTP packet is received. Hand over to sip_data.
        multitask.add(self.sip_data(fmt, packet))
    
    def sip_data(self, fmt, data): # handle media stream received from SIP
        try:
            p = RTP(data) if not isinstance(data, RTP) else data
            #if _debug: print 'RTP  pt=%r seq=%r ts=%r ssrc=%r marker=%r len=%d'%(p.pt, p.seq, p.ts, p.ssrc, p.marker, len(p.payload))
            if str(fmt.name).lower() == str(self._video.name).lower():  # this is a video (FLV) packet, just assemble and return to rtmp
                self.video_rtp2rtmp(p)
            else: # this is a audio (Speex) packet. Build RTMP header and return to rtmp
                payload = '\xb2' + p.payload
                t = (p.ts / (self._audio.rate / 1000)) # assume 20 ms packet at 16000 Hz, one 16 ts is 1 ms (t)
                if self.play_stream is not None:
                    header = Header(time=t, size=len(payload), type=0x08, streamId=self.play_stream.id)
                    m = Message(header, payload)
                    #if _debug: print '  RTMP pt=%x len=%d hdr=%r'%(m.header.type, m.size, m.header)
                    self.play_stream.send(m)
        except (ValueError, AttributeError), E:
            if _debug: print 'Invalid RTP parse error', E
        yield

    def rtmp_data(self, stream, message): # handle media data message received from RTMP
        #if _debug: print 'RTMP pt=%x len=%d'%(message.header.type, message.size)
        if self.session and self.session.media and self.session.media.hasType('video'): # the remote SIP user supports our video format. send FLV video to remote in RTP.
            self.video_rtmp2rtp(message)
        else: # the remote SIP user doesn't support our video. send audio (Speex) in RTP
            if message.header.type == 0x08 and message.size > 1: # audio packet of speex codec
                #if _debug: print '  Audio is %r'%(message.data[0])
                if self.session and self.session.media:
                    self._ts += (self._audio.rate * 20 / 1000) # assume 20 ms data at 16000 Hz
                    self.session.media.send(payload=message.data[1:], ts=self._ts, marker=False, fmt=self._audio)
        yield


    def video_rtmp2rtp(self, message): # convert given RTMP message to RTP packets and send to SIP side
        '''Formatting of RTMP media message to RTP payload and sending to RTP session.'''
        try:
            data = pack('>III', message.type, message.size, message.time) + message.data # assembled message
            origlen, packets, cseq = len(data), [], 0
            hdr  = pack('>Ihh', self._txseq, cseq, len(data)) # header for first chunk
            while len(data) > 0:
                packets.append('RTMP'+hdr+data[:1000])
                data = data[1000:]
                cseq += 1
                hdr = pack('>Ih', self._txseq, cseq)
            # if _debug: print 'rtmp2rtp type=%d,len=%d split seq=%d, chunks=%d'%(message.type, origlen, self._txseq, len(packets)) 
            self._txseq += 1
            if self.session and self.session.media:
                for packet in packets:
                    self.session.media.send(payload=packet, ts=message.time*(self._video.rate/1000), marker=False, fmt=self._video)
                    # yield multitask.sleep(0.005) # sleep for 5 ms
        except: 
            if _debug: print 'exception in rtmp2rtp', (sys and sys.exc_info())
            return
            
    def video_rtp2rtmp(self, packet): # convert given RTP packet to RTMP message and play to the rtmp side.
        '''The parsing of chunks from RTP payload is reverse of creating chunks.'''
        try:
            magic, payload = packet.payload[:4], packet.payload[4:]
            if magic != 'RTMP':
                if _debug: print 'ignoring non-RTMP packet in received video'
                return
            seq, cseq = unpack('>Ih', payload[:6])
            # if _debug: print 'rtp2rtmp received seq=%d cseq=%d len=%d'%(seq, cseq, len(payload))
            if cseq == 0: # first packet in the chunks. Initialize the rx state.
                self._rxseq, self._rxchunks[:] = seq, [] 
                self._rxlen, = unpack('>h', payload[6:8])
                self._rxchunks.append(payload[8:])
            else:
                if seq != self._rxseq or len(self._rxchunks) == 0:
                    if _debug: print 'probably missed a begin packet'
                    return
                if cseq != len(self._rxchunks):
                    if _debug: print 'probably out of order packet'
                    return
                self._rxchunks.append(payload[6:])
            got = sum(map(lambda x: len(x), self._rxchunks), 0)
            if got < self._rxlen: return # not all chunk is received yet
            if got > self._rxlen:
                if _debug: print 'unexpected error, got more than expected %d > %d'%(got, self._rxlen)
                return
            if self._rxlen < 12:
                if _debug: print 'received data is too small %d'%(self._rxlen)
                return
            
            data, message = ''.join(self._rxchunks), Message()
            self._rxlen, self._rxchunks[:] = 0, []  # clear the state now that we have full packet
            message.type, msglen, message.time = unpack('>III', data[0:12]); message.data = data[12:]
            if msglen != len(message.data):
                if _debug: print 'invalid message len %d != %d'%(msglen, len(message.data))
                return

            if self.play_stream is not None: self.play_stream.send(message)
        except:
            if _debug: print 'exception in rtp2rtmp', (sys and sys.exc_info())

class Gateway(App):
    '''The SIP-RTMP gateway implemented as RTMP server application.'''
    def __init__(self):
        App.__init__(self)
    def onConnect(self, client, *args):
        App.onConnect(self, client, args)
        for c in self.clients: multitask.add(c.connectionClosed())
        client.context = Context(self, client)
        multitask.add(client.context.rtmp_register(*args))
        return None
    def onDisconnect(self, client):
        App.onDisconnect(self, client)
        multitask.add(client.context.rtmp_unregister())
    def onCommand(self, client, cmd, *args):
        App.onCommand(self, client, cmd, args)
        if hasattr(client.context, 'rtmp_'+cmd) and callable(eval('client.context.rtmp_%s'%(cmd))): 
            exec 'multitask.add(client.context.rtmp_%s(*args))'%(cmd)
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
    def onStop(self, client, stream):
        if _debug: print self.name, 'onStop', client.path, stream.name
        client.context.play_stream = None
    def onStatus(self, client, info):
        if _debug: print self.name, 'onStatus', info
    def onResult(self, client, result):
        if _debug: print self.name, 'onResult', result
    def onPublishData(self, client, stream, message):
        multitask.add(client.context.rtmp_data(stream, message))
        return False

#---------------------------------- Testing -------------------------------
# The main routine to start, run and stop the service. This part is similar to rtmp.py
if __name__ == '__main__':
    from optparse import OptionParser
    parser = OptionParser()
    parser.add_option('-i', '--host',    dest='host',    default='0.0.0.0', help="listening IP address. Default '0.0.0.0'")
    parser.add_option('-p', '--port',    dest='port',    default=1935, type="int", help='listening port number. Default 1935')
    parser.add_option('-r', '--root',    dest='root',    default='./',       help="document root directory. Default './'")
    parser.add_option('-d', '--verbose', dest='verbose', default=False, action='store_true', help='enable debug trace')
    (options, args) = parser.parse_args()
    
    import rtmp, app.voip, std.rfc3550
    #rtmp._debug = options.verbose
    app.voip._debug = options.verbose
    #std.rfc3550._debug = options.verbose
    _debug = options.verbose
    try:
        agent = FlashServer()
        agent.apps['sip'] = Gateway
        agent.root = options.root
        agent.start(options.host, options.port)
        if _debug: print time.asctime(), 'Flash Server Starts - %s:%d' % (options.host, options.port)
        while True:
            try: multitask.run()
            except multitask.Timeout: pass
    except KeyboardInterrupt:
        pass
    if _debug: time.asctime(), 'Flash Server Stops'
