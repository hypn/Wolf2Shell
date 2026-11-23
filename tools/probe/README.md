# PROBE.COM — measure the DOS segment before launching Wolf3D

`PROBE.COM` is a tiny (92-byte) real-mode DOS helper that tells you the **PSP segment** DOS has assigned to programs in the current DOS session. Wolf2Shell needs that number to build a savegame whose injected far pointers land at the correct place inside `WOLF3D.EXE`.

You can think of it as a little "run-this-first helper". Strictly speaking it is **not** a TSR: it does not stay resident or hook interrupts. It starts, writes one file, and exits.

## The short version

From the DOS prompt, in the directory that contains `WOLF3D.EXE`:

```text
C:\WOLF3D> PROBE
C:\WOLF3D> WOLF3D.EXE
```

Play as usual, then quit Wolf3D back to DOS and read the file the probe left behind:

```text
C:\WOLF3D> TYPE PROBE.TXT
0192
```

Those four hex digits are the number you pass to the save builder (run from the repository root):

```bash
python3 tools/make-save/make-save.py --psp 0192 --slot 2 --payload text
```

The save is written to `./output/` by default. Copy the generated `SAVEGAM2.WL6` next to `WOLF3D.EXE`, start Wolf3D **in the same DOS session**, and load slot 2.

## What the probe actually does

`probe.asm` reads the `CS` register. For a DOS `.COM` file, `CS` is the segment of the program's PSP (Program Segment Prefix), and the program starts at offset `0100h` in that segment. The probe converts that segment to four uppercase hex digits and writes them, plus CR/LF, to `PROBE.TXT` in the current directory:

```text
0192<CR><LF>          (6 bytes total)
```

The file is created or overwritten every time you run `PROBE`. Nothing is printed on screen; `TYPE PROBE.TXT` (or opening the file from the host side) is how you see the value.

## Why we need this number

The exploit saves contain **far pointers** into Wolf3D's data segment (`DGROUP`). A far pointer is `segment:offset`, and the segment part has to be exactly right. Unfortunately the segment is not fixed:

* `WOLF3D.MAP` lists `DGROUP` as `3A390`, but that is a **zero-based, link-time** value — it is what the segment would be if DOS loaded the program at segment 0, which never happens in practice.
* At runtime DOS places the program wherever there is free memory. That location depends on the DOS/DOSBox session.

For this specific Wolf3D build (the GOG/retail LZEXE-packed `WOLF3D.EXE`), the runtime value is:

```text
LOAD_SEGMENT = PSP + 0x10
DGROUP       = LOAD_SEGMENT + 0x398D
```

With the example reading from `PROBE.TXT`:

| Step | Example |
|---|---:|
| PSP (from `PROBE.TXT`) | `0x0192` |
| `LOAD_SEGMENT = PSP + 0x10` | `0x01A2` |
| `DGROUP = LOAD_SEGMENT + 0x398D` | `0x3B2F` |

Using the link-time MAP value `0x3A39` directly produces far pointers into the wrong memory. If `DGROUP` is wrong when the save is built, the game either ignores the hook or crashes instead of running the payload. That is why the runtime value is measured first. See [`../../HURDLES.md`](../../HURDLES.md) for the full set of technical obstacles.

`make-save.py` does this arithmetic for you when you give it `--psp <hex>` (it prints the calculated `PSP`, `load` and `DGROUP` values). If you already know the runtime segment, you can skip the probe and pass `--dgroup <hex>` directly; if you are using a different Wolf3D build, `--dgroup-rel` overrides the `0x398D` constant.

## Why "run it first, read it afterwards"

`PROBE.COM` reports **its own** PSP. The trick is that when you run it and then immediately run `WOLF3D.EXE` in the same DOS session, with nothing loaded in between, DOS normally gives the next program the same starting segment. So the probe's number is our measurement of Wolf3D's PSP.

The file is written as soon as `PROBE` runs — you do not have to wait until after the game. In practice you read it after quitting Wolf3D because the game owns the screen (especially full-screen DOSBox) and there is no DOS prompt to type at while it is running.

## Important details

* **Same session, nothing in between.** Run `PROBE` immediately before `WOLF3D.EXE`. Starting other programs, installing TSRs, changing the DOSBox configuration, or rebooting can change the segment. If you change anything, measure again.
* **The value is environment-specific.** `0192` is the value measured in one GOG/DOSBox setup; it is not universal. The probe is deterministic for a given session state, so use whatever *your* `PROBE.TXT` says.
* **Build and play in a matching session.** Generate the save with the measured `--psp`, then play it from a DOS session that produces the same PSP (ideally the very session you measured in).
* **Only for the 16-bit DOS game.** This does not apply to Windows or modern source ports, which have different memory layouts.
* The `0x398D` offset is confirmed for the retail GOG build. Shareware/demo variants may differ; use `--dgroup-rel` / `--dgroup` if your build is different.

## Files

| File | Purpose |
|---|---|
| `probe.asm` | NASM source for the helper. |
| `PROBE.COM` | Prebuilt 92-byte executable, ready to copy next to `WOLF3D.EXE`. |
| `PROBE.TXT` | Generated output: four hex digits + CR/LF. Not included here; created in the directory where you run `PROBE`. |

To rebuild the executable from source (requires [NASM](https://www.nasm.us/)):

```bash
nasm -f bin probe.asm -o PROBE.COM
```

Keep `org 100h` in the source: that is what makes `CS` equal to the PSP segment rather than an offset into it.
