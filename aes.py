#!/usr/bin/env python
# (c) 2011, Cumulus Python <cumulus.python@gmail.com>. No rights reserved.
# Optimized version of pure Python AES.

'''
To check the time it takes for 1 iteration of encryption plus decryption of 1000 bytes of data using AES 128 bit key:
  $ python -m timeit "import aes; aes._test(repeat=1, mode=aes.CBC, dataSize=1000, keySize=128/8)"

To print the time taken by individual functions over 200 iterations:
  $ python -m cProfile aes.py

Performance Measurement
-----------------------
  $ python -m timeit "import aes; aes._test(repeat=1);"
  10 loops, best of 3: 29.5 msec per loop
'''

import os, sys, math, struct, random

OFB, CFB, CBC = 0, 1, 2 # mode of operation
SIZE_128, SIZE_192, SIZE_256 = 16, 24, 32

iv_null   = lambda: [0 for i in xrange(16)]
iv_random = lambda: [ord(random.randint(0, 255)) for i in xrange(16)]

def encrypt(key, data, iv, mode=CBC):
    key, keysize = map(ord, key), len(key)
    assert keysize in (16, 24, 32), 'invalid key size: %s' % keysize
    (mode, length, ciph) = _encrypt(data, mode, key, keysize, iv) # do not store the length
    return ''.join(map(chr, ciph))

def decrypt(key, data, iv, mode=CBC):
    key, data, keysize = map(ord, key), map(ord, data), len(key)
    assert keysize in (16, 24, 32), 'invalid key size: %s' % keysize
    return _decrypt(data, None, mode, key, keysize, iv)

def append_PKCS7_padding(s): # return s padded to a multiple of 16-bytes by PKCS7 padding
    numpads = 16 - (len(s)%16)
    return s + numpads*chr(numpads)

def strip_PKCS7_padding(s): # return s stripped of PKCS7 padding
    if len(s)%16 or not s: raise ValueError("String of len %d can't be PCKS7-padded" % len(s))
    numpads = ord(s[-1])
    if numpads > 16: raise ValueError("String ending with %r can't be PCKS7-padded" % s[-1])
    return s[:-numpads]



def _galois_multiplication(a, b): # Galois multiplication of 8 bit numbers a and b
    p = 0
    for counter in xrange(8):
        if b & 1: p ^= a
        hi_bit_set = a & 0x80
        a = (a << 1) & 0xff
        if hi_bit_set: a ^= 0x1b
        b >>= 1
    return p

