"""tools.xbs: the header, the block layout, and an encode/decode round trip."""
import math
import os
import tempfile
import unittest

from tools import xbs


class XbsTest(unittest.TestCase):
    def test_header(self):
        h = xbs.header(22050)
        self.assertEqual(len(h), 32)
        self.assertEqual(xbs.parse(h + bytes(36))[0], 22050)
        self.assertEqual(h[8:12], (12403).to_bytes(4, "little"))   # what the disc's 22,050 Hz files hold

    def test_round_trip(self):
        pcm = [int(12000 * math.sin(i / 7.0) + 3000 * math.sin(i / 2.3)) for i in range(1000)]
        data = xbs.encode(pcm, 16000)
        self.assertEqual((len(data) - 32) % xbs.BLOCK, 0)
        rate, out = xbs.decode(data)
        self.assertEqual(rate, 16000)
        self.assertEqual(len(out), 1024)                      # whole blocks of 64
        err = sum((a - b) ** 2 for a, b in zip(pcm, out)) / len(pcm)
        sig = sum(a * a for a in pcm) / len(pcm)
        self.assertGreater(10 * math.log10(sig / err), 15)   # 4-bit ADPCM on a busy signal
        self.assertEqual(out[0], pcm[0])                      # a block starts on its sample
        self.assertEqual(out[64], pcm[64])

    def test_resample(self):
        self.assertEqual(len(xbs.resample(list(range(100)), 22050, 44100)), 200)
        self.assertEqual(xbs.resample([1, 2, 3], 16000, 16000), [1, 2, 3])

    def test_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            wav, out = os.path.join(tmp, "in.wav"), os.path.join(tmp, "out.xbs")
            xbs.write_wav(wav, 22050, [0, 1000, -1000] * 100)
            self.assertEqual(xbs.main(["encode", wav, out, "--rate", "44100"]), 0)
            self.assertEqual(xbs.parse(open(out, "rb").read())[0], 44100)
            self.assertEqual(xbs.main(["decode", out, wav]), 0)

    def test_not_xbs(self):
        with self.assertRaises(ValueError):
            xbs.parse(b"RIFF" + bytes(60))


if __name__ == "__main__":
    unittest.main()
