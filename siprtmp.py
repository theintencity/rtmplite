# Copyright (c) 2007-2009, Mamta Singh. All rights reserved. See LICENSING for details.
# Copyright (c) 2010-2011, Kundan Singh.

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

  public function invited(yourName:String, myName:String):void { ... }

The client should display some kind of alert to the user on incoming call. If the user accepts the call, the client invokes
the "accept" RPC method to accept the incoming invitation using the same invitation identifier that was received in "invited".  

  nc.call('accept', null);

If the user wants to reject an incoming call, the client invokes the "reject" RPC method and also supplies the original 
invitation identifier and an optional reason for rejecting the call. The reason to reject is of the format "code text" where
code is a three digit reject code such as 486 for busy, and 603 for decline. The text is a human readable text phrase 
indicating the reason for rejection. The numeric code is optional, if not supplied, then the gateway uses a pre-configured
reject code of 603.

  nc.call('reject', null, '486 Busy Here');
  nc.call('reject', null);  // uses "603 Decline" as default

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

In an active call, you can send DTMF digits using RFC 2833. The following example sends digit "5" in the RTP session of the 
active call using RFC 2833 (touch-tones). 

  nc.call("sendDTMF", null, "5");
  
The digits are sent only if the remote end acknowledged support for telephone-event in SDP of session initiation. Only single
digit can be sent using sendDTMF using rfc2833.py module, and does not use redundancy rfc2198.py payload.

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

Major Updates
-------------
Support for transcoding between Flash Player's speex and SIP side's PCMU and PCMA using external audiospeex module.
If the audiospeex module is found in PYTHONPATH then it is automatically used, and session negotiation includes new
codecs of pcmu/8000 and pcma/8000 along with speex/8000 and speex/16000. Please see the project web site for details on
how to build/compile this audiospeex module.

Support for G.711 PCMU and PCMA, and H.264 from Flash Player 11. The NetConnection.connect API is modified to ignore the
rate parameter if codecs are supplied in "invite" or "accept" calls. The "invite" and "accept" calls can now have a list of
supported codecs with one or more of the following values.
codec       Flash Player sends and receives                   SDP contains
wideband    speex wideband.                                   speex/16000
narrowband  send speex wideband but receive speex narrowband. speex/8000
pcmu        pcmu at 8kHz and 20ms                             pcmu/8000
pcmu        pcma at 8kHz and 20ms                             pcma/8000
ulaw        speex                                             pcmu/8000 via transcoding
alaw        speex                                             pcma/8000 via transcoding
dtmf        sendDTMF, ignore on receive                       telephone-event/8000
h264        H264Avc (Baseline or Main)                        h264/90000
flv         RTMP message                                      x-flv/90000

The list supplied in "invite" or "accept" is used in decreasing order of preference.
For backward compatibility, if no list of codecs are supplied, it uses the default speex/16000 (or speex/8000) and
x-flv/90000. The media part is moved to a separate MediaContext class which is reused by both multitask and gevent version.

For example, following is the default for backward compatibility
  nc.call('invite', null, '"Bob Jones" <sip:bob@home.com>', 'wideband', 'dtmf', 'flv');

To support all codecs but prefer speex wideband, use
  nc.call(...., 'wideband', 'narrowband', 'pcmu', 'pcma', 'ulaw', 'alaw', 'dtmf', 'h264', 'flv')
  
If the application sends 'pcmu', 'pcma' or 'h264' it must be using Flash Player 11 or later that supports these codecs.
If the application sends 'ulaw' or 'alaw' but siprtmp cannot find the audiospeex module, it will continue the call with
speex in SDP. As mentioned above, if the application doesn't supply any codec, the default setting is used. If the application
supplies some codecs, others are not used. For example, if only 'wideband' is supplied and no video, it will not use
x-flv/90000 in SDP.

Additionally, the "accepted" callback can have two additional arguments for preferred audio and video codecs after the
media negotiation is complete. Note that "accepted" is invoked for both incoming and outgoing calls.

  public function accepted(audioCodec:String=null, videoCodec:String=null) { ... }

The audio and video codecs have the meaning as described below, and the Flash application should listen for the callback
to change the encoding for microphone and camera as needed before starting to publish. For backward compatibility with
existing Flash applications, if a list of codecs was not supplied in "invite" or "accept" then the additional arguments
are not supplied in "accepted" callback.

The "audioCodec" argument can be "speex", "pcmu", "pcma" or "default". If it is default, the application can use either
speex or nellymoser but not pcmu or pcma. The "videoCodec" argument can be "h264" or "default". If it is default, the
application can use any codec. The capability negotiation tries to honor the preference order of the codecs by comparing the
codecs supported by the Flash application and the remote SIP endpoint. If the remote side is capable of "flv" and the
Flash side specified "flv" then both audioCodec and videoCodec will be set to "default". If the remote side is not capable
of any of advertised video codecs, then the videoCodec will be set to null, to tell Flash application to stop video publish.
If the remote side is not capable of any of the advertised audio codecs but the call was accepted, then the audioCodec will
be set to null, to tell Flash application to stop audio publish. If the Flash application advertised "wideband", "narrowband",
"ulaw", "alaw", "pcmu", "pcma" but the remote side is capable of only "pcmu" then audioCodec will be set to "speex" requiring
transcoding to "pcmu". Hence, the application should always put "ulaw" or "alaw" after "pcmu" or "pcma" if available.
For audio codecs the first advertised codec which is supported by the target is used. Thus the Flash application has more
control of which audio codec will be used in case of multiple choices.

