# Wolf2Shell — Exploit Hurdles

This document describes the technical obstacles that stand between a crafted
Wolfenstein 3D savegame and reliable arbitrary code execution. Each item is a
property of the target binary, the DOS memory model, or the save format; none
depend on a particular build tool or workflow.

See [`TECHNICAL_INFO.md`](TECHNICAL_INFO.md) for the structures, save layout, and
offsets these obstacles act on, and [`README.md`](README.md) for the exploit
overview.

## Status

A working exploit exists for the retail 16-bit DOS build. The hurdles are
addressed as follows:

- **Runtime segment / PSP:** the PSP is measured in the target session, and the
  fixed per-build delta gives DGROUP; save pointers then land in the right
  memory.
- **Packed-binary delta:** recovered once per executable build through unpack
  emulation or relocation analysis.
- **Pointer model / `DS`:** the build uses near data pointers; `objtype.state`
  is a 2-byte near offset at `+6`. The injected write places that offset
  correctly, and the extra segment bytes fall into `flags`/padding. `think` is
  a far code pointer; payloads set `DS` from `CS` or avoid segment/register
  dependencies.
- **Preconditions / placement:** object #11 is used with an inline fake
  `statetype`; donor objects are neutralized and offsets are recalculated for
  each payload.
- **Checksum:** recomputed over the covered regions; object records are outside
  it.
- **Observability:** a minimal, register-independent payload confirms execution
  before richer payloads are tested.

The shareware `.WL1` build is now covered: its own DGROUP delta and
save/DGROUP offsets have been derived and are selectable with
`make-save.py --version shareware` (see [`tools/make-save/README.md`](tools/make-save/README.md)). The remaining
portability target is the demo (and any other alternate build), which needs its
own delta and re-confirmed offsets, with the pointer model validated per build.

## 1. Runtime DGROUP segment relocation

The injected `state` pointer must resolve to the fake `statetype` in Wolf3D's
data group (DGROUP), where BSS and the object list live, and the fake
statetype's `think` far pointer must name the runtime DGROUP segment.

- `WOLF3D.MAP` reports `DGROUP` as `3A390`, i.e. segment `0x3A39`. This is a
  **link-time, zero-based** value: it is only correct if DOS loaded the program
  at segment `0x0000`, which does not happen in practice.
- DOS loads an EXE at whatever segment is free above the kernel, COMMAND.COM,
  and any resident programs. The EXE relocation table fixes up references in
  code segments and initialized data, but **not in BSS**.
- Savegame bytes are copied into BSS, so any segment written into them remains
  unrelocated. A hardcoded `0x3A39` therefore points into unrelated memory
  whenever the load segment differs, and `ob->state->think` dereferences
  garbage instead of attacker code.
- The correct relationship for the retail build is:

  ```text
  LOAD_SEGMENT    = PSP + 0x10
  DGROUP(runtime) = LOAD_SEGMENT + 0x398D
  ```

  For example, `PSP = 0x0192` gives `DGROUP = 0x3B2F`, not `0x3A39`.

## 2. Load-segment (PSP) variability

`LOAD_SEGMENT` is not a constant. It depends on the DOS/DOSBox version,
`CONFIG.SYS`/`AUTOEXEC.BAT`, resident programs, device drivers, and the current
free-memory layout. It must be measured in the environment where the save will
be loaded.

- The Program Segment Prefix (PSP) is assigned per process. Running a small
  probe immediately before the game, with nothing started in between, normally
  yields the same starting segment for the game, because DOS reuses the freed
  block.
- The value is deterministic for a fixed session state but changes if the
  configuration, resident set, or session changes.
- The accompanying [`tools/probe/`](tools/probe/README.md) utility (`PROBE.COM`, 92 bytes)
  reports its own PSP segment as four hexadecimal digits, providing the value
  needed for the computation above.
- A save built for one PSP will silently miss its target in a session with a
  different PSP.

## 3. Recovering the DGROUP delta from a packed binary

The `0x398D` delta cannot be read directly from the shipped executable.

- Retail `WOLF3D.EXE` is packed with LZEXE 0.91 (signature `4C5A3931` following
  the MZ header), so the on-disk image does not contain the final segment
  layout.
- Borland C startup code (`C0.ASM`) bakes the DGROUP value into the unpacked
  image as a `mov dx, DGROUP` immediate. Recovering it requires either
  emulating the unpack stub at two different load segments and diffing the
  results, or rebuilding a relocated image and reading the resulting DATA
  segment.
- The recovered delta is **build-specific**. Different releases (shareware,
  registered, Spear of Destiny, demo, alternate localizations, or a different
  packer) use different values, and their internal offsets may differ as well.

## 4. Pointer width and calling convention (near data, far code)

The build uses the Borland **medium** model: data pointers are 2-byte near
offsets, code pointers are 4-byte far pointers.

