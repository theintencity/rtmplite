# Copyright (c) 2007-2009, Mamta Singh. All rights reserved. see README for details.
# description:
# Official AMF0 specification: http://opensource.adobe.com/wiki/download/attachments/1114283/amf0_spec_121207.pdf
# AMF documentation on OSFlash: http://osflash.org/documentation/amf

import struct, datetime, time, types
from StringIO import StringIO
import xml.etree.ElementTree as ET

class BytesIO(StringIO):
    '''Extend StringIO to raise error if reading after eof, allow read with optional length, and peek to next byte.'''
    def __init__(self, *args, **kwargs): StringIO.__init__(self, *args, **kwargs)
    def eof(self): return self.tell() >= self.len  # return true if next read will cause EOFError
    def remaining(self): return self.len - self.tell() # return number of remaining bytes
    
    def read(self, length=-1):
        if length > 0 and self.eof(): raise EOFError # raise error if reading beyond EOF
        if length > 0 and self.tell() + length > self.len: length = self.len - self.tell() # don't read more than available bytes
        return StringIO.read(self, length)
    def peek(self):
        if self.eof(): return None
        else:
            c = self.read(1)
            self.seek(self.tell()-1)
            return c
        
    for type, T, bytes in (('uchar', 'B', 1), ('char', 'b', 1), ('ushort', 'H', 2), ('short', 'h', 2), ('ulong', 'L', 4), ('long', 'l', 4), ('double', 'd', 8)):
        exec '''def read_%s(self): return struct.unpack("!%s", self.read(%d))[0]'''%(type, T, bytes)
        exec '''def write_%s(self, c): self.write(struct.pack("!%s", c))'''%(type, T)
    def read_utf8(self, length): return unicode(self.read(length), 'utf8')
    def write_utf8(self, c): self.write(c.encode('utf8'))

# Ported from http://viewvc.rubyforge.mmmultiworks.com/cgi/viewvc.cgi/trunk/lib/ruva/class.rb
# Ruby version is Copyright (c) 2006 Ross Bamford (rosco AT roscopeco DOT co DOT uk). The string is first converted to UTF16 BE
def _decode_utf8_modified(data):
    '''Decodes a unicode string from Modified UTF-8 data. See http://en.wikipedia.org/wiki/UTF-8#Java for details.'''
    utf16, i, b = [], 0, map(ord, data)
    while i < len(b):
        c = (b[i] & 0x80 == 0) and b[i:i+1]  or  (b[i] & 0xc0 == 0xc0) and b[i:i+2]  or  (b[i] & 0xe0 == 0xe0) and b[i:i+3]  or []
        c = b[i:i+1] if b[i] & 0x80 == 0 else b[i:i+2] if b[i] & 0xc0 == 0xc0 else b[i:i+3] if b[i] & 0xe0 == 0xe0 else []
        if len(c) == 0: raise ValueError('Invalid modified UTF-8')
        utf16.append(c[0] if len(c)==1 else (((c[0] & 0x1f) << 6) | (c[1] & 0x3f)) if len(c)==2 else (((c[0] & 0x0f) << 12) | ((c[1] & 0x3f) << 6) | (c[2] & 0x3f)) if len(c)==3 else -1)
    return unicode("".join([chr((c >> 8) & 0xff) + chr(c & 0xff) for c in utf16]), "utf_16_be")

