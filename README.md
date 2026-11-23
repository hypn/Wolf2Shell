# Wolf2Shell

**Wolf2Shell is an arbitrary code execution exploit for id Software's _Wolfenstein 3D_ (1992, DOS).** A crafted savegame causes the game to run attacker-supplied shellcode embedded in the save file, yielding control of the DOS machine. It abuses the save loader's failure to validate actor state pointers during deserialization; the payload executes in 16-bit real mode, where save data is loaded into executable memory.

![demoscene.gif](assets/demoscene.gif)

## Vulnerability

| | |
| --- | --- |
| **Class** | Insecure deserialization of untrusted data → control-flow hijack → arbitrary code execution (CWE-502 / CWE-94) |
| **Impact** | Arbitrary code execution in the game's DOS session |
| **Vector** | Crafted `SAVEGAM*.WL6` loaded through the in-game **Load Game** menu |
| **Affected** | Retail Wolfenstein 3D (DOS, 16-bit real mode): save loading in `WL_MAIN.C`, actor dispatch in `WL_PLAY.C`, structures in `WL_DEF.H` |

Wolf3D savegames serialize actor objects (`objtype`) directly, including the `state` pointer used by the AI update loop. The loader does not validate that pointer, and the object records are not covered by the save checksum. On the next AI tick, `DoActor()` executes `ob->state->think(ob)` — an indirect far call through save-controlled data. Wolf2Shell points `state` at a fake `statetype` embedded in the same object bytes and sets its `think` field to shellcode also stored in the save, so execution jumps into attacker code as soon as the save loads. The key environment-specific requirement is the runtime DGROUP segment the save data lands in (`DGROUP = PSP + 0x10 + 0x398D`; the delta is build-specific, and `PROBE.COM` measures the PSP). The tool rebuilds the save structure and recomputes the checksum so the game accepts the modified file.

## Documentation

- [`TECHNICAL_INFO.md`](TECHNICAL_INFO.md) — consolidated structures, save layout, DGROUP/PSP arithmetic, and the injection layout.
- [`HURDLES.md`](HURDLES.md) — technical obstacles to reliable execution and their status (including portability to other builds).
- [`tools/make-save/README.md`](tools/make-save/README.md) — builder usage, options, and save layout.
- [`tools/probe/README.md`](tools/probe/README.md) — measuring the DOS PSP segment.

## Payloads

Wolf2Shell supports three payload modes:

- **`reboot`** — Triggers a warm reboot payload.
- **`text`** — Switches to text mode, displays a custom message, writes a `PWNED.txt` file next to the game, then exits to DOS.
- **`asm`** — Assembles and injects a custom 16-bit NASM payload.

## Savegames

The ready-made saves live in [`savegames/`](savegames/):

| Savegame file | In-game name | What it does |
| --- | --- | --- |
| `savegames/SAVEGAM0.WL6` | Reboot! | Injects a two-byte `INT 19h` payload: loading the save warm-reboots the DOS machine. |
| `savegames/SAVEGAM1.WL6` | Text + Shell | Injects a text-mode payload that prints the configured message (default "Wolf2Shell by Hypn"), writes it to `PWNED.txt`, waits for a key, then exits to DOS. |
| `savegames/SAVEGAM2.WL6` | ASM payload! | Injects the assembled `wolf2shell.asm` payload: a VGA plasma, sine-wave scroller and PC-speaker demo; press a key to exit to DOS. |

### Playing the saves

These saves are for **retail Wolf3D running under DOSBox**:

1. See [`tools/probe/`](tools/probe/README.md) to get the **PSP segment** for your DOS session. Run `PROBE.COM` immediately before `WOLF3D.EXE`, then read `PROBE.TXT`. If it differs from the default `0192`, rebuild the saves with `python3 tools/make-save/make-save.py --psp <hex> ...` first.
2. Copy the `SAVEGAM0.WL6`, `SAVEGAM1.WL6` and `SAVEGAM2.WL6` files from `savegames/` into your Retail Wolf3D directory, next to `WOLF3D.EXE`.
3. Start the game under DOSBox from that directory (mount it, then run `WOLF3D.EXE`).
4. Choose **Load Game** in the main menu and select the slot with the matching in-game name (`Reboot!`, `Text + Shell`, or `ASM payload!`). The payload runs as soon as the save loads; the first one reboots, the other two wait for a key press before returning to DOS. The text payload also leaves `PWNED.txt` next to the game.

## Tools

- [`tools/make-save/`](tools/make-save/README.md) — the savegame builder (`make-save.py`), its base save, the demo payload source, and full usage/options documentation.
- [`tools/probe/`](tools/probe/README.md) — `PROBE.COM`, the helper that measures the DOS PSP segment.
