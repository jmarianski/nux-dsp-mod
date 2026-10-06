"""Tiny simulator for patch code (only the instruction forms in isa.py, under our ISA model).

It checks the *logic* of new code against a fake frame and RAM; it says nothing about whether the
ISA model itself is right — that is what hardware tests are for. Assumptions: cmp compares signed
16-bit values, imm8 is zero-extended (C: octave -2 test showed garbage with sign extension), shr is logical, `call` returns to the next instruction.
"""
from . import isa


class SimError(Exception):
    pass


def s16(v):
    v &= 0xFFFF
    return v - 0x10000 if v & 0x8000 else v


class Sim:
    def __init__(self, code_words, ram=None, fp=0x7000):
        self.code = code_words          # program memory (the image words)
        self.ram = dict(ram or {})      # data memory
        self.r = [0] * 8
        self.fp = fp
        self.flags = 0                  # result of last cmp: <0, 0, >0
        self.steps = 0

    def rd(self, a):
        return self.ram.get(a & 0xFFFF, 0)

    def wr(self, a, v):
        self.ram[a & 0xFFFF] = v & 0xFFFF

    def call(self, addr, max_steps=200000):
        """Run from addr until the matching ret. Returns the number of steps."""
        stack, pc = [None], addr
        while True:
            self.steps += 1
            if self.steps > max_steps:
                raise SimError("step limit (loop?) at %#x" % pc)
            x = self.code[pc]
            lit = self.code[pc + 1] if isa.is_two_words(x) else None
            d = isa.decode(x, lit)
            if d is None:
                raise SimError("unknown instruction %04x at %#x" % (x, pc))
            op, a = d
            nxt = pc + (2 if lit is not None else 1)
            r = self.r
            if op == "ret":
                pc = stack.pop()
                if pc is None:
                    return self.steps
                continue
            if op in ("mov", "cmp", "add", "and", "or"):
                dst, src = a
                v = r[src[1]] if isinstance(src, tuple) else (src & 0xFF)
                if op == "mov":
                    r[dst] = v & 0xFFFF
                elif op == "cmp":
                    self.flags = (s16(r[dst]) > s16(v)) - (s16(r[dst]) < s16(v))
                elif op == "add":
                    r[dst] = (r[dst] + v) & 0xFFFF
                elif op == "and":
                    r[dst] = r[dst] & v & 0xFFFF
                else:
                    r[dst] = (r[dst] | v) & 0xFFFF
            elif op == "shl":
                r[a[0]] = (r[a[0]] << a[1]) & 0xFFFF
            elif op == "shr":
                r[a[0]] = (r[a[0]] & 0xFFFF) >> a[1]
            elif op == "ldc":
                r[a[0]] = self.code[(r[1] + a[1]) & 0xFFFF]
            elif op in ("ld", "st"):
                reg, m = a
                ea = {"abs": 0, "r1": r[1], "fp": self.fp}[m[0]] + m[1]
                if op == "ld":
                    r[reg] = self.rd(ea)
                else:
                    self.wr(ea, r[reg])
            elif op == "li":
                r[a[0]] = a[1]
            elif op == "addi":
                r[a[0]] = (r[a[0]] + a[1]) & 0xFFFF
            elif op in ("jmp", "beq", "bne", "blt"):
                taken = {"jmp": True, "beq": self.flags == 0, "bne": self.flags != 0,
                         "blt": self.flags < 0}[op]
                if taken:
                    nxt = pc + 1 + a[0][1]
            elif op == "call":
                stack.append(nxt)
                nxt = a[0][1]
            else:
                raise SimError("%s not simulated (at %#x)" % (op, pc))
            pc = nxt
