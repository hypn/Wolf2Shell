# `make-save` — Wolf3D savegame builder

`make-save.py` builds a Wolfenstein 3D savegame (`SAVEGAM<slot>.WL6`) with an
injected payload. It rewrites object #11 in the save so the game's actor
dispatcher calls attacker-supplied code when the save is loaded, then
recomputes the save checksum so the loader accepts the file.

The vulnerability and the technical constraints behind the layout are described
in [../HURDLES.md](../../HURDLES.md), the consolidated structures and injection
layout in [../TECHNICAL_INFO.md](../../TECHNICAL_INFO.md), and the top-level
[README.md](../../README.md).

## Files

| File | Purpose |
| --- | --- |
| `make-save.py` | The builder. Python 3, no third-party modules. |
| `embed-save.py` | Refreshes an embedded base save from a clean save file. |
| `wolf2shell.asm` | Demo payload source for `--payload asm` (VGA plasma, scroller, PC-speaker). |

The clean base saves are **embedded** in `make-save.py` as gzip+base64 strings
(`EMBEDDED_SAVES`), so the builder is self-contained and needs no external save
files. To swap in a fresh base save, run `embed-save.py`:

```bash
python3 tools/make-save/embed-save.py retail    /path/to/SAVEGAM0.WL6
python3 tools/make-save/embed-save.py shareware /path/to/SAVEGAM0.WL1
```

`text` and `asm` payloads require [NASM](https://www.nasm.us/) on `PATH` (or
pass `--nasm`).

## Usage

Run from the repository root:

```bash
python3 make-save.py --slot 0 --payload reboot
python3 make-save.py --slot 1 --payload text --text "Wolf2Shell by Hypn"
python3 make-save.py --slot 2 --payload asm --asm wolf2shell.asm

# Shareware (Wolfenstein 3D v1.4, SAVEGAM?.WL1):
python3 make-save.py --version shareware --slot 0 --payload reboot
```

Output goes to `./output/` (relative to the current working directory, not the
script location) by default. Copy the
generated `SAVEGAM<slot>.WL6` (retail) or `SAVEGAM<slot>.WL1` (shareware) next
to `WOLF3D.EXE` and load that slot in-game.

### Options

```text
(required)
  --payload {asm,reboot,text}   Payload type
  --text TEXT                   Text for --payload text (default: "Wolf2Shell by Hypn")
  --asm ASM                     ASM file for --payload asm (default: wolf2shell.asm)

(defaults)
  --name NAME                   In-game save name (default: Reboot! / Text + Shell / ASM payload!)
  --version {retail,shareware}  Game version (default: retail)
  --psp PSP                     Wolf3d.exe PSP segment in hex (default: 0192)
  --outdir OUTDIR               Output directory (default: ./output)

(advanced)
  --dgroup DGROUP               Override runtime DGROUP segment directly
  --dgroup-rel DGROUP_REL       Override DGROUP delta (DGROUP = PSP+0x10+DGROUP_REL)
  --objlist-off OBJLIST_OFF     DGROUP-relative objlist offset (default 0xb51c)
  --tilemap-off TILEMAP_OFF     DGROUP-relative tilemap offset (default 0x75ba)
  --nasm NASM                   NASM executable (default: nasm)
```

## Payloads

- **`reboot`** — writes a two-byte `INT 19h` (`CD 19`) warm-reboot stub inline
  in object #11 and points `think` at it. No register or segment dependencies;
  used to verify that the hijack fires.
- **`text`** — assembles a small payload that switches to text mode, prints
  `--text`, writes the same message to `PWNED.txt` in the game's working
  directory (via DOS `INT 21h` create/write/close), waits for a key, and exits
  to DOS. The payload is placed in the tilemap and `think` points at that
  DGROUP offset.
- **`asm`** — assembles a custom 16-bit NASM source (`--asm`, default
  `wolf2shell.asm`) and injects it the same way as `text`. The source may use
  the `__PAYLOAD_ORG__` placeholder for the tilemap injection offset.