class AMF0(object):
    NUMBER, BOOL, STRING, OBJECT, MOVIECLIP, NULL, UNDEFINED, REFERENCE, MIXEDARRAY, OBJECTTERM, ARRAY, DATE, LONGSTRING, UNSUPPORTED, XML, TYPEDOBJECT, TYPEAMF3 = range(0x11)

    def __init__(self, data):
        self.obj_refs, self.data = list(), data if isinstance(data, BytesIO) else BytesIO(data)
    def _created(self, obj):
        self.obj_refs.append(obj); return obj
    def read(self):
        type = self.data.read_uchar()
        if   type == AMF0.NUMBER:   return self.data.read_double()      # a double
        elif type == AMF0.BOOL:     return bool(self.data.read_uchar()) # bool type
        elif type == AMF0.STRING:   return self.readString()            # unicode
        elif type == AMF0.OBJECT:   return self.readObject()            # dict
        elif type == AMF0.MOVIECLIP:raise NotImplementedError()
        elif type == AMF0.NULL:     return None
        elif type == AMF0.UNDEFINED:return None
        elif type == AMF0.REFERENCE:return self.readReference()
        elif type == AMF0.MIXEDARRAY: len = self.data.read_ulong(); return dict(map(lambda x: (int(x[0]) if x[0].isdigit() else x[0], x[1]), self.readObject().items()))
        elif type == AMF0.ARRAY: len, obj = self.data.read_ulong(), self._created([]); obj.extend(self.read() for i in xrange(len)); return obj 
        elif type == AMF0.DATE:     return self.readDate()
        elif type == AMF0.LONGSTRING:return self.readLongString()
        elif type == AMF0.UNSUPPORTED:return None
        elif type == AMF0.XML:      return self.readXML()
        elif type == AMF0.TYPEDOBJECT: classname = self.readString(); return self.readObject()
        elif type == AMF0.TYPEAMF3: return AMF3(self.data).read()
        else: raise ValueError('Invalid AMF0 type 0x%02x at %d' % (type, self.data.tell()-1))

    def readString(self): return self.data.read_utf8(self.data.read_ushort())
    def readLongString(self): return self.data.read_utf8(self.data.read_ulong())
    def readReference(self): return self.obj_refs[self.data.read_ushort()]
    def readXML(self): return ET.fromstring(self.readLongString())
    
    def readObject(self):
        obj, key = self._created(dict()), self.readString()
        while key != '' or self.data.peek() != chr(AMF0.OBJECTTERM):
            obj[key] = self.read(); key = self.readString()
        self.data.read(1) # discard OBJECTTERM
        return obj

    def readDate(self):
        ms, tz = self.data.read_double(), self.data.read_short()
        class TZ(datetime.tzinfo):
            def utcoffset(self, dt): return datetime.timedelta(minutes=tz)
            def dst(self,dt): return None
            def tzname(self,dt): return None
        return datetime.datetime.fromtimestamp(ms/1000.0, TZ())
    
    type_map = [ ((bool,), 'writeBoolean'), ((int,long,float), 'writeNumber'), ((types.StringTypes,), 'writeString'), ((types.InstanceType,), 'writeObject'), ((datetime.date, datetime.datetime), 'writeDate'), ((ET._ElementInterface,), 'writeXML'), ((types.DictType,), 'writeMixedArray'), ]

    def write(self, data):
        for tlist, method in self.type_map:
            for t in filter(lambda x: isinstance(data, x), tlist): return getattr(self, method)(data)
        if data == None: self.writeNull()
    
    def writeNull(self): self.data.write_uchar(AMF0.NULL)
    def writeNumber(self, n): self.data.write_uchar(AMF0.NUMBER); self.data.write_double(float(n))
    def writeBoolean(self, b): self.data.write_uchar(AMF0.BOOL); self.data.write_uchar(1 if b else 0)
    
    def writeString(self, s, writeType=True):
        s = unicode(s).encode('utf8')
        if writeType: self.data.write_uchar(AMF0.LONGSTRING if len(s) > 0xffff else AMF0.STRING)
        if len(s) > 0xffff: self.data.write_ulong(len(s))
        else: self.data.write_ushort(len(s))
        self.data.write(s)
        
    def writeMixedArray(self, o):
        if o in self.obj_refs:
            self.data.write_uchar(AMF0.REFERENCE); self.data.write_ushort(self.obj_refs.index(o))
        else:
            self.obj_refs.append(o); self.data.write_uchar(AMF0.MIXEDARRAY); self.data.write_ulong(len(o))
            for key, val in o.items(): self.writeString(key, writeType=False); self.write(val)
            self.writeString('', writeType=False); self.data.write_uchar(AMF0.OBJECTTERM)
            
    def writeObject(self, o):
        if o in self.obj_refs:
            self.data.write_uchar(AMF0.REFERENCE); self.data.write_ushort(self.obj_refs.index(o))
        else:
            self.obj_refs.append(o); self.data.write_uchar(AMF0.OBJECT)
            for key, val in o.__dict__.items(): self.writeString(key, False); self.write(val)
            self.writeString('', False); self.data.write_uchar(AMF0.OBJECTTERM)
    
    def writeDate(self, d):
        if isinstance(d, datetime.date): d = datetime.datetime.combine(d, datetime.time(0))
        self.data.write_uchar(AMF0.DATE)
        ms = time.mktime(d.timetuple)
        if d.tzinfo: tz = d.tzinfo.utcoffset.days*1440 + d.tzinfo.utcoffset.seconds/60
        else: tz = 0
        self.data.write_double(ms); self.data.write_short(tz)
    
    def writeXML(self, e):
        data = ET.tostring(e, 'utf8')
        self.data.write_uchar(AMF0.XML); self.data.write_ulong(len(data)); self.data.write(data)

