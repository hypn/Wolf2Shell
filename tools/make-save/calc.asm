; ============================================================================
;  WOLF2CALC - Wolf3D savegame-injected on-screen calculator
; ----------------------------------------------------------------------------
;  Template placeholder replaced by make-save.py:
;    __PAYLOAD_ORG__  -> DGROUP-relative offset where this blob is placed
;
;  Build : nasm -f bin -o calc.bin calc.asm     (after replacing the org)
;  Inject: python3 tools/make-save/make-save.py --payload asm --asm calc.asm \
;                 --slot 3 --name "Calculator"
;
;  Entered by DoActor's far call to ob->state->think(ob): CS = DGROUP,
;  IP = __PAYLOAD_ORG__.  The payload never returns to the game; Esc quits to
;  DOS like the other payloads.
;
;  Keys:  numpad 0-9            -> digits
;         numpad + - * /        -> operators
;         top-row 0-9 + - * /   -> same (shift for + and *)
;         Enter or =            -> evaluate
;         Backspace             -> delete last digit
;         C                     -> clear
;         Esc                   -> exit to DOS
;
;  NOTE: arithmetic uses 32-bit integer instructions (EAX/imul/idiv).  That is
;  fine under DOSBox (which emulates a 386 core); a pure 286 would not run it.
; ============================================================================

bits 16
org __PAYLOAD_ORG__

; ----------------------------------------------------------------------------
;  Palette indices (default VGA mode-13h palette)
; ----------------------------------------------------------------------------
C_BG        equ 8                   ; screen background (dark grey)
C_PANEL     equ 7                   ; display bezel
C_DISPBG    equ 0                   ; display interior (black)
C_DISPTXT   equ 10                  ; display digits (bright green)
C_TITLE     equ 15                  ; title text
C_NUMKEY    equ 7                   ; digit key face
C_NUMTXT    equ 0                   ; digit key label
C_OPKEY     equ 1                   ; operator key face (blue)
C_OPTXT     equ 15
C_EQKEY     equ 2                   ; '=' key face (green)
C_EQTXT     equ 15
C_CLRKEY    equ 4                   ; 'C' key face (red)
C_CLRTXT    equ 15
C_HINT      equ 15                  ; hint line

; ----------------------------------------------------------------------------
;  Button geometry
; ----------------------------------------------------------------------------
BTN_W       equ 60
BTN_H       equ 24
BTN_X0      equ 37
BTN_Y0      equ 78
BTN_DX      equ 62
BTN_DY      equ 27
KB_SIZE     equ 16                  ; keyboard ring-buffer entries (power of 2)

; ============================================================================
;  Entry
; ============================================================================
start:
        cli
        push    cs
        pop     ds                  ; DS = DGROUP (code segment) for data refs
        cld
        sti

        mov     ax, 0x0013          ; VGA 320x200x256
        int     0x10

        push    cs
        pop     ds

        mov     ax, 0x1130          ; ROM 8x8 font pointer (ES:BP, chars 0-127)
        mov     bh, 0x03
        int     0x10
        push    cs
        pop     ds
        mov     [fontseg], es
        mov     [fontoff], bp

        call    install_isr         ; take over the keyboard interrupt
        call    init_state
        call    draw_ui

; ============================================================================
;  Main loop - block for a scancode, act on it, repaint the display
; ============================================================================
mainloop:
        push    cs
        pop     ds
        call    kb_get_block        ; AL = scancode (blocks)
        push    cs
        pop     ds
        call    dispatch
        push    cs
        pop     ds
        call    draw_display
        jmp     mainloop

; ============================================================================
;  Exit to DOS
; ============================================================================
exit_prog:
        call    restore_isr
        mov     ax, 0x0003
        int     0x10
        mov     ax, 0x4C00
        int     0x21

