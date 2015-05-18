This is a python implementation of the Flash RTMP server with minimal support needed for real-time streaming and recording using AMF0. It also includes an RTMP client and a SIP-RTMP gateway.

<font color='#ff0000'>IMPORTANT</font> Please send any bug/support request to the [support group](http://groups.google.com/group/myprojectguide) instead of directly to the owner

Advanced application service such as shared object or web API are outside the scope. The goal is to use existing protocols and tools such as web servers as much as possible (API, progressive download). And only use this RTMP server when one needs to interoperate with Flash Player. Another objective is to keep the size small so that one can use it locally on a client machine instead of hosting on a remote server.

Our white paper on <a href='http://arxiv.org/pdf/1107.0011v1'>Flash based audio and video communication in the cloud</a> describes the benefits and problems of using Flash Player for communication, describes the motivation and overview of Flash VideoIO API, shows how to build various application scenarios with the API, compares various architecture and API options for interoperability between Flash Player and SIP/RTP, and describes our SIP-RTMP message flow, session negotiation, media transport and media format in detail. You can view the demo video of SIP-RTMP gateway on youtube for [audio call](http://www.youtube.com/watch?v=-_W2YVCIPg8) and [video call](http://www.youtube.com/watch?v=cI4nqBfHsXM).

## News ##

**New** in svn [r127](https://code.google.com/p/rtmplite/source/detail?r=127): contains support for experimental [RTMFP server in pure python](http://code.google.com/p/rtmplite/source/browse/trunk/rtmfp.py). Have not tested it much!

**New** in svn [r125](https://code.google.com/p/rtmplite/source/detail?r=125): H.264 now works between Bria 3 and Flash Player 11.2.202.96 (or later). See [this](http://p2p-sip.blogspot.com/2012/01/translating-h264-between-flash-player.html) article on _Translating H264 between Flash Player and SIP/RTP_ for details.

<a href='Hidden comment: 
*New* in version 8.0 (svn r118, p2p-sip svn r48): Added experimental support for H.264 and G.711 available in Flash Player 11. The gateway can translate with SIP video phones such as Ekiga. *Use latest from SVN* instead of download archive to get important bug fixes.

New in svn r83: In siprtmp.py, added support for transcoding between speex and pcmu/pcma voice codecs using the [http://code.google.com/p/py-audio py-audio] project. Just follow py-audio build instructions and place the audiospeex.so in your PYTHONPATH before starting siprtmp.py. Requires p2p-sip r37.


New in version 7.5 (svn r74): Added gevent-based version of the server and gateway. See siprtmp_gevent.py. Requires p2p-sip r33.

New in version 7.2 (svn r45): Fixed interoperability with ffmpeg, so that you can publish from there.

New in version 7.0 (svn r38): Fixed the video freeze problem that happened after 2-5 min.

New in version 6.0: Fixed several timing related bugs for recording, playback and live conferencing.
'></a>

## History ##

The project was started and most of the work was done in 2007. More recently I wrote example test application and finished the server part to make it complete. If you are interested in contributing, feel free to send me a patch with your changes. If you plan to use this software in your project or want to contribute significantly in this project or its features, feel free to send me a note to the [support group](http://groups.google.com/group/myprojectguide). You don't need to subscribe to that group to post a message. **I look forward to hearing from you!**

There are other open-source RTMP servers available such as rtmpy.org and osflash.org/red5. My implementation is different because it does not use the complex Twisted library as in rtmpy.org and it is pure Python based couple of files instead of hundreds of Java files of Red5. I did use AMF parsing from rtmpy.org though. Secondly my project is a much simpler version of a full Red5 server and useful only for dealing with real-time media and doesn't implement shared object or web server style applications.

## Quick Start ##

The software requires Python 2.6. After uncompressing the download or checking out the sources from SVN, run the server file with -h option to see all the command line options.
```
bash$ tar -zxvf rtmplite-7.0.tgz
bash$ cd rtmplite
bash$ python rtmp.py -h
```

To start the server with default options and debug trace, run the following:
```
bash$ python rtmp.py -d
```

A test client is available in testClient directory, and can be compiled using Flex Builder. I have already put the compiled SWF file in the bin-debug directory. Open your browser and then open the testClient.html file in your browser. The user interface will allow you to connect to the server to test the connection. You can also test streams by clicking on publish or play buttons.

See the README file for more information

## New Features/Other Projects ##

**Flash to SIP**: Starting with version 3.0 onwards, the software includes a [SIP-RTMP gateway module](http://code.google.com/p/rtmplite/source/browse/trunk/siprtmp.py) as well. The [siprtmp project page](http://code.google.com/p/siprtmp/) describes the SIP-RTMP module in detail. The project depends on the SIP stack from the "39 peers" [p2p-sip project](http://code.google.com/p/p2p-sip/). This module allows you to make Flash to SIP calls and vice-versa. With appropriate VoIP account you can also make Flash to phone or web to phone calls. _New:_ the gateway and sample Flash application now allow switching from 16000 (wideband) to 8000 (narrowband) sampling of Speex, so that it can work with certain telephony gateways.  _Please read the [FAQ](http://code.google.com/p/rtmplite/wiki/FaqSiprtmp)_

**Videocity**: The [Internet Videocity](http://code.google.com/p/videocity/) Project is another project that uses rtmplite as an RTMP server. The Videocity project aims at providing open source and free software tools to developers and system engineers to support enterprise and consumer video conferencing using ubiquitous web based Flash Player platform. The video communication is abstracted out as a city, where you own a home with several rooms, decorate your rooms with your favorite photos and videos, invite your friends and family to visit a room by handing out visiting card, or visit other people's rooms to video chat with them or to leave a video message if they are not in their home.

**Client**: The [rtmpclient](http://code.google.com/p/rtmplite/source/browse/trunk/rtmpclient.py) module in this project implements a Python-based RTMP client that allows you to copy between remote RTMP stream and local file. Unlike rtmpdump project, this one supports both (1) copy from local file to RTMP server by publishing a live stream, and (2) copy from RTMP server to local file by dumping a live stream. This simple tool can be used for various Flash streaming related testing, e.g., by injecting live stream to a Flash Media Server from local FLV file, or dumping a live stream from Flash Media Server to a local FLV file.

**Flash-VideoIO**: The [Flash-VideoIO](http://code.google.com/p/flash-videoio/) project aims at implementing reusable and generic Flash component with extensive JavaScript API to facilitate audio and video communication scenarios such as video messaging, broadcasting, call and conferencing. It is compatible with rtmplite media server for client server media streams. Take a look at <a href='http://myprojectguide.org/p/flash-videoio/11.html'>How to do SIP-based VoIP call?</a> as an alternative Javascript based front-end application to connect to siprtmp module of rtmplite server.

## License ##

The software is open source under GNU Public License (GPL). If the viral nature of GPL is not suitable for your deployment, we also sell low cost [alternative commercial license](http://theintencity.com/services.html). In particular, the alternative commercial license allows you to combine pieces of our software with your other proprietary elements.

## Contributing ##
If you have patch for a bug-fix or a feature, feel free to send us the patch to the [support group](http://groups.google.com/group/myprojectguide). If you plan to do significant contributions, please let me know and I will add you as a project member so that you can check in files using SVN. Please join the [support group](http://groups.google.com/group/myprojectguide) if you want to contribute or hear about the project announcements.

<b>Notice: </b> The owners of the project reserve all the rights to source code. All the contributors and committers automatically and implicitly assign all the rights to the owners by contributing to this project. The rights assignment implies that the owners reserve all the rights to publish or distribute the sources or binaries elsewhere under another license for commercial or non-commercial use. Irrespective of the rights, this project will continue to remain open source.

## User Comments ##

(Aug 2009): "I tried your RTMP-SIP gateway this afternoon. It's pretty neat. Awesome. Great job. I like it more than the Red5 project.  It's a very good idea to implement it with python and it's lightweight and better integrate with ..."

(Nov 2009): "I was looking for a lightweight rtmp server and tried out your server at http://code.google.com/p/siprtmp/ and it seems to have been running quite well. Hats off to you. ... Thanks for the great lightweight server."

If you have any feedback, criticism or comment on siprtmp or rtmplite, feel free to send them to [support group](http://groups.google.com/group/myprojectguide). You don't need to subscribe to that group to post a message.