# galois multiplication table _g1, _g2, ..., Rijndael S-box _sbox, inverted S-box _rsbox, Rcon _rcon
for i in (1, 2, 3, 9, 11, 13, 14): exec("_g%d = [_galois_multiplication(a, %d)  for a in xrange(256)]"%(i, i))
del i
_sbox  = map(ord, '\x63\x7c\x77\x7b\xf2\x6b\x6f\xc5\x30\x01\x67\x2b\xfe\xd7\xab\x76\xca\x82\xc9\x7d\xfa\x59\x47\xf0\xad\xd4\xa2\xaf\x9c\xa4\x72\xc0\xb7\xfd\x93\x26\x36\x3f\xf7\xcc\x34\xa5\xe5\xf1\x71\xd8\x31\x15\x04\xc7\x23\xc3\x18\x96\x05\x9a\x07\x12\x80\xe2\xeb\x27\xb2\x75\x09\x83\x2c\x1a\x1b\x6e\x5a\xa0\x52\x3b\xd6\xb3\x29\xe3\x2f\x84\x53\xd1\x00\xed\x20\xfc\xb1\x5b\x6a\xcb\xbe\x39\x4a\x4c\x58\xcf\xd0\xef\xaa\xfb\x43\x4d\x33\x85\x45\xf9\x02\x7f\x50\x3c\x9f\xa8\x51\xa3\x40\x8f\x92\x9d\x38\xf5\xbc\xb6\xda\x21\x10\xff\xf3\xd2\xcd\x0c\x13\xec\x5f\x97\x44\x17\xc4\xa7\x7e\x3d\x64\x5d\x19\x73\x60\x81\x4f\xdc\x22\x2a\x90\x88\x46\xee\xb8\x14\xde\x5e\x0b\xdb\xe0\x32\x3a\x0a\x49\x06\x24\x5c\xc2\xd3\xac\x62\x91\x95\xe4\x79\xe7\xc8\x37\x6d\x8d\xd5\x4e\xa9\x6c\x56\xf4\xea\x65\x7a\xae\x08\xba\x78\x25\x2e\x1c\xa6\xb4\xc6\xe8\xdd\x74\x1f\x4b\xbd\x8b\x8a\x70\x3e\xb5\x66\x48\x03\xf6\x0e\x61\x35\x57\xb9\x86\xc1\x1d\x9e\xe1\xf8\x98\x11\x69\xd9\x8e\x94\x9b\x1e\x87\xe9\xce\x55\x28\xdf\x8c\xa1\x89\x0d\xbf\xe6\x42\x68\x41\x99\x2d\x0f\xb0\x54\xbb\x16')
_rsbox = map(ord, '\x52\x09\x6a\xd5\x30\x36\xa5\x38\xbf\x40\xa3\x9e\x81\xf3\xd7\xfb\x7c\xe3\x39\x82\x9b\x2f\xff\x87\x34\x8e\x43\x44\xc4\xde\xe9\xcb\x54\x7b\x94\x32\xa6\xc2\x23\x3d\xee\x4c\x95\x0b\x42\xfa\xc3\x4e\x08\x2e\xa1\x66\x28\xd9\x24\xb2\x76\x5b\xa2\x49\x6d\x8b\xd1\x25\x72\xf8\xf6\x64\x86\x68\x98\x16\xd4\xa4\x5c\xcc\x5d\x65\xb6\x92\x6c\x70\x48\x50\xfd\xed\xb9\xda\x5e\x15\x46\x57\xa7\x8d\x9d\x84\x90\xd8\xab\x00\x8c\xbc\xd3\x0a\xf7\xe4\x58\x05\xb8\xb3\x45\x06\xd0\x2c\x1e\x8f\xca\x3f\x0f\x02\xc1\xaf\xbd\x03\x01\x13\x8a\x6b\x3a\x91\x11\x41\x4f\x67\xdc\xea\x97\xf2\xcf\xce\xf0\xb4\xe6\x73\x96\xac\x74\x22\xe7\xad\x35\x85\xe2\xf9\x37\xe8\x1c\x75\xdf\x6e\x47\xf1\x1a\x71\x1d\x29\xc5\x89\x6f\xb7\x62\x0e\xaa\x18\xbe\x1b\xfc\x56\x3e\x4b\xc6\xd2\x79\x20\x9a\xdb\xc0\xfe\x78\xcd\x5a\xf4\x1f\xdd\xa8\x33\x88\x07\xc7\x31\xb1\x12\x10\x59\x27\x80\xec\x5f\x60\x51\x7f\xa9\x19\xb5\x4a\x0d\x2d\xe5\x7a\x9f\x93\xc9\x9c\xef\xa0\xe0\x3b\x4d\xae\x2a\xf5\xb0\xc8\xeb\xbb\x3c\x83\x53\x99\x61\x17\x2b\x04\x7e\xba\x77\xd6\x26\xe1\x69\x14\x63\x55\x21\x0c\x7d')
_rcon  = map(ord, '\x8d\x01\x02\x04\x08\x10\x20\x40\x80\x1b\x36\x6c\xd8\xab\x4d\x9a\x2f\x5e\xbc\x63\xc6\x97\x35\x6a\xd4\xb3\x7d\xfa\xef\xc5\x91\x39\x72\xe4\xd3\xbd\x61\xc2\x9f\x25\x4a\x94\x33\x66\xcc\x83\x1d\x3a\x74\xe8\xcb\x8d\x01\x02\x04\x08\x10\x20\x40\x80\x1b\x36\x6c\xd8\xab\x4d\x9a\x2f\x5e\xbc\x63\xc6\x97\x35\x6a\xd4\xb3\x7d\xfa\xef\xc5\x91\x39\x72\xe4\xd3\xbd\x61\xc2\x9f\x25\x4a\x94\x33\x66\xcc\x83\x1d\x3a\x74\xe8\xcb\x8d\x01\x02\x04\x08\x10\x20\x40\x80\x1b\x36\x6c\xd8\xab\x4d\x9a\x2f\x5e\xbc\x63\xc6\x97\x35\x6a\xd4\xb3\x7d\xfa\xef\xc5\x91\x39\x72\xe4\xd3\xbd\x61\xc2\x9f\x25\x4a\x94\x33\x66\xcc\x83\x1d\x3a\x74\xe8\xcb\x8d\x01\x02\x04\x08\x10\x20\x40\x80\x1b\x36\x6c\xd8\xab\x4d\x9a\x2f\x5e\xbc\x63\xc6\x97\x35\x6a\xd4\xb3\x7d\xfa\xef\xc5\x91\x39\x72\xe4\xd3\xbd\x61\xc2\x9f\x25\x4a\x94\x33\x66\xcc\x83\x1d\x3a\x74\xe8\xcb\x8d\x01\x02\x04\x08\x10\x20\x40\x80\x1b\x36\x6c\xd8\xab\x4d\x9a\x2f\x5e\xbc\x63\xc6\x97\x35\x6a\xd4\xb3\x7d\xfa\xef\xc5\x91\x39\x72\xe4\xd3\xbd\x61\xc2\x9f\x25\x4a\x94\x33\x66\xcc\x83\x1d\x3a\x74\xe8\xcb')