; ============================================================================
;  install_isr / restore_isr - swap INT 09h via the real-mode IVT.
;  Wolf3D's own handler reads port 60h and does not chain to the BIOS, so the
;  BIOS keyboard buffer (what INT 16h reads) is never filled while the game is
;  running.  We install our own handler and restore the game's on exit.
; ============================================================================
install_isr:
        cli
        xor     ax, ax
        mov     es, ax
        mov     ax, [es:0x24]       ; old INT 09h offset
        mov     [oldint9_off], ax
        mov     ax, [es:0x26]       ; old INT 09h segment
        mov     [oldint9_seg], ax
        mov     ax, int9
        mov     [es:0x24], ax
        mov     ax, cs
        mov     [es:0x26], ax
        sti
        ret

restore_isr:
        cli
        xor     ax, ax
        mov     es, ax
        mov     ax, [oldint9_seg]
        mov     [es:0x26], ax
        mov     ax, [oldint9_off]
        mov     [es:0x24], ax
        sti
        ret

; ============================================================================
;  int9 - keyboard ISR.  Buffers make-code scancodes, tracks shift, EOIs PIC.
; ============================================================================
int9:
        push    ax
        push    bx
        push    cx
        push    ds
        push    cs
        pop     ds
        in      al, 0x60
        cmp     al, 0xE0            ; extended-key prefix
        jne     .notE0
        mov     byte [e0flag], 1
        jmp     .eoi
.notE0:
        cmp     al, 0xE1            ; Pause key
        je      .eoi
        mov     ah, al
        and     ah, 0x7F
        test    al, 0x80
        jnz     .brk
        ; ---- make code ----
        cmp     byte [e0flag], 0
        je      .plain
        ; E0-prefixed.  The numeric keypad's Enter and '/' are extended keys
        ; (E0 1C / E0 35) and are the only extended scancodes we want; every
        ; other E0 key (arrows, Home/End/PgUp/PgDn/Ins/Del, right Ctrl/Alt,
        ; PrintScreen) reuses a scancode we would otherwise misread.
        mov     byte [e0flag], 0
        cmp     ah, 0x1C
        je      .store
        cmp     ah, 0x35
        je      .store
        jmp     .eoi
.plain:
        cmp     ah, 0x2A            ; left shift
        je      .shifton
        cmp     ah, 0x36            ; right shift
        je      .shifton
.store:
        mov     bx, [kbtail]
        mov     cx, [kbcount]
        cmp     cx, KB_SIZE
        jae     .eoi                ; drop when full
        mov     [kbbuf + bx], ah
        inc     bx
        and     bx, KB_SIZE - 1
        mov     [kbtail], bx
        inc     word [kbcount]
        jmp     .eoi
.shifton:
        mov     byte [shift], 1
        jmp     .eoi
        ; ---- break code ----
.brk:
        mov     byte [e0flag], 0
        cmp     ah, 0x2A
        je      .shiftoff
        cmp     ah, 0x36
        je      .shiftoff
        jmp     .eoi
.shiftoff:
        mov     byte [shift], 0
.eoi:
        mov     al, 0x20
        out     0x20, al            ; end-of-interrupt to the 8259
        pop     ds
        pop     cx
        pop     bx
        pop     ax
        iret

; ============================================================================
;  kb_get_block - wait for and return the next scancode in AL
; ============================================================================
kb_get_block:
        cli
        cmp     word [kbcount], 0
        jne     .have
        sti
        jmp     kb_get_block
.have:
        mov     bx, [kbhead]
        mov     al, [kbbuf + bx]
        inc     bx
        and     bx, KB_SIZE - 1
        mov     [kbhead], bx
        dec     word [kbcount]
        sti
        ret

; ============================================================================
;  init_state - reset the calculator to "0"
; ============================================================================
init_state:
        mov     dword [acc], 0
        mov     byte [op], 0
        mov     byte [fresh], 1
        mov     byte [errflag], 0
        mov     byte [curstr], '0'
        mov     byte [curstr + 1], 0
        ret

; ============================================================================
;  dispatch - turn a scancode in AL into a calculator action
; ============================================================================
dispatch:
        cmp     al, 0x0B            ; '0'
        je      .zero
        cmp     al, 0x09            ; '8' / '*' (shift)
        je      .eight
        cmp     al, 0x02
        jb      .other
        cmp     al, 0x0A
        ja      .other
        add     al, '0' - 1         ; 0x02..0x0A -> '1'..'9'
        jmp     .digit
