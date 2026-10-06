"""Two-pass assembler for the NEK-100 DSP ISA (see isa.py, docs/ISA.md).

Syntax (one statement per line, `;` starts a comment):
    label:
    .org  EXPR                 set location counter (word address)
    .equ  NAME, EXPR           define a constant / RAM variable name
    .dw   EXPR[, EXPR...]      raw words
    OP    OPERANDS             e.g.  ld r7, [r1+5]   ldc r7, [r1+0] (program memory)   st [touch], r7   mov r7, #0x7f   call load_user_preset

Operands: rN | #EXPR | [r1+EXPR] | [fp+EXPR] | [EXPR] | EXPR (branch/call target).
EXPR: numbers, symbols, + - * & | << >> and parentheses.
"""
import ast
import re

from . import isa

REG = re.compile(r"^r([0-7])$")
LABEL = re.compile(r"^([A-Za-z_.][\w.]*):$")


class AsmError(Exception):
    pass


def eval_expr(text, symbols):
    try:
        tree = ast.parse(text.strip(), mode="eval").body
    except SyntaxError:
        raise AsmError("bad expression %r" % text)

    def ev(n):
        if isinstance(n, ast.Constant) and isinstance(n.value, int):
            return n.value
        if isinstance(n, ast.Name):
            if n.id not in symbols:
                raise AsmError("unknown symbol %r" % n.id)
            return symbols[n.id]
        if isinstance(n, ast.Attribute):  # local labels: patch.label
            name = dotted(n)
            if name not in symbols:
                raise AsmError("unknown symbol %r" % name)
            return symbols[name]
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.USub):
            return -ev(n.operand)
        if isinstance(n, ast.BinOp):
            ops = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b, ast.Mult: lambda a, b: a * b,
                   ast.BitAnd: lambda a, b: a & b, ast.BitOr: lambda a, b: a | b,
                   ast.LShift: lambda a, b: a << b, ast.RShift: lambda a, b: a >> b}
            if type(n.op) in ops:
                return ops[type(n.op)](ev(n.left), ev(n.right))
        raise AsmError("unsupported expression %r" % text)

    return ev(tree)


def dotted(n):
    return dotted(n.value) + "." + n.attr if isinstance(n, ast.Attribute) else n.id


def split_operands(text):
    out, depth, cur = [], 0, ""
    for ch in text:
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out


def parse_statement(line):
    """-> ('label', name) | ('org', expr) | ('dw', [exprs]) | ('op', op, operand_text) | None"""
    line = line.split(";", 1)[0].strip()
    if not line:
        return None
    m = LABEL.match(line)
    if m:
        return ("label", m.group(1))
    parts = line.split(None, 1)
    op, rest = parts[0].lower(), (parts[1] if len(parts) > 1 else "")
    if op == ".org":
        return ("org", rest)
    if op == ".equ":
        name, _, expr = rest.partition(",")
        return ("equ", name.strip(), expr)
    if op == ".dw":
        return ("dw", split_operands(rest))
    return ("op", op, rest)


def stmt_size(st):
    if st[0] == "dw":
        return len(st[1])
    if st[0] == "op":
        return isa.size_of(st[1], st[2])
    return 0


def operand(text, symbols):
    text = text.strip()
    m = REG.match(text)
    if m:
        return ("reg", int(m.group(1)))
    if text.startswith("#"):
        return ("imm", eval_expr(text[1:], symbols))
    if text.startswith("["):
        inner = text[1:-1].replace(" ", "")
        for base in ("r1", "fp"):
            if inner == base:
                return ("mem", base, 0)
            if inner.startswith(base + "+"):
                return ("mem", base, eval_expr(inner[3:], symbols))
        return ("mem", "abs", eval_expr(inner, symbols))
    return ("expr", eval_expr(text, symbols))


def need(cond, msg):
    if not cond:
        raise AsmError(msg)


