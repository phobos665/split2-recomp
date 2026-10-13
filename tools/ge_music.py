"""
GoldenEye 007 (N64) music, rendered from your own cartridge.

    py -3 -m tools.ge_music ROM --list
    py -3 -m tools.ge_music ROM --track 9 --seconds 270 --out dam.wav
    py -3 -m tools.ge_music ROM --track 9 --ts2 game --level siberia --mods build/Release/mods

GoldenEye's music is not recordings: each track is a sequence (libultra's
compressed MIDI, ALCSeq) played on an instrument bank (the 75-instrument
"B1" bank; the sound effects are the other one). This plays the sequence the
way libultra's sequence player does and mixes it to stereo. Holds no game
data.

Found on the PAL cartridge (6 Oct 2026; the public GoldenEye music renderer
documents the US one): the sequence table is a u16 count and then 8-byte
entries (u32 offset from the table, u16 size, u16 packed size), each a 1172
stream; there are 63 tracks, and track 9 is the Dam (M_DAM in the
decompilation's music list; 35, M_DAMX, its alternate).

What is played, from libultra's sequence player:

  * notes carry their own duration (no note-offs); running status; the
    0xFE escape replays bytes from earlier in the track; meta 0x51 is tempo,
    0x2E a loop start, 0x2D a loop end (count, count left, back offset;
    0xFF = for ever), 0x2F the end. A track's ticks per quarter is at +64.
  * a voice: the channel's program picks the instrument, the key and
    velocity pick its sound (keymap ranges); pitch is
    2 ** (((key - keyBase) * 100 + detune + bend) / 1200) against the
    22047 Hz the console runs at; gain is velocity * envelope * sample
    volume * channel volume (__vsVol); pan adds the channel's, the
    instrument's and the sound's around the centre (__vsPan).
  * envelopes: attack to attackVolume over attackTime, decay to decayVolume
    over decayTime, hold, release to 0 over releaseTime (microseconds).
  * looped samples repeat their loop for as long as the note sounds.

Not played: vibrato and tremolo, and the custom reverb (the channel's
effect send is ignored), so the result is drier than the console.
"""

import argparse
import math
import struct
import sys
import zlib

import numpy as np

from tools.ge_rom import Rom
from tools.ge_sound import decode_vadpcm

OUTPUT_RATE_N64 = 22047


# ------------------------------------------------------------------ the ROM

def find_sequence_table(d):
    for t in range(0x300000, len(d) - 16, 4):
        cnt = struct.unpack_from(">H", d, t)[0]
        if not 30 <= cnt <= 100:
            continue
        off, ulen, clen = struct.unpack_from(">IHH", d, t + 4)
        if not 0 < off < 0x40000 or clen < 16 or d[t + off:t + off + 2] != b"\x11\x72":
            continue
        try:
            raw = zlib.decompressobj(-15).decompress(d[t + off + 2:t + off + clen])
        except zlib.error:
            continue
        if len(raw) == ulen:
            return t
    raise ValueError("no music sequence table found")


def sequences(d):
    t = find_sequence_table(d)
    out = []
    for i in range(struct.unpack_from(">H", d, t)[0]):
        off, ulen, clen = struct.unpack_from(">IHH", d, t + 4 + 8 * i)
        out.append(zlib.decompressobj(-15).decompress(d[t + off + 2:t + off + clen]))
    return out