.eight:
        test    byte [shift], 1
        jnz     .star
        mov     al, '8'
        jmp     .digit
.zero:
        mov     al, '0'
.digit:
        jmp     handle_digit
.other:
        cmp     al, 0x0C            ; top-row '-' / numpad '-'
        je      .minus
        cmp     al, 0x4A
        je      .minus
        cmp     al, 0x0D            ; top-row '=' / '+' (shift)
        je      .pluseq
        cmp     al, 0x35            ; numpad '/'
        je      .slash
        cmp     al, 0x37            ; numpad '*'
        je      .star
        cmp     al, 0x4E            ; numpad '+'
        je      .plus
        cmp     al, 0x1C            ; Enter
        je      .enter
        cmp     al, 0x0E            ; Backspace
        je      .bs
        cmp     al, 0x1B            ; Esc
        je      .quit
        cmp     al, 0x2E            ; 'c'
        je      .clear
        cmp     al, 0x47            ; numpad block 0x47..0x52
        jb      .done
        cmp     al, 0x52
        ja      .done
        mov     bx, nummap
        mov     ah, 0
        mov     cx, ax
        sub     cx, 0x47
        add     bx, cx
        mov     al, [bx]
        cmp     al, '0'
        jb      handle_op
        cmp     al, '9'
        ja      handle_op
        jmp     handle_digit
.star:
        mov     al, '*'
        jmp     handle_op
.slash:
        mov     al, '/'
        jmp     handle_op
.minus:
        mov     al, '-'
        jmp     handle_op
.plus:
        mov     al, '+'
        jmp     handle_op
.pluseq:
        test    byte [shift], 1
        jnz     .plus
.enter:
        jmp     handle_eq
.bs:
        jmp     handle_bs
.quit:
        jmp     exit_prog
.clear:
        jmp     handle_clear
.done:
        ret

; ============================================================================
;  handle_digit - append AL (ASCII digit) to the current entry
; ============================================================================
handle_digit:
        cmp     byte [fresh], 0
        je      .noreset
        mov     byte [curstr], '0'
        mov     byte [curstr + 1], 0
        mov     byte [fresh], 0
.noreset:
        mov     si, curstr
        xor     cx, cx
.find:
        cmp     byte [si], 0
        je      .end
        inc     si
        inc     cx
        jmp     .find
.end:
        cmp     cx, 9               ; keep entries inside 32-bit range
        jae     .full
        cmp     cx, 1
        jne     .append
        cmp     byte [curstr], '0'
        jne     .append
        mov     byte [curstr], al   ; replace a lone leading zero
        ret
.append:
        mov     [si], al
        mov     byte [si + 1], 0
.full:
        ret

; ============================================================================
;  handle_op - fold the entry into the accumulator, AL = operator
; ============================================================================
handle_op:
        mov     [newop], al
        mov     si, curstr
        call    atoi                ; EAX = current entry
        mov     ebx, eax
        mov     cl, [op]
        test    cl, cl
        jz      .first
        mov     eax, [acc]
        call    apply               ; EAX = acc (op) entry
        mov     [acc], eax
        cmp     byte [errflag], 0
        je      .setop
        mov     byte [op], 0
        mov     dword [acc], 0
        jmp     .show
.first:
        mov     [acc], ebx
.setop:
        mov     al, [newop]
        mov     [op], al
.show:
        call    show_acc
        mov     byte [fresh], 1
        ret

; ============================================================================
;  handle_eq - evaluate the pending operation and show the result
; ============================================================================
handle_eq:
        mov     si, curstr
        call    atoi
        mov     ebx, eax
        mov     cl, [op]
        test    cl, cl
        jz      .none
        mov     eax, [acc]
        call    apply
        mov     [acc], eax
        mov     byte [op], 0
        cmp     byte [errflag], 0
        je      .show
        mov     dword [acc], 0