class AMF3:
    UNDEFINED, NULL, BOOL_FALSE, BOOL_TRUE, INTEGER, NUMBER, STRING, XML, DATE, ARRAY, OBJECT, XMLSTRING, BYTEARRAY = range(0x0d)
    PROPERTY, EXTERNALIZABLE, VALUE, PROXY = range(0x04)

    def __init__(self, data):
        self.obj_refs, self.str_refs, self.class_refs = list(), list(), list()
        self.data = data if isinstance(data, BytesIO) else BytesIO(data)

    def _created(self, obj, refs):
        refs.append(obj); return obj
        
    def read(self):
        type = self.data.read_uchar()
        if   type == AMF3.UNDEFINED:  return None
        elif type == AMF3.NULL:       return None
        elif type == AMF3.BOOL_FALSE: return False
        elif type == AMF3.BOOL_TRUE:  return True
        elif type == AMF3.INTEGER:    return self.readInteger()
        elif type == AMF3.NUMBER:     return self.data.read_double()
        elif type == AMF3.STRING:     return self.readString()
        elif type == AMF3.XML:        return self.readXML()
        elif type == AMF3.DATE:       return self.readDate()
        elif type == AMF3.ARRAY:      return self.readArray()
        elif type == AMF3.OBJECT:     return self.readObject()
        elif type == AMF3.XMLSTRING:  return self.readString(use_references=False)
        elif type == AMF3.BYTEARRAY:  return self.readByteArray()
        else: raise ValueError('Invalid AMF3 type 0x%02x at %d' % (type, self.data.tell()-1))
    
    def readInteger(self): # see http://osflash.org/amf3/parsing_integers for AMF3 integer data format
        n = result = 0;  b = self.data.read_uchar()
        while b & 0x80 and n < 3:
            result <<= 7; result |= b & 0x7f
            b = self.data.read_uchar(); n += 1
        if n < 3: result <<= 7; result |= b
        else: result <<= 8; result |= b
        if result & 0x10000000: result |= 0xe0000000
        return result # return a converted integer value
    
    def readString(self, use_references=True):
        length = self.readInteger()
        if use_references and length & 0x01 == 0: return self.str_refs[length >> 1]
        length >>= 1; buf = self.data.read(length)
        try: result = unicode(buf, 'utf8') # Try decoding as regular utf8 first. TODO: will it always raise exception?
        except UnicodeDecodeError: result = _decode_utf8_modified(buf)
        if use_references and len(result) != 0: self._created(result, self.str_refs)
        return result
    
    def readXML(self):
        return ET.fromstring(self.readString(False))
    
    def readByteArray(self):
        length = self.readInteger(); return self.data.read(length >> 1)
    
    def readDate(self):
        ref = self.readInteger()
        if ref & 0x01 == 0: return self.obj_refs[ref >> 1]
        ms = self.data.read_double()
        return self._created(datetime.datetime.fromtimestamp(ms/1000.0), self.obj_refs)
    
    def readArray(self):
        size = self.readInteger()
        if size & 0x01 == 0: return self.obj_refs[size >> 1]
        size >>= 1; key = self.readString()
        if key == '': # return python list
            result = self._created([], self.obj_refs)
            for i in xrange(size): result.append(self.read())
        else: # return python dict with key,value
            result = self._created({}, self.obj_refs)
            while key != '': result[key] = self.read(); key = self.readString()
            for i in xrange(size): result[i] = self.read()
        return result
    
    def readObject(self):
        type = self.readInteger()
        if type & 0x01 == 0: return self.obj_refs[type >> 1]
        class_ref = (type >> 1) & 0x01 == 0
        type >>= 2
        if class_ref: class_ = self.class_refs[type]
        else: class_ = AMF3Class(); class_.name, class_.encoding, class_.attrs = self.readString(), (type & 0x03), []
        type >>= 2
        obj = self._created(AMF3Object(class_) if class_.name else AMF3Object(), self.obj_refs)
        if class_.encoding & AMF3.EXTERNALIZABLE:
            if not class_ref: self.class_refs.append(class_)
            obj.__amf_externalized_data = self.read() # TODO: implement externalizeable interface here
        else:
            if class_.encoding & AMF3.VALUE:
                if not class_ref: self.class_refs.append(class_)
                attr = self.readString()
                while attr != '':
                    class_.attrs.append(attr)
                    setattr(obj, attr, self.read())
                    attr = self.readString()
            else:
                if not class_ref:
                    for i in range(type): class_.attrs.append(self.readString())
                    self.class_refs.append(class_)
                for attr in class_.attrs: setattr(obj, attr, self.read())
        return obj

