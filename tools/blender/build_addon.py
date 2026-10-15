"""Build the Blender add-on zip: tools/blender/ts2_character with a copy of
the converter (tools/ts2gltf.py, ts2xbr.py, ts2xbt.py) in its vendor/ folder,
so the add-on is one file to install.

  python3 -I tools/blender/build_addon.py              # -> build/ts2_character-<version>.zip
  python3 -I tools/blender/build_addon.py out.zip

Install (Blender 4.2 or later): Edit > Preferences > Get Extensions, the
menu at the top right, Install from Disk, pick the zip. Or from a shell:

  blender --command extension install-file -r user_default -e build/ts2_character-1.0.0.zip

Python 3, standard library only.
"""

import os
import re
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
ADDON = os.path.join(HERE, "ts2_character")
VENDORED = ("ts2gltf.py", "ts2xbr.py", "ts2xbt.py")


def version():
    with open(os.path.join(ADDON, "blender_manifest.toml")) as f:
        m = re.search(r'^version\s*=\s*"([^"]+)"', f.read(), re.M)
    return m.group(1) if m else "0"


def build(out):
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        # an extension zip holds the add-on's files at its top level
        for d, dirs, files in os.walk(ADDON):
            dirs[:] = [x for x in dirs if x not in ("__pycache__", "vendor")]
            for f in sorted(files):
                if f.endswith(".pyc") or f.startswith("."):
                    continue
                full = os.path.join(d, f)
                z.write(full, os.path.relpath(full, ADDON))
        for f in VENDORED:
            z.write(os.path.join(TOOLS, f), "vendor/" + f)
    return out


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(TOOLS), "build",
                                                             "ts2_character-%s.zip" % version())
    build(out)
    with zipfile.ZipFile(out) as z:
        print("%s: %s" % (out, ", ".join(z.namelist())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
