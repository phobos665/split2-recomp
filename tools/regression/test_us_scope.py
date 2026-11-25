"""Compare a tagged US sniper capture with the original, centred 4:3 optic.

Pass the original centred frame first, then one or more comparison frames.
--aspect is the display shape of the comparison frames. --aim also checks
the recovered reticle position against a known guest aim coordinate.
"""

import argparse
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scope_capture_probe import read_capture

SHADE = (0xC2F37, 0xC2F62, 0xC2F88, 0xC2FAF, 0xC2FD6, 0xC2FFD, 0xC3025, 0xC3050)
CORNERS = (0xC3096, 0xC30BF, 0xC30E8, 0xC3182)
ALPHA = 0xC2F03
TINT = 0xC31F3
VERTICAL, HORIZONTAL = 0xC34D2, 0xC34E7
CROSS = (VERTICAL, HORIZONTAL, 0xC3503, 0xC3520, 0xC353B, 0xC354E)
MASK = [*SHADE, *CORNERS, ALPHA, *SHADE, *CORNERS]
EPSILON = 0.001


def optic(path):
    _, w, h, draws = read_capture(path)
    try:
        start = next(i for i, draw in enumerate(draws) if draw.tag == SHADE[0])
    except StopIteration:
        raise ValueError(f"{path}: expected a modern sniper frame with RECOMP_TS2_UI_SITES=1") from None
    mask = draws[start:start + len(MASK)]
    if [d.tag for d in mask] != MASK or draws[start + len(MASK)].tag != TINT:
        raise ValueError(f"{path}: unrecognised mask pass order")
    cross = [d for d in draws[start + len(MASK) + 1:] if d.tag in CROSS]
    return w, h, mask, cross


def compare(reference, path, aspect, aim):
    w, h, mask, cross = optic(path)
    rw, rh, ref_mask, ref_cross = reference
    assert (rw, rh) == (w, h)
    scale = w * aspect[1] / (h * aspect[0])
    ref_lines = {d.tag: d for d in ref_cross}
    lines = {d.tag: d for d in cross}
    # Measure aim independently of the mask, from the two reticle lines.
    cx, cy = w / 2, h / 2
    dx = (lines[VERTICAL].vertices[0][0] - cx) / scale + cx - ref_lines[VERTICAL].vertices[0][0]
    dy = lines[HORIZONTAL].vertices[0][1] - ref_lines[HORIZONTAL].vertices[0][1]
    if aim and (abs(cx + dx - aim[0]) > EPSILON or abs(cy + dy - aim[1]) > EPSILON):
        raise ValueError(f"{path}: guest aim {(cx + dx, cy + dy)}, expected {aim}")

    def expected(draw):
        # A centred native recording contains the whole aperture and all four
        # crosshair tips. Translate that artwork first. Only the outer shade
        # vertices stay pinned to the viewport. The guest clips solid rects.
        solid = draw.tag == ALPHA or draw.tag in CROSS
        result = []
        for x, y, *other in draw.vertices:
            if draw.tag not in SHADE or x not in (0, w - 1):
                x = cx + (x + dx - cx) * scale
            if draw.tag not in SHADE or y not in (0, h - 1):
                y += dy
            if solid:
                x, y = min(w, max(0, x)), min(h, max(0, y))
            result.append((x, y, *other))
        if solid and (min(v[0] for v in result) == max(v[0] for v in result)
                      or min(v[1] for v in result) == max(v[1] for v in result)):
            return []
        return result

    def check(original, current):
        vertices = expected(original)
        if current is None:
            if vertices:
                raise ValueError(f"{path}: missing visible draw {original.tag:08X}")
            return
        if (scale != 1 and current.placement != 1) or len(current.vertices) != len(vertices):
            raise ValueError(f"{path}: {original.tag:08X} placement {current.placement}, "
                             f"{len(current.vertices)} vertices, expected {len(vertices)}")
        for i, (want, got) in enumerate(zip(vertices, current.vertices)):
            # Coordinates and UVs are floats. The packed colour occupies word
            # three even though the general capture probe decodes it as float.
            if want[3] != got[3] or len(want) != len(got) or any(
                not math.isclose(a, b, abs_tol=EPSILON, rel_tol=0)
                for j, (a, b) in enumerate(zip(want, got)) if j != 3
            ):
                raise ValueError(f"{path}: site {original.tag:08X}, vertex {i}: {got}, expected {want}")
    for original, current in zip(ref_mask, mask):
        check(original, current)
    for site in CROSS:
        check(ref_lines[site], lines.get(site))
    print(f"{path.name}: both mask passes, corner UVs, alpha clear and reticle match "
          f"at guest aim ({cx + dx:g}, {cy + dy:g})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference", type=Path)
    parser.add_argument("frames", type=Path, nargs="+")
    parser.add_argument("--aspect", default="16:9", help="display aspect of the comparison frames")
    parser.add_argument("--aim", nargs=2, type=float, metavar=("X", "Y"))
    args = parser.parse_args()
    aspect = tuple(map(int, args.aspect.split(":")))
    if len(aspect) != 2 or min(aspect) <= 0:
        parser.error("expected a positive W:H aspect")
    reference = optic(args.reference)
    for frame in args.frames:
        compare(reference, frame, aspect, args.aim)