def _core(word, iteration): # core key schedule: rotate 32-bit word 8 bits to left, apply S-box on all 4 parts and XOR the rcon output with first part
    word = word[1:] + word[:1]
    for i in xrange(4): word[i] = _sbox[word[i]]
    word[0] = word[0] ^ _rcon[iteration]
    return word

def _expandKey(key, size, expandedKeySize): # Rijndael's key expansion: expands an 128,192,256 key into an 176,208,240 bytes key
    currentSize, rconIteration = 0, 1
    expandedKey = [0]*expandedKeySize
    for j in xrange(size): expandedKey[j] = key[j] # set the 16, 24, 32 bytes of the expanded key to the input key
    currentSize += size
    while currentSize < expandedKeySize:
        t = expandedKey[currentSize-4:currentSize] # assign the previous 4 bytes to the temporary value t
        if currentSize % size == 0: # every 16,24,32 bytes we apply the core schedule to t and increment rconIteration afterwards
            t = _core(t, rconIteration)
            rconIteration += 1
        if size == SIZE_256 and ((currentSize % size) == 16): # For 256-bit keys, we add an extra sbox to the calculation
            for l in xrange(4): t[l] = _sbox[t[l]]
        for m in xrange(4): # We XOR t with the four-byte block 16,24,32 bytes before the new expanded key.  This becomes the next four bytes in the expanded key.
            expandedKey[currentSize] = expandedKey[currentSize - size] ^  t[m]
            currentSize += 1
    return expandedKey

def _addRoundKey(state, roundKey): # Adds (XORs) the round key to the state.
    for i in xrange(16): state[i] ^= roundKey[i]
    return state

def _createRoundKey(expanded, pos): # create a round key from the given expanded key and the position within
    subset = expanded[pos:pos+16]
    return [subset[0], subset[4], subset[8], subset[12],
            subset[1], subset[5], subset[9], subset[13],
            subset[2], subset[6], subset[10],subset[14],
            subset[3], subset[7], subset[11],subset[15]]

def _subBytes(state, isInv): # substitute all values from S-Box or inverted S-box
    return [_rsbox[x] for x in state] if isInv else [_sbox[x] for x in state]

def _shiftRows(state, isInv): # shift row all rows by row index
    if isInv:
        state[4], state[5], state[6], state[7] = state[7], state[4], state[5], state[6]
        state[8], state[9], state[10],state[11]= state[10],state[11],state[8], state[9]
        state[12],state[13],state[14],state[15]= state[13],state[14],state[15],state[12]
    else:
        state[4], state[5], state[6], state[7] = state[5], state[6], state[7], state[4]
        state[8], state[9], state[10],state[11]= state[10],state[11],state[8], state[9]
        state[12],state[13],state[14],state[15]= state[15],state[12],state[13],state[14]
    return state

