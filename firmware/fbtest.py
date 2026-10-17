#!/usr/bin/env python3
"""Generate fb_test.patch: far data, a game loop in the tick and timings, in one build.

VOL+ / VOL- on the main screen starts (and the next press stops) the test:

1. Far data. The 128x64 test card (splash.py) lives above 0xffff and is copied to the framebuffer with the
   firmware's own program-memory copy routine 0x7638, word for word as init_all calls it (0x4928: li32 of a
   program pointer, through the stack frame, ld32 + fix32 into L2 = source, L1 = RAM address : x9, r7 = count).
   The card shows for 3 s: if it looks right, far data reads work. (The first try loaded r4:r5 = bank:address
   with plain li's and no fix32: the card stayed blank and so did the font copied the same way.)
   The font and the number tables do not depend on it: far code writes them into RAM as immediates.
2. Benchmarks, once, then the game loop. 100 frames rendered back to back (R) and 100 forced LCD refreshes (L),
   timed in timer interrupts (RAM 0x295b, counted while the main loop waits for us).
3. Game loop: every FRAME_TICKS ticks (50 ms) a whole frame is rendered into the framebuffer: cleared, a sweeping
   line, a bouncing 8x8 box and five numbers:
       S  seconds counted in ticks (compare with a stopwatch: do ticks keep real time while we draw?)
       D  main loop clock (RAM 0x6d78, low word) per 100 ticks: its unit, if ticks keep time
       R  timer interrupts during 100 frames rendered back to back
       L  timer interrupts during 100 refreshes of the whole LCD (8 pages)
       K  RAM 0x295a, clock units per interrupt (D / K = interrupts per second)

Code that calls the firmware stays in bank 0; the renderer is far code and calls nothing (far code here is
leaf only, as in nek100-mod's battery_percent and extra_menu). RAM 0x6500..0x6560 (unused after init_all).

Usage: python3 firmware/fbtest.py [OUT.patch]
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import splash  # noqa: E402

# 3x5 glyphs, rows top to bottom
FONT_ROWS = {
    "0": ["###", "#.#", "#.#", "#.#", "###"], "1": [".#.", "##.", ".#.", ".#.", "###"],
    "2": ["###", "..#", "###", "#..", "###"], "3": ["###", "..#", "###", "..#", "###"],
    "4": ["#.#", "#.#", "###", "..#", "..#"], "5": ["###", "#..", "###", "..#", "###"],
    "6": ["###", "#..", "###", "#.#", "###"], "7": ["###", "..#", "..#", ".#.", ".#."],
    "8": ["###", "#.#", "###", "#.#", "###"], "9": ["###", "#.#", "###", "..#", "###"],
    "S": [".##", "#..", ".#.", "..#", "##."], "D": ["##.", "#.#", "#.#", "#.#", "##."],
    "R": ["##.", "#.#", "##.", "#.#", "#.#"], "L": ["#..", "#..", "#..", "#..", "###"],
    "K": ["#.#", "#.#", "##.", "#.#", "#.#"],
}
GLYPHS = "0123456789SDRLK"
LINES = [("S", "dp_sec"), ("D", "dp_d"), ("R", "dp_b"), ("L", "dp_l"), ("K", "SCALE")]
DIVS = [10000, 1000, 100, 10, 1]

RAM = dict(dp_on=0x6500, dp_t=0x6501, dp_tk=0x6502, dp_sec=0x6503, dp_c0=0x6504, dp_d=0x6505, dp_b=0x6506,
           dp_l=0x6507, dp_n=0x6508, dp_x=0x6509, dp_dx=0x650a, dp_y=0x650b, dp_dy=0x650c, dp_lx=0x650d,
           dp_i=0x650e, dp_k=0x650f, dp_v=0x6510, dp_ad=0x6511, dp_fr=0x6512,
           dp_tab=0x6514, dp_div=0x651e, dp_fnt=0x6530)  # written by dp_init: tab 10, div 10, font 45 -> ..0x655c
CLOCK = 0x6d78  # low word of the main loop's 32-bit clock: += IRQ counts * [0x295a] each pass (0x7c9b)
IRQS = 0x295b   # low word of the timer interrupt count; the main loop takes it and clears it (0x7c79)
SCALE = 0x295a  # the multiplier above (not a counter: the first build's D/R/L read it and showed 0)
DP_MAGIC = 0x600D
FRAME_TICKS = 5  # 20 frames/s


def address(var):
    return RAM[var] if var in RAM else globals()[var]


def font_words():
    out = []
    for g in GLYPHS:
        rows = FONT_ROWS[g]
        out += [sum((rows[y][c] == "#") << y for y in range(5)) for c in range(3)]
    return out


def table_words():
    tab = []
    for letter, var in LINES:
        tab += [GLYPHS.index(letter), address(var)]
    div = []
    for d in DIVS:
        div += [d, (-d) & 0xFFFF]
    return tab, div


def dw(ws, indent="    "):
    return "\n".join(indent + ".dw " + ", ".join("0x%04x" % w for w in ws[i:i + 8]) for i in range(0, len(ws), 8))


def unrolled_or(mask_reg):
    return "\n".join("    ld    r7, [r1+%d]\n    or    r7, %s\n    st    [r1+%d], r7" % (k, mask_reg, k)
                     for k in range(8))


def patch():
    card = []
    for w in splash.pack(splash.test_card()):
        card += [w & 0xFF, w >> 8]
    tab, div = table_words()
    pad = RAM["dp_fnt"] - RAM["dp_tab"] - len(tab) - len(div)
    assert pad >= 0 and RAM["dp_div"] == RAM["dp_tab"] + len(tab)
    data = tab + div + [0] * pad + font_words()
    init = "\n".join("    %s r7, #%#06x\n    st    [%#06x], r7" % ("mov  " if v < 0x100 else "li   ", v, RAM["dp_tab"] + i)
                     for i, v in enumerate(data) if i < len(tab) + len(div) or i >= len(tab) + len(div) + pad)
    equs = "\n".join(".equ %s, %#06x" % kv for kv in list(RAM.items()) + [("DP_MAGIC", DP_MAGIC)])
    line_down = "\n".join("    add   r1, #128\n    st    [r1+0], r6" for _ in range(7))
    return f""".patch fb_test