The recommended codec list for Flash Player 11+ is "wideband", "narrowband", "pcmu", "pcma", "ulaw", "alaw", "dtmf", "h264", "flv"
The recommended codec list for Flash Player 10  is "wideband", "narrowband", "ulaw", "alaw", "dtmf", "flv".
'''

from __future__ import with_statement
import os, sys, socket, time, traceback, random, multitask
from struct import pack, unpack
from rtmp import App, Header, Message, FlashServer
from amf import AMF0

try:
    from app.voip import User, Session, MediaSession
    from std.rfc3550 import RTP, Network as RTPNetwork
    from std.rfc2396 import Address
    from std.rfc4566 import SDP, attrs as format
    from std.rfc2833 import DTMF
    from std.rfc3261 import Header as SIPHeader
    from std.kutil import setlocaladdr, getlocaladdr
except:
    print 'Please include p2p-sip src directory in your PYTHONPATH'
    sys.exit(1)
    
try: import audiospeex, audioop
except: audiospeex = None
    
_debug = _debugAll = False # debug for regular trace and debugAll for media related traces

class Context(object):
    '''Context stores state needed for gateway. The client.context property holds an instance of this class. The methods invoked
    by RTMP side are prefixed with rtmp_ and those invoked by SIP side are prefixed sip_. All such methods are actually generators.
    '''
    def __init__(self, app, client):
        self.app, self.client = app, client
        self.user = self.session = self.outgoing = self.incoming = None # SIP User and session for this connection
        self.publish_stream = self.play_stream = self.media = self._preferred = None # streams on RTMP side, media context and preferred rate.
        self._gin = self._gss = None  # generators that needs to be closed on unregister
        if not hasattr(self.app, '_ports'): self.app._ports = {}     # used to persist SIP port wrt registering URI. map: uri=>port
        
    def rtmp_register(self, login=None, passwd='', display=None, rate="wideband"):
        global agent
        scheme, ignore, aor = self.client.path.partition('/')
        self._preferred = rate
        if _debug: print 'rtmp-register scheme=', scheme, 'aor=', aor, 'login=', login, 'passwd=', '*'*(len(passwd) if passwd else 0), 'display=', display
        addr = '"%s" <sip:%s>'%(display, aor) if display else 'sip:%s'%(aor)
        sock = socket.socket(type=socket.SOCK_DGRAM) # signaling socket for SIP
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        port = self.app._ports.get(aor, 0)
        try: sock.bind((agent.int_ip, port)); port = sock.getsockname()[1] 
        except: 
            if _debug: print '  exception in register', (sys and sys.exc_info() or None)
            yield self.client.rejectConnection(reason='Cannot bind socket port')
            raise StopIteration(None)
        #self.ports[name] = sock.getsockname()[1] # store the port number
        # TODO: storing and keeping the persistent port per user doesn't work well if the app is re-loaded in brief interval.
        try:
            user = self.user = User(sock, nat=False).start() # create SIP user. Ownership of sock is moved to User.
            user.context, user.username, user.password = self, login, passwd
            if user.password:
                if _debug: print '  registering addr=', addr, 'port=', port
                result, reason = yield user.bind(addr, refresh=True)
                if _debug: print '  registration returned', result, reason
                if result == 'failed': 
                    yield self.client.rejectConnection(reason=reason)
                    raise StopIteration(None)
                self._gin = self._incominghandler(); multitask.add(self._gin) # incoming SIP messages handler
            else: user.address = Address(addr)
            if _debug: print '  register successful', self.user.address
            yield self.client.accept()
        except: 
            if _debug: print '  exception in register', (sys and sys.exc_info() or None)
            yield self.client.rejectConnection(reason=sys and str(sys.exc_info()[1]) or 'Server Error')
            raise StopIteration(None)
        
    def rtmp_unregister(self):
        try:
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
            if self.media:
                self.media.close(); self.media = None
        except:
            if _debug: print '  exception in unregister', (sys and sys.exc_info() or None)
    
    def rtmp_invite(self, dest, *args):
        global agent
        try:
            if _debug: print 'rtmp-invite %r %r'%(dest, args)
            if self.user: # already a registered user exists
                if not self.session: # not already in a session, so create one
                    try: dest = Address(dest) # first try the default scheme supplied by application
                    except: dest = Address(self.user.address.uri.scheme + ':' + dest) # otherwise scheme is picked from registered URI
                    if _debug: print '  create media context'
                    media = MediaContext(self, None, agent.int_ip, self._preferred, RTPNetwork, *args) # create a media context for the call
                    self.outgoing = self.user.connect(dest, sdp=media.session.mysdp, provisional=True)
                    try:
                        session, reason = yield self.outgoing
                        if _debug: print '  session=', session, 'reason=', reason
                        while reason is not None and reason.partition(" ")[0] in ('180', '183'):
                            yield self.client.call('ringing', reason)
                            self.outgoing = self.user.continueConnect(session, provisional=True)
                            session, reason = yield self.outgoing
                    except:
                        media.close()
                        if self.outgoing is not None: raise 
                        else: raise StopIteration(None) # else call was cancelled in another task
                    self.outgoing = None # because the generator returned, and no more pending outgoing call
                    if session: # call connected
                        self.media, self.session, session.media = media, session, media.session
                        self.media.session.setRemote(session.yoursdp)
                        self._gss = self._sessionhandler(); multitask.add(self._gss) # receive more requests from SIP
                        codecs = self.media.accepting();
                        if _debug: print 'sip-accepted %r'%(codecs,) 
                        yield self.client.call('accepted', *codecs)
                    else: # connection failed, close media socket
                        media.close()
                        yield self.client.call('rejected', reason)
                else: yield self.client.call('rejected', 'Already in an active or pending call')
            else: yield self.client.call('rejected', 'Registration required before making a call')
        except StopIteration:
            if _debug: print '  stopping invite generator'
        except:
            if _debug: print '  exception in invite', (sys and sys.exc_info() or None)
            if _debug: traceback.print_exc()
            yield self.client.call('rejected', 'Internal server error')

    def rtmp_accept(self, *args):
        global agent
        if _debug: print 'rtmp-accept %r'%(args,)
        incoming = self.incoming; self.incoming = reason = media = None # clear self.incoming, and store value in incoming
        try:
            if self.user is not None and incoming is not None:
                self.media = MediaContext(self, incoming[1].request, agent.int_ip, self._preferred, RTPNetwork, *args) # create a media context for the call
                if self.media.session.mysdp is None:
                    reason = '488 Incompatible SDP'
                else:
                    session, reason = yield self.user.accept(incoming, sdp=self.media.session.mysdp)
                    if session: # call connected
                        self.session, session.media = session, self.media.session
                        self._gss = self._sessionhandler(); multitask.add(self._gss) # receive more requests from SIP
                        codecs = self.media.accepting();
                        if _debug: print 'sip-accepted %r'%(codecs,) 
                        yield self.client.call('accepted', *codecs)
                    else:
                        if not reason: reason = '500 Internal Server Error in Accepting'
            else:
                if _debug: print '  no incoming call. ignored.'
        except:
            if _debug: print '  exception in rtmp_accept', (sys and sys.exc_info()) 
            reason = '500 Internat Server Exception'
        if reason:
            if self.media:
                self.media.close(); self.media = None
            if self.user: yield self.user.reject(incoming, reason) # TODO: a better way would be to reject in _incominghandler
            if self.client: yield self.client.call('byed')
            
    def rtmp_reject(self, reason='Decline'):
        try:
            if _debug: print 'rtmp-reject'
            if self.user is not None and self.incoming is not None:
                yield self.user.reject(self.incoming, reason)
                self.incoming = None # no more pending incoming call
            elif _debug: print '  no incoming call. ignored'
        except:
            if _debug: print '  exception in reject', (sys and sys.exc_info() or None)
        
    def rtmp_bye(self):
        try:
            if _debug: print 'rtmp-bye'
            if self.session is None and self.outgoing is not None: # pending outgoing invite
                if _debug: print '  cancel outbound invite'
                self.outgoing.close()
                self.outgoing = None
            elif self.session:
                yield self._cleanup()
        except:
            if _debug: print '  exception in bye', (sys and sys.exc_info() or None)

    def sip_invite(self, dest):
        try:
            if _debug: print 'sip-invite' 
            yield self.client.call('invited', str(dest), str(self.user.address))
        except:
            if _debug: print '  exception in sip_invite', (sys and sys.exc_info() or None)
        yield
        
    def sip_cancel(self, dest):
        try: 
            if _debug: print 'sip-cancel' 
            yield self.client.call('cancelled', str(dest), str(self.user.address))
        except:
            if _debug: print '  exception in sip_cancel', (sys and sys.exc_info() or None)
        yield
        
    def sip_bye(self):
        try: 
            if _debug: print 'sip-bye' 
            yield self.client.call('byed')
        except:
            if _debug: print '  exception in sip_bye', (sys and sys.exc_info() or None)
        yield
        
    def sip_hold(self, value):
        try: 
            if _debug: print 'sip-hold', value 
            yield self.client.call('holded', value)
        except:
            if _debug: print '  exception in sip_hold', (sys and sys.exc_info() or None)
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
        try:
            session = self.session
            while True:
                cmd, arg = (yield session.recv())
                if cmd == 'close': multitask.add(self.sip_bye()); break # exit from session handler
                if cmd == 'change': # new SDP received from SIP side
                    is_hold = bool(arg and arg['c'] and arg['c'].address == '0.0.0.0')
                    multitask.add(self.sip_hold(is_hold))
            yield self._cleanup()
        except GeneratorExit: pass
        except:
            if _debug: print 'exception in sessionhandler', (sys and sys.exc_info() or None)
        self._gss = None
        if _debug: print 'sessionhandler exiting'
        
    def _cleanup(self): # cleanup a session
        if self.session:
            yield self.session.close()    # close the session
            self.session = None
        if self.media:
            self.media.close()
            self.media = None
        if self._gss is not None: self._gss.close(); self._gss = None

    def received(self, media, fmt, packet): # an RTP packet is received. Hand over to sip_data.
        if fmt is not None:
            multitask.add(self.sip_data(fmt, packet))
    
    def sip_data(self, fmt, data): # handle media stream received from SIP
        try:
            p = RTP(data) if not isinstance(data, RTP) else data
            if _debugAll: print ' <-s pt=%r seq=%r ts=%r ssrc=%r marker=%r len=%d'%(p.pt, p.seq, p.ts, p.ssrc, p.marker, len(p.payload))
            if self.media:
                messages = self.media.rtp2rtmp(fmt, p)
                if self.play_stream and messages:
                    for message in messages:
                        if _debugAll: print 'f<-  type=%r len=%r time=%r codec=0x%02x'%(message.type, message.size, message.time, message.data and ord(message.data[0]) or -1)
                        yield self.play_stream.send(message)
        except (ValueError, AttributeError), E:
            if _debug: print '  exception in sip_data', E; traceback.print_exc()
        yield

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
        yield
        
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
        yield
        
    def rtmp_hold(self, value):
        try:
            if _debug: print 'rtmp-hold', value
            self.session.hold(value)
        except:
            if _debug: print '  exception in rtmp_hold'; traceback.print_exc()
            traceback.print_exc()
        yield
        
    def requestFIR(self):
        # TODO: this should be sent if we received INFO for FIR from remote.
        if self.session and self.session.ua:
            ua = self.session.ua
            m = ua.createRequest('INFO')
            m['Content-Type'] = SIPHeader('application/media_control+xml', 'Content-Type')
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

class MediaContext(object):
    '''MediaContext stores the media related session and context for any transcoding for the gateway.
    It is independent of multitask or gevent and reused by gevent version.
    '''
    def __init__(self, context, request=None, listen_ip=None, rate='wideband', NetworkClass=None, *args):
        if not NetworkClass: raise ValueError('must supply the RTP NetworkClass')
        self._context, self._rate, self._codecs = context, rate, args
        self._flv, self._h264, self._touchtone, self._narrowband, self._wideband, self._pcmu, self._pcma = format(pt=-1, name='x-flv', rate=90000), format(pt=-1, name='h264', rate=90000), format(pt=-1, name='telephone-event', rate=8000), format(pt=-1, name='speex', rate=8000), format(pt=-1, name='speex', rate=16000), format(pt=0, name='pcmu', rate=8000), format(pt=8, name='pcma', rate=8000)
        self._audio, self._video = self._getMediaStreams()
        
        self._reset()
        streams = [x for x in [self._audio, self._video] if x]
        self.session = MediaSession(app=context, streams=streams, request=request, listen_ip=listen_ip, NetworkClass=NetworkClass) # create the actual MediaSession

    def close(self):
        if self.session:
            self.session.close()
            self.session = None
        self._reset()
        self._context = self.session = None
 
    def _reset(self):
        # x-flv states
        self._flv1_txseq = self._flv2_rxseq = self._flv2_rxlen = 0 
        self._flv2_rxchunks = []

        # H264 transcoder state
        self._h1_cfgVer = self._h1_profileIdc = self._h1_profileCompat = self._h1_levelIdc = self._h1_lenSize = self._h1_SPS = self._h1_PPS = self._h1_data = None
        self._h2_SPS, self._h2_PPS, self._h2_sentSeq, self._h2_sentMetaData, self._h2_startTs, self._h2_startTm, self._h2_queue, self._h2_firstTime, self._h2_lastFIR = None, None, False, False, 0, 0, [], True, 0
        
        # Audio transcoder state: 1 for rtmp->rtp and 2 for rtp->rtmp
        self._au1_resample = self._au1_speex2lin = self._au1_lin2speex = self._au1_fmt = self._au2_lin2speex = None # transcoder states for audiospeex module.
        self._au1_ts = self._au2_ts0 = self._au2_tm = self._au2_ssrc = 0
        
    def rtmp2rtp(self, stream, message): # public method called by Context to transcode RTMP to RTP for media.
        if self.session: # order of following processing is important
            if self.session.hasType('video') and self.session.hasYourFormat(self._flv): # the remote SIP user supports our video format. send FLV video to remote in RTP.
                return self._rtmp2rtpFLV(message) # both audio and video sent via this
            elif message.header.type == Message.VIDEO and message.size > 1: # possibly H.264 video packet
                if self.session.hasYourFormat(self._h264): # if h264 is available
                    return self._rtmp2rtpH264(message)
                # else just ignore the message for audio-only call to SIP VoIP phone
            elif message.header.type == Message.AUDIO and message.size > 1: # audio packet of speex codec.
                return self._rtmp2rtpAU(message)
            elif _debug: print '  ignoring in rtmp2rtp type=', message.header.type, 'size=', message.size

    def rtp2rtmp(self, fmt, p): # public method called by Context to transcode RTP to RTMP for media
        if str(fmt.name).lower() == str(self._flv.name).lower(): # this is a video (FLV) packet, just assemble and return to rtmp
            return self._rtp2rtmpFLV(p)
        elif str(fmt.name).lower() == str(self._touchtone.name).lower(): # this is DTMF
            if _debug: print 'ignoring incoming DTMF touchtone'
        elif str(fmt.name).lower() == str(self._h264.name).lower(): # this is H264
            return self._rtp2rtmpH264(fmt, p)
            #if self.session and self.session.hasYourFormat(self._h264): # uncomment for loopback
            #    self.session.send(payload=p.payload, ts=p.ts, marker=p.marker, fmt=self._h264)
        else: # this is a audio (Speex) packet. Build RTMP header and return to rtmp
            if self._context.play_stream: # avoid transcoding if play-stream is not created yet.
                return self._rtp2rtmpAU(fmt, p)
    
    def dtmf2rtp(self, digit): # public method called by Context to send DTMF to RTP.
        if len(digit) != 1:
            if _debug: print '  only single digit DTMF is supported in sendDTMF'
        elif not self.session or not self.session.hasType('audio'):
            if _debug: print '  ignoring sendDTMF: not an active audio call'
        else:
            payload = repr(DTMF(key=digit, end=True))
            if _debug: print '  sending payload %r'%(payload,)
            return [(payload, self._au1_ts, False, self._touchtone)]
    
    def _getMediaStreams(self):
        global audiospeex
        audio, video = SDP.media(media='audio'), SDP.media(media='video')
        if not self._codecs: # use the default codecs for backward compatibility
            audio.fmt, video.fmt = [format(pt=96, name='speex', rate=8000 if self._rate == 'narrowband' else 16000)], [format(pt=97, name='x-flv', rate=90000)]
            if audiospeex: 
                audio.fmt.extend([format(pt=98, name='speex', rate=16000 if self._rate == 'narrowband' else 8000), format(pt=0, name='pcmu', rate=8000), format(pt=8, name='pcma', rate=8000)])
            # add touchtone format to allow sending this format as well.
            audio.fmt.extend([format(pt=101, name='telephone-event', rate=8000)])
        else:
            pcmu = pcma = narrowband = hasvideo = hasaudio = False
            for codec in self._codecs:
                if   codec == 'wideband':                         audio.fmt.append(format(pt=96, name='speex', rate=16000));           hasaudio = True
                elif codec == 'narrowband' and not narrowband:    audio.fmt.append(format(pt=98, name='speex', rate=8000));            hasaudio = narrowband = True
                elif codec == 'pcmu' and not pcmu:                audio.fmt.append(format(pt=0, name='pcmu', rate=8000));              hasaudio = pcmu = True
                elif codec == 'pcma' and not pcma:                audio.fmt.append(format(pt=8, name='pcma', rate=8000));              hasaudio = pcma = True
                elif codec == 'ulaw' and audiospeex and not pcmu: audio.fmt.append(format(pt=0, name='pcmu', rate=8000));              hasaudio = pcmu = True
                elif codec == 'alaw' and audiospeex and not pcma: audio.fmt.append(format(pt=8, name='pcma', rate=8000));              hasaudio = pcma = True
                elif codec == 'dtmf':                             audio.fmt.append(format(pt=101, name='telephone-event', rate=8000)); hasaudio = True
                elif codec == 'flv':                              video.fmt.append(format(pt=97, name='x-flv', rate=90000));           hasvideo = True
                elif codec and codec.startswith('h264'):          video.fmt.append(format(pt=99, name='h264', rate=90000));            hasvideo = True
                elif _debug: print 'ignoring %r, may already be added'%(codec,)
                if codec and codec.startswith('h264') and 'a' not in video: video['a'] = ['fmtp:99 profile-level-id=420014;packetization-mode=1'] # TODO: handle h264/baseline vs h264/main
            if not hasaudio: audio = None
            if not hasvideo: video = None
        return (audio, video)
    
    def _rtmp2rtpFLV(self, message): # convert given RTMP message to RTP packets and send to SIP side
        data = pack('>III', message.type, message.size, message.time) + message.data # assembled message
        origlen, packets, cseq = len(data), [], 0
        hdr  = pack('>Ihh', self._flv1_txseq, cseq, len(data)) # header for first chunk
        while len(data) > 0:
            packets.append('RTMP'+hdr+data[:1000])
            data = data[1000:]
            cseq += 1
            hdr = pack('>Ih', self._flv1_txseq, cseq)
#        if _debug: print '  FLV sending type=%d,len=%d split seq=%d, chunks=%d'%(message.type, origlen, self._flv1_txseq, len(packets)) 
        self._flv1_txseq += 1
        return [(packet, message.time*(self._flv.rate/1000), False, self._flv) for packet in packets]
            
    def _rtp2rtmpFLV(self, p): # convert given RTP packet to RTMP message and play to the rtmp side.
        magic, payload = p.payload[:4], p.payload[4:]
        if magic != 'RTMP':
            if _debug: print 'ignoring non-RTMP packet in received video'
            return
        seq, cseq = unpack('>Ih', payload[:6])
#        if _debug: print '  FLV received seq=%d cseq=%d len=%d'%(seq, cseq, len(payload))
        if cseq == 0: # first packet in the chunks. Initialize the rx state.
            self._flv2_rxseq, self._flv2_rxchunks[:] = seq, [] 
            self._flv2_rxlen, = unpack('>h', payload[6:8])
            self._flv2_rxchunks.append(payload[8:])
        else:
            if seq != self._flv2_rxseq or len(self._flv2_rxchunks) == 0:
                if _debug: print 'probably missed a begin packet'
                return
            if cseq != len(self._flv2_rxchunks):
                if _debug: print 'probably out of order packet'
                return
            self._flv2_rxchunks.append(payload[6:])
        got = sum(map(lambda x: len(x), self._flv2_rxchunks), 0)
        if got < self._flv2_rxlen: return # not all chunk is received yet
        if got > self._flv2_rxlen:
            if _debug: print 'unexpected error, got more than expected %d > %d'%(got, self._flv2_rxlen)
            return
        if self._flv2_rxlen < 12:
            if _debug: print 'received data is too small %d'%(self._flv2_rxlen)
            return
        
        data, message = ''.join(self._flv2_rxchunks), Message()
        self._flv2_rxlen, self._flv2_rxchunks[:] = 0, []  # clear the state now that we have full packet
        message.type, msglen, message.time = unpack('>III', data[0:12]); message.data = data[12:]
        if msglen != len(message.data):
            if _debug: print 'invalid message len %d != %d'%(msglen, len(message.data))
            return
        return [message]

    def _rtmp2rtpH264(self, message):
#        if _debug: print 'f-> ', len(message.data), repr(message.data[:20])
        messages = []
        if message.data[:2] == '\x17\x00': # AVC seq
            data = message.data[2:]
            cfgVer, profileIdc, profileCompat, levelIdc = unpack('>BBBB', data[3:7])
            if cfgVer == 1:
                lenSize = (ord(data[7]) & 0x03) + 1
                numSPS, data, SPS = (ord(data[8]) & 0x1f), data[9:], []
                for i in range(numSPS):
                    lenSPS, data = unpack('>H', data[:2])[0], data[2:]
                    SPS.append(data[:lenSPS])
                    data = data[lenSPS:]
                numPPS, data, PPS = ord(data[0]), data[1:], []
                for j in range(numPPS):
                    lenPPS, data = unpack('>H', data[:2])[0], data[2:]
                    PPS.append(data[:lenPPS])
                    data = data[lenPPS:]
#                if _debug: print 'avcCfg: cfgVer=%r profileIdc=%r profileCompat=%r levelIdc=%r lenSize=%r numSPS=%r numPPS=%r SPS=%r PPS=%r'%(cfgVer, profileIdc, profileCompat, levelIdc, lenSize, numSPS, numPPS, SPS, PPS)
                # store the parameter sets
                self._h1_cfgVer, self._h1_profileIdc, self._h1_profileCompat, self._h1_levelIdc, self._h1_lenSize, self._h1_SPS, self._h1_PPS, self._h1_data = cfgVer, profileIdc, profileCompat, levelIdc, lenSize, SPS, PPS, message.data
                if SPS: # send this to other end.
                    ts, marker = message.time * self._h264.rate / 1000, True
#                    if _debug: print ' ->s', len(SPS[0]), repr(SPS[0])
                    messages.append((SPS[0], ts, marker, self._h264))
                if PPS:
#                    if _debug: print ' ->s', len(PPS[0]), repr(PPS[0])
                    ts, marker = message.time * self._h264.rate / 1000, True
                    messages.append((PPS[0], ts, marker, self._h264))
        elif message.data[:2] == '\x17\x01' or message.data[:2] == '\x27\x01': # AVC intra or inter
            if self._h1_PPS and self._h1_SPS: # indicates that SPS/PPS are sent
                try:
                    nals = []
                    lenSize, data = self._h1_lenSize, message.data[5:]
                    while data:
                        nalSize = data[:lenSize]
                        if lenSize == 1: nalSize = unpack('>B', nalSize)[0]
                        elif lenSize == 2: nalSize = unpack('>H', nalSize)[0]
                        elif lenSize == 4: nalSize = unpack('>I', nalSize)[0]
                        else: raise ValueError('invalid lenSize %d'%(lenSize,))
                        nalData, data = data[lenSize:lenSize+nalSize], data[lenSize+nalSize:]
                        nals.append(nalData)
#                    if _debug: print '      nals count=', len(nals), 'types=', repr([(ord(x[0]) & 0x1f) for x in nals])
                    if nals:
                        remaining = nals[-1]
                        # message.data = message.data[:5] + pack('>I', len(remaining)) + remaining
                        maxSize = 1446
                        nalType, nri = (ord(remaining[0]) & 0x1f), (ord(remaining[0]) & 0x60)
                        if nalType == 5 or nalType == 1: # others are ignored for now
                            ts, marker = message.time * self._h264.rate / 1000, True # treat each Message as an access unit
                            if len(remaining) <= (maxSize-1):
#                                if _debug: print ' ->s', len(remaining), repr(remaining[:15])
                                messages.append((remaining, ts, marker, self._h264))
                            else: # TODO: only if packetization-mode != 0
                                start = 0x80
                                remaining = remaining[1:]
                                while remaining:
                                    data, remaining = remaining[:maxSize-2], remaining[maxSize-2:]
                                    end = 0x00 if remaining else 0x40
                                    payload = pack('>BB', nri | 28, start | end | nalType) + data
                                    start = 0x00
#                                    if _debug: print ' ->s', len(payload), repr(payload[:15])
                                    messages.append((payload, ts, bool(end), self._h264))
                except:
                    print 'exception', sys.exc_info()
                    traceback.print_exc()
        return messages
        
    def _rtp2rtmpH264(self, fmt, p):

        messages = []
        nalType = ord(p.payload[0]) & 0x1f

        if nalType == 7: # SPS
            self._h2_SPS = p.payload
        elif nalType == 8: # PPS
            self._h2_PPS = p.payload
        elif len(p.payload) > 1:
            if nalType == 24: # cisco phone sends SPS/PPS in aggregated packet
                payload = p.payload[1:]
                while payload:
                    size, payload = unpack('>H', payload[:2])[0], payload[2:]
                    naldata, payload = payload[:size], payload[size:]
                    nt = ord(naldata[0]) & 0x1f
                    if nt == 7:
                        self._h2_SPS = naldata
                        if _debug: print 'extract SPS from aggregated %r'%(naldata,)
                    elif nt == 8:
                        self._h2_PPS = naldata
                        if _debug: print 'extract PPS from aggregated %r'%(naldata,)
            if nalType in (1, 5, 28, 24):
                p.nalType = nalType
                self._h2_queue.append(p) # assumes sorted order by seq.
        
        if len(self._h2_queue) >= 2 and (self._h2_queue[-1].seq != (self._h2_queue[-2].seq + 1)):
            if (self._h2_queue[-2].seq != 65535) or (self._h2_queue[-1].seq != 0):
                if _debug: print 'new packet does not directly follow previous: %r != %r + 1'%(self._h2_queue[-1].seq, self._h2_queue[-2].seq)

        if len(self._h2_queue) >= 2 and (self._h2_queue[-1].ts != self._h2_queue[-2].ts):
            if _debug: print 'clearing old queue since new packet has different ts: %r != %r'%(self._h2_queue[-1].ts, self._h2_queue[-2].ts)
            self._h2_queue[:] = self._h2_queue[-1:] # clear the queue
            
        # we recieved the marker, so we know this is the end of the frame
        if p.marker and len(self._h2_queue) > 0:
            queued, self._h2_queue = self._h2_queue, []
            # handle fragmentation and aggregation
            nalType, realNri, payloads, newdata, pendingdata = 0, 0, [], '', []

            for q in queued:
                if q.nalType == 5 or q.nalType == 1:
                    if not newdata:
                        nalType = q.nalType
                        # 0x17 (for intra-frame) or 0x27 (for non-intra frame)
                        # 0x00 (configuration data) or 0x01 (picture data)
                        newdata = ('\x17' if nalType == 5 else '\x27') + '\x01\x00\x00\x00'
                    newdata += pack('>I', len(q.payload)) + q.payload
                elif q.nalType == 24: # expand aggregated packet
                    payload = q.payload[1:]
                    while payload:
                        size, payload = unpack('>H', payload[:2])[0], payload[2:]
                        naldata, payload = payload[:size], payload[size:]
                        nt = ord(naldata[0]) & 0x1f
                        if nt == 5 or nt == 1: # don't handle 7 and 8 as they are already handled before
                            if not newdata:
                                nalType = nt
                                newdata = ('\x17' if nalType == 5 else '\x27') + '\x01\x00\x00\x00'
                            if _debug: print 'extract from aggregate type=%r len=%r'%(nalType, len(naldata))
                            newdata += pack('>I', len(naldata)) + naldata
                elif q.nalType == 28: # aggregate all fragments
                    if not newdata:
                        nalType, realNri = (ord(q.payload[1]) & 0x1f), (ord(q.payload[0]) & 0x60)
                        # 0x17 (for intra-frame) or 0x27 (for non-intra frame)
                        # 0x00 (configuration data) or 0x01 (picture data)
                        newdata = ('\x17' if nalType == 5 else '\x27') + '\x01\x00\x00\x00'
                    pendingdata.append(q.payload[2:])
                    if ord(q.payload[1]) & 0x40: # end bit
                        remaining = pack('>B', nalType | realNri) + ''.join(pendingdata)
                        if _debug: print 'aggregated %r packets, len=%r, type=%r'%(len(pendingdata), len(remaining), nalType)
                        pendingdata[:] = []
                        newdata += pack('>I', len(remaining)) + remaining
                    else:
                        continue
                    
            # we store the data of the frame
            if newdata:
                payloads.append(newdata)
            
            SPS, PPS, sentSeq = self._h2_SPS, self._h2_PPS, self._h2_sentSeq
            if self._context.play_stream is None or not PPS or not SPS or PPS and SPS and not sentSeq and nalType != 5:
                if _debug: print 'H264 drop until next intra'
                self._h2_queue[:] = [] # drop until next intra
                if (time.time() - self._h2_lastFIR) > 5.0:
                    self._h2_lastFIR = time.time()
                    self._context.requestFIR()
            else:
                if PPS and SPS and not sentSeq and nalType == 5:
                    self._h2_sentSeq = sentSeq = True
                
                # compute the timestamp
                if not self._h2_startTs:
                    self._h2_startTs = p.ts
                if not self._h2_startTm:
                    self._h2_startTm = self._context.play_stream.client.relativeTime
                tm = (p.ts - self._h2_startTs) / (self._h264.rate / 1000) + self._h2_startTm

                if payloads and nalType == 5: # send SPS/PPS                    
                    if _debug: print "   SPS", repr(SPS), "PPS", repr(PPS)
                    
                    # 0x17 (1 if intra, 7 for H.264/AVC) 0x00 (configuration data)
                    data = '\x17\x00\x00\x00\x00\x01' + SPS[1:4] + '\xff\xe1' + pack('>H', len(SPS)) + SPS + '\x01' + pack('>H', len(PPS)) + PPS                    
                    payloads.insert(0, data)
                if self._context.play_stream:
                    messages.extend([Message(Header(time=tm, size=len(payload), type=Message.VIDEO, streamId=self._context.play_stream.id), payload) for payload in payloads])
        return messages
    
    def accepting(self): # called by Context to return the selected codec after negotiation
        global audiospeex
        session = self.session
        if not self._codecs: # do not set codecs for backward compatibility with older applications
            preferred = self._audio and self._audio.fmt[0]
            if audiospeex and session.hasType('audio') and not session.hasYourFormat(preferred): # if we have audiospeex transcoding module and remote doesn't have our preferred format, enable transcoding
                fmt = ([fy for fy in self._audio.fmt if session.hasYourFormat(fy)] + [None])[0]
                if _debug: print '  enable transcoding between %r/%r and %r/%r'%(preferred.name if preferred else None, preferred.rate if preferred else 0, fmt.name if fmt else None, fmt.rate if fmt else 0)
                if fmt: self._au1_fmt = fmt # this will enable transcoding in rtmp2rtpAU
            return tuple()
        else:
            if 'flv' in self._codecs and self.session.hasYourFormat(self._flv):
                return ('default', 'default') # let the Flash Player choose between speex/nellymoser and h264/sorenson.
            audiop = videop = None
            for codec in self._codecs: # need to deal with only audio codecs
                if not audiop and codec in ('wideband', 'narrowband', 'pcmu', 'pcma', 'ulaw', 'alaw'):
                    if codec == 'wideband' and session.hasYourFormat(self._wideband) or codec == 'narrowband' and session.hasYourFormat(self._narrowband) or codec == 'pcmu' and session.hasYourFormat(self._pcmu) or codec == 'pcma' and session.hasYourFormat(self._pcma):
                        audiop = 'speex' if codec in ('wideband', 'narrowband') else codec # no transcoding needed
                    elif codec == 'ulaw' and session.hasYourFormat(self._pcmu) or codec == 'alaw' and session.hasYourFormat(self._pcma):
                        if audiospeex: # enable transcoding if needed
                            preferred = self._narrowband
                            fmt = ([fy for fy in self._audio.fmt if session.hasYourFormat(fy)] + [None])[0]
                            if _debug: print '  enable transcoding between %r/%r and %r/%r'%(preferred.name if preferred else None, preferred.rate if preferred else 0, fmt.name if fmt else None, fmt.rate if fmt else 0)
                            if fmt: self._au1_fmt = fmt
                            audiop = 'speex'
                if not videop and codec == 'h264' and session.hasYourFormat(self._h264):
                    videop = 'h264'
            return (audiop, videop)
                
    def _rtmp2rtpAU(self, message):
        global audiospeex
#        if _debug: print '  AU received %r'%(message.data[0],)
        first, payload, fmt = ord(message.data[0]), message.data[1:], None
        codec = {0xb0: 'speex', 0x70: 'pcma', 0x80: 'pcmu'}.get(first & 0xf0, '')
        if not codec: return # probably nellymoser or something else but target doesn't support x-flv.
        session = self.session
        if not self._au1_fmt: # no transcoding needed
            if codec == 'speex' and session.hasYourFormat(self._wideband):
                fmt = self._wideband
            elif codec == 'speex' and session.hasYourFormat(self._narrowband):
                fmt, payload = self._narrowband, self._removeWideband(payload) # remove wideband if target supports only narrowband but not wideband
            elif codec == 'pcmu' and session.hasYourFormat(self._pcmu):
                fmt = self._pcmu
            elif codec == 'pcma' and session.hasYourFormat(self._pcma):
                fmt = self._pcma
            elif _debug: print 'ignoring codec audio type %r'%(first,)
        elif audiospeex: # perform transcoding from speex/16000 to self._au1_fmt
            fmt = self._au1_fmt
            if str(fmt.name).lower() != 'speex' or fmt.rate != 16000: # only if transcoding is needed.
                linear, self._au1_speex2lin = audiospeex.speex2lin(payload, sample_rate=16000, state=self._au1_speex2lin)
                linear, self._au1_resample = audiospeex.resample(linear, input_rate=16000, output_rate=fmt.rate, state=self._au1_resample)

                if str(fmt.name).lower() == 'speex' and fmt.rate != 16000: # transcode speex/16000 to speex/rate
                    payload, self._au1_lin2speex = audiospeex.lin2speex(linear, sample_rate=fmt.rate, state=self._au1_lin2speex)
                elif str(fmt.name).lower() == 'pcmu' and fmt.rate == 8000 or fmt.pt == 0: # transcode speex/16000 to pcmu/8000
                    payload = audioop.lin2ulaw(linear, 2)
                elif str(fmt.name).lower() == 'pcma' and fmt.rate == 8000 or fmt.pt == 8:
                    payload = audioop.lin2alaw(linear, 2)
                else: raise ValueError, 'ignoring unsupported payload type %r %r/%r'%(fmt.pt, fmt.name, fmt.rate)
        # TODO: map from RTMP timestamp to RTP
        if fmt: self._au1_ts += (fmt.rate * 20 / 1000) # assume 20 ms at 8000 or 16000 Hz
        return [(payload, self._au1_ts, False, fmt)] if payload and fmt else None
        
    def _rtp2rtmpAU(self, fmt, p):
        global audiospeex
        if not self._au1_fmt: # no transcoding needed
            speex_data, input_rate = p.payload, fmt.rate or 8000 # TODO: assume pcmu or pcma at 8kHz
            if str(fmt.name).lower() == 'speex':
                type = '\xb2'
            elif str(fmt.name).lower() == 'pcmu' and fmt.rate == 8000 or fmt.pt == 0:
                type = '\x82'
            elif str(fmt.name).lower() == 'pcma' and fmt.rate == 8000 or fmt.pt == 8:
                type = '\x72'
            else:
                raise ValueError, 'ignoring unsupported payload type %r %r/%r'%(fmt.pt, fmt.name, fmt.rate)
        elif str(fmt.name).lower() == 'speex': # no transcoding since Flash supports speex 8000/16000 anyway
            type, speex_data, input_rate = '\xb2', p.payload, fmt.rate
        else: # perform transcoding from self._au1_fmt to speex/8000
            type, input_rate = '\xb2', fmt.rate or 8000
            if str(fmt.name).lower() == 'pcmu' and fmt.rate == 8000 or fmt.pt == 0:
                linear = audioop.ulaw2lin(p.payload, 2)
            elif str(fmt.name).lower() == 'pcma' and fmt.rate == 8000 or fmt.pt == 8:
                linear = audioop.alaw2lin(p.payload, 2)
            else: 
                raise ValueError, 'ignoring unsupported payload type %r %r/%r'%(fmt.pt, fmt.name, fmt.rate)
            # TODO: never send speex/16000 to Flash after transcoding
            speex_data, self._au2_lin2speex = audiospeex.lin2speex(linear, sample_rate=8000, state=self._au2_lin2speex)
        if self._au2_ssrc and p.ssrc != self._au2_ssrc: # ssrc has probably changed, so reset timers.
            self._au2_ts0 = self._au2_tm = self._au2_ssrc = 0
        if not self._au2_ts0: self._au2_ts0 = p.ts
        if not self._au2_ssrc: self._au2_ssrc = p.ssrc
        if not self._au2_tm: self._au2_tm = self._context.play_stream.client.relativeTime
        payload, tm = type + speex_data, (p.ts - self._au2_ts0) / (input_rate / 1000) + self._au2_tm
        header = Header(time=tm, size=len(payload), type=Message.AUDIO, streamId=self._context.play_stream.id)
        m = Message(header, payload)
#        if _debug: print '  RTMP pt=%x len=%d hdr=%r'%(m.header.type, m.size, m.header)
        return [m]
        
    def _removeWideband(self, payload):
        if ord(payload[0]) & 0x80 == 0: # narrowband
            mode = (ord(payload[0]) & 0x78) >> 3
            bits = (5, 43, 119, 160, 220, 300, 364, 492, 79)[mode] if mode < 9 else 0
            size, bits = bits / 8, bits % 8
            if bits and (size + 1) <= len(payload):
                payload = payload[:size] + chr(((ord(payload[size]) & ((0xff << (8-bits)) & 0xff)) | (0xff >> (bits + 1))) & 0xff)
            elif not bits and size <= len(payload):
                payload = payload[:size]
        return payload

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
        if hasattr(client.context, 'rtmp_%s'%(cmd,)) and callable(eval('client.context.rtmp_%s'%(cmd,))):
            multitask.add(eval('client.context.rtmp_%s'%(cmd,))(*args))
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
        multitask.add(client.context.rtmp_data(stream, message))
        return False

#---------------------------------- Testing -------------------------------
# The main routine to start, run and stop the service. This part is similar to rtmp.py
if __name__ == '__main__':
    from optparse import OptionParser
    parser = OptionParser(version='SVN $Revision$, $Date$'.replace('$', ''))
    parser.add_option('-i', '--host',    dest='host',    default='0.0.0.0', help="listening IP address for RTMP. Default '0.0.0.0'")
    parser.add_option('-p', '--port',    dest='port',    default=1935, type="int", help='listening port number for RTMP. Default 1935')
    parser.add_option('-r', '--root',    dest='root',    default='./',       help="document path prefix. Directory must end with /. Default './'")
    parser.add_option('-l', '--int-ip',  dest='int_ip',  default='0.0.0.0', help="listening IP address for SIP and RTP. Default '0.0.0.0'")
    parser.add_option('-e', '--ext-ip',  dest='ext_ip',  default=None,      help='IP address to advertise in SIP/SDP. Default is to use "--int-ip" or any local interface')
    parser.add_option('-d', '--verbose', dest='verbose', default=False, action='store_true', help='enable debug trace')
    parser.add_option('-D', '--verbose-all', dest='verbose_all', default=False, action='store_true', help='enable full debug trace of all modules')
    (options, args) = parser.parse_args()
    
    import rtmp, app.voip, std.rfc3550, std.rfc3261
    rtmp._debug = options.verbose_all
    app.voip._debug = options.verbose or options.verbose_all
    #std.rfc3550._debug = options.verbose
    std.rfc3261._debug = options.verbose_all
    _debug = options.verbose or options.verbose_all
    _debugAll = options.verbose_all
    
    if _debug and not audiospeex:
        print 'warning: audiospeex module not found; disabling transcoding to/from speex'
    
    if options.ext_ip: setlocaladdr(options.ext_ip)
    elif options.int_ip != '0.0.0.0': setlocaladdr(options.int_ip)
    
    try:
        agent = FlashServer()
        agent.apps['sip'] = Gateway
        agent.root, agent.int_ip, agent.ext_ip = options.root, options.int_ip, options.ext_ip
        agent.start(options.host, options.port)
        if _debug: print time.asctime(), 'Flash Server Starts - %s:%d' % (options.host, options.port)
        while True:
            try: multitask.run()
            except multitask.Timeout: pass
    except KeyboardInterrupt:
        pass
    if _debug: time.asctime(), 'Flash Server Stops'
