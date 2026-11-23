# Wolf2Shell — Technical Information

Consolidated technical facts behind the savegame code-execution path: the
structures, save layout, runtime segment arithmetic, and payload placement used
by the exploit. Crash scenarios and unrelated save-field bugs are out of scope.
See [`HURDLES.md`](HURDLES.md) for the obstacle/status view and [`README.md`](README.md)
for the exploit overview.

## 1. Target and memory model

- Wolfenstein 3D, retail DOS release, 16-bit real mode.
- Built with Borland C++ 3.0 using the **medium** memory model: near data
  pointers, far code pointers.
- The shipped `WOLF3D.EXE` is packed with LZEXE 0.91 (signature `4C5A3931`
  after the MZ header).
- DGROUP is `0xF030` bytes (below 64 KB); code is larger than 130 KB.
- Real mode has no NX/W^X, no ASLR, and no pointer validation. Save data is
  loaded into DGROUP/BSS, which is directly executable.

## 2. Vulnerable code path

The save loader deserializes `objtype` records directly into the object list
(`LoadTheGame` in `WL_MAIN.C`). It does not validate the `state` pointer and the
object records are not covered by the save checksum.

Actor dispatch (`DoActor` in `WL_PLAY.C`) then does:

```c
if (!ob->active && !areabyplayer[ob->areanumber])
    return;

if (!(ob->flags & (FL_NONMARK|FL_NEVERMARK)))
    actorat[ob->tilex][ob->tiley] = NULL;

if (!ob->ticcount) {
    think = ob->state->think;
    if (think)
        think(ob);
    ...
}
```

For the hijack to fire:

1. `active != 0`, or the object's area is flagged in `areabyplayer`.
2. `ticcount == 0`, so the `think` branch is taken.
3. `state` resolves to readable memory.
4. `state->think` is non-null and points at executable bytes.

## 3. Object and state structures

### `objtype` (60 bytes, medium model)

| Offset | Size | Field | Notes |
| ---: | ---: | --- | --- |
| +0 | 2 | `active` | `ac_badobject = -1`, `ac_no = 0`, `ac_yes = 1` |
| +2 | 2 | `ticcount` | `0` selects the `think` branch |
| +4 | 2 | `obclass` | `3` = guard, `6` = SS, etc. |
| +6 | 2 | `state` | **near** pointer to a `statetype` in DGROUP |
| +8 | 1 | `flags` | `FL_SHOOTABLE`, `FL_NEVERMARK`, etc. |
| +9 | 1 | padding | |
| +10 | 4 | `distance` | `long` |
| +14 | 2 | `dir` | enum |
| +16 | 4 | `x` | `fixed` (`long`) |
| +20 | 4 | `y` | `fixed` |
| +24 | 2 | `tilex` | unsigned |
| +26 | 2 | `tiley` | unsigned |
| +28 | 1 | `areanumber` | |
| +29 | 1 | padding | |
| +30 | 2 | `viewx` | `int` |
| +32 | 2 | `viewheight` | unsigned |
| +34 | 4 | `transx` | `fixed` |
| +38 | 4 | `transy` | `fixed` |
| +42 | 2 | `angle` | `int` |
| +44 | 2 | `hitpoints` | `int` |
| +46 | 4 | `speed` | `long` |
| +50 | 2 | `temp1` | `int` |
| +52 | 2 | `temp2` | `int` |
| +54 | 2 | `temp3` | `int` |
| +56 | 2 | `next` | near `objtype *` |
| +58 | 2 | `prev` | near `objtype *` |

The near pointer width is confirmed by the save bytes: at `+6` the four bytes
are `state_low, state_high, flags, padding`. For example, the base save's object
#11 has `state = 0x1C8A` and `flags = 0x01`, encoded as
`8A 1C 01 00`. The apparent `0001` segment in that word is actually the
`flags` byte plus padding, not a far-pointer segment. The loader's
`memcpy(new, &nullobj, sizeof(nullobj) - 4)` also strips two 2-byte near
pointers (`next`, `prev`), not two 4-byte far pointers.

### `statetype` (16 bytes)