class InstrumentBank:
    """The music bank: instruments of sounds, each with its envelope, keymap
    and wavetable (decoded once, on first use)."""

    def __init__(self, d):
        self.d = d
        best = None
        i = 0
        while True:
            i = d.find(b"B1\x00\x01", i)
            if i < 0:
                break
            bank = struct.unpack_from(">I", d, i + 4)[0]
            if bank < 0x100000:
                n = struct.unpack_from(">h", d, i + bank)[0]
                if best is None or n > best[1]:
                    best = (i, n)
            i += 4
        if best is None:
            raise ValueError("no instrument bank found")
        self.ctl = ctl = best[0]
        u32 = lambda o: struct.unpack_from(">I", d, ctl + o)[0]
        bank = u32(4)
        ninst = struct.unpack_from(">h", d, ctl + bank)[0]
        self.rate = u32(bank + 4)
        inst_offs = [u32(bank + 12 + 4 * k) for k in range(ninst)]
        self.instruments = []
        ends = [bank + 12 + 4 * ninst]
        for io in inst_offs:
            if not io:
                self.instruments.append(None)
                continue
            vol, pan, prio, flags = d[ctl + io:ctl + io + 4]
            bend, nsnd = struct.unpack_from(">hh", d, ctl + io + 12)
            sounds = []
            for k in range(nsnd):
                so = u32(io + 16 + 4 * k)
                env, km, wt = u32(so), u32(so + 4), u32(so + 8)
                span, svol = d[ctl + so + 12], d[ctl + so + 13]
                at, dt, rt = struct.unpack_from(">iii", d, ctl + env)
                av, dv = d[ctl + env + 12], d[ctl + env + 13]
                vmin, vmax, kmin, kmax, kbase, det = struct.unpack_from(">BBBBBb", d, ctl + km)
                base, length, typ = u32(wt), u32(wt + 4), d[ctl + wt + 8]
                loop_off, book_off = u32(wt + 12), u32(wt + 16)
                loop = None
                if loop_off:
                    ls, le, lc = struct.unpack_from(">IIi", d, ctl + loop_off)
                    if le > ls:
                        loop = (ls, le, lc)
                book = None
                if typ == 0 and book_off:
                    order, npred = u32(book_off), u32(book_off + 4)
                    book = (list(struct.unpack_from(f">{order * npred * 8}h", d, ctl + book_off + 8)), order, npred)
                sounds.append({"env": (at, dt, rt, av, dv), "keys": (kmin, kmax), "vels": (vmin, vmax),
                               "key_base": kbase, "detune": det, "pan": span, "vol": svol,
                               "wave": (base, length, typ, book, loop)})
                ends.append(max(so + 16, wt + 20, env + 16, km + 8))
            self.instruments.append({"vol": vol, "pan": pan, "bend": bend, "sounds": sounds})
        # The sample table follows the control file: the first 16-byte
        # boundary at which every ADPCM wavetable's frame headers are valid.
        start = (ctl + max(ends) + 15) & ~15
        waves = [s["wave"] for ins in self.instruments if ins for s in ins["sounds"] if s["wave"][2] == 0]
        for tbl in range(start, start + 0x40000, 16):
            if all(d[tbl + b + f] & 15 < bk[2] for b, ln, _, bk, _ in waves[:40]
                   for f in range(0, min(ln, 90) - 8, 9)):
                self.tbl = tbl
                break
        else:
            raise ValueError("no sample table after the instrument bank")
        self._pcm = {}

    def pcm(self, wave):
        base, length, typ, book, loop = wave
        if base not in self._pcm:
            raw = self.d[self.tbl + base:self.tbl + base + length]
            if typ == 0:
                pcm = decode_vadpcm(raw, *book)
            else:
                pcm = list(struct.unpack(f">{len(raw) // 2}h", raw[:len(raw) & ~1]))
            self._pcm[base] = np.array(pcm, dtype=np.float32) / 32768.0
        return self._pcm[base]

    def sound_for(self, program, key, vel):
        ins = self.instruments[program] if program < len(self.instruments) else None
        if not ins:
            return None, None
        for s in ins["sounds"]:
            if s["keys"][0] <= key <= s["keys"][1] and s["vels"][0] <= vel <= s["vels"][1]:
                return ins, s
        return ins, (ins["sounds"][0] if ins["sounds"] else None)


# ------------------------------------------------------------------ sequences

