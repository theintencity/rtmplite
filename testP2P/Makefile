
VERSION:=1.0

#MXMLC45:=/Applications/Adobe\ Flex\ Builder\ 3/sdks/4.5/bin/mxmlc
MXMLC45:=/Applications/Adobe\ Flash\ Builder\ 4/sdks/4.5/bin/mxmlc

BINARIES:= bin-debug/testP2P.swf
     
all: ${BINARIES}

bin-debug/testP2P.swf: src/testP2P.mxml Makefile
	${MXMLC45} -output $@ -compiler.debug=true \
	-swf-version=12 -target-player 10.3.0 \
	-static-link-runtime-shared-libraries=true -source-path src -- src/testP2P.mxml

clean: 
	rm -f bin-debug/testP2P.swf
