; ============================================================================
;  WOLF2SHELL savegame-injected variant (based on demoscene/wolf2b.asm)
; ----------------------------------------------------------------------------
;  Template placeholders replaced by demoscene-save.py:
;    __PAYLOAD_ORG__  -> DGROUP-relative offset where this blob is placed
;
;  Build: nasm -f bin -o wolf2b_save.bin wolf2b_save.asm
;  This binary is injected into a Wolf3D SAVEGAM?.WL6 and reached via the
;  enemy obj->state->think far-pointer hijack (see s11.py / DIAGNOSIS.md).
; ============================================================================
;
;  Original effect: VGA mode 13h plasma + sine-wave scroller + PC speaker.
;  Savegame adaptation: DS/ES set from CS on entry; BSS tables emitted as
;  bytes (resb) so the full runtime footprint is in the injected blob.
; ---------------------------------------------------------------------------

bits 16
org __PAYLOAD_ORG__

SCALE       equ 3                   ; scroller font magnification (8x8 -> 24x24)
NOTELEN     equ 2                   ; frames per music step (smaller = faster)

; ----------------------------------------------------------------------------
;  Entry - reached by far call from DoActor: think(ob)
;  CS = DGROUP at runtime, IP = __PAYLOAD_ORG__.  We never return.
; ----------------------------------------------------------------------------
start:
        push    cs
        pop     ds                  ; DS = DGROUP/code segment for data refs
        push    cs
        pop     es                  ; ES = DGROUP for font copy destination
        cld
        sti                         ; be nice to DOS interrupts

        mov     ax, 0x0013
        int     0x10

        mov     ax, 0x1130          ; copy ROM 8x8 font (chars 0..127) locally
        mov     bh, 0x03
        int     0x10
        push    es
        push    cs
        pop     es
        pop     ds
        mov     si, bp
        mov     di, fontbuf
        mov     cx, 1024
        rep     movsb
        push    cs
        pop     ds

        call    buildSin
        call    setPalette

; ----------------------------------------------------------------------------
;  Main loop
; ----------------------------------------------------------------------------
mainLoop:
        mov     dx, 0x3DA           ; sync to vertical retrace
.wait1: in      al, dx
        test    al, 8
        jnz     .wait1
.wait2: in      al, dx
        test    al, 8
        jz      .wait2

        call    drawPlasma
        call    drawScroll
        call    updateMusic

        add     byte [t],      3    ; <-- plasma flow speed
        add     byte [t2],     4
        add     word [scrollX],4    ; <-- ribbon travel speed along the wave

        mov     ah, 0x01
        int     0x16
        jz      mainLoop

; ----------------------------------------------------------------------------
;  Exit
; ----------------------------------------------------------------------------
        xor     ah, ah
        int     0x16
        in      al, 0x61
        and     al, 0xFC
        out     0x61, al
        mov     ax, 0x0003
        int     0x10
        mov     ax, 0x4C00
        int     0x21

; ============================================================================
;  buildSin - 256-entry sine table, 0..64, centre 32 (parabolic, no FPU/data)
; ============================================================================
buildSin:
        xor     bx, bx
.sb:    mov     ax, bx
        cmp     ax, 128
        jb      .firsthalf
        sub     ax, 128
        mov     cx, 128
        sub     cx, ax
        mul     cx
        shr     ax, 7
        mov     cx, ax
        mov     ax, 32
        sub     ax, cx
        jmp     .store
.firsthalf:
        mov     cx, 128
        sub     cx, ax
        mul     cx
        shr     ax, 7
        add     ax, 32
.store: mov     [sintab + bx], al
        inc     bx
        cmp     bx, 256
        jb      .sb
        ret

; ============================================================================
;  setPalette - "electric" ramp built procedurally:
;       Blue  = i/4            (deep blue grows with intensity)
;       Green = clamp(i-100)   (cyan only in the brighter half)
;       Red   = clamp(i-150)   (whitens only at the hottest peaks)
;   -> dark navy lows, electric-blue mids, cyan ridges, white-hot crests.
;   Colour 255 is forced to white for the text.
; ============================================================================
setPalette:
        mov     dx, 0x3C8
        xor     al, al
        out     dx, al
        inc     dx                  ; 0x3C9 data port (writes R,G,B per index)
        xor     cx, cx
.pl:    mov     ax, cx              ; --- Red = clamp(i-150, 0..63) ---
        sub     ax, 150
        jns     .rpos
        xor     ax, ax
        jmp     .rout
.rpos:  cmp     ax, 63
        jbe     .rout
        mov     ax, 63
.rout:  out     dx, al
        mov     ax, cx              ; --- Green = clamp(i-100, 0..63) ---
        sub     ax, 100
        jns     .gpos
        xor     ax, ax
        jmp     .gout
.gpos:  cmp     ax, 63
        jbe     .gout
        mov     ax, 63
.gout:  out     dx, al
        mov     ax, cx              ; --- Blue = i/4 ---
        shr     ax, 2
        out     dx, al
        inc     cx
        cmp     cx, 256
        jb      .pl
        mov     dx, 0x3C8           ; colour 255 -> white
        mov     al, 255
        out     dx, al
        inc     dx
        mov     al, 63
        out     dx, al
        out     dx, al
        out     dx, al
        ret

; ============================================================================
;  drawPlasma - colour = sin(x+t) + sin(y+t) + sin(x+y+t2), half-res 2x2 blocks
; ============================================================================
drawPlasma:
        mov     ax, 0xA000
        mov     es, ax
        xor     di, di
        xor     bp, bp