class _Track:
    """libultra cseq: 0xFE hi lo n replays n bytes from (hi lo) + 4 back."""

    def __init__(self, data, pos):
        self.d = bytearray(data)
        self.pos = pos
        self.bpos = self.blen = 0

    def byte(self):
        if self.blen:
            b = self.d[self.bpos]
            self.bpos += 1
            self.blen -= 1
            return b
        b = self.d[self.pos]
        self.pos += 1
        if b == 0xFE:
            hi = self.d[self.pos]
            self.pos += 1
            if hi != 0xFE:
                lo, n = self.d[self.pos], self.d[self.pos + 1]
                self.pos += 2
                self.bpos = self.pos - (((hi << 8) | lo) + 4)
                self.blen = n
                b = self.d[self.bpos]
                self.bpos += 1
                self.blen -= 1
        return b

    def varlen(self):
        v = 0
        while True:
            b = self.byte()
            v = (v << 7) | (b & 0x7F)
            if not b & 0x80:
                return v


def read_track(data, start, max_ticks):
    """Events as (tick, kind, a, b, c): ('on', ch, key, vel, dur), ('cc', ch,
    ctl, val), ('prog', ch, p), ('bend', ch, value), ('tempo', usec/quarter).
    Loops for ever are followed until max_ticks."""
    r = _Track(data, start)
    t, last, ev = 0, 0, []
    while t <= max_ticks:
        t += r.varlen()
        st = r.byte()
        if st == 0xFF:
            ty = r.byte()
            if ty == 0x51:
                ev.append((t, "tempo", (r.byte() << 16) | (r.byte() << 8) | r.byte()))
            elif ty == 0x2F:
                break
            elif ty == 0x2E:
                r.byte()
                r.byte()
            elif ty == 0x2D:
                p = r.pos
                count, left = r.d[p], r.d[p + 1]
                back = struct.unpack_from(">I", r.d, p + 2)[0]
                if left == 0xFF:
                    r.pos = p + 6 - back            # for ever: until max_ticks
                elif left == 0:
                    r.d[p + 1] = count
                    r.pos = p + 6
                else:
                    r.d[p + 1] = left - 1
                    r.pos = p + 6 - back
            else:
                raise ValueError(f"unknown meta event {ty:#x}")
            last = 0
            continue
        if st & 0x80:
            a = r.byte()
            last = st
        else:
            a, st = st, last
        kind, ch = st & 0xF0, st & 0x0F
        if kind in (0xC0, 0xD0):
            if kind == 0xC0:
                ev.append((t, "prog", ch, a))
            continue
        b = r.byte()
        if kind == 0x90:
            dur = r.varlen()
            if b:
                ev.append((t, "on", ch, a, b, dur))
        elif kind == 0xB0:
            ev.append((t, "cc", ch, a, b))
        elif kind == 0xE0:
            ev.append((t, "bend", ch, (b << 7) | a))
    return ev


def events(seq, seconds):
    """All tracks' events, with each tick turned into seconds by the tempo
    map, until `seconds` have been covered."""
    offs = struct.unpack_from(">16I", seq, 0)
    division = struct.unpack_from(">I", seq, 64)[0]
    # Ticks enough for `seconds` at the slowest plausible tempo.
    max_ticks = int(seconds * division * 4) + division * 64
    ev = []
    for o in offs:
        if o:
            ev += read_track(seq, o, max_ticks)
    ev.sort(key=lambda e: (e[0], 0 if e[1] in ("tempo", "prog", "cc", "bend") else 1))
    tempo, t_tick, t_sec = 500000, 0, 0.0
    timed = []
    for e in ev:
        t_sec += (e[0] - t_tick) * tempo / 1e6 / division
        t_tick = e[0]
        if e[1] == "tempo":
            tempo = e[2]
        if e[1] == "on":
            # Duration in ticks at the tempo now (tempo changes inside a
            # note are rare enough to ignore).
            timed.append((t_sec, "on", e[2], e[3], e[4], e[5] * tempo / 1e6 / division))
        else:
            timed.append((t_sec,) + e[1:])
        if t_sec > seconds:
            break
    return timed


# ------------------------------------------------------------------ the mix

