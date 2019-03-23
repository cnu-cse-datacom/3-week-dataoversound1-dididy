from __future__ import print_function # python 2와 3를 동시에 사용할 수 있도록 함 print함수 괄호 안한거 상관없게 하도록 함

import sys # __name__에서 쓰임 왜쓰일까?
import wave # https://iamaman.tistory.com/495

from io import StringIO # 파일 입출력 // .write(), .read(), .seek()

import alsaaudio # 오디오 녹음
import colorama # 터미널 글자색이나 배경색 바꿔주는거
import numpy as np # np로 호출하는게 관례가 됨 수치해석이나 통계관련 기능 구현에 필요

from reedsolo import RSCodec, ReedSolomonError # encode decode https://pypi.org/project/reedsolo/
from termcolor import cprint # 터미널 글자에 대한 설정
from pyfiglet import figlet_format # ASCII ART를 위한.. 이거였구만

HANDSHAKE_START_HZ = 8192 # chirp 의 주파수 대역의 시작?
HANDSHAKE_END_HZ = 8192 + 512 # 아마 여기까지인듯 https://en.wikipedia.org/wiki/Audio_frequency
 
START_HZ = 1024 # 뭘까
STEP_HZ = 256 # 이건 또 뭐고
BITS = 4 # 

FEC_BYTES = 4 # Forward Error Correction

def stereo_to_mono(input_file, output_file): # decode_file 함수에서 쓰임
    inp = wave.open(input_file, 'r')
    params = list(inp.getparams())
    params[0] = 1 # nchannels
    params[3] = 0 # nframes

    out = wave.open(output_file, 'w')
    out.setparams(tuple(params))

    frame_rate = inp.getframerate()
    frames = inp.readframes(inp.getnframes())
    data = np.fromstring(frames, dtype=np.int16)
    left = data[0::2]
    out.writeframes(left.tostring())

    inp.close()
    out.close()

def yield_chunks(input_file, interval): # decode_file 함수에서 쓰임
    wav = wave.open(input_file)
    frame_rate = wav.getframerate()

    chunk_size = int(round(frame_rate * interval))
    total_size = wav.getnframes()

    while True:
        chunk = wav.readframes(chunk_size)
        if len(chunk) == 0:
            return

        yield frame_rate, np.fromstring(chunk, dtype=np.int16)

def dominant(frame_rate, chunk): # decode_file, listen_linux 함수에서 쓰임
    #print("chunk",chunk)
    w = np.fft.fft(chunk)
    #print("w:",w)
    freqs = np.fft.fftfreq(len(chunk))
    #print("freqs:",freqs)
    peak_coeff = np.argmax(np.abs(w))
    #print("peak_coeff:",peak_coeff)
    peak_freq = freqs[peak_coeff]
    #print("peak_freq",peak_freq)
    return abs(peak_freq * frame_rate) # in Hz

def match(freq1, freq2): # listen_linux 함수에서 쓰임
    return abs(freq1 - freq2) < 20

def decode_bitchunks(chunk_bits, chunks): # extract_packet 함수에서 
    out_bytes = []

    next_read_chunk = 0
    next_read_bit = 0

    byte = 0
    bits_left = 8
    while next_read_chunk < len(chunks):
        can_fill = chunk_bits - next_read_bit
        #print("can:",can_fill)
        to_fill = min(bits_left, can_fill)
        #print("to:",to_fill)
        offset = chunk_bits - next_read_bit - to_fill
        #print("offset:",offset)
        byte <<= to_fill
        #print("byte:",byte)
        shifted = chunks[next_read_chunk] & (((1 << to_fill) - 1) << offset)
        #print("shifted:",shifted)
        byte |= shifted >> offset;
        #print("byte",byte)
        bits_left -= to_fill
        #print("bits_left:",bits_left)
        next_read_bit += to_fill
        #print("next_read:",next_read_bit)
        if bits_left <= 0:

            out_bytes.append(byte)
            byte = 0
            bits_left = 8

        if next_read_bit >= chunk_bits:
            next_read_chunk += 1
            next_read_bit -= chunk_bits
    #print(out_bytes)

    return out_bytes

def decode_file(input_file, speed): # 왜 if __name__ == '__main__': 에 주석처리 되어 있을까
    wav = wave.open(input_file)
    if wav.getnchannels() == 2:
        mono = StringIO()
        stereo_to_mono(input_file, mono) 

        mono.seek(0)
        input_file = mono
    wav.close()

    offset = 0
    for frame_rate, chunk in yield_chunks(input_file, speed / 2):
        dom = dominant(frame_rate, chunk)
        print("{} => {}".format(offset, dom))
        offset += 1

def extract_packet(freqs): # listen_linux 함수에서 쓰임
    freqs = freqs[::2]
    bit_chunks = [int(round((f - START_HZ) / STEP_HZ)) for f in freqs]
    bit_chunks = [c for c in bit_chunks[1:] if 0 <= c < (2 ** BITS)]
    return bytearray(decode_bitchunks(BITS, bit_chunks))

def display(s): # listen_linux 함수에서 쓰임
    cprint(figlet_format(s.replace(' ', '   '), font='doom'), 'yellow')

def listen_linux(frame_rate=44100, interval=0.1): # 사실상 main함수로 봐야 함

    mic = alsaaudio.PCM(alsaaudio.PCM_CAPTURE, alsaaudio.PCM_NORMAL)
    mic.setchannels(1)
    mic.setrate(44100)
    mic.setformat(alsaaudio.PCM_FORMAT_S16_LE)

    num_frames = int(round((interval / 2) * frame_rate))
    mic.setperiodsize(num_frames)
    print("start...")

    in_packet = False
    packet = []

    while True:
        l, data = mic.read()
        if not l:
            continue

        chunk = np.fromstring(data, dtype=np.int16)
        dom = dominant(frame_rate, chunk)

        if in_packet and match(dom, HANDSHAKE_END_HZ):
            byte_stream = extract_packet(packet)
            print("original code",byte_stream)

            try:
                byte_stream = RSCodec(FEC_BYTES).decode(byte_stream)
                byte_stream = byte_stream.decode("utf-8")
                display(byte_stream)
                display("")
            except ReedSolomonError as e:
                print("{}: {}".format(e, byte_stream))

            packet = []
            in_packet = False
        elif in_packet:
            packet.append(dom)
        elif match(dom, HANDSHAKE_START_HZ):
            in_packet = True

if __name__ == '__main__':
    colorama.init(strip=not sys.stdout.isatty()) # 터미널 글자색 관련 설정

    #decode_file(sys.argv[1], float(sys.argv[2]))
    listen_linux() # main함수에 