class AMF3Class:
    def __init__(self, name=None, encoding=None, attrs=None):
        self.name, self.encoding, self.attrs = name, encoding, attrs

class AMF3Object:
    def __init__(self, class_=None): self.__amf_class = class_
    def __repr__(self): return "<AMF3Object [%s] at 0x%08X>" % (self.__amf_class and self.__amf_class.name or "no class", id(self))

#------------------------------------------------------------------------------
# Unit Test Code

class AMFMessageHeader:
    def __init__(self): self.name = self.required = self.length = self.data = None
    def __repr__(self): return '<AMFMessageHeader %s = %r>' % (self.name, self.data)

class AMFMessageBody:
    def __init__(self): self.target = self.response = self.length = self.data = None
    def __repr__(self): return '<AMFMessageBody %s = %r>' % (self.target, self.data)
    
class AMFMessage:
    def __init__(self): self.amfVersion, self.clientType, self.headers, self.bodies = None, None, [], []
    def __repr__(self): return '<AMFMessage %s %s>'%(' '.join(map(repr, self.headers)), ' '.join(map(repr, self.bodies)))

class AMFMessageEncoder:
    def __init__(self, data): self.data = BytesIO(data)
    def encode(self): return AMFMessage()

class AMFMessageParser:
    def __init__(self, data):
        self.data = BytesIO(data)
    
    def parse(self):
        msg = AMFMessage()
        msg.amfVersion = self.data.read_uchar()
        parser_class = AMF0 if msg.amfVersion == 0 else AMF3 if msg.amfVersion == 3 else None
        if not parser_class: raise Exception('Invalid AMF version %d' % (msg.amfVersion))
        msg.clientType, header_count = self.data.read_uchar(), self.data.read_short()
        for i in xrange(header_count):
            header = AMFMessageHeader()
            header.name = self.data.read_utf8(self.data.read_ushort())
            header.required = bool(self.data.read_uchar())
            msg.length = self.data.read_ulong()
            header.data = parser_class(self.data).read()
            msg.headers.append(header)
        bodies_count = self.data.read_short()
        for i in xrange(bodies_count):
            body = AMFMessageBody()
            body.target = self.data.read_utf8(self.data.read_ushort())
            body.response = self.data.read_utf8(self.data.read_ushort())
            body.length = self.data.read_ulong()
            body.data = parser_class(self.data).read()
            msg.bodies.append(body)
        return msg

if __name__ == '__main__':
    import sys, glob
    for fname in sum(map(lambda x: glob.glob(x), sys.argv[1:]), []):
        print "parsing", fname, 
        f = file(fname, "r"); data = f.read(); f.close()
        p = AMFMessageParser(data)
        try: obj = p.parse()
        except: raise
        else: print "  success"

# Original source from rtmpy.org's amf.py, util.py with following Copyright:
#
# Copyright (c) 2007 The RTMPy Project. All rights reserved.
# 
# Arnar Birgisson
# Thijs Triemstra
# 
# Permission is hereby granted, free of charge, to any person obtaining
# a copy of this software and associated documentation files (the
# "Software"), to deal in the Software without restriction, including
# without limitation the rights to use, copy, modify, merge, publish,
# distribute, sublicense, and/or sell copies of the Software, and to
# permit persons to whom the Software is furnished to do so, subject to
# the following conditions:
# 
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
# 
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE
# LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION
# WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
