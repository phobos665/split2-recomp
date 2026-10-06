"""
TimeSplitters 2 sounds (.xbs, in data/sounds.pak): decode to WAV, encode
from WAV.

    py -3 -m tools.xbs decode gun_silenced22.xbs out.wav
    py -3 -m tools.xbs encode in.wav out.xbs --like gun_silenced22.xbs

An .xbs is a 24-byte header, 8 zero bytes, and Xbox ADPCM blocks from
offset 32 to the end of the file (there is no length field):

    +0   u16 0x0069 (Xbox ADPCM), u16 channels (1), u32 rate,
         u32 bytes per second (rate * 36 / 64), u16 block size (36),
         u16 bits per sample (4)
    +16  u16 4, u16 0x4001, u16 64 (samples per block), u16 0xBFFF

-- the same in all 1,824 sounds on the disc but the rate. A block is the
first sample (s16), the step index, a zero byte, and 63 four-bit steps, low
nibble first: 64 samples (the toolkit's src/hle/xbox_adpcm.c decodes it).

The rate a sound plays at is also in its definition in sound/sounddata
(0x0759 for a 22,050 Hz file, 0x0EAA for 44,100, 0x0556 for 16,000), so a
replacement must be written at the rate of the file it replaces; encode
resamples to the --like file's rate.
"""

import argparse
import struct
import sys
import wave

STEPS = [
    7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 19, 21, 23, 25, 28, 31, 34, 37, 41, 45, 50, 55, 60, 66, 73, 80, 88, 97,
    107, 118, 130, 143, 157, 173, 190, 209, 230, 253, 279, 307, 337, 371, 408, 449, 494, 544, 598, 658, 724,
    796, 876, 963, 1060, 1166, 1282, 1411, 1552, 1707, 1878, 2066, 2272, 2499, 2749, 3024, 3327, 3660, 4026,
    4428, 4871, 5358, 5894, 6484, 7132, 7845, 8630, 9493, 10442, 11487, 12635, 13899, 15289, 16818, 18500,
    20350, 22385, 24623, 27086, 29794, 32767]
INDEX_ADJUST = [-1, -1, -1, -1, 2, 4, 6, 8]
BLOCK, SAMPLES = 36, 64
HEADER_TAIL = struct.pack("<HHHH", 4, 0x4001, 64, 0xBFFF)


def header(rate):
    return struct.pack("<HHIIHH", 0x69, 1, rate, rate * BLOCK // SAMPLES, BLOCK, 4) + HEADER_TAIL + bytes(8)


def parse(data):
    """(rate, ADPCM blocks) of an .xbs."""
    tag, channels, rate = struct.unpack_from("<HHI", data, 0)
    if tag != 0x69 or channels != 1:
        raise ValueError("not a mono Xbox ADPCM .xbs")
    return rate, data[32:]


def _step(code, predictor, index):
    step = STEPS[index]
    delta = step >> 3
    if code & 1:
        delta += step >> 2
    if code & 2:
        delta += step >> 1
    if code & 4:
        delta += step
    predictor = predictor - delta if code & 8 else predictor + delta
    predictor = max(-32768, min(32767, predictor))
    index = max(0, min(88, index + INDEX_ADJUST[code & 7]))
    return predictor, index


def decode(data):
    """An .xbs as (rate, signed 16-bit samples)."""
    rate, blocks = parse(data)
    out = []
    for b in range(0, len(blocks) - BLOCK + 1, BLOCK):
        predictor, index = struct.unpack_from("<hb", blocks, b)
        index = max(0, min(88, index))
        out.append(predictor)
        for n in range(SAMPLES - 1):
            byte = blocks[b + 4 + (n // 8) * 4 + (n % 8) // 2]
            predictor, index = _step((byte >> ((n & 1) * 4)) & 15, predictor, index)
            out.append(predictor)
    return rate, out


def encode(samples, rate):
    """Signed 16-bit samples to an .xbs at `rate` (the caller resamples).
    Each step picks the code whose result is nearest, against the decoder's
    own state, so the error does not build up."""
    samples = list(samples)
    samples += [0] * ((-len(samples)) % SAMPLES)
    blocks = bytearray()
    index = 0
    for b in range(0, len(samples), SAMPLES):
        chunk = samples[b:b + SAMPLES]
        predictor = chunk[0]
        block = bytearray(struct.pack("<hBB", predictor, index, 0)) + bytearray(32)
        for n in range(SAMPLES - 1):
            want = chunk[n + 1]
            best = None
            for code in range(16):
                p, i = _step(code, predictor, index)
                err = abs(p - want)
                if best is None or err < best[0]:
                    best = (err, code, p, i)
            _, code, predictor, index = best
            at = 4 + (n // 8) * 4 + (n % 8) // 2
            block[at] |= code << ((n & 1) * 4)
        blocks += block
    return header(rate) + bytes(blocks)


def resample(samples, src_rate, dst_rate):
    """Linear interpolation; enough for 11-44 kHz effects."""
    if src_rate == dst_rate or not samples:
        return list(samples)
    n = max(1, int(len(samples) * dst_rate / src_rate))
    out = []
    for i in range(n):
        x = i * src_rate / dst_rate
        k = int(x)
        f = x - k
        a = samples[min(k, len(samples) - 1)]
        b = samples[min(k + 1, len(samples) - 1)]
        out.append(int(round(a + (b - a) * f)))
    return out


def read_wav(path):
    with wave.open(path, "rb") as w:
        if w.getsampwidth() != 2:
            raise ValueError(f"{path}: 16-bit WAV expected")
        ch, rate, raw = w.getnchannels(), w.getframerate(), w.readframes(w.getnframes())
    pcm = struct.unpack(f"<{len(raw) // 2}h", raw)
    if ch == 2:
        pcm = [(pcm[i] + pcm[i + 1]) // 2 for i in range(0, len(pcm), 2)]
    return rate, list(pcm)


def write_wav(path, rate, samples):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack(f"<{len(samples)}h", *samples))


def main(argv=None):
    ap = argparse.ArgumentParser(description="TimeSplitters 2 .xbs sounds")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("decode", help=".xbs to WAV")
    d.add_argument("xbs")
    d.add_argument("wav")
    e = sub.add_parser("encode", help="WAV to .xbs")
    e.add_argument("wav")
    e.add_argument("xbs")
    g = e.add_mutually_exclusive_group(required=True)
    g.add_argument("--like", help="the .xbs it replaces: its rate is used")
    g.add_argument("--rate", type=int)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "decode":
            rate, pcm = decode(open(a.xbs, "rb").read())
            write_wav(a.wav, rate, pcm)
        else:
            rate = a.rate or parse(open(a.like, "rb").read())[0]
            src_rate, pcm = read_wav(a.wav)
            open(a.xbs, "wb").write(encode(resample(pcm, src_rate, rate), rate))
    except (OSError, ValueError) as err:
        print(f"xbs: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