.title "doom-piano: VOL+/VOL- on the main screen starts/stops a framebuffer test (far data, game loop, timings)"
; Generated by doom-piano/firmware/fbtest.py, do not edit by hand. Our own code and data only.

.hook 0x03fce expect 0xd7c8 0x54a8     ; volume handler, op 0, main screen: ccall of the VOL redraw
    call  dp_vol
.end
.hook 0x007ea expect 0xd7c8 0x4e75     ; tick_10ms: ccall lcd_refresh (sends the framebuffer when flagged)
    call  dp_tick
.end

.code
{equs}

dp_vol:                                 ; start (card, then the loop) or stop
    ld    r7, [dp_on]                   ; on only while it holds DP_MAGIC: after init_all this RAM holds leftovers
    li    r6, #DP_MAGIC                 ; of the ramdata copy (0x6b here), which crashed the first build at power-on
    cmp   r7, r6
    bne   .start
    mov   r7, #0
    st    [dp_on], r7
    ret
.start:
    st    [dp_on], r6
    mov   r7, #0
    st    [dp_t], r7
    st    [dp_tk], r7
    st    [dp_sec], r7
    st    [dp_d], r7
    st    [dp_b], r7
    st    [dp_l], r7
    st    [dp_lx], r7
    st    [dp_fr], r7
    mov   r7, #40
    st    [dp_x], r7
    mov   r7, #20
    st    [dp_y], r7
    mov   r7, #1
    st    [dp_dx], r7
    st    [dp_dy], r7
    call  dp_init                       ; table, divisors and font: far code storing immediates (known to work)
    ccall dp_cpcard                     ; the card: far data through the firmware's copy routine (the test);
                                        ; ccall: enter/ret_pop functions are always ccall'ed (919 of 919)
    ld    r7, [0x6a50]                  ; bit 0: the tick sends the framebuffer to the LCD
    mov   r6, #1
    or    r7, r6
    st    [0x6a50], r7
    ret