## How the injection works

The save is a flat image of the game's state. The object list begins at file
offset 13,909; each `objtype` is 60 bytes. The builder targets object #11 (the
first live guard in the base save):

```text
obj#11 = 13909 + 11 * 60

+0    active    = 1            ; dispatcher considers the actor alive
+2    ticcount  = 0            ; think fires on the next tick
+6    state     = 0xB7D2       ; near offset of fake statetype (obj#11+34)
+8    flags/pad = DGROUP bytes ; segment bytes written here (see note)
+34   fake statetype
+40     think   = DGROUP:Bxxx  ; -> tilemap payload, or obj#11+48 for reboot
+44     action  = 0
+48   (reboot payload bytes)
```

`objtype.state` is a 2-byte near pointer in this build. The builder still
writes the 16-bit DGROUP segment at `+8`/`+9`; those bytes land in `flags` and
padding, which affect only actorat bookkeeping and do not prevent the `think`
call.

For `text` and `asm`, the shellcode is written at the start of the tilemap and
`think` points at the DGROUP-relative tilemap offset. For `reboot`, the two
bytes are stored directly after the fake statetype.

Object records are not covered by the save checksum; the builder recomputes the
checksum over the covered regions (`gamestate`, level ratios, tilemap,
`actorat`, and the trailing tables) before writing the file.

## Runtime segment (DGROUP)

The injected `think` far pointer (and the segment bytes written alongside
`state`) need the runtime data segment, which depends on where DOS loaded the
game:

```text
LOAD_SEGMENT    = PSP + 0x10
DGROUP(runtime) = LOAD_SEGMENT + DGROUP_REL
                   retail:    DGROUP_REL = 0x398D
                   shareware: DGROUP_REL = 0x3783
```

`--psp` supplies the measured value. `PROBE.COM` in
[../probe/](../probe/README.md) reports the PSP for the current DOS session.
If the runtime segment is already known, `--dgroup` sets it directly;
`--dgroup-rel` overrides the delta for a different build.

## Game versions

`--version` selects the build-specific constants (all DGROUP-relative):

| Value | `retail` (`.WL6`) | `shareware` (`.WL1`) | How it is obtained |
| --- | ---: | ---: | --- |
| `DGROUP_REL` | `0x398D` | `0x3783` | emulate the LZEXE stub, read the `mov dx, DGROUP` immediate |
| `objlist_off` | `0xB51C` | `0xAB6E` | shareware value confirmed from the base save's own `actorat` near pointers |
| `tilemap_off` | `0x75BA` | `0x6BD8` | code-immediate match against the retail image |

Everything else (save layout, `objtype`/`statetype`, obj#11, checksum, sentinel)
is identical between the two builds. The retail values are confirmed for the
GOG/retail LZEXE-packed `WOLF3D.EXE`; the shareware values are derived from the
LZEXE-packed shareware `WOLF3D.EXE` v1.4. See [`../../HURDLES.md`](../../HURDLES.md)
§9 and [`../../SHAREWARE.md`](../../SHAREWARE.md) for the derivation.

## Notes

- Slots are `0`–`9`; the engine builds save names with a single digit.
- `--name` sets the save label stored in the 32-byte header (not checksummed). It
  defaults to a per-payload label (`Reboot!`, `Text + Shell`, `ASM payload!`), so
  the three payloads are distinguishable in the Load Game menu.
- Generated files are written as `SAVEGAM<slot>.WL6` (retail) or
  `SAVEGAM<slot>.WL1` (shareware); use `--outdir` to write elsewhere.
- The `text` payload creates or overwrites `PWNED.txt` next to the game and
  writes the `--text` message into it (no trailing newline).
- The retail defaults (`--psp 0192`, `DGROUP_REL 0x398D`, object/tilemap offsets)
  match the retail GOG build; `--version shareware` uses the shareware constants.
  Runtime segment values vary by DOS environment, so measure the PSP in the
  session that will load the save.
