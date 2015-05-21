## SIP-RTMP gateway ##

> This project was migrated from <https://code.google.com/p/siprtmp> on May 17, 2015  
> Keywords: *SIP*, *RTMP*, *Flash*, *Python*, *VoIP*, *Gateway*, *Phone*, *VideoPhone*  
> Members: *voipresearcher* (owner), *theintencity* (owner), *kundan10*  
> Links: [Support](http://groups.google.com/group/myprojectguide), [Download](https://github.com/theintencity/rtmplite/tree/downloads)  
> License: [GNU GPL v3](http://www.gnu.org/licenses/gpl.html)  
> Others: starred by 58 users  

![logo](/siprtmp.png)

The goal of this project is to allow [Flash to SIP calls](http://myprojectguide.org/node/6#comment-2) and vice versa. In particular it allows multimedia calls from Flash Player to SIP network and SIP network to Flash Player. The gateway implements translation of signaling as well as media between Flash Player's RTMP and standard SIP, SDP and RTP/RTCP. The client side API allows you or any third-party to build user interface of web-based audio and video phone that uses SIP in the back end. The user applications can be built using ActionScript for web browser as well as standalone AIR. The Gateway can run either as a server hosted by the provider, or as a local application on the client's host. Thus, this software caters to various customers and users.

<font color='#ff0000'>IMPORTANT</font> Please send any bug/support request to the [support group](http://groups.google.com/group/myprojectguide) instead of directly to the owner

News: Added translation of H.264 video and G.711 in Flash Player 11. Use latest from SVN instead of download version for subsequent bug fixes. The translation now works between Bria 3 and Flash Player 11.2.202.96 (beta) after a bug fix in Flash Player.

News: Added transcoding between speex and pcmu/pcma voice codecs using the [py-audio](https://github.com/theintencity/py-audio) project.

News: Added gevent-based version of the siprtmp gateway for improved performance.

News: Added support for -e option to specify external public IP address which is advertised in all SIP/SDP messages. This is useful for running siprtmp.py on Amazon EC2. Please see [FAQ](/siprtmp-faq.md) for details.

News: Support for narrowband Speex codec has been added in version 6.0 for interoperability with certain telephony gateways which do not support wideband Speex codec.

News: Added a demo video and subtitles file for getting started with siprtmp. See the [download](https://github.com/theintencity/rtmplite/tree/downloads) folder.

## Further documentation ##

I have written the source code in Python with extensive documentation in the source code itself. The code comment explains how the software works, design choices as well as overview of the client API. Please see the [siprtmp.py source code](/siprtmp.py) for details. Feel free to browse through the client side of the code to know how the API is used in the ActionScript client.

Our white paper on <a href='http://arxiv.org/pdf/1107.0011v1'>Flash based audio and video communication in the cloud</a> (section 7) compares various architecture and API options for interoperability between Flash Player and SIP/RTP, and describes our SIP-RTMP message flow, session negotiation, media transport and media format in detail. You can view the demo video of SIP-RTMP gateway on youtube for [audio call](http://www.youtube.com/watch?v=-_W2YVCIPg8) and [video call](http://www.youtube.com/watch?v=cI4nqBfHsXM).

## Download and browse source ##

This project shares the source code repository with the [RTMP Server](/rtmp.py) project. Since I own both the projects, I decided to keep a single source repository to simplify software development.

**[Download](https://github.com/theintencity/rtmplite/tree/downloads)** the latest version, or get **[source control](https://github.com/theintencity/rtmplite.git)** access to the software. I have also put the current versions of the download in the download section of this page, but I request you to get the latest version from the links above. You will also need to download the dependencies as mentioned in the Quick Start section below.

## License ##

The software is open source under GNU Public License (GPL). If the viral nature of GPL is not suitable for your deployment, we also sell low cost [alternative commercial license](http://theintencity.com/services.html). In particular, the alternative commercial license allows you to combine pieces of our software with your other proprietary elements.

## Support and Feedback ##

If you are a VoIP provider who needs to use this web-to-phone feature for your network, please get in touch with me on how I can help you. I can point you in the right direction from installation, provisioning, trouble shooting to building a client Flash application for your web site. _Please see the [FAQ](/siprtmp-faq.md) as well._

If you are a developer who wants to add a new feature to the software or use the software in your project, feel free to post a message to the support group. I can provide direction on which module to look at or modify for your work.

You can post a message to the [support group](http://groups.google.com/group/myprojectguide). You don't need to subscribe to that group to post a message. **I look forward to hearing from you!**

## Quick Start ##

The software requires Python 2.6. It has an external dependency on the [p2p-sip](http://github.com/theintencity/p2p-sip) project. Please download the latest version of the source code from the [p2p-sip project page](http://github.com/theintencity/p2p-sip). Please follow the instructions on that site on how to install. I have provided the current instructions below, which may change later the project.

```
bash$ tar -zxvf source-*.tgz
bash$ export PYTHONPATH=p2p-sip/src:.
```

Next, download the siprtmp source code from this rtmplite project. Make sure to download version 3.0 or later which includes support for siprtmp module. For support of narrowband codec use version 6.0 or later.

```
bash$ tar -zxvf rtmplite-6.0.tgz
```

Now that you have the p2p-sip and rtmplite directories, you can run the siprtmp module form the rtmplite directory as follows. Make sure to set the PYTHONPATH correctly to point to dependencies.

```
bash$ cd rtmplite
bash$ export PYTHONPATH=../p2p-sip/src:.
bash$ python siprtmp.py -d
```

The siprtmp module takes the same command line as the rtmp module. The difference is that siprtmp module also enables the sip application for SIP-RTMP gateway service. At this point your SIP-RTMP gateway server is running on local host.

You can visit [http://myprojectguide.org/p/siprtmp](http://myprojectguide.org/p/siprtmp) to view the user interface for making or receiving calls. This is same as the Video Phone client described next under Testing.

## Testing ##

I will describe two test scenarios below which allow you to test the service locally without requiring an external SIP account. The testing employs the sample Video Phone client available in the rtmplite directory  under videoPhone subdirectory. The `rtmplite/videoPhone/bin-release` folder contains a VideoPhone.html file which embeds the Flash application for the sample client.

You will also need two additional software for doing the test: a SIP server and a SIP client. I use [Free X-Lite](http://www.counterpath.com/) SIP user agent because it also supports wide-band speex audio codec, which is required by this SIP-RTMP gateway software. I also use the sipd.py module available in the p2p-sip code I mentioned before, for the SIP server functions. You may be able to use some other SIP server or SIP user agent as long as they are in the same network as your SIP-RTMP gateway, i.e., no firewall or NAT among these. Run the SIP server in another terminal as follows since you have already installed p2p-sip code. The -d option allows you to trace various SIP messages handled by the server.

```
bash$ cd p2p-sip/src
bash$ export PYTHONPATH=app:external:.
bash$ python app/sipd.py -d
```

**First test:** In the first test, open the VideoPhone.html from browsers on two different computers (or if you don't have two different computers, perhaps from two different browsers or browser instances, so that cookies do not mess up your testing). When the Flash widget loads, it first tries grab your devices. You will need to "Allow" access to your devices and also check the "Remember" box in the Flash Player settings so that it stores your preference for this page.

Next, specify your configuration information in the widget. The first is the gateway URL, which should be rtmp://localhost/sip if you are running the siprtmp gateway locally. Suppose your local IP address is 192.168.1.3 then you will use this in your SIP addresses. The next field is your SIP address. You can pick two random names such as "alice" and "bob" and then use say alice@192.168.1.3 on the first browser and bob@192.168.1.3 on the second browser. The next field is your authentication name which you can use alice and bob respectively on the two browsers. Next is the authentication password which you can put anything as our SIP server in this test does not do authentication. Then the display name can be set as say "Alice 1" and "Bob 2". When it prompts you to remember the configuration, you should check that so that you don't have to go through the whole configuration process next time for this web page. After you click next, it will try to connect to the gateway server, which in turn generates SIP registrations to the SIP server. At this point both your web clients are ready to make and receive calls. At this point, your local video should appear in the widget.

In the first browser, type sip:bob@192.168.1.3 which is the SIP address of the second browser. Then click on the next button. The second browser should receive an incoming call indicated by the blinking button. Click on the blinking button to accept the call. You may click on the other button to reject the call, alternatively. Once the call is established you should be able to hear and see between these two web clients. There are a few user interface controls that allow you to switch between local video, remote video and picture-in-picture mode. When you want to terminate the call, click the appropriate button on one of the browser's widget, or simply close the browser. The other side should receive the call termination signal and close the call.


**Second test:** In the second test, we will interoperate between this Video Phone of first user, alice, and a standard SIP user agent, X-Lite. This will be an audio call test because X-Lite does not understand the RTMP video format used by the Flash Player. Since X-Lite supports wideband Speex audio codec, we can interoperate between our gateway and X-Lite.

The first step is to install and configure your X-Lite client on the second computer or as a replacement for second browser on your computer. Once installed, open the "Options" dialog box using the right-click menu, and go to the Advanced then Audio Codecs tab. Make sure "Speex Wideband" is among the enabled codecs listed on that page. Also, under the Advanced then Quality of Service tab, make sure that all the options are set to "None" otherwise X-Lite is known to cause problems in certain network conditions. Feel free to explore other settings as appropriate.

Next, create a new SIP account in X-Lite using the "SIP Account" setting in the right-click menu.  Add or modify the account to reflect the second user's credentials such as display name as Bob 2, user name as bob, domain as 192.168.1.3 and enable to register with domain and receive calls. Also set the outbound proxy mode to 192.168.1.3. Under the Topology tab select to use local IP address and do not discover STUN server, since all our testing is in the intra-net. Once you close the SIP Account dialog box, X-Lite will register with our SIP server on behalf of user bob.

Now you can use the same procedure as before to place a call from widget of the first browser to the X-Lite user. When the phone rings, answer the phone and your should get connected between the first browser and the X-Lite phone. Only audio will work between these two clients. The widget will display blank video of the remote party.

You may terminate the call either from the widget or X-Lite client.

For other variations in this test, you can try initiating the call from the X-Lite client by dialing alice which is received by the first browser's widget. Similarly, you can also test canceling an outgoing call or rejecting an incoming call from either of the clients.

Once you are comfortable testing the set up, you can explore further options in the gateway, the SIP server as well as the client. You may also want to build your own Flash application using the client API to connect to the gateway directly. For Flash Player to allow device access your Flash application must have a minimum dimension of 214x137. This is the dimension of the sample Video Phone application included in the software.

### Narrowband Speex ###

For connecting to telephony gateways such as Asterix, you will need to use narrowband Speex codec. If you would like to use narrowband Speex codec at 8000 Hz instead of the default wideband codec at 16000 Hz, you can right click on your Flash application and choose "Use narrowband Speex" from the menu option. The right click context menu allows you to switch between narrowband and wideband codecs. But you MUST do the selection before it connects to the gateway server. Hence this must be done before you click on the next button on the remember prompt. The settings are saved hence you don't need to switch it next time if you have selected to remember the configuration. Please see the [FAQ](/siprtmp-faq.md) as well.

### White-labelled phone ###

If you are interested in building a white-labelled web-based phone to talk to siprtmp, take a look at <a href='http://myprojectguide.org/p/flash-videoio/11.html'>How to do SIP-based VoIP call?</a> The VideoPhone application available with siprtmp has its own call control user interface, but you can use <a href='https://github.com/theintencity/flash-videoio'>flash-videoio</a> project for a clean Javascript enabled application interface to connect to siprtmp.

## Deployment ##

A real-deployment of this software will require far more testing and a few more features. Since there is no NAT and firewall traversal support in the gateway currently, you need to run the siprtmp gateway in the public Internet if you want to deploy this service. Secondly, this gateway should have direct access to the SIP server and assumes that if the SIP client is behind NAT and firewall then the SIP client or server somehow manage to traverse them, such that gateway sees the SIP side on the public Internet. Since the gateway does not implement RTMP tunneling, the connection from browser client to the gateway may not work under certain restricted firewall, such as those that block RTMP TCP port 1935 from client to the server/gateway.

As I mentioned before, I would love to hear from you if you plan to use this software in your project or deployment! I may also be able to point you to the right direction on how to proceed with the deployment and help troubleshoot this software for your project.

## Final Words ##

This software is provided with a hope to break away from the Flash Player's restrictions, to allow interoperability between Flash applications and SIP network, and to allow Flash and Flex developers to build interesting new Internet Multimedia applications using the SIP technology. As such this software is released under GNU GPL v3, and if you use this software in your project, you will also need to release the source code of your project. I believe a free software should be viral and GNU GPL gives a tool to do so. If the software does not work, you can contribute to fix it. There is no warranty or guarantee on this software. If we share our time and effort, all of us will benefit.