| Offset | Size | Field | Notes |
| ---: | ---: | --- | --- |
| +0 | 1 | `rotate` | boolean |
| +1 | 1 | padding | |
| +2 | 2 | `shapenum` | `int`; `-1` means take from `ob->temp1` |
| +4 | 2 | `tictime` | `int` |
| +6 | 4 | `think` | **far** function pointer |
| +10 | 4 | `action` | **far** function pointer |
| +14 | 2 | `next` | near `statetype *` |

The MAP statetype entries are spaced `0x10` bytes apart (for example
`s_grdstand` at `0x1C7A` and `s_grdpath1` at `0x1C8A`), confirming the 16-byte
size. The source definition also confirms it:

```c
typedef struct statestruct {
    boolean rotate;
    int     shapenum;
    int     tictime;
    void    (*think)(), (*action)();
    struct  statestruct *next;
} statetype;
```

`think` and `action` are code pointers and therefore far; `next` is a data
pointer and therefore near.

### Relocation asymmetry (real vs. fake statetype)

The game's real statetypes live in DGROUP's **initialized DATA** (for example
`s_grdstand` at `0x1C7A`). The EXE loader relocates the far pointers inside
them, so their `think`/`action` targets are valid at runtime. Pointing
`ob->state` at one of these needs no segment math, but it also cannot execute
attacker code.

The injected fake statetype lives in `objlist` (BSS). BSS is not part of the
EXE image, so nothing in it is relocated at load time. The far `think` pointer
written into the save must therefore name the runtime DGROUP segment
explicitly; this is the reason for the `PSP + 0x10 + 0x398D` arithmetic.

## 4. Save format

The base save is 19,273 bytes with 23 object records (player, 21 actors, and
the sentinel):

| Offset | Size | Field | Checksummed |
| ---: | ---: | --- | :---: |
| 0 | 32 | Header name | No |
| 32 | 66 | `gamestate` | Yes |
| 98 | 80 | `LevelRatios[8]` | Yes |
| 178 | 4096 | `tilemap[64][64]` | Yes |
| 4274 | 8192 | `actorat[64][64]` | Yes |
| 12466 | 1369 | `areaconnect[37][37]` | No |
| 13835 | 74 | `areabyplayer[37]` | No |
| 13909 | `N * 60` | Object records | **No** |
| ... | 2 | `laststatobj` | Yes |
| ... | 3200 | `statobjlist[400]` | Yes |
| ... | 128 | `doorposition[64]` | Yes |
| ... | 640 | `doorobjlist[64]` | Yes |
| ... | 10 | `pwallstate`, `pwallx`, `pwally`, `pwalldir`, `pwallpos` | Yes |
| end-4 | 4 | Checksum (little-endian `long`) | — |

### Object loading

`InitActorList()` sets `objcount = 1` and installs the player. The loader then
reads the player object, followed by 60-byte records until a record whose
`active` field equals `ac_badobject` (`0xFFFF`). Each record is copied with
`memcpy(new, &nullobj, sizeof(nullobj) - 4)`, so `next`/`prev` are not restored.
`objlist` has `MAXACTORS = 150` entries (9000 bytes). The trailing tables are
sized by `MAXSTATS = 400` and `MAXDOORS = 64`.

The loader reads every field with `CA_FarRead` of `sizeof(struct)` and does no
validation of pointer-valued fields. Records are stored contiguously, so object
#N occupies file offset `13909 + N * 60` and DGROUP offset
`0xB51C + N * 60`.

`actorat[64][64]` is an array of 2-byte **near** object pointers, consistent
with the medium model.

### Checksum

`DoChecksum` accumulates, for each covered region:

```c
for (i = 0; i < size - 1; i++)
    checksum += source[i] ^ source[i + 1];
```

It is called once per region, so no byte pair spans a region boundary. The
covered regions are `gamestate`, `LevelRatios`, `tilemap`, `actorat`,
`laststatobj`, `statobjlist`, `doorposition`, `doorobjlist`, and the five
pushwall fields. The header, `areaconnect`, `areabyplayer`, the object records,
and the checksum itself are outside the check.

## 5. Runtime DGROUP and PSP

`WOLF3D.MAP` reports `DGROUP 3A390`, i.e. segment `0x3A39`. This is a
**link-time, zero-based** value and is not the runtime segment.

For the retail build:

```text
LOAD_SEGMENT    = PSP + 0x10
DGROUP(runtime) = LOAD_SEGMENT + 0x398D
```

