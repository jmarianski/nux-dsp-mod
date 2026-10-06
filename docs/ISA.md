# NEK-100 DSP control CPU — instruction set (reverse engineered)

The DSP of the NUX NEK-100 is a Dream SAM5xxx chip. Its control CPU runs a 16-bit, word-addressed
instruction set similar to Dream's "P16". There is no public documentation; everything below was
inferred from the firmware and, where marked **C**, confirmed by running patched code on the instrument.

- **C** — confirmed on hardware (a patch using exactly this form behaved as predicted)
- **H** — hypothesis from code context (consistent everywhere, never tested in isolation)

Words that `isa.py` does not recognise are kept as `.dw`, so `disasm → asm` is always byte-identical
whatever the gaps in this table.

## Registers and memory

`r0`…`r7`, a frame pointer `fp`, word addresses for code and data. Functions return their result in `r0`.
Initialised RAM data is copied from the file (see `ramdata` in the map) to RAM address 0 at boot, so a RAM
variable `X` lives at file word `ramdata_start + X`.

## Instructions known to the assembler

| Syntax | Encoding | Notes | |
|---|---|---|---|
| `mov rD, #imm8` | `0Dii` | | C |
| `cmp rD, #imm8` | `0(D+8)ii` | sets flags for `beq/bne/blt` | C |
| `add rD, #imm8` | `1Dii` | imm8 is **zero-extended** (C: `add r, #-5` adds 251); to subtract, `li` the 16-bit value into a register and `add rD, rS` | C |
| `and rD, #imm8` | `1(D+8)ii` | | C |
| `mov rD, rS` | `8D0S` | | C |
| `cmp rD, rS` | `8(D+8)0S` | | C |
| `add rD, rS` | `9D0S` | | C |
| `and rD, rS` | `9(D+8)0S` | | C |
| `or rD, rS` | `aD0S` | | C |
| `shl rN, k` / `shr rN, k` | `fN9k` / `fNdk` | k = 1..15 (`fN90` is `st [abs]`); shr is logical | C |
| `ldc rR, [r1+k]` | `dR9k` | read **program memory** (tables, patch data), k = 0..15 | C |
| `ld rR, [r1+k]` / `st [r1+k], rR` | `cR9k` / `c(R+8)9k` | k = 0..15 | C |
| `ld rR, [fp+k]` / `st [fp+k], rR` | `cRbk` / `c(R+8)bk` | function arguments / locals | C |
| `ld rR, [abs]` / `st [abs], rR` | `fR80 a` / `fR90 a` | two words | C |
| `li rR, #imm16` | `dR48 i` | | C |
| `addi rR, #imm16` | `dR4a i` | | C |
| `push rN` | `7e0N` | | H |
| `push #imm16` | `c14c i` | argument for `ccall` | C |
| `call target` | `d6c8 a` | plain call, frame (`fp`) preserved — ideal for hooks inside a function | C |
| `ccall target` | `d7c8 a` | call of a C-style function, arguments pushed before, callee pops them | C |
| `ret` | `d1ca` | return from a `call` | C |
| `jmp rel8` | `78rr` | target = pc + 1 + rel | C |
| `blt / beq / bne rel8` | `e1rr / e2rr / e3rr` | after `cmp`; target = pc + 1 + rel | C |
| `b.e0 rel8` | `e0rr` | conditional, condition unknown | H |
| `lbN rel16` | `fNe7 r` | long branch, condition N unknown; target = pc + 2 + rel | H |

## Seen but not modelled (shown as `.dw` with a hint)

| Word | Guess |
|---|---|
| `7d0e` | function prologue |
| `c04c n` | prologue with n words of locals |
| `d5cN` | epilogue: return and drop N argument words |
| `d0ce a` | branch/jump with 16-bit target |
| `b7kk` / `bfkk` | skip kk words if r7 is zero / not zero (H) |
| `830d 2b0N` | recompute fp after a call (`ccall` clobbers it) |
| `fXf1 …` | possibly a three-word form with a 32-bit address; the length rule counts it as one word, which can misalign a few lines of the listing locally (the round trip stays exact) |

## Writing hook code

A hook replaces a few words inside an existing function with a `call` into your own code in the pool.
Because `call` keeps `fp`, your code sees the same `[fp+k]` as the hooked function. Your code must:

1. redo whatever the replaced instructions did (the `expect` words), and
2. leave registers and flags the way the following original code needs them.

Look at the generated listing around the hook site (`nuxdsp disasm`) before choosing which words to replace.