.show:
        call    show_acc
        mov     byte [fresh], 1
        ret
.none:
        mov     [acc], ebx
        call    show_acc
        mov     byte [fresh], 1
        ret

; ============================================================================
;  handle_bs - delete the last digit
; ============================================================================
handle_bs:
        cmp     byte [fresh], 0
        jne     .done
        mov     si, curstr
        xor     cx, cx
.find:
        cmp     byte [si], 0
        je      .end
        inc     si
        inc     cx
        jmp     .find
.end:
        cmp     cx, 1
        jbe     .zero
        dec     si
        mov     byte [si], 0
        ret
.zero:
        mov     byte [curstr], '0'
        mov     byte [curstr + 1], 0
.done:
        ret

; ============================================================================
;  handle_clear - reset everything
; ============================================================================
handle_clear:
        mov     dword [acc], 0
        mov     byte [op], 0
        mov     byte [errflag], 0
        mov     byte [fresh], 1
        mov     byte [curstr], '0'
        mov     byte [curstr + 1], 0
        ret

; ============================================================================
;  show_acc - render [acc] (or an error) into curstr
; ============================================================================
show_acc:
        cmp     byte [errflag], 0
        je      .ok
        mov     si, errtxt
        mov     di, curstr
.cp:
        mov     al, [si]
        mov     [di], al
        inc     si
        inc     di
        test    al, al
        jnz     .cp
        mov     byte [errflag], 0
        ret
.ok:
        mov     eax, [acc]
        mov     di, curstr
        call    itoa
        ret

; ============================================================================
;  atoi - EAX = signed value of the ASCII string at SI
; ============================================================================
atoi:
        xor     eax, eax
        xor     cx, cx
        cmp     byte [si], '-'
        jne     .loop
        mov     cx, 1
        inc     si
.loop:
        xor     edx, edx
        mov     dl, [si]
        cmp     dl, '0'
        jb      .done
        cmp     dl, '9'
        ja      .done
        imul    eax, eax, 10
        sub     dl, '0'
        add     eax, edx
        inc     si
        jmp     .loop
.done:
        test    cx, cx
        jz      .out
        neg     eax
.out:
        ret

; ============================================================================
;  itoa - write signed EAX as decimal at DI (null-terminated)
; ============================================================================
itoa:
        test    eax, eax
        jns     .pos
        mov     byte [di], '-'
        inc     di
        neg     eax
.pos:
        mov     ebx, 10
        xor     cx, cx
.div:
        xor     edx, edx
        div     ebx
        add     dl, '0'
        push    dx
        inc     cx
        test    eax, eax
        jnz     .div
.pop:
        pop     dx
        mov     [di], dl
        inc     di
        loop    .pop
        mov     byte [di], 0
        ret

; ============================================================================
;  apply - EAX = EAX (CL op) EBX;  sets errflag on divide-by-zero
; ============================================================================
apply:
        cmp     cl, '+'
        je      .add
        cmp     cl, '-'
        je      .sub
        cmp     cl, '*'
        je      .mul
        cmp     cl, '/'
        je      .div
        ret
.add:
        add     eax, ebx
        ret
.sub:
        sub     eax, ebx
        ret
.mul:
        imul    eax, ebx
        ret
.div:
        test    ebx, ebx
        jz      .zero
        cdq
        idiv    ebx
        ret
.zero:
        mov     byte [errflag], 1
        ret

; ============================================================================
;  UI drawing
; ============================================================================

; --- draw_ui - paint the whole frame once -----------------------------------
draw_ui:
        ; background
        mov     word [cx_pos], 0
        mov     word [cy_pos], 0
        mov     word [cw], 320
        mov     word [boxh], 200
        mov     byte [curcolor], C_BG
        call    fillbox

        ; title
        mov     word [cx_pos], 88
        mov     word [cy_pos], 8
        mov     byte [curcolor], C_TITLE
        mov     word [curscale], 2
        mov     si, title
        call    drawStr

        ; display bezel
        mov     word [cx_pos], 14
        mov     word [cy_pos], 27
        mov     word [cw], 292
        mov     word [boxh], 42
        mov     byte [curcolor], C_PANEL
        call    fillbox

        ; buttons
        mov     si, buttons