def _envelope(n, rate, env, held):
    at, dt, rt, av, dv = env
    att = max(1, int(max(at, 0) * rate / 1e6))
    dec = int(dt * rate / 1e6) if dt > 0 else 0
    rel = max(1, int(max(rt, 0) * rate / 1e6))
    g = np.empty(n, dtype=np.float32)
    k = min(att, n)
    g[:k] = np.linspace(0, av / 127, att, endpoint=False, dtype=np.float32)[:k]
    pos = k
    hold_level = av / 127
    if dt != -1 and pos < held:
        k = min(dec, held - pos) if dec else 0
        if k:
            g[pos:pos + k] = np.linspace(av / 127, dv / 127, dec, endpoint=False, dtype=np.float32)[:k]
        pos += k
        hold_level = dv / 127 if pos >= att + dec else g[pos - 1]
    if pos < held:
        g[pos:held] = hold_level
        pos = held
    level = g[pos - 1] if pos else 0
    k = min(rel, n - pos)
    if k > 0:
        g[pos:pos + k] = np.linspace(level, 0, rel, endpoint=False, dtype=np.float32)[:k]
        pos += k
    g[pos:] = 0
    return g


def render(rom_data, track, seconds, rate=44100, log=print):
    """Track `track` as a float32 stereo array of shape (n, 2)."""
    bank = InstrumentBank(rom_data)
    seq = sequences(rom_data)[track]
    ev = events(seq, seconds)
    n_out = int(seconds * rate)
    mix = np.zeros((n_out + rate * 4, 2), dtype=np.float32)
    chans = [{"prog": 0, "vol": 127, "pan": 64, "bend": 8192, "sustain": False} for _ in range(16)]
    notes = 0
    for e in ev:
        t = e[0]
        if t >= seconds:
            break
        kind = e[1]
        if kind == "tempo":
            continue
        ch = e[2]
        c = chans[ch]
        if kind == "prog":
            c["prog"] = e[3]
        elif kind == "cc":
            if e[3] == 7:
                c["vol"] = e[4]
            elif e[3] == 10:
                c["pan"] = e[4]
        elif kind == "bend":
            c["bend"] = e[3]
        elif kind == "on":
            key, vel, dur = e[3], e[4], e[5]
            ins, snd = bank.sound_for(c["prog"], key, vel)
            if not snd:
                continue
            src = bank.pcm(snd["wave"])
            if not len(src):
                continue
            cents = (key - snd["key_base"]) * 100 + snd["detune"] + (c["bend"] - 8192) / 8192 * ins["bend"]
            step = 2 ** (cents / 1200) * OUTPUT_RATE_N64 / rate
            held = int(dur * rate)
            rel = int(max(snd["env"][2], 0) * rate / 1e6)
            n = held + rel
            pos = np.arange(n, dtype=np.float64) * step
            loop = snd["wave"][4]
            if loop:
                ls, le = loop[0], min(loop[1], len(src))
                if le > ls:
                    over = pos >= le
                    pos[over] = ls + np.mod(pos[over] - ls, le - ls)
            keep = pos < len(src) - 1
            if not keep.all():
                n = int(np.argmin(keep)) if not keep[0] else 0
                pos = pos[:n]
            if not n:
                continue
            i = pos.astype(np.int64)
            f = (pos - i).astype(np.float32)
            wav = src[i] * (1 - f) + src[i + 1] * f
            env = _envelope(n, rate, snd["env"], min(held, n))
            gain = (vel / 127) * (snd["vol"] / 127) * (c["vol"] / 127)
            pan = min(127, max(0, c["pan"] + snd["pan"] + ins["pan"] - 128)) / 127
            start = int(t * rate)
            out = (wav * env * gain)[:max(0, len(mix) - start)]
            n = len(out)
            mix[start:start + n, 0] += out * math.cos(pan * math.pi / 2)
            mix[start:start + n, 1] += out * math.sin(pan * math.pi / 2)
            notes += 1
    log(f"track {track}: {notes} notes in {seconds:.0f} s, {sum(1 for i in bank.instruments if i)} instruments")
    return mix[:n_out]