.row:   mov     ax, bp
        add     al, [t2]
        mov     dh, al
        mov     ax, bp
        add     al, [t]
        xor     bh, bh
        mov     bl, al
        mov     al, [sintab + bx]
        mov     [rowval], al
        mov     dl, [t]
        mov     cx, 160
.col:   mov     bl, dl
        mov     al, [sintab + bx]
        mov     bl, dh
        add     al, [sintab + bx]
        add     al, [rowval]
        mov     ah, al
        mov     [es:di], ax
        mov     [es:di + 320], ax
        add     di, 2
        add     dl, 2
        add     dh, 2
        dec     cx
        jnz     .col
        add     di, 320
        add     bp, 2
        cmp     bp, 200
        jb      .row
        ret

; ============================================================================
;  drawScroll - 3x text welded to a travelling wave. The vertical position of
;               every screen column is sin(scrollX + x), so a given letter
;               (fixed scrollX+x) keeps its height on the curve and the whole
;               wavy ribbon of text slides ALONG the wave as scrollX advances.
; ============================================================================
drawScroll:
        mov     ax, 0xA000
        mov     es, ax
        mov     ax, [scrollX]       ; glyph column for the leftmost screen pixel
        xor     dx, dx
        div     word [msgWpix]
        mov     ax, dx
        xor     dx, dx
        div     word [scaleWord]
        mov     bp, ax              ; BP = glyph column index
        mov     [sc], dl
        xor     si, si              ; SI = screen x
.sx:    mov     ax, bp              ; glyph = MSG[gcol / 8]
        shr     ax, 3
        mov     bx, msg
        add     bx, ax
        mov     al, [bx]
        xor     ah, ah
        shl     ax, 3
        add     ax, fontbuf
        mov     [glyphptr], ax
        mov     ax, bp              ; mask = 0x80 >> (gcol & 7)
        and     ax, 7
        mov     cl, al
        mov     al, 0x80
        shr     al, cl
        mov     [mask], al
        mov     ax, [scrollX]       ; wave y = baseY + sin(scrollX + x)
        add     ax, si
        xor     bh, bh
        mov     bl, al
        mov     al, [sintab + bx]
        xor     ah, ah
        add     ax, [baseYadj]
        mov     bx, 320
        mul     bx
        add     ax, si
        mov     di, ax
        mov     bx, [glyphptr]
        mov     cx, 8
.vg:    mov     al, [bx]
        test    al, [mask]
        jz      .blank
        mov     ah, SCALE
.fill:  mov     byte [es:di], 255
        add     di, 320
        dec     ah
        jnz     .fill
        jmp     .vnext
.blank: add     di, [lineSkip]
.vnext: inc     bx
        dec     cx
        jnz     .vg
        inc     byte [sc]
        mov     al, [sc]
        cmp     al, SCALE
        jb      .nostep
        mov     byte [sc], 0
        inc     bp
        mov     ax, [msgWcol]
        cmp     bp, ax
        jb      .nostep
        sub     bp, ax
.nostep:
        inc     si
        cmp     si, 320
        jb      .sx
        ret

; ============================================================================
;  updateMusic - fast, busy techno pattern on the PC speaker (PIT channel 2)
; ============================================================================
updateMusic:
        dec     byte [musicTimer]
        jnz     .done
        mov     byte [musicTimer], NOTELEN
        mov     bx, [noteIdx]
        shl     bx, 1
        mov     ax, [melody + bx]
        inc     word [noteIdx]
        mov     cx, [noteIdx]
        cmp     cx, NUMNOTES
        jb      .idxok
        mov     word [noteIdx], 0
.idxok: cmp     ax, 0
        je      .rest
        push    ax
        mov     al, 0xB6
        out     0x43, al
        pop     ax
        out     0x42, al
        mov     al, ah
        out     0x42, al
        in      al, 0x61
        or      al, 3
        out     0x61, al
        ret
.rest:  in      al, 0x61
        and     al, 0xFC
        out     0x61, al
.done:  ret

; ============================================================================
;  Data
; ============================================================================
t           db  0
t2          db  0
scrollX     dw  0
baseYadj    dw  70
glyphptr    dw  0
mask        db  0
rowval      db  0
sc          db  0
musicTimer  db  1
noteIdx     dw  0

scaleWord   dw  SCALE
lineSkip    dw  320 * SCALE

; --- PIT divisors (1193180 / Hz): kick, bass stabs and high "hat" stabs ---
K           equ 18356               ; ~65 Hz  kick
A2          equ 10847               ; 110 Hz  bass
C3          equ 9108                ; 131 Hz
D3          equ 8117                ; 147 Hz
E3          equ 7231                ; 165 Hz
A4          equ 2712                ; 440 Hz  mid stab
A5          equ 1356                ; 880 Hz  high stab
; 32-step bar: kick on every beat, machine-gun bass/stab fills between
melody      dw  K, A5, A2, A5,  A2, A4, A2, A5
            dw  K, A5, C3, A5,  C3, A4, C3, A5
            dw  K, A5, A2, A5,  A2, A4, A2, A5
            dw  K, A5, E3, A5,  D3, A4, C3, A5
NUMNOTES    equ ($ - melody) / 2

msg         db  "Wolf2Shell, by Hypn      "
msgLEN      equ $ - msg
msgWcol     dw  msgLEN * 8
msgWpix     dw  msgLEN * 8 * SCALE

; --- runtime-generated tables (emitted in-file for save injection) ---
; Original used `equ` BSS past COM image. In a save blob we must include
; these bytes so the payload has space to write into.
sintab      resb 256
fontbuf     resb 1024
