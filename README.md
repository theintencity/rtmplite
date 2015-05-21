# What is rtmplite? #
More details in [rtmplite](/rtmplite.md) and [siprtmp](/siprtmp.md)

> This project was migrated from <https://code.google.com/p/rtmplite> on May 17, 2015  
> Additionally the documentation from <https://code.google.com/p/siprtmp> was merged on May 17, 2015  
> Please see these individual description files for [rtmplite](/rtmplite.md) or [siprtmp](/siprtmp.md)  

# Copyright #

Copyright (c) 2007-2009, Mamta Singh.  
Copyright (c) 2010-2011, Kundan Singh. All rights reserved.  
Copyright (c) 2011-2012, Intencity Cloud Technologies. All rights reserved.  
Copyright (c) 2011, Cumulus Python. No rights reserved.  

See [contributors](/people.png).

# RTMP server #

The main program is rtmp.py. Please see the embedded documentation in that file.
Some parts of the documentation are copied here. Other modules such as amf, util
and multitask are used from elsewhere and contain their respective copyright 
notices.

# SIP-RTMP gateway #

The siprtmp module implements a SIP-RTMP gateway.  Please see the google 
code project for details on demo instructions and support information.
The project description is contained in siprtmp.py file itself. The command
line of siprtmp is same as rtmp, hence just replce rtmp by siprtmp in the 
following example to start the gateway.

# RTMP client #

The rtmpclient module implements a simple RTMP client. Please see the documentation
in rtmpclient.py source file on how it works and how it can be used.

# RTMFP server #

The rtmfp module implements a simple and imcomplete RTMFP rendezvous server. Please
see the documentation in rtmfp.py source file on how it works.

# Getting Started #

Dependencies: Python 2.6 and Python 2.5

Typically an application can launch this server as follows:
```
$ python rtmp.py -d
```
The -d option enables debug trace so you know what is happening in the server.

To know the command line options use the -h option:
```
$ python rtmp.py -h
```

A test client is available in testClient directory, and can be compiled 
using Flex Builder. Alternatively, you can use the SWF file to launch
from testClient/bin-debug after starting the server. Once you have 
launched the client in the browser, you can connect to
local host by clicking on 'connect' button. Then click on publish 
button to publish a stream. Open another browser with
same URL and first connect then play the same stream name. If 
everything works fine you should be able to see the video
from first browser to the second browser. Similar, in the first 
browser, if you check the record box before publishing,
it will create a new FLV file for the recorded stream. You can 
close the publishing stream and play the recorded stream to
see your recording. Note that due to initial delay in timestamp 
(in case publish was clicked much later than connect),
your played video will start appearing after some initial delay.
