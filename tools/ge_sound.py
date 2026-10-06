"""
GoldenEye 007 (N64) sound effects: the bank, VADPCM decoding, WAV output.
Used by tools.ge_guns; holds no game data.

The effects are one standard libaudio bank ("B1" control file, then its
sample table): one instrument of 261 sounds, all VADPCM. The game plays a
sound by number (sndPlaySfx), and a gun's weapon stats hold the number of
its firing sound; on the PAL cartridge that number is bank entry number - 1
(Bank.sound), heard 6 Oct 2026.

Two details from the game's sound player (snd.c in the decompilation):

  * pitch: a sound plays at the bank's rate (22050 Hz) times
    2 ** ((keyBase * 100 + detune - 6000) / 1200), the detune left out when
    bit 0x20 of keyMax is set. That rate is what the WAV is written at.
  * chains: when keyMap.velocityMin + (keyMin & 0xC0) * 4 is not zero it
    names the next sound, started velocityMax * 33 ms later -- a gunshot can
    be a shot and its tail. chain() follows them.
"""

import struct
import wave


class Sound:
    def __init__(self, num, rate, data, book, order, npred, next_sound, delay_ms, loop):
        self.num, self.rate, self.data = num, rate, data
        self.book, self.order, self.npred = book, order, npred
        self.next_sound, self.delay_ms, self.loop = next_sound, delay_ms, loop

    def pcm(self):
        """The sound as signed 16-bit samples."""
        return decode_vadpcm(self.data, self.book, self.order, self.npred)


def _codebook(book, order, npred):
    """The decoder's coefficient table: for each predictor, 8 rows of
    order + 8 weights (libaudio's own expansion of the book)."""
    tables = []
    for p in range(npred):
        t = [[0] * (order + 8) for _ in range(8)]
        for j in range(order):
            for k in range(8):
                t[k][j] = book[(p * order + j) * 8 + k]
        for k in range(1, 8):
            t[k][order] = t[k - 1][order - 1]
        t[0][order] = 2048
        for k in range(1, 8):
            for j in range(k):
                t[j][k + order] = 0
            for j in range(k, 8):
                t[j][k + order] = t[j - k][order]
        tables.append(t)
    return tables


def decode_vadpcm(data, book, order, npred):
    tables = _codebook(book, order, npred)
    out = []
    state = [0] * 16
    for f in range(0, len(data) - 8, 9):
        head = data[f]
        scale, table = 1 << (head >> 4), tables[(head & 15) % npred]
        ix = []
        for b in data[f + 1:f + 9]:
            for n in (b >> 4, b & 15):
                ix.append((n - 16 if n > 7 else n) * scale)
        frame = [0] * 16
        for j in range(2):
            vec = (state[16 - order:] if j == 0 else frame[8 - order:8]) + [0] * 8
            for i in range(8):
                vec[order + i] = ix[j * 8 + i]
                row = table[i]
                acc = sum(row[k] * vec[k] for k in range(order + i))
                v = (acc >> 11) + ix[j * 8 + i]
                frame[j * 8 + i] = max(-32768, min(32767, v))
        state = frame
        out += frame
    return out


class Bank:
    def __init__(self, rom, ctl):
        d = rom.data
        self.ctl = ctl
        u32 = lambda o: struct.unpack_from(">I", d, ctl + o)[0]
        s16 = lambda o: struct.unpack_from(">h", d, ctl + o)[0]
        bank = u32(4)
        ninst, self.rate = s16(bank), u32(bank + 4)
        inst = u32(bank + 12)
        raw = []
        for num in range(s16(inst + 14)):
            so = u32(inst + 16 + 4 * num)
            wt = u32(so + 8)
            raw.append((u32(wt), u32(wt + 4), u32(u32(wt + 16) + 4)))
        # The sample table follows the control file, after some zero
        # padding (16 bytes in the PAL ROM). Take the first 16-byte boundary
        # at which every sound's frame headers name one of its predictors.
        start = (ctl + bank + 12 + 4 * ninst + 15) & ~15
        for tbl in range(start, start + 0x100, 16):
            if all((d[tbl + base + f] & 15) < npred for base, length, npred in raw
                   for f in range(0, min(length, 270) - 8, 9)):
                self.tbl = tbl
                break
        else:
            raise ValueError("no sample table found after the sound bank")
        self.sounds = []
        for num in range(s16(inst + 14)):
            so = u32(inst + 16 + 4 * num)
            km, wt = u32(so + 4), u32(so + 8)
            vmin, vmax, kmin, kmax, kbase, detune = struct.unpack_from(">BBBBBb", d, ctl + km)
            base, length, typ = u32(wt), u32(wt + 4), d[ctl + wt + 8]
            if typ != 0:
                raise ValueError(f"sound {num}: not VADPCM")
            loop_off, book_off = u32(wt + 12), u32(wt + 16)
            order, npred = u32(book_off), u32(book_off + 4)
            book = list(struct.unpack_from(f">{order * npred * 8}h", d, ctl + book_off + 8))
            cents = kbase * 100 + (0 if kmax & 0x20 else detune) - 6000
            rate = round(self.rate * 2 ** (cents / 1200))
            nxt = vmin + (kmin & 0xC0) * 4
            self.sounds.append(Sound(num, rate, d[self.tbl + base:self.tbl + base + length],
                                     book, order, npred, nxt, vmax * 33, bool(loop_off)))

    @classmethod
    def find(cls, rom):
        """The effects bank: the one whose single instrument has the most sounds."""
        d, i, best = rom.data, 0, None
        while True:
            i = d.find(b"B1\x00\x01", i)
            if i < 0:
                break
            bank = struct.unpack_from(">I", d, i + 4)[0]
            if bank < 0x100000 and struct.unpack_from(">h", d, i + bank)[0] == 1:
                inst = struct.unpack_from(">I", d, i + bank + 12)[0]
                n = struct.unpack_from(">h", d, i + inst + 14)[0]
                if best is None or n > best[1]:
                    best = (i, n)
            i += 4
        if best is None:
            raise ValueError("no sound bank found")
        return cls(rom, best[0])

    def sound(self, num):
        """The sound the game plays as `num` (its weapon stats' and its own
        chains' numbering): bank entry num - 1. Found by ear on the PAL
        cartridge, 6 Oct 2026: the silenced PP7's stats say 46, and its shot is
        entry 45; entry 46 is a punch."""
        return self.sounds[num - 1]

    def chain(self, num):
        """The sound the game plays as `num` and the ones it starts, as
        [(sound, start in ms)]."""
        out, at, seen = [], 0, set()
        while num and num not in seen and 0 < num <= len(self.sounds):
            seen.add(num)
            s = self.sound(num)
            out.append((s, at))
            at += s.delay_ms
            num = s.next_sound
        return out


def write_wav(path, rate, samples):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack(f"<{len(samples)}h", *samples))


def mix_chain(chain, rate):
    """A chain of sounds mixed into one track at `rate` (each resampled,
    nearest sample: these are 11-22 kHz effects)."""
    tracks = []
    for s, at in chain:
        pcm = s.pcm()
        n = int(len(pcm) * rate / s.rate)
        tracks.append((int(at * rate / 1000), [pcm[min(int(i * s.rate / rate), len(pcm) - 1)] for i in range(n)]))
    total = max((a + len(t) for a, t in tracks), default=0)
    mix = [0] * total
    for a, t in tracks:
        for i, v in enumerate(t):
            mix[a + i] += v
    return [max(-32768, min(32767, v)) for v in mix]
