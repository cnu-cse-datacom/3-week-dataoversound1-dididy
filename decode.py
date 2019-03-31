from __future__ import print_function  # python 2와 3를 동시에 사용할 수 있도록 함 print함수 괄호 안한거 상관없게 하도록 함

import sys  # __name__에서 쓰임 왜쓰일까?
import wave  # https://iamaman.tistory.com/495

from io import StringIO  # 파일 입출력 // .write(), .read(), .seek()

import alsaaudio  # 오디오 녹음
import colorama  # 터미널 글자색이나 배경색 바꿔주는거
import numpy as np  # np로 호출하는게 관례가 됨 수치해석이나 통계관련 기능 구현에 필요

from reedsolo import RSCodec, ReedSolomonError  # encode decode https://pypi.org/project/reedsolo/
from termcolor import cprint  # 터미널 글자에 대한 설정
from pyfiglet import figlet_format  # ASCII ART를 위한.. 이거였구만

HANDSHAKE_START_HZ = 4096  # Handshake 시작 주파수 // 송신자와 수신자가 통신을 시작하는 약속하는 단계
HANDSHAKE_END_HZ = 5120 + 1024  # Handshake 끝 주파수 // 송신자와 수신자가 데이터 수집 종료를 약속하는 단계

START_HZ = 1024
STEP_HZ = 256
BITS = 4

FEC_BYTES = 4  # Forward Error Correction

# def stereo_to_mono(input_file, output_file):  # decode_file 함수에서 쓰임 // 오디오 트랙을 1개로 합침
#     inp = wave.open(input_file, 'r')
#     params = list(inp.getparams())
#     params[0] = 1  # nchannels
#     params[3] = 0  # nframes
#
#     out = wave.open(output_file, 'w')
#     out.setparams(tuple(params))
#
#     frame_rate = inp.getframerate()
#     frames = inp.readframes(inp.getnframes())
#     data = np.fromstring(frames, dtype=np.int16)
#     left = data[0::2]
#     out.writeframes(left.tostring())
#
#     inp.close()
#     out.close()

# def yield_chunks(input_file, interval):  # decode_file 함수에서 쓰임 // ????
#     wav = wave.open(input_file)
#     frame_rate = wav.getframerate()
#
#     chunk_size = int(round(frame_rate * interval))
#     total_size = wav.getnframes()
#
#     while True:
#         chunk = wav.readframes(chunk_size)
#         if len(chunk) == 0:
#             return
#
#         yield frame_rate, np.fromstring(chunk, dtype=np.int16)

def dominant(frame_rate, chunk):  # decode_file, listen_linux 함수에서 쓰임 // 수신한 청크의 주파수를 dominant() 함수로 계산
    w = np.fft.fft(chunk)
    freqs = np.fft.fftfreq(len(chunk))
    peak_coeff = np.argmax(np.abs(w))
    peak_freq = freqs[peak_coeff]
    print(abs(peak_freq * frame_rate)) # hz를 출력하기 위해 넣은 코
    return abs(peak_freq * frame_rate) # in Hz

def match(freq1, freq2):  # listen_linux 함수에서 쓰임 // 두 수의 차의 절대값을 구하는 함수
    return abs(freq1 - freq2) < 20 # abs() 함수는 내장함수로 절대값 구하는 함수임

def decode_bitchunks(chunk_bits, chunks):  # extract_packet 함수에서 return 으로 반환할 때 쓰임
    out_bytes = []

    next_read_chunk = 0
    next_read_bit = 0

    byte = 0
    bits_left = 8
    while next_read_chunk < len(chunks):
        can_fill = chunk_bits - next_read_bit
        to_fill = min(bits_left, can_fill)
        offset = chunk_bits - next_read_bit - to_fill
        byte <<= to_fill
        shifted = chunks[next_read_chunk] & (((1 << to_fill) - 1) << offset)
        byte |= shifted >> offset;
        bits_left -= to_fill
        next_read_bit += to_fill
        if bits_left <= 0:

            out_bytes.append(byte)
            byte = 0
            bits_left = 8

        if next_read_bit >= chunk_bits:
            next_read_chunk += 1
            next_read_bit -= chunk_bits

    return out_bytes

# def decode_file(input_file, speed):
#     wav = wave.open(input_file)
#     if wav.getnchannels() == 2:
#         mono = StringIO()
#         stereo_to_mono(input_file, mono)
#
#         mono.seek(0)
#         input_file = mono
#     wav.close()
#
#     offset = 0
#     for frame_rate, chunk in yield_chunks(input_file, speed / 2):
#         dom = dominant(frame_rate, chunk)
#         print("{} => {}".format(offset, dom))
#         offset += 1

def extract_packet(freqs):  # listen_linux 함수에서 쓰임
    freqs = freqs[::2]
    bit_chunks = [int(round((f - START_HZ) / STEP_HZ)) for f in freqs]
    bit_chunks = [c for c in bit_chunks[1:] if 0 <= c < (2 ** BITS)]
    return bytearray(decode_bitchunks(BITS, bit_chunks))

def display(s):  # listen_linux 함수에서 쓰임 // 글자색을 노란색으로 바꾸는 // figlet_format은 ASCII아트 형태로
    cprint(figlet_format(s.replace(' ', '   '), font='doom'), 'yellow')

def listen_linux(frame_rate=44100, interval=0.1):  # 사실상 main함수로 봐야 함

    mic = alsaaudio.PCM(alsaaudio.PCM_CAPTURE, alsaaudio.PCM_NORMAL, device="default")  # 리눅스 사운드 구동을 위한 alsa 드라이버를 이용하여 PCM 코덱을 호출

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

        chunk = np.fromstring(data, dtype=np.int16)  # fromstring()함수는 XML 형태로 저장해 주는 것?
        dom = dominant(frame_rate, chunk)  # dominant() // 수신한 chunk의 주파수를 dominant() 함수로 계산

        if in_packet and match(dom, HANDSHAKE_END_HZ):  # match() // (두 수의 차의 절대값 구하는 과정) 핸드쉐이크 종료 주파수를 수신하고 디코딩을 시작
            byte_stream = extract_packet(packet)  # extract_packet() [ decode_bitchunks() ]
            try:
                byte_stream = RSCodec(FEC_BYTES).decode(byte_stream)  # RSCodec() 함수로 Reed Solomon 코딩된 FEC 바이트를 디코딩
                byte_stream = byte_stream.decode("utf-8")

                display(byte_stream)  # display() // 디코딩된 결과 출력
            except ReedSolomonError as e:
                pass
                #print("{}: {}".format(e, byte_stream))

            packet = []
            in_packet = False
        elif in_packet:
            packet.append(dom)
        elif match(dom, HANDSHAKE_START_HZ):  # match() // 두 수의 차의 절대값 구하는 과정
            in_packet = True

if __name__ == '__main__':
    colorama.init(strip=not sys.stdout.isatty())  # 터미널 글자색 관련 설정

    #decode_file(sys.argv[1], float(sys.argv[2]))  # 이건 .wav 파일을 읽어오는 경우 실행
    listen_linux()
