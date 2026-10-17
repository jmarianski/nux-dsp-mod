#!/usr/bin/env python3
"""p16cc: a small C compiler for the NEK-100 DSP control CPU (P16XT), emitting nuxdsp assembly.

The language: C with 16-bit words only. int, short, char (all one 16-bit word, signed), unsigned, void,
pointers, arrays (any rank), function definitions, globals with initializers, the usual statements (if, while,
do, for, switch, break, continue, return) and operators. No structs, long, floats, strings or recursion yet.
Extras: __asm("line") as a statement, extern variables and functions resolved by the assembler (firmware map,
other patch code).

The machine model is the one confirmed on the instrument (nek100-mod docs/ISA.md and nek100-re FINDINGS):
ld/st [abs] and [r1+k], li/addi, mov/cmp/add/and/or/sub, shl/shr by constants, beq/bne/blt (signed), jmp,
call/ret, plus ljmp (d0ce, absolute within the 64K bank; strong hypothesis from the firmware's bank 1 code).

ABI (our own; the stack and enter/ret_pop are left alone):
  * Every function has a static frame in RAM: parameters first, then locals, then expression temporaries.
    Frames of functions that are never active at once share RAM (overlay along the call graph), so there is
    no recursion, and C code must not be re-entered (it runs from the main loop's tick and key handlers).
  * Caller stores the arguments into the callee's frame (symbol NAME__f), `call NAME`, result in r7.
  * extern functions (asm) get up to three arguments in r7, r6, r5 and return r7.
  * Generated code uses r1, r4, r5, r6, r7 and keeps r0, r2, r3 (asm glue must keep what its caller needs).
  * Globals and frames are RAM words in [ram_start, ram_end); __cc_init zeroes the globals and stores their
    initializers (call it once before anything else).
Multiplication, division and variable shifts are runtime routines (__mul, __udiv, __div, ...).

Usage: p16cc.py FILE.c [-o OUT.asm] [--ram START:END]
"""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "nek100-mod"))
from nuxdsp import isa  # noqa: E402

# ---------------------------------------------------------------------------------------------- lexer

KEYWORDS = {"int", "short", "char", "unsigned", "signed", "void", "const", "volatile", "static", "extern",
            "register", "if", "else", "while", "do", "for", "return", "break", "continue", "switch", "case",
            "default", "sizeof", "__asm", "long", "struct", "union", "float", "double", "goto", "typedef"}
PUNCT = sorted("<<= >>= ... -> ++ -- << >> <= >= == != && || += -= *= /= %= &= |= ^= "
               "( ) [ ] { } , ; : ? ~ ! + - * / % & | ^ < > =".split(), key=len, reverse=True)


class CError(Exception):
    pass


class Tok:
    __slots__ = ("kind", "val", "line")

    def __init__(self, kind, val, line):
        self.kind, self.val, self.line = kind, val, line

    def __repr__(self):
        return "%s:%r" % (self.kind, self.val)


def preprocess(src):
    """Comments out, object-like #define expanded (by the lexer), other directives rejected."""
    src = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group().count("\n"), src, flags=re.S)
    src = re.sub(r"//[^\n]*", "", src)
    defines, out = {}, []
    for line in src.split("\n"):
        s = line.strip()
        if s.startswith("#"):
            m = re.match(r"#\s*define\s+([A-Za-z_]\w*)(\s+(.*))?$", s)
            if m and not s[m.end(1):].startswith("("):
                defines[m.group(1)] = (m.group(3) or "").strip()
                out.append("")
                continue
            if re.match(r"#\s*pragma\b", s):
                out.append("")
                continue
            raise CError("unsupported directive: %s" % s)
        out.append(line)
    return "\n".join(out), defines


def lex(src):
    src, defines = preprocess(src)
    toks, i, line = [], 0, 1
    n = len(src)
    while i < n:
        c = src[i]
        if c == "\n":
            line += 1
            i += 1
            continue
        if c.isspace():
            i += 1
            continue
        m = re.compile(r"0[xX][0-9a-fA-F]+|0[bB][01]+|\d+").match(src, i)
        if m:
            t = m.group()
            v = int(t, 16) if t[:2] in ("0x", "0X") else int(t[2:], 2) if t[:2] in ("0b", "0B") else int(t, 8 if len(t) > 1 and t[0] == "0" else 10)
            i = m.end()
            while i < n and src[i] in "uUlL":
                i += 1
            toks.append(Tok("num", v, line))
            continue
        if c.isalpha() or c == "_":
            m = re.compile(r"[A-Za-z_]\w*").match(src, i)
            w = m.group()
            i = m.end()
            if w in defines:
                sub = lex(defines[w])[:-1]
                for t in sub:
                    t.line = line
                toks += sub
            else:
                toks.append(Tok("kw" if w in KEYWORDS else "id", w, line))
            continue
        if c == "'":
            m = re.compile(r"'(\\.|[^'\\])'").match(src, i)
            if not m:
                raise CError("line %d: bad character literal" % line)
            ch = m.group(1)
            esc = {"\\n": 10, "\\t": 9, "\\0": 0, "\\\\": 92, "\\'": 39, '\\"': 34, "\\r": 13}
            toks.append(Tok("num", esc[ch] if ch in esc else ord(ch), line))
            i = m.end()
            continue
        if c == '"':
            m = re.compile(r'"((\\.|[^"\\])*)"').match(src, i)
            if not m:
                raise CError("line %d: bad string" % line)
            toks.append(Tok("str", bytes(m.group(1), "utf-8").decode("unicode_escape"), line))
            i = m.end()
            continue
        for p in PUNCT:
            if src.startswith(p, i):
                toks.append(Tok("p", p, line))
                i += len(p)
                break
        else:
            raise CError("line %d: unexpected %r" % (line, c))
    toks.append(Tok("eof", None, line))
    return toks


# ---------------------------------------------------------------------------------------------- types

class Type:
    def __init__(self, kind, unsigned=False, base=None, n=None, params=None):
        self.kind, self.unsigned, self.base, self.n, self.params = kind, unsigned, base, n, params

    def size(self):
        if self.kind == "array":
            if self.n is None:
                raise CError("array of unknown size")
            return self.n * self.base.size()
        if self.kind == "void":
            raise CError("void has no size")
        return 1

    def scalar(self):
        return self.kind in ("int", "ptr")

    def is_ptr(self):
        return self.kind in ("ptr", "array")

    def __repr__(self):
        if self.kind == "int":
            return "unsigned" if self.unsigned else "int"
        if self.kind == "ptr":
            return "%r*" % self.base
        if self.kind == "array":
            return "%r[%s]" % (self.base, self.n)
        return self.kind


INT, UINT, VOID = Type("int"), Type("int", unsigned=True), Type("void")


def ptr_to(t):
    return Type("ptr", unsigned=True, base=t)


def decay(t):
    return ptr_to(t.base) if t.kind == "array" else t


# ---------------------------------------------------------------------------------------------- AST

class Node:
    def __init__(self, kind, line=0, **kw):
        self.kind, self.line, self.type = kind, line, None
        self.__dict__.update(kw)

    def __repr__(self):
        return "Node(%s)" % self.kind


class Var:
    """A variable: global (sym = its name) or in a frame (frame = function name, off)."""

    def __init__(self, name, type, sym=None, frame=None, off=0, extern=False):
        self.name, self.type, self.sym, self.frame, self.off, self.extern = name, type, sym, frame, off, extern
        self.init = None

    def addr(self, k=0):
        base = self.sym if self.sym else "%s__f+%d" % (self.frame, self.off)
        return base if k == 0 else "%s+%d" % (base, k)