_mixColumnInv = lambda c0, c1, c2, c3: (_g14[c0] ^ _g9[c3] ^ _g13[c2] ^ _g11[c1], _g14[c1] ^ _g9[c0] ^ _g13[c3] ^ _g11[c2], _g14[c2] ^ _g9[c1] ^ _g13[c0] ^ _g11[c3], _g14[c3] ^ _g9[c2] ^ _g13[c1] ^ _g11[c0])
_mixColumn = lambda c0, c1, c2, c3: (_g2[c0] ^ _g1[c3] ^ _g1[c2] ^ _g3[c1], _g2[c1] ^ _g1[c0] ^ _g1[c3] ^ _g3[c2], _g2[c2] ^ _g1[c1] ^ _g1[c0] ^ _g3[c3], _g2[c3] ^ _g1[c2] ^ _g1[c1] ^ _g3[c0])
    
def _mixColumns(state, isInv): # galois multiplication of 4x4 matrix
    state[0], state[4], state[8], state[12] = (_mixColumnInv if isInv else _mixColumn)(state[0], state[4], state[8], state[12])
    state[1], state[5], state[9], state[13] = (_mixColumnInv if isInv else _mixColumn)(state[1], state[5], state[9], state[13])
    state[2], state[6], state[10],state[14] = (_mixColumnInv if isInv else _mixColumn)(state[2], state[6], state[10],state[14])
    state[3], state[7], state[11],state[15] = (_mixColumnInv if isInv else _mixColumn)(state[3], state[7], state[11],state[15])
    return state

def _aes_round(state, roundKey): # forward round operations
    return _addRoundKey(_mixColumns(_shiftRows(_subBytes(state, False), False), False), roundKey)

def _aes_invRound(state, roundKey): # inverse round operations
    return _mixColumns(_addRoundKey(_subBytes(_shiftRows(state, True), True), roundKey), True)

def _aes_main(state, expandedKey, nbrRounds): # initial operations, standard round, and final operations of forward direction
    state = _addRoundKey(state, _createRoundKey(expandedKey, 0))
    for i in xrange(1, nbrRounds):
        state = _addRoundKey(_mixColumns(_shiftRows(_subBytes(state, False), False), False), _createRoundKey(expandedKey, 16*i))
    return _addRoundKey(_shiftRows(_subBytes(state, False), False), _createRoundKey(expandedKey, 16*nbrRounds))

def _aes_invMain(state, expandedKey, nbrRounds): # initial operations, standard round, and final operations of inverse direction
    state = _addRoundKey(state, _createRoundKey(expandedKey, 16*nbrRounds))
    for i in xrange(nbrRounds-1, 0, -1):
        state = _mixColumns(_addRoundKey(_subBytes(_shiftRows(state, True), True), _createRoundKey(expandedKey, 16*i)), True)
    return _addRoundKey(_subBytes(_shiftRows(state, True), True), _createRoundKey(expandedKey, 0))

_last_key = _last_expanded_key = None

_rounds = {SIZE_128: 10, SIZE_192: 12, SIZE_256: 14}

def _aes_block(iput, key, size, isInv): # encrypt 128-bit input block against the given key of given size
    global _last_key, _last_expanded_key, _rounds
    if size not in _rounds: return None
    nbrRounds = _rounds.get(size)
    expandedKeySize = 16*(nbrRounds+1) # the expanded keySize

    block = [iput[i+4*j] for i in xrange(4) for j in xrange(4)]
    expandedKey = _last_expanded_key if _last_key == key else _expandKey(key, size, expandedKeySize) # expand the key into an 176, 208, 240 bytes key the expanded key
    _last_key, _last_expanded_key = key, expandedKey
    
    block = _aes_invMain(block, expandedKey, nbrRounds) if isInv else _aes_main(block, expandedKey, nbrRounds)  # encrypt or decrypt the block using the expandedKey
    return [block[i+4*j] for i in xrange(4) for j in xrange(4)]