dp_cpcard:                              ; 1024 words dp_card -> framebuffer, word for word as init_all's 0x4928
    .dw   0xc04c, 0x0004                ; enter #4
    .dw   0xf8d0 | (dp_card >> 16), dp_card & 0xffff  ; li32 L0, program pointer (0x4928: f8d1 2cf7)
    .dw   0xd3c8, 0xffff                ; st [fp-1], r0
    .dw   0xd3c9, 0xfffe                ; st [fp-2], r1
    li    r0, #framebuffer
    .dw   0x8109                        ; mov r1, x9
    li    r7, #1024
    .dw   0xfae2, 0xfffe                ; ld32 L2, [fp-2]
    .dw   0xfaf7                        ; fix32 L2: source
    .dw   0xf148                        ; mov32 L1, L0: destination r2 = RAM address, r3 = x9
    call  0x7638
    .dw   0xd5c8                        ; ret_pop #0

dp_tick:                                ; in place of tick_10ms's ccall lcd_refresh
    ld    r7, [dp_on]
    li    r6, #DP_MAGIC
    cmp   r7, r6
    bne   .refresh
    ld    r7, [dp_t]
    add   r7, #1
    st    [dp_t], r7
    li    r6, #300                      ; the card stays 3 s
    cmp   r7, r6
    blt   .refresh
    bne   .run
    call  dp_bench                      ; once
