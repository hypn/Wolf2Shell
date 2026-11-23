#!/usr/bin/env python3
"""Refresh an EMBEDDED_SAVES entry in make-save.py from a clean base save.

make-save.py carries its base saves as gzip+base64 strings in EMBEDDED_SAVES,
so it runs self-contained (no external save files).  Use this helper to swap in
a new base save -- for example a fresh save you made in-game.

Usage:
    python3 embed-save.py VERSION SAVEFILE [TARGET ...]

    VERSION    retail | shareware
    SAVEFILE   a clean Wolf3D save (19273 bytes, non-SPEAR)
    TARGET     one or more make-save.py files to rewrite
               (default: the make-save.py next to this script)

Examples:
    python3 embed-save.py shareware ./SAVEGAM0.WL1
    python3 embed-save.py retail ../../wolf3d/saves/SAVEGAM0.WL6 ../make-save.py
"""
from __future__ import annotations

import base64
import gzip
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SAVE_SIZE = 19273
VERSIONS = ("retail", "shareware")


def encode(save: bytes) -> str:
    # mtime=0 keeps the blob deterministic (so re-embedding is idempotent).
    return base64.b64encode(gzip.compress(save, 9, mtime=0)).decode("ascii")


def patch(target: Path, version: str, blob: str) -> None:
    src = target.read_text(encoding="utf-8")
    pattern = re.compile(r'(?m)^(\s*)"%s":\s*"[^"]*",\s*$' % re.escape(version))
    new, n = pattern.subn(r'\1"%s": "%s",' % (version, blob), src)
    if n == 0:
        raise SystemExit(f"{target}: no EMBEDDED_SAVES[{version!r}] entry found")
    if n > 1:
        raise SystemExit(f"{target}: {n} EMBEDDED_SAVES[{version!r}] entries found (expected 1)")
    target.write_text(new, encoding="utf-8")


def main() -> None:
    if len(sys.argv) < 3 or sys.argv[1] in ("-h", "--help"):
        print(__doc__.strip())
        raise SystemExit(0 if len(sys.argv) > 1 else 2)

    version, save_path = sys.argv[1], Path(sys.argv[2])
    if version not in VERSIONS:
        raise SystemExit(f"VERSION must be one of {VERSIONS}")
    if not save_path.exists():
        raise SystemExit(f"save file not found: {save_path}")

    save = save_path.read_bytes()
    if len(save) != SAVE_SIZE:
        raise SystemExit(f"{save_path}: {len(save)} bytes (expected {SAVE_SIZE} for non-SPEAR)")

    blob = encode(save)
    assert gzip.decompress(base64.b64decode(blob)) == save  # round-trip guard

    targets = [Path(t) for t in sys.argv[3:]] or [HERE / "make-save.py"]
    for target in targets:
        if not target.exists():
            raise SystemExit(f"target not found: {target}")
        patch(target, version, blob)
        print(f"embedded {version} base save from {save_path} -> {target} ({len(blob)} chars)")


if __name__ == "__main__":
    main()