def _encrypt(stringIn, mode, key, size, IV):
    assert len(key) % size == 0 and len(IV) % 16 == 0
    cipherOut, firstRound = [], True
    if stringIn != None:
        for start in xrange(0, len(stringIn), 16):
            plaintext = map(ord, stringIn[start:start+16])
            if len(plaintext) < 16: plaintext += [0]*(16-len(plaintext))
            if mode == CFB:
                output = _aes_block(IV if firstRound else iput, key, size, False)
                firstRound = False
                # TODO: verify the following
                ciphertext = [(0 if len(plaintext)-1 < i else plaintext[0]) ^ (0 if len(output)-1 < i else output[i]) for i in xrange(16)]
                cipherOut += [ciphertext[k] for k in xrange(end-start)]
                iput = ciphertext if mode == CFB else output
            elif mode == CBC:
                iput = [plaintext[i] ^ IV[i] for i in xrange(16)] if firstRound else [plaintext[i] ^ ciphertext[i] for i in xrange(16)]
                firstRound = False
                ciphertext = _aes_block(iput, key, size, False)
                cipherOut += ciphertext
    return mode, len(stringIn), cipherOut

def _decrypt(cipherIn, originalsize, mode, key, size, IV):
    assert len(key) % size == 0 and len(IV) % 16 == 0
    stringOut, firstRound = [], True
    if cipherIn != None:
        for start in xrange(0, len(cipherIn), 16):
            ciphertext = cipherIn[start:start+16]
            end = start + len(ciphertext)
            if mode == CFB or mode == OFB:
                output = _aes_block(IV if firstRound else iput, key, size, False) # TODO: verify that it calls encrypt, and not decrypt
                firstRound = False
                # TODO: verify the following
                plaintext = [(0 if len(output)-1 < i else output[0]) ^ (0 if len(ciphertext)-1 < i else ciphertext[i]) for i in xrange(16)]
                stringOut += [plaintext[k] for k in xrange(end-start)]
                iput = ciphertext if mode == CFB else output
            elif mode == CBC:
                output = _aes_block(ciphertext, key, size, True)
                plaintext = [IV[i] ^ output[i] for i in xrange(16)] if firstRound else [iput[i] ^ output[i] for i in xrange(16)]
                firstRound = False
                end1 = originalsize if originalsize is not None and originalsize < end else end
                stringOut += [plaintext[k] for k in xrange(end1-start)]
                iput = ciphertext
    return ''.join(map(chr, stringOut))

def _test(debug=False, mode=CBC, dataSize=1000, keySize=16, repeat=100):
    cleartext = ''.join([chr(random.randint(0, 255)) for i in xrange(dataSize)])
    if debug: print 'cleartext=%r'%(cleartext,)
    for i in xrange(repeat):
        cypherkey, iv = [random.randint(1,255) for i in xrange(keySize)], [0 for i in xrange(keySize)]
        mode1, orig_len, ciph = _encrypt(cleartext, mode, cypherkey, keySize, iv)
        if debug: print 'mode=%s, original length=%s (%s)\nencrypted=%s'%(mode, orig_len, len(cleartext), ciph)
        decr = _decrypt(ciph, orig_len, mode1, cypherkey, keySize, iv)
        if debug: print 'decrypted=%r'%(decr,)
        assert decr == cleartext

def _test2():
    encoded = "%\x01\xf6o\xfd\x00\xb7\x9a\xd8\x01A\xf5\xae\xeb\x91y\x15\x8d\x19@\x9d\x83\x05\xef'\x16\x86|v4~j\x8ejT'\x9f\x97d\xd6\x19\xd5\xfa\xd5C\xeb\xd2g\xfb\xd9 \xc0\x86l\xe6^\x94\x05<\xa0\xe6\xbc\xa1\xbd\xea\x8c\xfe\xd8"
    decr = decrypt('Adobe Systems 02', encoded[4:], iv=iv_null())
    assert decr.find('rtmfp://localhost/myapp') >= 0

if __name__ == "__main__":
    _test()
    _test2()