Example: `PSP = 0x0192` gives `LOAD_SEGMENT = 0x01A2` and
`DGROUP = 0x3B2F`.

The `0x398D` delta was recovered from the packed executable by emulating the
LZEXE unpack stub at two different load segments and diffing the results;
the result was cross-checked against a rebuilt relocated image and the
statetype table. It is build-specific.

### Measuring the PSP

A small DOS `.COM` probe reports its own `CS`, which for a `.COM` program is the
PSP segment. Running the probe immediately before `WOLF3D.EXE` in the same DOS
session, with nothing started in between, normally yields the game's load
segment. The value depends on the DOS/DOSBox version, configuration, resident
programs, and free-memory layout, so it must be measured per environment.

### Key DGROUP offsets

| Symbol | DGROUP offset | Size |
| --- | ---: | ---: |
| `areabyplayer` | `0x52DC` | 74 |
| `doorposition` | `0x5328` | 128 |
| `actorat` | `0x55BA` | 8192 |
| `tilemap` | `0x75BA` | 4096 |
| `doorobjlist` | `0x86BA` | 640 |
| `laststatobj` | `0x893A` | 2 |
| `statobjlist` | `0x893C` | 3200 |
| `player` | `0x95BC` | pointer |
| `gamestate` | `0x95C2` | 66 |
| `LevelRatios` | `0x9906` | 80 |
| `objlist` | `0xB51C` | 9000 |

`areaconnect` is an exception: it lives in its own segment at `33DA:0000`, not
in DGROUP. `pwallstate` is at `0x5326`, `pwalldir` at `0x52D6`, and `pwallpos`
at `0x53A8`.

Useful `statetype` offsets in DGROUP: `s_player` `0x190C`, `s_grdstand`
`0x1C7A`, `s_grdpath1` `0x1C8A`, `s_grdpath1s` `0x1C9A`, `s_grdpath2`
`0x1CAA`, `s_grdchase1` `0x1D3A`.

Useful MAP code addresses:

| Symbol | MAP address | Purpose |
| --- | --- | --- |
| `_Quit` | `048F:14CF` | exit to DOS with an error string |
| `_Message` | `06A5:3960` | in-game message box |
| `_puts` | `0000:3E13` | C library stdout |

These are link-time segments; a payload that calls them must apply the runtime
load-segment relocation.

## 6. Injection layout

The builder targets object #11 (file offset `13909 + 11 * 60 = 14569`,
DGROUP offset `0xB7B0`). In the base save this is the first live guard:
`active = 1`, `ticcount = 7`, `obclass = 3`, `state = 0x1C8A`
(`s_grdpath1`), `flags = 0x01`.

| Offset | Field | Value / purpose |
| ---: | --- | --- |
| +0 | `active` | `1` |
| +2 | `ticcount` | `0` |
| +6 | `state` (2) | `0xB7D2`, the fake `statetype` at obj#11+34 |
| +8 | `flags` (1) | low byte of DGROUP (the builder writes the segment here) |
| +9 | padding (1) | high byte of DGROUP |
| +34 | fake `statetype` | |
| +36 | `shapenum` | `0` |
| +38 | `tictime` | `0` |
| +40 | `think` (4) | far pointer; target `0xB7E0` for reboot, `0x75BA` for text/asm |
| +44 | `action` (4) | `0` |
| +48 | payload / `next` | `CD 19` for reboot; unused for text/asm |

Because `state` is a near pointer, only the offset at `+6` matters. The builder
writes a 4-byte value anyway: the offset lands at `+6`, and the DGROUP segment
bytes land in `flags`/padding. The modified flags affect only actorat
bookkeeping; they do not prevent the `think` call.

`think` is a far code pointer. The far call enters with `CS = DGROUP` and
`IP = target`; the payload sets `DS` from `CS` when it needs data references.

### Payloads

- **`reboot`** — two bytes `CD 19` (`INT 19h`) at obj#11+48 (`0xB7E0`); `think`
  points directly there. No register or segment dependencies.
- **`text`** — payload assembled into the tilemap at DGROUP `0x75BA` (file
  offset 178), maximum 4096 bytes. It calls the game's own `ShutdownId()` to
  restore the hooked INT 08h/INT 09h/sound IRQ, sets video mode 3, prints the
  configured message via BIOS teletype, prompts `(press any key to exit)`, waits
  for a key, and exits via `INT 21h AX=4C00`.