.run:
    ld    r7, [dp_tk]
    add   r7, #1
    st    [dp_tk], r7
    cmp   r7, #100
    blt   .draw
    mov   r7, #0
    st    [dp_tk], r7
    ld    r7, [dp_sec]
    add   r7, #1
    st    [dp_sec], r7
    ld    r7, [{CLOCK:#06x}]
    ld    r6, [dp_c0]
    st    [dp_c0], r7
    .dw   0xaf06                        ; sub r7, r6
    st    [dp_d], r7
.draw:
    ld    r7, [dp_fr]                   ; a frame every FRAME_TICKS ticks: at 100 fps the STN LCD shows a pale smear
    add   r7, #1
    st    [dp_fr], r7
    cmp   r7, #{FRAME_TICKS}
    blt   .refresh
    mov   r7, #0
    st    [dp_fr], r7
    call  dp_frame
.refresh:
    ccall 0x4e75
    ret

dp_bench:                               ; R: 100 frames back to back, L: 100 refreshes of the whole LCD
    ld    r7, [{IRQS:#06x}]
    st    [dp_c0], r7
    mov   r7, #100
    st    [dp_n], r7
.r:
    call  dp_frame
    ld    r7, [dp_n]
    li    r6, #0xffff
    add   r7, r6
    st    [dp_n], r7
    cmp   r7, #0
    bne   .r
    ld    r7, [{IRQS:#06x}]
    ld    r6, [dp_c0]
    .dw   0xaf06                        ; sub r7, r6
    st    [dp_b], r7
    ld    r7, [{IRQS:#06x}]
    st    [dp_c0], r7
    mov   r7, #100
    st    [dp_n], r7
.l:
    ld    r7, [0x6a50]
    mov   r6, #1
    or    r7, r6
    st    [0x6a50], r7
    ccall 0x4e75
    ld    r7, [dp_n]
    li    r6, #0xffff
    add   r7, r6
    st    [dp_n], r7
    cmp   r7, #0
    bne   .l
    ld    r7, [{IRQS:#06x}]
    ld    r6, [dp_c0]
    .dw   0xaf06                        ; sub r7, r6
    st    [dp_l], r7
    ld    r7, [{CLOCK:#06x}]
    st    [dp_c0], r7
    ret
.end

.code 0x1a280
; far, leaf (calls nothing): one whole frame into the framebuffer, then the refresh flag
dp_frame:
    li    r1, #framebuffer
    li    r6, #(framebuffer + 1024)
    mov   r7, #0
.clr:
    st    [r1+0], r7
    st    [r1+1], r7
    st    [r1+2], r7
    st    [r1+3], r7
    add   r1, #4
    cmp   r1, r6
    bne   .clr
    ld    r7, [dp_lx]                   ; a vertical line sweeping the screen
    add   r7, #1
    and   r7, #127
    st    [dp_lx], r7
    li    r1, #framebuffer
    add   r1, r7
    mov   r6, #0xff
    st    [r1+0], r6
{line_down}
    ld    r7, [dp_x]                    ; the box bounces in x 32..120, y 0..56
    ld    r6, [dp_dx]
    add   r7, r6
    st    [dp_x], r7
    cmp   r7, #120                      ; bounce and clamp: the box is drawn at fb + page*128 + x, so x and y
    blt   .x1                           ; must stay in range whatever the RAM held (the first build wrote far
    li    r6, #0xffff                   ; outside the framebuffer from power-on leftovers and crashed)
    st    [dp_dx], r6
    mov   r7, #120
    st    [dp_x], r7
.x1:
    cmp   r7, #33
    blt   .x2
    jmp   .x3
.x2:
    mov   r6, #1
    st    [dp_dx], r6
    mov   r7, #32
    st    [dp_x], r7
.x3:
    ld    r7, [dp_y]
    ld    r6, [dp_dy]
    add   r7, r6
    st    [dp_y], r7
    cmp   r7, #56
    blt   .y1
    li    r6, #0xffff
    st    [dp_dy], r6
    mov   r7, #56
    st    [dp_y], r7
.y1:
    cmp   r7, #1
    blt   .y2
    jmp   .y3
.y2:
    mov   r6, #1
    st    [dp_dy], r6
    mov   r7, #0
    st    [dp_y], r7
.y3:
    mov   r6, r7                        ; r6 = y & 7, r7 = page
    and   r6, #7
    shr   r7, 3
    mov   r5, #0xff                     ; r5 = rows in this page, r4 = rows in the next one
    mov   r4, #0xff
    mov   r2, #0
.m:
    cmp   r2, r6
    blt   .ms
    shr   r4, 1
    jmp   .mn
.ms:
    shl   r5, 1
.mn:
    add   r2, #1
    cmp   r2, #8
    bne   .m
    and   r5, #0xff
    shl   r7, 7
    li    r1, #framebuffer
    add   r1, r7
    ld    r7, [dp_x]
    add   r1, r7
{unrolled_or("r5")}
    cmp   r4, #0
    beq   .nohi
    add   r1, #128
{unrolled_or("r4")}
.nohi:
    mov   r7, #0                        ; the numbers: line i in page i, a letter and 5 digits
    st    [dp_i], r7
.line:
    ld    r7, [dp_i]
    shl   r7, 7
    li    r6, #framebuffer
    add   r7, r6
    st    [dp_ad], r7
    ld    r7, [dp_i]
    shl   r7, 1
    li    r1, #dp_tab
    add   r1, r7
    ld    r6, [r1+0]                    ; the letter
    ld    r1, [r1+1]                    ; the variable
    ld    r7, [r1+0]
    st    [dp_v], r7
    mov   r7, #0
    st    [dp_k], r7
    mov   r7, r6
.glyph:                                 ; glyph r7 at dp_ad (rows 1..5 of the page), then a blank column
    mov   r6, r7
    shl   r6, 1
    add   r6, r7
    li    r1, #dp_fnt
    add   r1, r6
    ld    r5, [r1+0]
    ld    r4, [r1+1]
    ld    r3, [r1+2]
    shl   r5, 1
    shl   r4, 1
    shl   r3, 1
    ld    r1, [dp_ad]
    st    [r1+0], r5
    st    [r1+1], r4
    st    [r1+2], r3
    mov   r7, #0
    st    [r1+3], r7
    add   r1, #4
    st    [dp_ad], r1
    ld    r7, [dp_k]                    ; next digit: divisor pairs (d, -d)
    cmp   r7, #5
    beq   .lnext
    mov   r6, r7
    shl   r6, 1
    li    r1, #dp_div
    add   r1, r6
    add   r7, #1
    st    [dp_k], r7
    ld    r6, [r1+0]
    ld    r4, [r1+1]
    ld    r5, [dp_v]
    mov   r7, #0
.dv:
    cmp   r7, #9                        ; at most 9 per digit, whatever the RAM holds
    beq   .dd
    cmp   r5, r6
    blt   .dd
    add   r5, r4
    add   r7, #1
    jmp   .dv
.dd:
    st    [dp_v], r5
    jmp   .glyph
.lnext:
    ld    r7, [dp_i]
    add   r7, #1
    st    [dp_i], r7
    cmp   r7, #{len(LINES)}
    bne   .line
    ld    r7, [0x6a50]
    mov   r6, #1
    or    r7, r6
    st    [0x6a50], r7
    ret
dp_init:                                ; far, leaf: line table, divisor pairs and font into RAM dp_tab..
{init}
    ret
dp_card:
{dw(card)}
.end
"""


def main(out):
    open(out, "w").write(patch())
    print("wrote", out)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "fb_test.patch"))
