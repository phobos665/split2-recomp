#!/usr/bin/env python3
"""Print draw metadata and vertices from a d3d8_replay frame capture.

Captures are game content and are intentionally ignored by Git. This probe is
useful when a scope draw needs to be matched to a tagged 2D call site without
loading a full image into a model context.
"""

from __future__ import annotations

import argparse
import json
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


MAGIC = b"XBRD3D8"
DRAW_UP = 9
DRAW_INDEXED_UP = 10
TWOD_PLACEMENT = 28


@dataclass
class Draw:
    index: int
    kind: str
    tag: int
    placement: int
    primitive: int
    primitive_count: int
    stride: int
    vertices: list[tuple[float, ...]]


def parse_draws(spec: str) -> set[int]:
    draws: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo, hi = (int(value, 0) for value in part.split("-", 1))
            draws.update(range(lo, hi + 1))
        else:
            draws.add(int(part, 0))
    return draws


def floats(payload: bytes, offset: int, stride: int, count: int) -> list[tuple[float, ...]]:
    words = stride // 4
    rows = []
    for index in range(count):
        rows.append(struct.unpack_from(f"<{words}f", payload, offset + index * stride))
    return rows


def read_capture(path: Path) -> tuple[int, int, int, list[Draw]]:
    data = path.read_bytes()
    if len(data) < 32 or data[:8] != MAGIC + b"\0":
        raise ValueError(f"{path} is not a D3D8 capture")

    version, header_bytes, frame, width, height = struct.unpack_from("<IIIII", data, 8)
    pos = header_bytes
    draw_index = 0
    tag = 0
    placement = 0
    draws: list[Draw] = []

    while pos + 8 <= len(data):
        chunk_type, chunk_bytes = struct.unpack_from("<II", data, pos)
        if chunk_type == 0:
            break
        payload = data[pos + 8 : pos + 8 + chunk_bytes]

        if chunk_type == TWOD_PLACEMENT:
            placement, tag = struct.unpack_from("<II", payload, 0)
        elif chunk_type in (DRAW_UP, DRAW_INDEXED_UP):
            if chunk_type == DRAW_UP:
                primitive, primitive_count, stride, vertex_bytes = struct.unpack_from(
                    "<IIII", payload, 0
                )
                vertex_offset = 16
                kind = "up"
            else:
                (
                    primitive,
                    _min_index,
                    _vertex_count,
                    primitive_count,
                    _index_format,
                    index_bytes,
                    stride,
                    vertex_bytes,
                ) = struct.unpack_from("<IIIIIIII", payload, 0)
                vertex_offset = 32 + index_bytes
                kind = "indexed"

            if stride:
                vertices = floats(payload, vertex_offset, stride, vertex_bytes // stride)
            else:
                vertices = []
            draws.append(
                Draw(
                    index=draw_index,
                    kind=kind,
                    tag=tag,
                    placement=placement,
                    primitive=primitive,
                    primitive_count=primitive_count,
                    stride=stride,
                    vertices=vertices,
                )
            )
            draw_index += 1

        pos += 8 + chunk_bytes + (-chunk_bytes & 3)

    return frame, width, height, draws


def selected(
    draws: Iterable[Draw], draw_filter: set[int], site_filter: set[int]
) -> Iterable[Draw]:
    for draw in draws:
        if draw_filter and draw.index not in draw_filter:
            continue
        if site_filter and draw.tag not in site_filter:
            continue
        yield draw


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("--draws", default="", help="0-based indexes/ranges, e.g. 12-17,25")
    parser.add_argument("--sites", default="", help="comma-separated hexadecimal site tags")
    parser.add_argument(
        "--vertices",
        type=int,
        default=2,
        help="vertices to print per selected draw (default 2; use -1 for all)",
    )
    parser.add_argument("--json", action="store_true", help="emit JSON instead of text")
    args = parser.parse_args()

    draw_filter = parse_draws(args.draws)
    site_filter = {
        int(value, 16) for value in args.sites.split(",") if value.strip()
    }
    frame, width, height, draws = read_capture(args.capture)
    chosen = list(selected(draws, draw_filter, site_filter))

    if args.json:
        print(
            json.dumps(
                {
                    "capture": str(args.capture),
                    "frame": frame,
                    "width": width,
                    "height": height,
                    "draw_count": len(draws),
                    "draws": [
                        {
                            "index": draw.index,
                            "kind": draw.kind,
                            "tag": f"{draw.tag:08X}",
                            "placement": draw.placement,
                            "primitive": draw.primitive,
                            "primitive_count": draw.primitive_count,
                            "stride": draw.stride,
                            "vertices": draw.vertices,
                        }
                        for draw in chosen
                    ],
                },
                indent=2,
            )
        )
        return 0

    print(f"{args.capture}: frame={frame} size={width}x{height} draws={len(draws)}")
    for draw in chosen:
        print(
            f"draw={draw.index:4d} {draw.kind:7s} prim={draw.primitive} "
            f"count={draw.primitive_count} stride={draw.stride} "
            f"tag={draw.tag:08X} placement={draw.placement}"
        )
        count = len(draw.vertices) if args.vertices < 0 else min(args.vertices, len(draw.vertices))
        for index, vertex in enumerate(draw.vertices[:count]):
            values = " ".join(f"{value:.6g}" for value in vertex)
            print(f"  v{index}: {values}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
