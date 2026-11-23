org 100h
start:
    mov ax, cs
    mov di, hexbuf
    mov cl, 4
.hexloop:
    rol ax, 4
    mov bl, al
    and bl, 0x0F
    mov bh, 0
    mov dl, [hexdigits+bx]
    mov [di], dl
    inc di
    dec cl
    jnz .hexloop

    mov ah, 0x3C        ; create file
    xor cx, cx
    mov dx, fname
    int 0x21
    jc done
    mov bx, ax          ; file handle

    mov ah, 0x40        ; write
    mov cx, 6
    mov dx, hexbuf
    int 0x21

    mov ah, 0x3E        ; close
    int 0x21

done:
    mov ax, 0x4C00
    int 0x21

hexdigits db '0123456789ABCDEF'
fname     db 'PROBE.TXT',0
hexbuf    db '0000',0x0D,0x0A