.bloop:
        mov     al, [si]
        test    al, al
        jz      .bdone
        ; drop shadow
        mov     ax, [si + 3]
        add     ax, 3
        mov     [cx_pos], ax
        mov     ax, [si + 5]
        add     ax, 3
        mov     [cy_pos], ax
        mov     word [cw], BTN_W
        mov     word [boxh], BTN_H
        mov     byte [curcolor], 0
        call    fillbox
        ; key face
        mov     ax, [si + 3]
        mov     [cx_pos], ax
        mov     ax, [si + 5]
        mov     [cy_pos], ax
        mov     al, [si + 1]
        mov     [curcolor], al
        call    fillbox
        ; key label
        mov     ax, [si + 3]
        add     ax, 18
        mov     [cx_pos], ax
        mov     ax, [si + 5]
        mov     [cy_pos], ax
        mov     al, [si + 2]
        mov     [curcolor], al
        mov     word [curscale], 3
        mov     al, [si]
        mov     [curchar], al
        call    drawChar
        add     si, 7
        jmp     .bloop
.bdone:
        ; hint line
        mov     word [cx_pos], 12
        mov     word [cy_pos], 190
        mov     byte [curcolor], C_HINT
        mov     word [curscale], 1
        mov     si, hint
        call    drawStr

        call    draw_display
        ret

; --- draw_display - repaint the display interior and value -------------------
draw_display:
        mov     word [cx_pos], 16
        mov     word [cy_pos], 29
        mov     word [cw], 288
        mov     word [boxh], 38
        mov     byte [curcolor], C_DISPBG
        call    fillbox

        ; right-align the value
        mov     si, curstr
        xor     cx, cx
.len:
        cmp     byte [si], 0
        je      .got
        inc     si
        inc     cx
        jmp     .len
.got:
        mov     ax, cx
        mov     bx, [dispscale]
        shl     bx, 3
        mul     bx                  ; AX = len * 8 * scale
        mov     bx, 16 + 288
        sub     bx, ax
        sub     bx, 10
        mov     [cx_pos], bx
        mov     word [cy_pos], 36
        mov     byte [curcolor], C_DISPTXT
        mov     ax, [dispscale]
        mov     [curscale], ax
        mov     si, curstr
        call    drawStr
        ret

; --- drawStr - SI = string; advances [cx_pos] --------------------------------
drawStr:
        push    si
.next:
        mov     al, [si]
        test    al, al
        jz      .done
        inc     si
        mov     [curchar], al
        call    drawChar
        mov     ax, [curscale]
        shl     ax, 3
        add     [cx_pos], ax
        jmp     .next
.done:
        pop     si
        ret

; --- drawChar - [curchar] at ([cx_pos],[cy_pos]) scale [curscale] ------------
drawChar:
        push    si
        mov     al, [curchar]
        xor     ah, ah
        shl     ax, 3
        add     ax, [fontoff]
        mov     si, ax
        mov     es, [fontseg]
        mov     di, glyphbuf
        mov     cx, 8
.grab:
        mov     al, [es:si]
        mov     [di], al
        inc     si
        inc     di
        loop    .grab

        mov     si, glyphbuf
        mov     ax, 0xA000
        mov     es, ax
        xor     cx, cx              ; row
.row:
        mov     ax, [curscale]
        mov     bl, cl
        xor     bh, bh
        mul     bx                  ; AX = scale * row
        add     ax, [cy_pos]
        mov     dx, 320
        mul     dx
        add     ax, [cx_pos]
        mov     di, ax
        mov     al, [si]
        inc     si
        mov     [rowbits], al
        mov     bx, 8
.bit:
        shl     byte [rowbits], 1
        jnc     .skip
        call    putblk