- **`asm`** — a custom 16-bit NASM payload assembled into the tilemap at the
  same offset. The shipped demo sets `DS`/`ES` from `CS`, switches to VGA mode
  13h, and runs a plasma/sine-scroller/PC-speaker effect; it does not return to
  DOS.

An inline payload that exceeds the remaining space in obj#11 spills into
following object records. Those donor objects must be neutralized
(`active = 0`, `areanumber = 0`) so the dispatcher skips them. That
neutralization relies on `areabyplayer[0] == 0` for the save/level in question,
and all offsets must be recalculated if the payload length changes.

## 7. Recovering DOS state before returning to the shell

The savegame hijack runs **inside** the game, after it has taken over the
interrupt vectors the BIOS/DOS installed at boot. DOS does not restore those
vectors when a program terminates, so a payload that ends with
`INT 21h AX=4C00` leaves the IVT pointing at the game's ISRs — which live in
the memory DOS is about to free:

- **INT 09h (keyboard).** `INL_StartKbd()` (`ID_IN.C`) does
  `OldKeyVect = getvect(9); setvect(9, INL_KeyService)`. `INL_KeyService` reads
  the keyboard controller itself and **never chains to the BIOS**, so BIOS
  `INT 16h` — the usual "press any key" wait — never sees a keystroke. Without a
  restore, the `text` payload's key prompt hangs forever.
- **INT 08h (timer) + sound IRQ.** The sound driver (`ID_SD.C`) does
  `t0OldService = getvect(8); setvect(8, isr)` and hooks the SB IRQ. After exit
  the next timer tick jumps into freed memory.

**Fix: call the game's own `ShutdownId()` (`WL_MAIN.C`) before exiting.** It runs
`US_Shutdown(); SD_Shutdown(); PM_Shutdown(); IN_Shutdown(); VW_Shutdown();
CA_Shutdown(); MM_Shutdown();` — `SD_Shutdown()` restores INT 08h and the SB IRQ,
and `IN_Shutdown()` restores INT 09h and clears the BIOS ctrl/alt/shift flags.
Both are guarded by `SD_Started` / `IN_Started`, which are set during normal
play, so they run.

`ShutdownId()` is build-specific. It is easy to locate by its signature —
`push bp; mov bp, sp;` followed by exactly **seven far calls**, then
`pop bp; retf`:

| Build | load-module offset | far call from the payload |
| --- | ---: | --- |
| retail `.WL6` | `0x54B9` | `DS-0x3442:0x0009` |
| shareware `.WL1` | `0x50BA` | `DS-0x3278:0x000A` |

The delta is LOAD-relative, so it is PSP-independent. A payload far-calls it
with the usual real-mode `retf` trick:

```asm
        mov ax, ds                  ; DS = DGROUP
        sub ax, 0x3442              ; -> ShutdownId's code segment
        push cs                     ; return segment
        push word .done             ; return offset
        push ax                     ; target segment
        push strict word 0x0009     ; target offset
        retf
.done:
        push cs
        pop ds                      ; ShutdownId may have clobbered DS
```

The `make-save.py` `text` payload does this at entry, so its key prompt works
and its exit is clean. The retail `s12.py` / `pwned_shellcode.asm` goes further
and also force-writes IVT[8]/[9] from the game's saved vectors
(`DGROUP:0xECE3` and `DGROUP:0x4786`) in case the shutdown guards skip.

Payloads that deliberately never return to DOS (for example the `asm`
demoscene) need none of this.

## 8. Caveats

- The DGROUP delta is specific to the executable build; the PSP/load segment is
  specific to the DOS session.
- Other builds — notably the shareware `.WL1` release and the demo — require
  their own delta and re-confirmed save/DGROUP offsets. The shareware values are
  derived and shipped (`DGROUP_REL 0x3783`, `objlist 0xAB6E`, `tilemap 0x6BD8`);
  the demo is still outstanding.
- The donor-object neutralization assumes `areabyplayer[0] == 0`.
- MAP addresses are link-time; runtime code/data segments must account for the
  load segment.

---

See also: [README.md](README.md) — exploit overview; [HURDLES.md](HURDLES.md) —
obstacles to reliable execution and portability; [tools/make-save/README.md](tools/make-save/README.md) —
builder usage.