def write_wav(path, stereo, rate, peak=0.9):
    m = np.abs(stereo).max() or 1
    pcm = np.clip(stereo / m * peak * 32767, -32768, 32767).astype("<i2")
    with open(path, "wb") as f:
        data = pcm.tobytes()
        f.write(b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVEfmt " +
                struct.pack("<IHHIIHH", 16, 1, 2, rate, rate * 4, 4, 16) + b"data" + struct.pack("<I", len(data)) + data)


# TimeSplitters 2 plays each level's music from loose files, music/<name>.wav
# (stereo Xbox ADPCM, 44.1 kHz), which the mods folder replaces by path.
# Seen opened in the Siberia run, 6 Oct 2026.
TS2_LEVEL_MUSIC = {
    "siberia": ["ts2_siberia02_44_fx.wav", "ts2_siberia02b_44_fx.wav"],
}


def _rms_sample(data, pieces=8, seconds=4):
    """The loudness of a TS2 music file: `pieces` stretches spread through
    it. One stretch in the middle is not enough -- Siberia's first track is
    at 1,567 in one place and 6,736 in another, 4,943 on average."""
    from tools import xbs
    o = data.find(b"data")
    size = struct.unpack_from("<I", data, o + 4)[0]
    block = 2 * xbs.BLOCK
    per_second = 44100 // xbs.SAMPLES * block
    total, count = 0.0, 0
    for k in range(pieces):
        at = o + 8 + (size * k // pieces) // block * block
        piece = data[:o + 8] + data[at:at + seconds * per_second]
        piece = piece[:o + 4] + struct.pack("<I", len(piece) - o - 8) + piece[o + 8:]
        _, left, right = xbs.decode_stereo_wav(piece)
        v = np.array(left + right, dtype=np.float64)
        total += (v * v).sum()
        count += len(v)
    return math.sqrt(total / max(count, 1))


def build_ts2_music(rom_data, track, game_dir, mods_dir, level, log=print):
    """Replace a level's music with a GoldenEye track: rendered to each
    file's own length, matched to its loudness, encoded as the disc's are."""
    import os
    from tools import xbs
    out = os.path.join(mods_dir, "music")
    os.makedirs(out, exist_ok=True)
    for name in TS2_LEVEL_MUSIC[level]:
        original = open(os.path.join(game_dir, "music", name), "rb").read()
        o = original.find(b"data")
        seconds = struct.unpack_from("<I", original, o + 4)[0] / (2 * xbs.BLOCK) * xbs.SAMPLES / 44100
        mix = render(rom_data, track, seconds, 44100, log)
        want = _rms_sample(original)
        have = math.sqrt(float((mix.astype(np.float64) ** 2).mean())) * 32767 or 1
        scale = min(want / have, 0.98 * 32767 / (np.abs(mix).max() * 32767 or 1)) * 32767
        pcm = np.clip(mix * scale, -32768, 32767).astype(np.int16)
        xbs.write_stereo_wav(os.path.join(out, name), pcm[:, 0], pcm[:, 1], 44100, original)
        log(f"wrote {os.path.join(out, name)}: {seconds:.0f} s, loudness matched to the original "
            f"(rms {want:.0f})")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="GoldenEye 007 music, rendered from your own cartridge")
    ap.add_argument("rom")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--track", type=int, default=9, help="9 is the Dam")
    ap.add_argument("--seconds", type=float, default=180)
    ap.add_argument("--out", default="track.wav")
    ap.add_argument("--ts2", metavar="GAME_DIR", help="instead: replace a TS2 level's music in the mods folder")
    ap.add_argument("--level", default="siberia", choices=sorted(TS2_LEVEL_MUSIC))
    ap.add_argument("--mods", default="mods")
    a = ap.parse_args(argv)
    d = Rom.open(a.rom).data
    if a.ts2:
        return build_ts2_music(d, a.track, a.ts2, a.mods, a.level)
    if a.list:
        for i, s in enumerate(sequences(d)):
            offs = struct.unpack_from(">16I", s, 0)
            print(f"{i:2}: {sum(1 for o in offs if o):2} tracks, {len(s):6} bytes")
        return 0
    write_wav(a.out, render(d, a.track, a.seconds), 44100)
    print("wrote", a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
