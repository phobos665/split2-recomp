"""
tools.ts2_weapons against a synthetic XBE: one section covering the weapon
tables and the string table, filled the way the PAL disc lays them out.
"""
import json
import os
import struct
import tempfile
import unittest

from tools import ts2_weapons as tw

BASE, SEC_VA, SEC_SIZE, SEC_RAW = 0x10000, 0x2C0000, 0x80000, 0x1000


def make_xbe():
    data = bytearray(SEC_RAW + SEC_SIZE)
    data[:4] = b"XBEH"
    struct.pack_into("<I", data, 0x104, BASE)
    struct.pack_into("<II", data, 0x11C, 1, BASE + 0x200)          # 1 section, headers at 0x200
    struct.pack_into("<6I", data, 0x200, 7, SEC_VA, SEC_SIZE, SEC_RAW, SEC_SIZE, BASE + 0x300)
    data[0x300:0x306] = b".data\0"

    def put(va, fmt, *v):
        struct.pack_into(fmt, data, SEC_RAW + va - SEC_VA, *v)

    # A string, its string-table entry (number 994), and the weapon type
    # record that names it: type 11, string 994, key word 994.
    put(0x2F0000, "13s", b"Sniper Rifle\0")
    put(tw.STRINGS_EN + 4 * 994, "<I", 0x2F0000)
    put(tw.TYPE_TABLE + 11 * tw.TYPE_SIZE, "<ii", 994, 994)
    # Definition 6 keys on 993 (the type's second word minus one).
    r = tw.DEF_TABLE + 6 * tw.DEF_SIZE
    put(r, "<i", 993)
    put(r + 0x10, "<ii", 4, 5)
    put(r + 0x7C, "<f", 30.0)
    # The other definitions key on -1: unnamed.
    for w in range(tw.DEF_COUNT):
        if w != 6:
            put(tw.DEF_TABLE + w * tw.DEF_SIZE, "<i", -1)
    return bytes(data)


class WeaponsTest(unittest.TestCase):
    def test_names_and_fields(self):
        weapons = tw.read_weapons(tw.Xbe(make_xbe()))
        self.assertEqual(len(weapons), tw.DEF_COUNT)
        w = weapons[6]
        self.assertEqual(w["name"], "Sniper Rifle")
        self.assertEqual(w["clip"]["value"], 5)
        self.assertEqual(w["clip"]["address"], "0x002C461C")
        self.assertEqual(w["projectile_speed"]["value"], 30.0)
        self.assertIsNone(weapons[0]["name"])

    def test_cli_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            xbe = os.path.join(tmp, "default.xbe")
            open(xbe, "wb").write(make_xbe())
            out = os.path.join(tmp, "w.json")
            self.assertEqual(tw.main([xbe, "--json", out]), 0)
            self.assertEqual(json.load(open(out))[6]["ammo_type"]["value"], 4)

    def test_not_an_xbe(self):
        with self.assertRaises(ValueError):
            tw.Xbe(b"nope" + bytes(0x200))


if __name__ == "__main__":
    unittest.main()