class Func:
    def __init__(self, name, type, line):
        self.name, self.type, self.line = name, type, line
        self.params, self.body, self.defined = [], None, False
        self.nlocal, self.ntemp, self.calls = 0, 0, set()


# ---------------------------------------------------------------------------------------------- parser

class Parser:
    def __init__(self, toks):
        self.t, self.i = toks, 0
        self.globals, self.funcs, self.order = {}, {}, []
        self.scopes, self.func = [], None
        self.statics = 0

    # -- tokens
    def peek(self, k=0):
        return self.t[self.i + k]

    def next(self):
        t = self.t[self.i]
        self.i += 1
        return t

    def at(self, val, k=0):
        t = self.t[self.i + k]
        return t.kind in ("p", "kw") and t.val == val

    def accept(self, val):
        if self.at(val):
            self.i += 1
            return True
        return False

    def expect(self, val):
        t = self.next()
        if t.kind not in ("p", "kw") or t.val != val:
            raise CError("line %d: expected %r, got %r" % (t.line, val, t.val))
        return t

    def err(self, msg, t=None):
        t = t or self.peek()
        raise CError("line %d: %s" % (t.line, msg))

    # -- declarations
    def is_type_start(self):
        t = self.peek()
        return t.kind == "kw" and t.val in ("int", "short", "char", "unsigned", "signed", "void", "const",
                                            "volatile", "static", "extern", "register", "long", "struct",
                                            "union", "float", "double", "typedef")

    def specifiers(self):
        storage, unsigned, void, seen = None, False, False, False
        while self.is_type_start():
            t = self.next()
            v = t.val
            if v in ("long", "struct", "union", "float", "double", "typedef"):
                self.err("'%s' is not supported (16-bit ints and pointers only)" % v, t)
            if v in ("static", "extern"):
                storage = v
            elif v == "unsigned":
                unsigned, seen = True, True
            elif v == "void":
                void, seen = True, True
            elif v in ("int", "short", "char", "signed"):
                seen = True
        if not seen and storage is None:
            self.err("type expected")
        return storage, (VOID if void else UINT if unsigned else INT)

    def declarator(self, base):
        """-> (name, type). Pointers, arrays and function parameter lists; no abstract declarators."""
        t = base
        while self.accept("*"):
            while self.at("const") or self.at("volatile"):
                self.next()
            t = ptr_to(t)
        tok = self.next()
        if tok.kind != "id":
            self.err("name expected (function pointers are not supported)", tok)
        return tok.val, self.suffix(t)

    def suffix(self, t):
        if self.accept("("):
            params = []
            if self.at("void") and self.at(")", 1):
                self.next()
            while not self.at(")"):
                _, pt = self.specifiers()
                pname, pt = self.declarator(pt) if not (self.at(",") or self.at(")")) else (None, pt)
                params.append((pname, decay(pt) if pt.kind == "array" else pt))
                if not self.accept(","):
                    break
            self.expect(")")
            return Type("func", base=t, params=params)
        if self.accept("["):
            n = None if self.at("]") else self.const_expr()
            self.expect("]")
            inner = self.suffix(t)
            return Type("array", base=inner, n=n)
        return t

    def const_expr(self):
        e = self.fold(self.conditional())
        if e.kind != "num":
            self.err("constant expected")
        return e.val

    def program(self):
        while self.peek().kind != "eof":
            self.top_decl()
        return self

    def top_decl(self):
        storage, base = self.specifiers()
        if self.accept(";"):
            return
        while True:
            line = self.peek().line
            name, t = self.declarator(base)
            if t.kind == "func":
                f = self.funcs.get(name)
                if f is None:
                    f = self.funcs[name] = Func(name, t, line)
                    self.order.append(f)
                if self.at("{"):
                    if f.defined:
                        self.err("%s defined twice" % name)
                    f.type, f.defined = t, True
                    self.function_body(f)
                    return
            else:
                if name in self.globals and not self.globals[name].extern:
                    if storage != "extern":
                        self.err("%s defined twice" % name)
                else:
                    v = Var(name, t, sym=name, extern=(storage == "extern"))
                    self.globals[name] = v
                    if self.accept("="):
                        v.init = self.initializer(v.type)
                        if v.type.kind == "array" and v.type.n is None:
                            v.type.n = len(v.init) if isinstance(v.init, list) else None
            if not self.accept(","):
                break
        self.expect(";")

    def initializer(self, t):
        """-> int (scalar) or list of ints (flattened array, zero padded)."""
        if t.kind == "array":
            self.expect("{")
            items = []
            while not self.at("}"):
                if t.base.kind == "array":
                    items += self.initializer(t.base)
                else:
                    items.append(self.const_expr())
                if not self.accept(","):
                    break
            self.expect("}")
            if t.n is None:
                t.n = len(items) // (t.base.size())
            total = t.size()
            if len(items) > total:
                self.err("too many initializers")
            return items + [0] * (total - len(items))
        if self.accept("{"):
            v = self.const_expr()
            self.accept(",")
            self.expect("}")
            return v
        return self.const_expr() & 0xFFFF

    # -- functions and scopes
    def function_body(self, f):
        self.func = f
        self.scopes = [{}]
        f.params = []
        for pname, pt in f.type.params:
            if pname is None:
                self.err("parameter without a name in %s" % f.name)
            v = self.local(pname, pt)
            f.params.append(v)
        f.body = self.compound(new_scope=False)
        self.func = None

    def local(self, name, t):
        f = self.func
        if name in self.scopes[-1]:
            self.err("%s declared twice" % name)
        v = Var(name, t, frame=f.name, off=f.nlocal)
        f.nlocal += t.size()
        self.scopes[-1][name] = v
        return v

    def lookup(self, name, tok):
        for s in reversed(self.scopes):
            if name in s:
                return s[name]
        if name in self.globals:
            return self.globals[name]
        self.err("unknown name %s" % name, tok)

    # -- statements
    def compound(self, new_scope=True):
        line = self.expect("{").line
        if new_scope:
            self.scopes.append({})
        items = []
        while not self.accept("}"):
            items += self.block_item()
        if new_scope:
            self.scopes.pop()
        return Node("block", line, items=items)

    def block_item(self):
        if self.is_type_start():
            return self.local_decl()
        return [self.statement()]

    def local_decl(self):
        storage, base = self.specifiers()
        out = []
        while True:
            tok = self.peek()
            name, t = self.declarator(base)
            if t.kind == "func":
                self.err("local function declarations are not supported", tok)
            if storage == "extern":
                v = Var(name, t, sym=name, extern=True)
                self.scopes[-1][name] = v
            elif storage == "static":
                self.statics += 1
                v = Var(name, t, sym="%s__s%d" % (name, self.statics))
                self.globals[v.sym] = v
                self.scopes[-1][name] = v
                if self.accept("="):
                    v.init = self.initializer(t)
            else:
                init = None
                if self.accept("="):
                    if t.kind == "array":
                        init = self.initializer(t)
                    else:
                        init = self.assign()
                v = self.local(name, t)
                if init is not None:
                    ref = Node("var", tok.line, var=v)
                    if isinstance(init, list):
                        for k, val in enumerate(init):
                            out.append(Node("expr", tok.line, e=Node("assign", tok.line, op="=",
                                       l=Node("index", tok.line, a=ref, i=Node("num", tok.line, val=k)),
                                       r=Node("num", tok.line, val=val))))
                    else:
                        out.append(Node("expr", tok.line, e=Node("assign", tok.line, op="=", l=ref, r=init)))
            if not self.accept(","):
                break
        self.expect(";")
        return out

    def statement(self):
        t = self.peek()
        line = t.line
        if self.at("{"):
            return self.compound()
        if self.accept(";"):
            return Node("block", line, items=[])
        if self.accept("if"):
            self.expect("(")
            c = self.expr()
            self.expect(")")
            th = self.statement()
            el = self.statement() if self.accept("else") else None
            return Node("if", line, c=c, th=th, el=el)
        if self.accept("while"):
            self.expect("(")
            c = self.expr()
            self.expect(")")
            return Node("while", line, c=c, body=self.statement())
        if self.accept("do"):
            body = self.statement()
            self.expect("while")
            self.expect("(")
            c = self.expr()
            self.expect(")")
            self.expect(";")
            return Node("do", line, c=c, body=body)
        if self.accept("for"):
            self.expect("(")
            self.scopes.append({})
            init = []
            if self.is_type_start():
                init = self.local_decl()
            elif not self.accept(";"):
                init = [Node("expr", line, e=self.expr())]
                self.expect(";")
            c = None if self.at(";") else self.expr()
            self.expect(";")
            step = None if self.at(")") else self.expr()
            self.expect(")")
            body = self.statement()
            self.scopes.pop()
            return Node("for", line, init=init, c=c, step=step, body=body)
        if self.accept("switch"):
            self.expect("(")
            e = self.expr()
            self.expect(")")
            return Node("switch", line, e=e, body=self.statement())
        if self.accept("case"):
            v = self.const_expr()
            self.expect(":")
            return Node("case", line, val=v & 0xFFFF, st=self.statement())
        if self.accept("default"):
            self.expect(":")
            return Node("default", line, st=self.statement())
        if self.accept("return"):
            e = None if self.at(";") else self.expr()
            self.expect(";")
            return Node("return", line, e=e)
        if self.accept("break"):
            self.expect(";")
            return Node("break", line)
        if self.accept("continue"):
            self.expect(";")
            return Node("continue", line)
        if self.accept("__asm"):
            self.expect("(")
            text = ""
            while self.peek().kind == "str":
                text += self.next().val
            self.expect(")")
            self.expect(";")
            return Node("asm", line, text=text)
        e = self.expr()
        self.expect(";")
        return Node("expr", line, e=e)

    # -- expressions
    def expr(self):
        e = self.assign()
        while self.at(","):
            line = self.next().line
            e = Node("comma", line, a=e, b=self.assign())
        return e

    def assign(self):
        l = self.conditional()
        t = self.peek()
        if t.kind == "p" and t.val in ("=", "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "<<=", ">>="):
            self.next()
            return Node("assign", t.line, op=t.val, l=l, r=self.assign())
        return l

    def conditional(self):
        c = self.binary(0)
        if self.at("?"):
            line = self.next().line
            a = self.expr()
            self.expect(":")
            b = self.conditional()
            return Node("cond", line, c=c, a=a, b=b)
        return c

    PREC = [("||",), ("&&",), ("|",), ("^",), ("&",), ("==", "!="), ("<", ">", "<=", ">="), ("<<", ">>"),
            ("+", "-"), ("*", "/", "%")]

    def binary(self, level):
        if level == len(self.PREC):
            return self.unary()
        e = self.binary(level + 1)
        while self.peek().kind == "p" and self.peek().val in self.PREC[level]:
            t = self.next()
            r = self.binary(level + 1)
            kind = {"||": "or", "&&": "and"}.get(t.val, "bin")
            e = Node(kind, t.line, op=t.val, a=e, b=r)
        return e

    def unary(self):
        t = self.peek()
        if t.kind == "p" and t.val in ("-", "+", "!", "~", "*", "&", "++", "--"):
            self.next()
            x = self.unary()
            if t.val in ("++", "--"):
                return Node("incdec", t.line, op=t.val, post=False, x=x)
            return Node("unary", t.line, op=t.val, x=x)
        if self.at("sizeof"):
            self.next()
            if self.at("(") and self.is_type_start_at(1):
                self.next()
                ty = self.type_name()
                self.expect(")")
            else:
                ty = self.typeof(self.unary())
            return Node("num", t.line, val=ty.size())
        if self.at("(") and self.is_type_start_at(1):
            self.next()
            ty = self.type_name()
            self.expect(")")
            return Node("cast", t.line, to=ty, x=self.unary())
        return self.postfix()

    def is_type_start_at(self, k):
        t = self.peek(k)
        return t.kind == "kw" and t.val in ("int", "short", "char", "unsigned", "signed", "void", "const",
                                            "volatile", "long", "struct", "union", "float", "double")

    def type_name(self):
        _, t = self.specifiers()
        while self.accept("*"):
            t = ptr_to(t)
        return t

    def postfix(self):
        e = self.primary()
        while True:
            t = self.peek()
            if self.accept("["):
                i = self.expr()
                self.expect("]")
                e = Node("index", t.line, a=e, i=i)
            elif self.at("("):
                self.next()
                args = []
                while not self.at(")"):
                    args.append(self.assign())
                    if not self.accept(","):
                        break
                self.expect(")")
                if e.kind != "fname":
                    self.err("only direct calls are supported", t)
                e = Node("call", t.line, f=e.f, args=args)
            elif t.kind == "p" and t.val in ("++", "--"):
                self.next()
                e = Node("incdec", t.line, op=t.val, post=True, x=e)
            else:
                return e

    def primary(self):
        t = self.next()
        if t.kind == "num":
            n = Node("num", t.line, val=t.val & 0xFFFF)
            n.type = UINT if t.val > 0x7FFF else INT   # as C: a literal that does not fit int
            return n
        if t.kind == "id":
            if self.at("(") and t.val not in [n for s in self.scopes for n in s] and t.val not in self.globals:
                f = self.funcs.get(t.val)
                if f is None:
                    self.err("call of undeclared function %s" % t.val, t)
                return Node("fname", t.line, f=f)
            return Node("var", t.line, var=self.lookup(t.val, t))
        if t.kind == "p" and t.val == "(":
            e = self.expr()
            self.expect(")")
            return e
        self.err("expression expected, got %r" % (t.val,), t)

    # -- types of expressions (used by sizeof and the code generator)
    def typeof(self, e):
        if e.type is not None:
            return e.type
        k = e.kind
        if k == "num":
            t = INT
        elif k == "var":
            t = e.var.type
        elif k == "index":
            at = decay(self.typeof(e.a))
            if not at.is_ptr():
                at = decay(self.typeof(e.i))
                if not at.is_ptr():
                    self.err("subscript of a non-pointer", Tok("", "", e.line))
            t = at.base
        elif k == "unary":
            xt = self.typeof(e.x)
            if e.op == "*":
                xt = decay(xt)
                if not xt.is_ptr():
                    raise CError("line %d: dereference of a non-pointer" % e.line)
                t = xt.base
            elif e.op == "&":
                t = ptr_to(xt)
            elif e.op == "!":
                t = INT
            else:
                t = decay(xt)
        elif k == "cast":
            t = e.to
        elif k == "call":
            t = e.f.type.base
        elif k == "assign":
            t = decay(self.typeof(e.l))
        elif k == "incdec":
            t = decay(self.typeof(e.x))
        elif k in ("and", "or"):
            t = INT
        elif k == "comma":
            t = decay(self.typeof(e.b))
        elif k == "cond":
            ta, tb = decay(self.typeof(e.a)), decay(self.typeof(e.b))
            t = ta if ta.is_ptr() else tb if tb.is_ptr() else (UINT if ta.unsigned or tb.unsigned else INT)
        elif k == "bin":
            ta, tb = decay(self.typeof(e.a)), decay(self.typeof(e.b))
            if e.op in ("==", "!=", "<", ">", "<=", ">="):
                t = INT
            elif e.op in ("<<", ">>"):
                t = ta
            elif e.op == "-" and ta.is_ptr() and tb.is_ptr():
                t = INT
            elif e.op in ("+", "-") and ta.is_ptr():
                t = ta
            elif e.op == "+" and tb.is_ptr():
                t = tb
            else:
                t = UINT if (ta.unsigned or tb.unsigned) and not (ta.is_ptr() or tb.is_ptr()) else INT
        else:
            raise CError("line %d: cannot type %s" % (e.line, k))
        e.type = t
        return t

    def fold(self, e):
        """Constant folding of integer expressions (16-bit, signedness from the operand types)."""
        if e.kind == "bin":
            a, b = self.fold(e.a), self.fold(e.b)
            e.a, e.b = a, b
            if a.kind == "num" and b.kind == "num":
                u = self.typeof(a).unsigned or self.typeof(b).unsigned
                x, y = a.val, b.val
                sx, sy = (x, y) if u else (s16(x), s16(y))
                op = e.op
                if op in ("/", "%") and y == 0:
                    return e
                v = {"+": lambda: x + y, "-": lambda: x - y, "*": lambda: x * y,
                     "/": lambda: int(sx / sy) if not u else x // y,
                     "%": lambda: (sx - int(sx / sy) * sy) if not u else x % y,
                     "&": lambda: x & y, "|": lambda: x | y, "^": lambda: x ^ y,
                     "<<": lambda: x << (y & 31), ">>": lambda: (x >> (y & 31)) if u else (sx >> (y & 31)),
                     "==": lambda: int(x == y), "!=": lambda: int(x != y), "<": lambda: int(sx < sy),
                     ">": lambda: int(sx > sy), "<=": lambda: int(sx <= sy), ">=": lambda: int(sx >= sy)}[op]()
                n = Node("num", e.line, val=v & 0xFFFF)
                n.type = UINT if u and op not in ("==", "!=", "<", ">", "<=", ">=") else INT
                return n
        elif e.kind == "unary" and e.op in ("-", "~", "!", "+"):
            x = self.fold(e.x)
            e.x = x
            if x.kind == "num":
                v = {"-": -x.val, "~": ~x.val, "!": int(x.val == 0), "+": x.val}[e.op]
                return Node("num", e.line, val=v & 0xFFFF)
        elif e.kind in ("and", "or"):
            a, b = self.fold(e.a), self.fold(e.b)
            e.a, e.b = a, b
            if a.kind == "num" and b.kind == "num":
                v = (a.val and b.val) if e.kind == "and" else (a.val or b.val)
                return Node("num", e.line, val=int(bool(v)))
        elif e.kind == "cond":
            c = self.fold(e.c)
            if c.kind == "num":
                return self.fold(e.a if c.val else e.b)
        elif e.kind == "cast":
            x = self.fold(e.x)
            if x.kind == "num" and e.to.kind == "int":
                n = Node("num", e.line, val=x.val)
                n.type = e.to
                return n
            e.x = x
        return e


def s16(v):
    v &= 0xFFFF
    return v - 0x10000 if v & 0x8000 else v


# ---------------------------------------------------------------------------------------------- code generator

NEG = {"eq": "ne", "ne": "eq", "lt": "ge", "ge": "lt"}


class Gen:
    def __init__(self, parser):
        self.p = parser
        self.out = []        # items: ("i", text) | ("l", label) | ("j", label) | ("jc", cond, label)
        self.nlabel = 0
        self.f = None
        self.loops = []      # (break label, continue label)
        self.rt = set()      # runtime routines used

    def label(self):
        self.nlabel += 1
        return ".c%d" % self.nlabel

    def i(self, text):
        self.out.append(("i", text))

    def put(self, lab):
        self.out.append(("l", lab))

    def j(self, lab):
        self.out.append(("j", lab))

    def jc(self, cond, lab):
        self.out.append(("jc", cond, lab))

    def tmp(self, d):
        self.f.ntemp = max(self.f.ntemp, d + 1)
        return "%s__t+%d" % (self.f.name, d)

    def typeof(self, e):
        return self.p.typeof(e)

    # -- loads of constants and simple operands
    def li(self, reg, v):
        v &= 0xFFFF
        self.i(("mov   r%d, #%d" if v < 256 else "li    r%d, #%#06x") % (reg, v))

    def addc(self, reg, v):
        v &= 0xFFFF
        if v == 0:
            return
        if v < 256:
            self.i("add   r%d, #%d" % (reg, v))
        else:
            self.i("addi  r%d, #%#06x" % (reg, v))

    def mem_of(self, e):
        """A memory operand for e if it is a word at a fixed address: scalar variable, or a fixed array element."""
        if e.kind == "var" and e.var.type.scalar():
            return e.var.addr()
        if e.kind == "index":
            a, i = e.a, self.p.fold(e.i)
            if a.kind == "var" and a.var.type.kind == "array" and i.kind == "num" and self.typeof(e).scalar():
                return a.var.addr(s16(i.val) * a.var.type.base.size())
        if e.kind == "unary" and e.op == "*":
            x = self.p.fold(e.x)
            if x.kind == "num":
                return "%#06x" % x.val
            if x.kind == "cast" and x.x.kind == "num":
                return "%#06x" % x.x.val
        return None

    def simple(self, e):
        e = self.p.fold(e)
        return e.kind == "num" or self.mem_of(e) is not None or (e.kind == "var" and e.var.type.kind == "array")

    def load(self, e, reg):
        """Load a simple operand into reg."""
        e = self.p.fold(e)
        if e.kind == "num":
            self.li(reg, e.val)
        elif e.kind == "var" and e.var.type.kind == "array":
            self.i("li    r%d, #(%s)" % (reg, e.var.addr()))
        else:
            self.i("ld    r%d, [%s]" % (reg, self.mem_of(e)))

    # -- expressions: value in r7; d = first free temporary
    def expr(self, e, d=0):
        e = self.p.fold(e)
        k = e.kind
        t = self.typeof(e)
        if self.simple(e):
            self.load(e, 7)
            return
        if k == "var":  # functions / non-scalar handled above
            raise CError("line %d: cannot use %s as a value" % (e.line, e.var.name))
        if k == "index" or (k == "unary" and e.op == "*"):
            if t.kind == "array":
                self.addr(e, d)
                return
            self.addr_into_r1(e, d)
            self.i("ld    r7, [r1+%d]" % self.r1_off)
            return
        if k == "unary":
            if e.op == "&":
                self.addr(e.x, d)
            elif e.op == "-":
                self.expr(e.x, d)
                self.i("mov   r6, r7")
                self.i("mov   r7, #0")
                self.i("sub   r7, r6")
            elif e.op == "~":
                self.expr(e.x, d)
                self.i("mov   r6, r7")
                self.i("li    r7, #0xffff")
                self.i("sub   r7, r6")
            elif e.op == "+":
                self.expr(e.x, d)
            elif e.op == "!":
                self.bool_value(e, d)
            return
        if k == "cast":
            self.expr(e.x, d)
            return
        if k == "call":
            self.call(e, d)
            return
        if k == "assign":
            self.assign(e, d)
            return
        if k == "incdec":
            self.incdec(e, d)
            return
        if k == "comma":
            self.expr(e.a, d)
            self.expr(e.b, d)
            return
        if k == "cond":
            lb, le = self.label(), self.label()
            self.branch(e.c, lb, False, d)
            self.expr(e.a, d)
            self.j(le)
            self.put(lb)
            self.expr(e.b, d)
            self.put(le)
            return
        if k in ("and", "or") or (k == "bin" and e.op in ("==", "!=", "<", ">", "<=", ">=")):
            self.bool_value(e, d)
            return
        if k == "bin":
            self.binop(e, d)
            return
        raise CError("line %d: cannot compile %s" % (e.line, k))

    def bool_value(self, e, d):
        lf, le = self.label(), self.label()
        self.branch(e, lf, False, d)
        self.i("mov   r7, #1")
        self.j(le)
        self.put(lf)
        self.i("mov   r7, #0")
        self.put(le)

    def right_to_r6(self, b, d):
        """Left operand in r7; bring the right one to r6 (keeping r7)."""
        if self.simple(b):
            self.load(b, 6)
        else:
            self.i("st    [%s], r7" % self.tmp(d))
            self.expr(b, d + 1)
            self.i("mov   r6, r7")
            self.i("ld    r7, [%s]" % self.tmp(d))

    def binop(self, e, d):
        ta, tb = decay(self.typeof(e.a)), decay(self.typeof(e.b))
        a, b, op = self.p.fold(e.a), self.p.fold(e.b), e.op
        # pointer arithmetic: scale the integer side
        if op in ("+", "-") and ta.is_ptr() and not tb.is_ptr():
            b = self.scaled(b, ta.base.size())
        elif op == "+" and tb.is_ptr() and not ta.is_ptr():
            a, b, ta, tb = b, self.scaled(a, tb.base.size()), tb, ta
        unsigned = ta.unsigned if op in ("<<", ">>") else ta.unsigned or tb.unsigned
        self.expr(a, d)
        self.apply(op, b, d, unsigned)
        if op == "-" and ta.is_ptr() and tb.is_ptr() and ta.base.size() > 1:
            self.div_const(ta.base.size(), False)

    def scaled(self, e, n):
        if n == 1:
            return e
        return self.p.fold(Node("bin", e.line, op="*", a=e, b=Node("num", e.line, val=n)))

    def apply(self, op, b, d, unsigned):
        """r7 = r7 op b."""
        b = self.p.fold(b)
        if b.kind == "num":
            v = b.val
            if op == "+":
                self.addc(7, v)
                return
            if op == "-":
                self.addc(7, -v)
                return
            if op == "&" and v < 256:
                self.i("and   r7, #%d" % v)
                return
            if op == "*":
                self.mul_const(v)
                return
            if op in ("<<", ">>"):
                self.shift_const(op, v, unsigned)
                return
            if op in ("/", "%") and v and v & (v - 1) == 0 and (unsigned or op == "/"):
                if op == "%":
                    self.li(6, v - 1)
                    self.i("and   r7, r6")
                else:
                    self.div_const(v, not unsigned)
                return
        if op in ("<<", ">>"):
            self.right_to_r6(b, d)
            name = "__shl" if op == "<<" else "__shr" if unsigned else "__sar"
            self.rt.add(name)
            self.i("call  %s" % name)
            return
        self.right_to_r6(b, d)
        if op in ("+", "-", "&", "|"):
            self.i("%s   r7, r6" % {"+": "add", "-": "sub", "&": "and", "|": "or "}[op])
        elif op == "^":
            self.i("mov   r5, r7")
            self.i("and   r5, r6")
            self.i("or    r7, r6")
            self.i("sub   r7, r5")
        elif op == "*":
            self.rt.add("__mul")
            self.i("call  __mul")
        elif op in ("/", "%"):
            name = "__udiv" if unsigned else "__div"
            self.rt.add(name)
            if name == "__div":
                self.rt.add("__udiv")
            self.i("call  %s" % name)
            if op == "%":
                self.i("mov   r7, r5")
        else:
            raise CError("operator %s" % op)

    def mul_const(self, v):
        v &= 0xFFFF
        if v == 0:
            self.i("mov   r7, #0")
            return
        if v == 1:
            return
        bits = [k for k in range(16) if v >> k & 1]
        if len(bits) > 4:
            self.li(6, v)
            self.rt.add("__mul")
            self.i("call  __mul")
            return
        if len(bits) == 1:
            self.i("shl   r7, %d" % bits[0])
            return
        self.i("mov   r5, r7")
        if bits[-1]:
            self.i("shl   r7, %d" % bits[-1])
        for k in bits[:-1]:
            self.i("mov   r6, r5")
            if k:
                self.i("shl   r6, %d" % k)
            self.i("add   r7, r6")

    def shift_const(self, op, v, unsigned):
        v &= 0xFFFF
        if v == 0:
            return
        if v >= 16:
            if op == "<<" or unsigned:
                self.i("mov   r7, #0")
                return
            v = 15
        if op == "<<":
            self.i("shl   r7, %d" % v)
        elif unsigned:
            self.i("shr   r7, %d" % v)
        else:
            ln, le = self.label(), self.label()
            self.i("cmp   r7, #0")
            self.i("blt   %s" % ln)
            self.i("shr   r7, %d" % v)
            self.i("jmp   %s" % le)
            self.put(ln)
            self.i("li    r6, #0xffff")
            self.i("sub   r6, r7")
            self.i("shr   r6, %d" % v)
            self.i("li    r7, #0xffff")
            self.i("sub   r7, r6")
            self.put(le)

    def div_const(self, v, signed):
        """r7 /= v, v a power of two (signed: rounds toward zero, as C)."""
        k = v.bit_length() - 1
        if k == 0:
            return
        if not signed:
            self.i("shr   r7, %d" % k)
            return
        lp = self.label()
        self.i("cmp   r7, #0")
        self.i("blt   %s" % lp)
        self.i("jmp   %s_" % lp)
        self.put(lp)
        self.addc(7, v - 1)
        self.put(lp + "_")
        self.shift_const(">>", k, False)

    # -- addresses
    def addr(self, e, d):
        """r7 = address of the lvalue e (or of an array)."""
        e = self.p.fold(e)
        if e.kind == "var":
            self.i("li    r7, #(%s)" % e.var.addr())
            return
        if e.kind == "unary" and e.op == "*":
            self.expr(e.x, d)
            return
        if e.kind == "index":
            a, i = e.a, e.i
            if not decay(self.typeof(a)).is_ptr():
                a, i = i, a
            size = decay(self.typeof(a)).base.size()
            ii = self.p.fold(i)
            if ii.kind == "num":
                self.expr(a, d)
                self.addc(7, s16(ii.val) * size)
                return
            if a.kind == "var" and a.var.type.kind == "array":
                self.expr(self.scaled(i, size), d)
                self.i("li    r6, #(%s)" % a.var.addr())
                self.i("add   r7, r6")
                return
            self.expr(a, d)
            self.apply("+", self.scaled(i, size), d, True)
            return
        raise CError("line %d: not an lvalue" % e.line)

    def addr_into_r1(self, e, d):
        """r1 + self.r1_off = address of lvalue e (r7 may be clobbered)."""
        self.r1_off = 0
        e = self.p.fold(e)
        if e.kind == "index":
            a, i = e.a, e.i
            if not decay(self.typeof(a)).is_ptr():
                a, i = i, a
            size = decay(self.typeof(a)).base.size()
            i = self.p.fold(i)
            off = 0
            if size == 1 and i.kind == "bin" and i.op == "+" and self.p.fold(i.b).kind == "num" \
                    and 0 <= s16(self.p.fold(i.b).val) <= 15:
                off, i = s16(self.p.fold(i.b).val), i.a
            elif size == 1 and i.kind == "num" and 0 <= s16(i.val) <= 15:
                off, i = s16(i.val), None
            if i is None:
                self.expr(a, d)
                self.i("mov   r1, r7")
            elif a.kind == "var" and a.var.type.kind == "array":
                self.expr(self.scaled(i, size), d)
                self.i("li    r1, #(%s)" % a.var.addr())
                self.i("add   r1, r7")
            else:
                self.expr(a, d)
                self.apply("+", self.scaled(i, size), d, True)
                self.i("mov   r1, r7")
            self.r1_off = off
            return
        self.addr(e, d)
        self.i("mov   r1, r7")

    # -- assignment
    def assign(self, e, d):
        l, r, op = e.l, e.r, e.op
        lt = self.typeof(l)
        if not lt.scalar():
            raise CError("line %d: assignment to a non-scalar" % e.line)
        binop = op[:-1] if op != "=" else None
        if binop and lt.is_ptr() and binop in ("+", "-"):
            r = self.scaled(r, lt.base.size())
        m = self.mem_of(l)
        if m is not None:
            if binop:
                self.i("ld    r7, [%s]" % m)
                self.apply(binop, r, d, lt.unsigned or decay(self.typeof(r)).unsigned)
            else:
                self.expr(r, d)
            self.i("st    [%s], r7" % m)
            return
        if binop is None and self.simple(r):
            self.addr_into_r1(l, d)
            self.load(r, 7)
            self.i("st    [r1+%d], r7" % self.r1_off)
            return
        self.addr_into_r1(l, d)
        off = self.r1_off
        if off:
            self.addc(1, off)
        self.i("st    [%s], r1" % self.tmp(d))
        if binop:
            self.i("ld    r7, [r1+0]")
            self.apply(binop, r, d + 1, lt.unsigned or decay(self.typeof(r)).unsigned)
        else:
            self.expr(r, d + 1)
        self.i("ld    r1, [%s]" % self.tmp(d))
        self.i("st    [r1+0], r7")

    def incdec(self, e, d):
        t = decay(self.typeof(e.x))
        step = t.base.size() if t.is_ptr() else 1
        step = step if e.op == "++" else -step
        m = self.mem_of(e.x)
        if m is not None:
            self.i("ld    r7, [%s]" % m)
            if e.post:
                self.i("mov   r6, r7")
                self.addc(6, step)
                self.i("st    [%s], r6" % m)
            else:
                self.addc(7, step)
                self.i("st    [%s], r7" % m)
            return
        self.addr_into_r1(e.x, d)
        off = self.r1_off
        self.i("ld    r7, [r1+%d]" % off)
        if e.post:
            self.i("mov   r6, r7")
            self.addc(6, step)
            self.i("st    [r1+%d], r6" % off)
        else:
            self.addc(7, step)
            self.i("st    [r1+%d], r7" % off)

    # -- calls
    def call(self, e, d):
        f = e.f
        params = f.type.params
        if len(e.args) != len(params):
            raise CError("line %d: %s takes %d arguments" % (e.line, f.name, len(params)))
        if not f.defined:
            if len(e.args) > 3:
                raise CError("line %d: extern %s: at most 3 arguments (r7, r6, r5)" % (e.line, f.name))
            for k, a in enumerate(e.args):
                self.expr(a, d + k)
                self.i("st    [%s], r7" % self.tmp(d + k))
            for k in reversed(range(len(e.args))):
                self.i("ld    r%d, [%s]" % (7 - k, self.tmp(d + k)))
            self.i("call  %s" % f.name)
            return
        self.f.calls.add(f.name)
        has_call = any(self.contains_call(a) for a in e.args)
        if has_call:
            for k, a in enumerate(e.args):
                self.expr(a, d + k)
                self.i("st    [%s], r7" % self.tmp(d + k))
            for k in range(len(e.args)):
                self.i("ld    r7, [%s]" % self.tmp(d + k))
                self.i("st    [%s__f+%d], r7" % (f.name, k))
        else:
            for k, a in enumerate(e.args):
                self.expr(a, d)
                self.i("st    [%s__f+%d], r7" % (f.name, k))
        self.i("call  %s" % f.name)

    def contains_call(self, e):
        if isinstance(e, Node):
            if e.kind == "call":
                return True
            return any(self.contains_call(v) for k, v in e.__dict__.items() if k not in ("type", "var", "f"))
        if isinstance(e, list):
            return any(self.contains_call(x) for x in e)
        return False

    # -- conditions
    def branch(self, e, lab, when, d):
        """Jump to lab if bool(e) == when."""
        e = self.p.fold(e)
        if e.kind == "num":
            if bool(e.val) == when:
                self.j(lab)
            return
        if e.kind == "unary" and e.op == "!":
            self.branch(e.x, lab, not when, d)
            return
        if e.kind in ("and", "or"):
            if (e.kind == "and") == when:
                skip = self.label()
                self.branch(e.a, skip, not when, d)
                self.branch(e.b, lab, when, d)
                self.put(skip)
            else:
                self.branch(e.a, lab, when, d)
                self.branch(e.b, lab, when, d)
            return
        if e.kind == "bin" and e.op in ("==", "!=", "<", ">", "<=", ">="):
            ta, tb = decay(self.typeof(e.a)), decay(self.typeof(e.b))
            unsigned = ta.unsigned or tb.unsigned or ta.is_ptr() or tb.is_ptr()
            op = e.op
            a, b = self.p.fold(e.a), self.p.fold(e.b)
            if op in ("==", "!=") or not unsigned:
                self.expr(a, d)
                if b.kind == "num" and b.val < 256 and (op in ("==", "!=") or True):
                    swap = op in (">", "<=")
                    if swap:
                        self.li(6, b.val)
                        self.i("cmp   r6, r7")
                    else:
                        self.i("cmp   r7, #%d" % b.val)
                else:
                    self.right_to_r6(b, d)
                    swap = op in (">", "<=")
                    self.i("cmp   r6, r7" if swap else "cmp   r7, r6")
            else:  # unsigned: both biased by 0x8000, then the signed comparison
                self.expr(a, d)
                self.right_to_r6(b, d)
                self.i("addi  r7, #0x8000")
                self.i("addi  r6, #0x8000")
                swap = op in (">", "<=")
                self.i("cmp   r6, r7" if swap else "cmp   r7, r6")
            cond = {"==": "eq", "!=": "ne", "<": "lt", ">=": "ge", ">": "lt", "<=": "ge"}[op]
            self.jc(cond if when else NEG[cond], lab)
            return
        self.expr(e, d)
        self.i("cmp   r7, #0")
        self.jc("ne" if when else "eq", lab)

    # -- statements
    def stmt(self, s):
        k = s.kind
        if k == "block":
            for x in s.items:
                self.stmt(x)
        elif k == "expr":
            self.expr(s.e, 0)
        elif k == "if":
            le = self.label()
            self.branch(s.c, le, False, 0)
            self.stmt(s.th)
            if s.el:
                lend = self.label()
                self.j(lend)
                self.put(le)
                self.stmt(s.el)
                self.put(lend)
            else:
                self.put(le)
        elif k == "while":
            top, end = self.label(), self.label()
            self.put(top)
            self.branch(s.c, end, False, 0)
            self.loops.append((end, top))
            self.stmt(s.body)
            self.loops.pop()
            self.j(top)
            self.put(end)
        elif k == "do":
            top, cont, end = self.label(), self.label(), self.label()
            self.put(top)
            self.loops.append((end, cont))
            self.stmt(s.body)
            self.loops.pop()
            self.put(cont)
            self.branch(s.c, top, True, 0)
            self.put(end)
        elif k == "for":
            for x in s.init:
                self.stmt(x)
            top, cont, end = self.label(), self.label(), self.label()
            self.put(top)
            if s.c is not None:
                self.branch(s.c, end, False, 0)
            self.loops.append((end, cont))
            self.stmt(s.body)
            self.loops.pop()
            self.put(cont)
            if s.step is not None:
                self.expr(s.step, 0)
            self.j(top)
            self.put(end)
        elif k == "switch":
            end = self.label()
            cases, default = [], [None]
            self.collect_cases(s.body, cases, default)
            self.expr(s.e, 0)
            if len(cases) > 1:
                self.i("st    [%s], r7" % self.tmp(0))
            for n, (val, node) in enumerate(cases):
                node.label = self.label()
                if n:
                    self.i("ld    r7, [%s]" % self.tmp(0))
                if val < 256:
                    self.i("cmp   r7, #%d" % val)
                else:
                    self.li(6, val)
                    self.i("cmp   r7, r6")
                self.jc("eq", node.label)
            if default[0] is not None:
                default[0].label = self.label()
                self.j(default[0].label)
            else:
                self.j(end)
            self.loops.append((end, self.loops[-1][1] if self.loops else None))
            self.stmt(s.body)
            self.loops.pop()
            self.put(end)
        elif k in ("case", "default"):
            self.put(s.label)
            self.stmt(s.st)
        elif k == "return":
            if s.e is not None:
                self.expr(s.e, 0)
            self.i("ret")
        elif k == "break":
            if not self.loops:
                raise CError("line %d: break outside a loop or switch" % s.line)
            self.j(self.loops[-1][0])
        elif k == "continue":
            conts = [c for _, c in self.loops if c is not None]
            if not conts:
                raise CError("line %d: continue outside a loop" % s.line)
            self.j(self.loops[-1][1])
        elif k == "asm":
            for line in s.text.split("\n"):
                if line.strip():
                    if line.strip().endswith(":"):
                        self.put(line.strip()[:-1])
                    else:
                        self.i(line.strip())
        else:
            raise CError("line %d: statement %s" % (s.line, k))

    def collect_cases(self, s, cases, default):
        if not isinstance(s, Node):
            return
        if s.kind == "switch":
            return
        if s.kind == "case":
            cases.append((s.val, s))
        elif s.kind == "default":
            default[0] = s
        for k, v in s.__dict__.items():
            if k in ("type", "var", "f", "e", "c", "step"):
                continue
            if isinstance(v, Node):
                self.collect_cases(v, cases, default)
            elif isinstance(v, list):
                for x in v:
                    self.collect_cases(x, cases, default)

    def function(self, f):
        self.f = f
        self.out.append(("l", f.name))
        self.stmt(f.body)
        last = self.out[-1]
        if not (last[0] == "i" and last[1] == "ret"):
            self.i("ret")
        self.f = None


# ---------------------------------------------------------------------------------------------- layout

def short_size(item):
    if item[0] == "j":
        return 1
    return 2 if item[1] == "ge" else 1


def long_size(item):
    if item[0] == "j":
        return 2
    return 4 if item[1] == "lt" else 3


def insn_size(text):
    op = text.split()[0]
    if op == ".dw":
        return len(text[3:].split(","))
    rest = text[len(op):]
    return isa.size_of(op, rest)


def relax(items, long_jumps=True):
    """Choose short or long forms for jumps so that every target is in range; -> assembly lines.
    long_jumps=False: a jump out of short reach is an error (ljmp is not confirmed on the device)."""
    long = set()
    while True:
        addr, pc, where = {}, 0, []
        for n, it in enumerate(items):
            where.append(pc)
            if it[0] == "l":
                addr[it[1]] = pc
            elif it[0] == "i":
                pc += insn_size(it[1])
            else:
                pc += long_size(it) if n in long else short_size(it)
        grew = False
        for n, it in enumerate(items):
            if it[0] in ("j", "jc") and n not in long:
                lab = it[-1]
                if lab not in addr:
                    raise CError("unknown label %s" % lab)
                br = where[n] + (1 if it[0] == "jc" and it[1] == "ge" else 0)
                rel = addr[lab] - (br + 1)
                if not -128 <= rel <= 127:
                    if not long_jumps:
                        raise CError("jump to %s out of short reach (%d words): split the function (long jumps off)"
                                     % (lab, rel))
                    long.add(n)
                    grew = True
        if not grew:
            break
    out, k = [], 0
    for n, it in enumerate(items):
        if it[0] == "l":
            out.append("%s:" % it[1])
        elif it[0] == "i":
            out.append("    " + it[1])
        elif it[0] == "j":
            out.append("    %s %s" % ("ljmp " if n in long else "jmp  ", it[1]))
        else:
            cond, lab = it[1], it[2]
            k += 1
            s = ".s%d" % k
            if n not in long:
                if cond == "ge":
                    out += ["    blt   %s" % s, "    jmp   %s" % lab, "%s:" % s]
                else:
                    out.append("    %s   %s" % ({"eq": "beq", "ne": "bne", "lt": "blt"}[cond], lab))
            elif cond == "lt":
                out += ["    blt   %s_" % s, "    jmp   %s" % s, "%s_:" % s, "    ljmp  %s" % lab, "%s:" % s]
            else:
                out += ["    %s   %s" % ({"eq": "bne", "ne": "beq", "ge": "blt"}[cond], s), "    ljmp  %s" % lab,
                        "%s:" % s]
    return out


# ---------------------------------------------------------------------------------------------- runtime

RUNTIME = {
    "__mul": """
__mul:                                  ; r7 = r7 * r6 (low 16 bits); uses r4, r5, r6
    mov   r5, r7
    mov   r7, #0
.mu_l:
    cmp   r6, #0
    beq   .mu_d
    mov   r4, r6
    and   r4, #1
    cmp   r4, #0
    beq   .mu_s
    add   r7, r5
.mu_s:
    shl   r5, 1
    shr   r6, 1
    jmp   .mu_l
.mu_d:
    ret
""",
    "__udiv": """
__udiv:                                 ; r7 = r7 / r6, r5 = r7 % r6, unsigned (r6 = 0: r7 = 0xffff); uses r1, r4
    addi  r6, #0x8000                   ; the divisor biased: unsigned compares as signed
    mov   r5, #0
    mov   r4, #16
.ud_l:
    mov   r1, r5                        ; (r5:r7) <<= 1, the bit shifted out of r5 kept in __rt0
    shr   r1, 15
    st    [__rt0], r1
    shl   r5, 1
    mov   r1, r7
    shr   r1, 15
    or    r5, r1
    shl   r7, 1
    ld    r1, [__rt0]
    cmp   r1, #0
    bne   .ud_s
    mov   r1, r5
    addi  r1, #0x8000
    cmp   r1, r6
    blt   .ud_n
.ud_s:
    mov   r1, r5                        ; r5 -= divisor (= (r5 + 0x8000) - biased divisor)
    addi  r1, #0x8000
    sub   r1, r6
    mov   r5, r1
    add   r7, #1
.ud_n:
    addi  r4, #0xffff
    cmp   r4, #0
    bne   .ud_l
    addi  r6, #0x8000
    ret
""",
    "__div": """
__div:                                  ; r7 = r7 / r6, r5 = r7 % r6, signed as C (toward zero); uses r1, r4
    mov   r1, #0                        ; bit 0: negate the quotient, bit 1: the remainder
    cmp   r7, #0
    blt   .dv_na
    jmp   .dv_a
.dv_na:
    mov   r4, r7
    mov   r7, #0
    sub   r7, r4
    mov   r1, #3
.dv_a:
    cmp   r6, #0
    blt   .dv_nb
    jmp   .dv_b
.dv_nb:
    mov   r4, r6
    mov   r6, #0
    sub   r6, r4
    mov   r4, r1
    and   r4, #1
    cmp   r4, #0
    beq   .dv_1
    addi  r1, #0xffff
    jmp   .dv_b
.dv_1:
    add   r1, #1
.dv_b:
    st    [__rt1], r1
    call  __udiv
    ld    r1, [__rt1]
    mov   r4, r1
    and   r4, #1
    cmp   r4, #0
    beq   .dv_q
    mov   r4, r7
    mov   r7, #0
    sub   r7, r4
.dv_q:
    and   r1, #2
    cmp   r1, #0
    beq   .dv_r
    mov   r4, r5
    mov   r5, #0
    sub   r5, r4
.dv_r:
    ret
""",
    "__shl": """
__shl:                                  ; r7 <<= r6 (r6 & 31)
    and   r6, #31
.sl_l:
    cmp   r6, #0
    beq   .sl_d
    shl   r7, 1
    addi  r6, #0xffff
    jmp   .sl_l
.sl_d:
    ret
""",
    "__shr": """
__shr:                                  ; r7 >>= r6 (r6 & 31), logical
    and   r6, #31
.sr_l:
    cmp   r6, #0
    beq   .sr_d
    shr   r7, 1
    addi  r6, #0xffff
    jmp   .sr_l
.sr_d:
    ret
""",
    "__sar": """
__sar:                                  ; r7 >>= r6 (r6 & 31), arithmetic; uses r4
    and   r6, #31
.sa_l:
    cmp   r6, #0
    beq   .sa_d
    cmp   r7, #0
    blt   .sa_n
    shr   r7, 1
    jmp   .sa_e
.sa_n:
    shr   r7, 1
    li    r4, #0x8000
    or    r7, r4
.sa_e:
    addi  r6, #0xffff
    jmp   .sa_l
.sa_d:
    ret
""",
}


# ---------------------------------------------------------------------------------------------- driver

class Result:
    def __init__(self, lines, symbols, frames, globals_, ram_used):
        self.lines = lines            # assembly lines (a block of a nuxdsp patch, needs an origin)
        self.symbols = symbols        # {name: RAM address}: globals, frames (NAME__f), temps (NAME__t)
        self.frames = frames          # {function: (frame address, size)}
        self.globals = globals_       # {name: (address, size)}
        self.ram_used = ram_used

    def text(self):
        return "\n".join(self.lines) + "\n"


def compile_c(src, ram=(0x6440, 0x6500), long_jumps=True):
    p = Parser(lex(src)).program()
    g = Gen(p)
    funcs = [f for f in p.order if f.defined]
    for f in funcs:
        g.function(f)
    rt = set(g.rt)
    if "__div" in rt:
        rt.add("__udiv")

    # RAM: runtime words, globals, then the frames (overlaid along the call graph)
    addr, symbols, glob = ram[0], {}, {}
    if rt & {"__udiv", "__div"}:
        symbols["__rt0"], symbols["__rt1"] = addr, addr + 1
        addr += 2
    for name, v in p.globals.items():
        if v.extern:
            continue
        n = v.type.size()
        symbols[v.sym] = addr
        glob[v.sym] = (addr, n)
        addr += n
    gend = addr
    byname = {f.name: f for f in funcs}
    callers = {f.name: [h.name for h in funcs if f.name in h.calls] for f in funcs}
    base, state = {}, {}

    def place(name, stack=()):
        if name in base:
            return base[name]
        if name in stack:
            raise CError("recursion through %s is not supported (static frames)" % " -> ".join(stack + (name,)))
        b = 0
        for c in callers[name]:
            b = max(b, place(c, stack + (name,)) + size(byname[c]))
        base[name] = b
        return b

    def size(f):
        return f.nlocal + f.ntemp

    frames, top = {}, gend
    for f in funcs:
        b = gend + place(f.name)
        frames[f.name] = (b, size(f))
        symbols[f.name + "__f"] = b
        symbols[f.name + "__t"] = b + f.nlocal
        top = max(top, b + size(f))
    if top > ram[1]:
        raise CError("RAM: %d words needed, %d available (%#x..%#x)" % (top - ram[0], ram[1] - ram[0], ram[0], ram[1]))

    # __cc_init: zero the globals, then store the initializers
    init = [("l", "__cc_init")]
    if gend > ram[0]:
        init += [("i", "li    r1, #%#06x" % ram[0]), ("i", "li    r6, #%#06x" % gend), ("i", "mov   r7, #0"),
                 ("l", ".ci_z"), ("i", "st    [r1+0], r7"), ("i", "add   r1, #1"), ("i", "cmp   r1, r6"),
                 ("jc", "ne", ".ci_z")]
    for name, v in p.globals.items():
        if v.extern or v.init is None:
            continue
        vals = v.init if isinstance(v.init, list) else [v.init]
        last = None
        for k, val in enumerate(vals):
            val &= 0xFFFF
            if val:
                if val != last:
                    init.append(("i", ("mov   r7, #%d" if val < 256 else "li    r7, #%#06x") % val))
                    last = val
                init.append(("i", "st    [%s+%d], r7" % (v.sym, k)))
    init.append(("i", "ret"))

    lines = ["; generated by doom-piano/cc/p16cc.py"]
    lines += [".equ %s, %#06x" % (k, v) for k, v in symbols.items()]
    lines += relax(g.out + init, long_jumps)
    for name in ("__mul", "__udiv", "__div", "__shl", "__shr", "__sar"):
        if name in rt:
            lines += RUNTIME[name].strip("\n").split("\n")
    return Result(lines, symbols, frames, glob, top - ram[0])


def main(argv):
    import argparse
    ap = argparse.ArgumentParser(description="C (16-bit subset) -> nuxdsp assembly for the NEK-100 DSP")
    ap.add_argument("src")
    ap.add_argument("-o", "--out")
    ap.add_argument("--ram", default="0x6440:0x6500", help="RAM for globals and frames, START:END")
    a = ap.parse_args(argv)
    lo, hi = (int(x, 0) for x in a.ram.split(":"))
    try:
        r = compile_c(open(a.src).read(), (lo, hi))
    except CError as e:
        sys.exit("%s: %s" % (a.src, e))
    if a.out:
        open(a.out, "w").write(r.text())
    else:
        sys.stdout.write(r.text())
    print("RAM: %d words" % r.ram_used, file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1:])