- DGROUP is only `0xF030` bytes (below 64 KB), and the loader strips
  `sizeof(objtype) - 4` bytes when serializing an object, consistent with
  2-byte `next`/`prev` near pointers.
- `objtype.state` is a 2-byte near pointer at `obj + 6`; `flags` follows at
  `+8`. The save bytes confirm this: the four bytes at `+6` are
  `state_low, state_high, flags, padding`.
- The injected `state` write places the near offset at `+6`; the additional
  segment bytes land in `flags`/padding. The modified flags affect only actorat
  bookkeeping; they do not prevent the `think` call.
- `statetype.think` and `.action` are far code pointers; `statetype.next` is a
  near pointer. In this build `statetype` is 16 bytes, with `think` at `+6`.
- If `think(ob)` passes `ob` as a near pointer, the stack on entry is
  `ret_IP`, `ret_CS`, `ob_offset` with no `ob_segment`. Payloads that need the
  object pointer must account for this.
- Payloads that assume `DS == DGROUP` on entry should set `DS` from `CS`
  explicitly; the indirect call does not guarantee it.

## 5. Preconditions for reaching the indirect call

Execution reaches attacker code only when the engine's actor dispatch conditions
are satisfied (`DoActor` in `WL_PLAY.C`):

```c
if (!ob->active && !areabyplayer[ob->areanumber]) return;
...
if (!ob->ticcount) {
    think = ob->state->think;
    if (think)
        think(ob);
```

- The object must have `active != 0`, or its area must be flagged as containing
  the player.
- `ticcount` must be `0` so the think handler fires on the next tick.
- `state` must point to readable memory, and the `think` field at `state + 6`
  must be non-null.
- The object list must remain terminated by the `ac_badobject` sentinel; a
  missing sentinel causes the loader to exhaust the object array.

## 6. Payload placement inside fixed-size object records

`objtype` is 60 bytes and the fake `statetype` is 16 bytes, so the fake state and
the shellcode are packed into the same record and, for longer payloads, into
subsequent records.

- The fake `statetype` must sit at an offset the object fields do not overwrite
  before `DoActor` consumes them.
- Inline shellcode longer than the remaining record space spills into following
  objects. Those donor objects must be neutralized (`active = 0`,
  `areanumber = 0`) so the dispatcher skips them.
- Neutralizing a donor object by clearing its area assumes
  `areabyplayer[0] == 0` for that save and level; this is not guaranteed for
  arbitrary saves.
- Every offset in the injected layout must be recalculated if the payload
  length changes.

## 7. Checksum coverage

- Most save fields are covered by an XOR-pair checksum (`DoChecksum`), but the
  serialized object records are **not**.
- A crafted save must preserve or recompute the checksum over the covered
  regions, or the loader rejects it.
- Because the object records are outside the checksum, the control-flow fields
  can be modified without affecting the integrity check.

## 8. Failure observability

Failed exploitation is ambiguous: an incorrect segment, an incorrect pointer
width, and an incorrect stack assumption all present as the same symptoms
(hang, black screen, stopped audio, or silent no-op).

- A minimal payload with no register or segment dependencies, such as a 2-byte
  `INT 19h` (`CD 19`), distinguishes "code did not execute" from "code executed
  in the wrong environment".
- Richer payloads are only meaningful once the segment arithmetic is confirmed,
  because they additionally depend on DS and the calling convention.

## 9. Portability

- The DGROUP delta is fixed per executable build.
- The PSP/load segment is fixed per DOS session configuration.
- Save formats and internal offsets vary between Wolf3D versions (for example
  `.WL6` retail versus `.WL1` shareware) and between the full game and the
  demo.
- Consequently, a save that works in one build/environment is not portable to
  another without re-measuring the PSP and re-deriving the build-specific
  delta.

### Derived values per build

| Value | retail (`.WL6`) | shareware (`.WL1`) | How obtained |
| --- | ---: | ---: | --- |
| `DGROUP_REL` | `0x398D` | `0x3783` | emulate the LZEXE unpack stub, read the `mov dx, DGROUP` immediate |
| `objlist` (DGROUP-relative) | `0xB51C` | `0xAB6E` | shareware value read from the base save's own `actorat` near pointers |
| `tilemap` (DGROUP-relative) | `0x75BA` | `0x6BD8` | code-immediate match against the retail image |

`objlist` can be recovered from any save without touching the binary: every
non-wall `actorat[x][y]` entry is a near pointer equal to
`objlist + k * sizeof(objtype)` for the object `k` sitting on that tile. The PSP
is still measured per session with `PROBE.COM`.

The shareware values are wired into `make-save.py` as `--version shareware`.
The demo build still needs its own derivation (its unpacked startup suggests a
`0x3818` delta, but that must be confirmed).

---

See also: [`TECHNICAL_INFO.md`](TECHNICAL_INFO.md) — structures, save layout, and
offsets; [`README.md`](README.md) — exploit overview.
