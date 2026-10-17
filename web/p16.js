/* The P16 control CPU of the NEK-100, as nek100-mod's simulator (sim.py) models it, running a program that
 * tools/webbuild.py predecoded. Works in the browser (window.P16) and in node (require).
 *
 * Model (same as sim.py): 16-bit registers r0..r7, fp fixed, cmp unsigned, imm8 zero-extended, shr logical,
 * call/ret on a host-side stack. Calls to the program's natives run host functions instead (this.natives[name]).
 */
(function (root) {
  "use strict";

  class P16Error extends Error {}

  class P16 {
    constructor(prog, natives) {
      this.prog = prog;
      const c = prog.code;
      this.start = c.start;
      this.op = Int32Array.from(c.op.map((o) => o));
      this.a = Int32Array.from(c.a);
      this.b = Int32Array.from(c.b);
      const ids = {};
      prog.ops.forEach((name, k) => (ids[name] = k));
      this.ids = ids;
      this.ram = new Uint16Array(65536);
      this.r = new Uint16Array(8);
      this.fp = 0x7000;
      this.flags = 0;
      this.steps = 0;
      this.natives = natives || {};
      this.nativeAt = {};
      for (const [addr, name] of Object.entries(prog.natives)) this.nativeAt[+addr] = name;
      this.far = prog.far;
    }

    rd(a) { return this.ram[a & 0xffff]; }
    wr(a, v) { this.ram[a & 0xffff] = v; }
    sym(name) { return this.prog.symbols[name]; }
    get(name, k = 0) { return this.ram[this.prog.symbols[name] + k]; }

    farRead(addr) {
      for (const seg of this.far) {
        const i = addr - seg.addr;
        if (i >= 0 && i < seg.words.length) return seg.words[i];
      }
      return 0xffff;
    }

    /* Call an entry point (name or address) with arguments in its static frame; -> r7. */
    call(entry, ...args) {
      const addr = typeof entry === "string" ? this.prog.entry[entry] : entry;
      if (typeof entry === "string" && this.prog.frames[entry] !== undefined)
        args.forEach((v, k) => this.wr(this.prog.frames[entry] + k, v));
      this.run(addr, 50000000);
      return this.r[7];
    }

    run(addr, maxSteps) {
      const ID = this.ids, op = this.op, A = this.a, B = this.b, r = this.r, ram = this.ram, start = this.start;
      const stack = [-1];
      let pc = addr, steps = 0;
      const RET = ID.ret, SUB = ID.sub, MOV_R = ID.mov_r, MOV_I = ID.mov_i, CMP_R = ID.cmp_r, CMP_I = ID.cmp_i;
      const ADD_R = ID.add_r, ADD_I = ID.add_i, AND_R = ID.and_r, AND_I = ID.and_i, OR_R = ID.or_r;
      const SHL = ID.shl, SHR = ID.shr, LDC = ID.ldc, LD_ABS = ID.ld_abs, LD_R1 = ID.ld_r1, LD_FP = ID.ld_fp;
      const ST_ABS = ID.st_abs, ST_R1 = ID.st_r1, ST_FP = ID.st_fp, LI = ID.li, ADDI = ID.addi;
      const JMP = ID.jmp, BEQ = ID.beq, BNE = ID.bne, BLT = ID.blt, LJMP = ID.ljmp, CALL = ID.call;
      let flags = this.flags;
      const fp = this.fp;
      for (;;) {
        if (++steps > maxSteps) {
          this.steps += steps;
          throw new P16Error("step limit (loop?) at 0x" + pc.toString(16));
        }
        const i = pc - start;
        const o = i >= 0 && i < op.length ? op[i] : 0;
        const a = A[i], b = B[i];
        let nxt = pc + 1;
        switch (o) {
          case RET:
            pc = stack.pop();
            if (pc < 0) { this.flags = flags; this.steps += steps; return; }
            continue;
          case SUB: r[a] = r[a] - r[b]; break;
          case MOV_R: r[a] = r[b]; break;
          case MOV_I: r[a] = b; break;
          case CMP_R: flags = r[a] > r[b] ? 1 : r[a] < r[b] ? -1 : 0; break;
          case CMP_I: flags = r[a] > b ? 1 : r[a] < b ? -1 : 0; break;
          case ADD_R: r[a] = r[a] + r[b]; break;
          case ADD_I: r[a] = r[a] + b; break;
          case AND_R: r[a] = r[a] & r[b]; break;
          case AND_I: r[a] = r[a] & b; break;
          case OR_R: r[a] = r[a] | r[b]; break;
          case SHL: r[a] = r[a] << b; break;
          case SHR: r[a] = r[a] >>> b; break;
          case LDC: r[a] = 0xffff; break;               /* bank-0 constants: none in our programs */
          case LD_ABS: r[a] = ram[b]; nxt = pc + 2; break;
          case LD_R1: r[a] = ram[(r[1] + b) & 0xffff]; break;
          case LD_FP: r[a] = ram[(fp + b) & 0xffff]; break;
          case ST_ABS: ram[b] = r[a]; nxt = pc + 2; break;
          case ST_R1: ram[(r[1] + b) & 0xffff] = r[a]; break;
          case ST_FP: ram[(fp + b) & 0xffff] = r[a]; break;
          case LI: r[a] = b; nxt = pc + 2; break;
          case ADDI: r[a] = r[a] + b; nxt = pc + 2; break;
          case JMP: nxt = b; break;
          case BEQ: if (flags === 0) nxt = b; break;
          case BNE: if (flags !== 0) nxt = b; break;
          case BLT: if (flags < 0) nxt = b; break;
          case LJMP: nxt = b; break;
          case CALL: {
            const name = this.nativeAt[b];
            if (name !== undefined) {
              this.flags = flags;
              const f = this.natives[name];
              if (!f) throw new P16Error("native " + name + " missing");
              f(this);
              flags = this.flags;
              nxt = pc + 2;
            } else {
              stack.push(pc + 2);
              nxt = b;
            }
            break;
          }
          default:
            this.steps += steps;
            throw new P16Error("instruction not simulated at 0x" + pc.toString(16));
        }
        pc = nxt;
      }
    }
  }

  /* The ray program's natives (the asm glue in firmware/ray.py), with hooks for the page. */
  function rayNatives(hooks) {
    hooks = hooks || {};
    return {
      trace: (m) => hooks.trace && hooks.trace(m.r[7]),                 /* r7 = the marker */
      farcopy: (m) => {
        let dst = m.get("fr_dst"), hi = m.get("fr_hi"), lo = m.get("fr_lo");
        const n = m.get("fr_n");
        if (m.get("fr_mode") !== 0) [hi, lo] = [lo, hi];   /* layout 1 is the wrong one on the piano */
        let addr = hi * 65536 + lo;
        for (let k = 0; k < n; k++) m.wr(dst + k, m.farRead(addr + k));
      },
      synth: (m) => {
        const st = m.r[7], data = m.r[6];                 /* CIN << 8 | status, d1 << 8 | d2 */
        hooks.synth && hooks.synth(st & 0xff, data >> 8, data & 0xff);
      },
      fr_init: (m) => { for (const [a, v] of m.prog.fr_init) m.wr(a, v); },
      mdiag: (m) => {
        const dv = m.sym("dv");
        const p = [0x0060, 0x0626, 0xaaaa, 0xbbbb, 0xcccc, 0xdddd, 0xeeee, 0x9999];   /* as the piano sent */
        p.forEach((v, k) => m.wr(dv + 20 + k, v));
      },
      ljtest: (m) => m.wr(m.sym("lj"), 1),
    };
  }

  const api = { P16, P16Error, rayNatives };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else Object.assign(root, api);
})(typeof window !== "undefined" ? window : globalThis);