def encode_op(op, rest, pc, symbols):
    ops = [operand(t, symbols) for t in split_operands(rest)]
    kinds = tuple(o[0] for o in ops)

    def reg(o):
        return o[1]

    if op == "ret":
        return isa.encode("ret", ())
    if op in ("mov", "cmp", "add", "and", "or") and kinds[0] == "reg":
        if kinds[1:] == ("reg",):
            return isa.encode(op, (reg(ops[0]), ("r", reg(ops[1]))))
        need(kinds[1:] == ("imm",) and op != "or", "%s needs rD, #imm8 or rD, rS" % op)
        v = ops[1][1]
        need(0 <= v <= 255, "imm8 out of range: %d (imm8 is zero-extended, C: no negative values; use li + a register)" % v)
        return isa.encode(op, (reg(ops[0]), v & 0xFF))
    if op in ("shl", "shr"):
        need(kinds == ("reg", "expr") and 1 <= ops[1][1] <= 15, "shl/shr rN, 1..15")
        return isa.encode(op, (reg(ops[0]), ops[1][1]))
    if op == "ldc":
        need(kinds == ("reg", "mem") and ops[1][1] == "r1" and 0 <= ops[1][2] <= 15,
             "ldc rR, [r1+k] (k = 0..15) reads program memory")
        return isa.encode(op, (reg(ops[0]), ops[1][2]))
    if op in ("ld", "st"):
        r, m = (ops[0], ops[1]) if op == "ld" else (ops[1], ops[0])
        need(r[0] == "reg" and m[0] == "mem", "%s operands" % op)
        if m[1] in ("r1", "fp"):
            need(0 <= m[2] <= 15, "offset must be 0..15")
        return isa.encode(op, (reg(r), (m[1], m[2])))
    if op == "push":
        if kinds == ("reg",):
            return isa.encode("push", (reg(ops[0]),))
        need(kinds == ("imm",), "push rN | push #imm16")
        return isa.encode("push", (("imm", ops[0][1]),))
    if op in ("li", "addi"):
        need(kinds == ("reg", "imm"), "%s rN, #imm16" % op)
        return isa.encode(op, (reg(ops[0]), ops[1][1]))
    if op in ("call", "ccall"):
        need(kinds == ("expr",) and 0 <= ops[0][1] <= 0xFFFF, "call target")
        return isa.encode(op, (("abs", ops[0][1]),))
    if op in ("jmp", "b.e0", "blt", "beq", "bne"):
        need(kinds == ("expr",), "branch target")
        rel = ops[0][1] - (pc + 1)
        need(-128 <= rel <= 127, "%s target out of range (%d)" % (op, rel))
        return isa.encode(op, (("rel8", rel),))
    if re.fullmatch(r"lb[0-7]", op):
        need(kinds == ("expr",), "branch target")
        return isa.encode(op, (("rel16", ops[0][1] - (pc + 2)),))
    raise AsmError("unknown instruction %r" % op)


def assemble(lines, symbols=None, origin=None, label_prefix=None, labels_only=False,
             predefined_labels=False):
    """Assemble an iterable of source lines.

    Returns (words: {addr: word}, labels: {name: addr}). `symbols` are pre-defined names.
    Labels starting with '.' are local: they get `label_prefix` prepended (e.g. 'touch_off.done').
    labels_only: stop after pass 1.  predefined_labels: labels may already be in `symbols`
    (with the same address), as when a builder resolved all blocks' labels beforehand.
    """
    symbols = dict(symbols or {})
    stmts = []
    for n, line in enumerate(lines, 1):
        try:
            st = parse_statement(line)
        except AsmError as e:
            raise AsmError("line %d: %s" % (n, e))
        if st:
            stmts.append((n, st))

    def local(name):
        return (label_prefix + name) if (label_prefix and name.startswith(".")) else name

    def fix_locals(text):
        if not label_prefix:
            return text
        return re.sub(r"(?<![\w.])\.(?=[A-Za-z_])", label_prefix + ".", text)

    labels, pc = {}, origin
    for n, st in stmts:  # pass 1: addresses
        if st[0] == "equ":
            if st[1] in symbols:
                raise AsmError("line %d: duplicate symbol %r" % (n, st[1]))
            symbols[st[1]] = eval_expr(st[2], symbols)
        elif st[0] == "org":
            pc = eval_expr(st[1], symbols)
        elif st[0] == "label":
            if pc is None:
                raise AsmError("line %d: label before .org" % n)
            name = local(st[1])
            if name in symbols and predefined_labels and symbols[name] == pc:
                pass
            elif name in labels or name in symbols:
                raise AsmError("line %d: duplicate symbol %r" % (n, name))
            labels[name] = pc
        else:
            if pc is None:
                raise AsmError("line %d: code before .org" % n)
            pc += stmt_size(st)
    if labels_only:
        return {}, labels
    allsyms = dict(symbols)
    allsyms.update(labels)
    out, pc = {}, origin
    for n, st in stmts:  # pass 2: encode
        try:
            if st[0] == "org":
                pc = eval_expr(st[1], allsyms)
                continue
            if st[0] in ("label", "equ"):
                continue
            if st[0] == "dw":
                ws = [eval_expr(fix_locals(e), allsyms) & 0xFFFF for e in st[1]]
            else:
                ws = encode_op(st[1], fix_locals(st[2]), pc, allsyms)
            if len(ws) != stmt_size(st):
                raise AsmError("internal size mismatch")
            for w in ws:
                if pc in out:
                    raise AsmError("address %#x written twice" % pc)
                out[pc] = w
                pc += 1
        except AsmError as e:
            raise AsmError("line %d: %s" % (n, e))
    return out, labels


def block_size(lines):
    return sum(stmt_size(st) for st in map(parse_statement, lines) if st)