.skip:
        mov     ax, [curscale]
        add     di, ax
        dec     bx
        jnz     .bit
        inc     cx
        cmp     cx, 8
        jb      .row
        pop     si
        ret

; --- putblk - scale x scale block at ES:DI (ES = A000) -----------------------
putblk:
        push    di
        push    cx
        push    bx
        mov     ax, [curscale]
        mov     [blkw], ax
        xor     cx, cx
.prow:
        push    di
        mov     bx, [blkw]
        mov     al, [curcolor]
.pcol:
        mov     [es:di], al
        inc     di
        dec     bx
        jnz     .pcol
        pop     di
        add     di, 320
        inc     cx
        cmp     cx, [blkw]
        jb      .prow
        pop     bx
        pop     cx
        pop     di
        ret

; --- fillbox - ([cx_pos],[cy_pos]) size [cw] x [ch] colour [curcolor] --------
fillbox:
        cld
        mov     ax, [cy_pos]
        mov     bx, 320
        mul     bx
        add     ax, [cx_pos]
        mov     di, ax
        mov     ax, 0xA000
        mov     es, ax
        mov     dx, [boxh]
        mov     al, [curcolor]
        mov     ah, al
.row:
        push    di
        mov     cx, [cw]
        mov     bx, cx
        shr     cx, 1
        rep     stosw
        test    bx, 1
        jz      .even
        stosb
.even:
        pop     di
        add     di, 320
        dec     dx
        jnz     .row
        ret

; ============================================================================
;  Data
; ============================================================================
fontseg     dw  0
fontoff     dw  0
oldint9_off dw  0
oldint9_seg dw  0
cx_pos      dw  0
cy_pos      dw  0
cw          dw  0
boxh        dw  0
blkw        dw  0
curchar     db  0
curcolor    db  0
curscale    dw  1
rowbits     db  0
glyphbuf    times 8 db 0

acc         dd  0
op          db  0
newop       db  0
fresh       db  1
errflag     db  0
shift       db  0
e0flag      db  0
curstr      times 16 db 0
dispscale   dw  3

kbhead      dw  0
kbtail      dw  0
kbcount     dw  0
kbbuf       times KB_SIZE db 0

title       db  "WOLF2CALC", 0
hint        db  "0-9  + - * /  ENTER=  C=CLR  ESC=QUIT", 0
errtxt      db  "DIV BY 0", 0

; numpad scancodes 0x47..0x52 -> digits / operators
nummap      db  '7','8','9','-','4','5','6','+','1','2','3','0'

; ============================================================================
;  Button table: char, face colour, label colour, x, y  (7 bytes each)
; ============================================================================
%macro BTN 5
        db  %1, %2, %3
        dw  BTN_X0 + (%4) * BTN_DX, BTN_Y0 + (%5) * BTN_DY
%endmacro

buttons:
        BTN '7', C_NUMKEY, C_NUMTXT, 0, 0
        BTN '8', C_NUMKEY, C_NUMTXT, 1, 0
        BTN '9', C_NUMKEY, C_NUMTXT, 2, 0
        BTN '/', C_OPKEY,  C_OPTXT,  3, 0
        BTN '4', C_NUMKEY, C_NUMTXT, 0, 1
        BTN '5', C_NUMKEY, C_NUMTXT, 1, 1
        BTN '6', C_NUMKEY, C_NUMTXT, 2, 1
        BTN '*', C_OPKEY,  C_OPTXT,  3, 1
        BTN '1', C_NUMKEY, C_NUMTXT, 0, 2
        BTN '2', C_NUMKEY, C_NUMTXT, 1, 2
        BTN '3', C_NUMKEY, C_NUMTXT, 2, 2
        BTN '-', C_OPKEY,  C_OPTXT,  3, 2
        BTN '0', C_NUMKEY, C_NUMTXT, 0, 3
        BTN 'C', C_CLRKEY, C_CLRTXT, 1, 3
        BTN '=', C_EQKEY,  C_EQTXT,  2, 3
        BTN '+', C_OPKEY,  C_OPTXT,  3, 3
        db  0
