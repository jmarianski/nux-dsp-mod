/* A raycaster for the NEK-100's 128x64 LCD, compiled by cc/p16cc.py (16-bit ints, static frames).
 *
 * Fixed point 8.8 (256 = one map cell or 1.0), angles 0..255 for a full turn. Walls: side 0 (x faces) solid,
 * side 1 (y faces) a checkerboard, so corners read on a one-bit screen. The asm glue (ray.py) calls
 * rc_start once, rc_tick every 10 ms tick and rc_key for every note; the framebuffer goes to the LCD when
 * LCD_FLAG bit 0 is set. ray.py prepends: #define SELFTEST_EXPECT <value the simulator computed>.
 */
extern unsigned framebuffer[];                 /* 0x662a: 8 pages x 128 columns, bit 0 = top row of the page */
#define LCD_FLAG (*(unsigned *)0x6a50)
#define CLOCK_LO (*(unsigned *)0x6d78)         /* the main loop's clock, us; moves between ticks only */
#define CLOCK_HI (*(unsigned *)0x6d79)

#define W 128
#define H 64
#define MAPN 16

/* keys: bit k = MIDI note 47 + k held */
#define K_STRAFE_L 0    /* B2 */
#define K_LEFT 1        /* C3 */
#define K_FWD 2         /* C#3 */
#define K_BACK 3        /* D3 */
#define K_FWD2 4        /* D#3 */
#define K_RIGHT 5       /* E3 */
#define K_STRAFE_R 6    /* F3 */

/* prepended by ray.py: unsigned map[16] (bit x of row y = wall), int sintab[65] (256 * sin(i * pi / 128)),
 * unsigned digits[30] (3x5 digits, 3 columns each, bit 0 = top) */

int px, py, pa;                 /* player: 8.8 cells, angle */
unsigned held;
int ticks, drew, t0, dt, st_val, st_ok, nframe;
int lj;                                         /* the ljmp test (C8): 1 = came back */
void ljtest(void);                              /* asm (ray.py) */
void trace(int v);                              /* asm (ray.py): a marker to the host, one per tick over USB MIDI */
int stage;

int isin(int a)
{
    a = a & 255;
    if (a < 64) return sintab[a];
    if (a < 128) return sintab[128 - a];
    if (a < 192) return -sintab[a - 128];
    return -sintab[256 - a];
}

int icos(int a) { return isin(a + 64); }

/* (a * b) >> 8 with a 32-bit product, from 8-bit halves */
int fmul(int a, int b)
{
    int neg = 0;
    unsigned x, y, xh, xl, yh, yl, r;
    if (a < 0) { a = -a; neg = 1; }
    if (b < 0) { b = -b; neg = !neg; }
    x = a; y = b;
    xh = x >> 8; xl = x & 255; yh = y >> 8; yl = y & 255;
    r = ((xh * yh) << 8) + xh * yl + xl * yh + ((xl * yl) >> 8);
    if (neg) return -r;
    return r;
}

int wall(int x, int y)
{
    if (x < 0 || y < 0 || x >= MAPN || y >= MAPN) return 1;
    return (map[y] >> x) & 1;
}

unsigned now(void) { return (CLOCK_HI << 6) | (CLOCK_LO >> 10); }   /* ~1.024 ms units */

unsigned span(int lo, int hi)                   /* rows lo..hi-1 of one page (8 rows) */
{
    if (lo < 0) lo = 0;
    if (hi > 8) hi = 8;
    if (lo >= hi) return 0;
    return (0xff << lo) & (0xff >> (8 - hi));
}

void column(int x, int top, int bot, int side)
{
    int p;
    unsigned pat;
    pat = 0xff;
    if (side) pat = (x & 1) ? 0x55 : 0xaa;
    for (p = 0; p < 8; p++) framebuffer[p * W + x] = span(top - p * 8, bot - p * 8) & pat;
}

/* One column, split in pieces so that every jump stays short (ljmp is not confirmed on the device). */
int rdx, rdy, rpx, rpy;                         /* view direction and camera plane of this frame */
int mx, my, sx, sy, side;
unsigned ddx, ddy, sdx, sdy;

unsigned inv(int r)                             /* 1 / |r| in 8.8, at most 0x7fff */
{
    unsigned a, d;
    a = r < 0 ? -r : r;
    if (a < 3) return 0x7fff;
    d = 65535u / a;
    if (d > 0x7fff) d = 0x7fff;
    return d;
}

void setup(int rx, int ry)
{
    mx = px >> 8;
    my = py >> 8;
    ddx = inv(rx);
    ddy = inv(ry);
    if (rx < 0) { sx = -1; sdx = fmul(px & 255, ddx); }
    else { sx = 1; sdx = fmul(256 - (px & 255), ddx); }
    if (ry < 0) { sy = -1; sdy = fmul(py & 255, ddy); }
    else { sy = 1; sdy = fmul(256 - (py & 255), ddy); }
}

void dda(void)
{
    int n;
    side = 0;
    for (n = 0; n < 40; n++) {
        if (sdx < sdy) { sdx += ddx; mx += sx; side = 0; }
        else { sdy += ddy; my += sy; side = 1; }
        if (wall(mx, my)) return;
    }
}

void cast(int x)
{
    int cam, h, top;
    unsigned perp;
    cam = x * 4 - 256;
    setup(rdx + fmul(rpx, cam), rdy + fmul(rpy, cam));
    dda();
    perp = side ? sdy - ddy : sdx - ddx;
    if (perp < 256) h = H;
    else h = 16384u / perp;
    if (h > H) h = H;
    top = (H - h) >> 1;
    column(x, top, top + h, side);
}

void view(void)
{
    rdx = icos(pa);
    rdy = isin(pa);
    rpx = fmul(-rdy, 170);                      /* camera plane, 0.66 = a 66 degree view */
    rpy = fmul(rdx, 170);
}

#define PARTS 8                                 /* a frame is drawn over 8 ticks, 16 columns each */

void render_part(int c)
{
    int x;
    for (x = c * (W / PARTS); x < (c + 1) * (W / PARTS); x++) cast(x);
}

void render(void)
{
    int c;
    view();
    for (c = 0; c < PARTS; c++) render_part(c);
}

void digit(int x, int page, int d)
{
    int c;
    for (c = 0; c < 3; c++) framebuffer[page * W + x + c] = digits[d * 3 + c] << 1;
    framebuffer[page * W + x + 3] = 0;
}

void number(int x, int page, unsigned v, int n)
{
    int k;
    for (k = n - 1; k >= 0; k--) {
        digit(x + k * 4, page, v % 10);
        v = v / 10;
    }
}

void move(int dx, int dy)
{
    int nx, ny;
    nx = px + dx;
    ny = py + dy;
    if (!wall(nx >> 8, py >> 8)) px = nx;
    if (!wall(px >> 8, ny >> 8)) py = ny;
}

void steer(void)
{
    int dirx, diry, sp;
    if (held & (1 << K_LEFT)) pa = pa - 4;
    if (held & (1 << K_RIGHT)) pa = pa + 4;
    pa = pa & 255;
    dirx = icos(pa);
    diry = isin(pa);
    sp = 40;
    if (held & ((1 << K_FWD) | (1 << K_FWD2))) move(fmul(dirx, sp), fmul(diry, sp));
    if (held & (1 << K_BACK)) move(-fmul(dirx, sp), -fmul(diry, sp));
    if (held & (1 << K_STRAFE_L)) move(fmul(diry, sp), -fmul(dirx, sp));
    if (held & (1 << K_STRAFE_R)) move(-fmul(diry, sp), fmul(dirx, sp));
    view();
}

void finish(void)
{
    number(0, 0, dt, 3);                        /* last frame's time, ~ms */
    if (lj) digit(124, 7, lj);                  /* the ljmp test came back */
    if (!st_ok) {
        number(0, 1, st_val, 5);
    }
    LCD_FLAG = LCD_FLAG | 1;
    nframe++;
    trace(0x400 + (nframe & 0xff));
}

void frame(void)                                /* all of it at once (the simulator's tests) */
{
    int c;
    steer();
    for (c = 0; c < PARTS; c++) render_part(c);
    finish();
}

unsigned sth;
int sta;

void st_step(int i)
{
    sth = sth * 31 + (unsigned)i;
    sth = sth ^ (sth >> 5);
    sta = sta * 3 / 7 + i * 13 - sta % 11;
    sth += (unsigned)sta;
    sth += fmul(sta, i * 37);
    sth += (unsigned)(sta >> 2);
    sth += isin(i * 7) + (unsigned)(i << 9) / 3;
}

int selftest(void)
{
    int i;
    sth = 1;
    sta = -1234;
    for (i = 0; i < 40; i++) st_step(i);
    return sth;
}

/* Diagnostics, sent to the host before the game: dv[0..15] raw results of single instructions (asm, ray.py's
 * adiag), dv[16..] C operations, each a word that the simulator computes too (ray.py --diag). */
#define NDV 32
unsigned dv[NDV];
int dn;
void adiag(void);                               /* asm (ray.py) */
/* Far reads (asm farcopy: fr_n words from program address fr_hi:fr_lo to RAM fr_dst through the firmware's copy
 * 0x7638). The pointer's two halves go to the stack frame in an order not known yet: fr_mode 0 or 1, tried on test
 * patterns (word i of pattern k = 0x1357 * (k + 1) + 0x0f1d * i) right after our code (0), at 0x28000 (1) and at
 * 0x3f000 (2), near the end of the 512 KB partition. */
unsigned fr_dst, fr_hi, fr_lo, fr_n, fr_mode;
void farcopy(void);                             /* asm (ray.py) */
void fr_init(void);                             /* asm: pt_hi/pt_lo and mu_shi/mu_slo */
void synth(int status, int data);               /* asm: synth_send(CIN << 8 | status, d1 << 8 | d2) */
unsigned pt_hi[3], pt_lo[3];
unsigned fbuf[16];
int fmode;                                      /* the layout that read pattern 0 right, -1 none */

int far_test(int k, int mode)                   /* -> how many of the 8 words came right */
{
    int i, n;
    for (i = 0; i < 16; i++) fbuf[i] = 0xdead;
    fr_dst = (unsigned)fbuf;
    fr_hi = pt_hi[k];
    fr_lo = pt_lo[k];
    fr_n = 8;
    fr_mode = mode;
    farcopy();
    n = 0;
    for (i = 0; i < 8; i++) if (fbuf[i] == 0x1357 * (k + 1) + 0x0f1d * i) n++;
    return n;
}

/* Music: the stream of tools/wad.py (two words an event: wait << 8 | status, d1 << 8 | d2; 0x00ff = again) */
unsigned mu_shi, mu_slo, mu_hi, mu_lo, mu_wait;
unsigned mbuf[16];
int mu_i, mu_ok;

unsigned mword(void)
{
    if (mu_i >= 16) {
        fr_dst = (unsigned)mbuf;
        fr_hi = mu_hi;
        fr_lo = mu_lo;
        fr_n = 16;
        fr_mode = fmode;
        farcopy();
        mu_lo += 16;
        if (mu_lo < 16) mu_hi++;
        mu_i = 0;
    }
    return mbuf[mu_i++];
}

void mu_restart(void)
{
    mu_hi = mu_shi;
    mu_lo = mu_slo;
    mu_i = 16;
    mu_wait = 0;
}

void mu_tick(void)
{
    unsigned w0, w1, st;
    int n;
    if (!mu_ok) return;
    if (mu_wait) {
        mu_wait--;
        if (mu_wait) return;
    }
    for (n = 0; n < 64; n++) {
        w0 = mword();
        w1 = mword();
        st = w0 & 255;
        if (st == 255) {
            mu_restart();
            return;
        }
        if (st) synth((st >> 4) << 8 | st, w1);
        mu_wait = w0 >> 8;
        if (mu_wait) return;
    }
}

void mu_stop(void)                              /* a panel key leaves the game: all notes off */
{
    int c;
    mu_ok = 0;
    for (c = 0; c < 16; c++) {
        synth(0x0bb0 | c, 123 << 8);
        synth(0x0bb0 | c, 120 << 8);
    }
}

void cdiag(void)
{
    fr_init();
    dv[16] = far_test(0, 0);
    dv[17] = fbuf[0];
    dv[18] = far_test(0, 1);
    dv[19] = fbuf[0];
    fmode = -1;
    if (dv[16] == 8) fmode = 0;
    else if (dv[18] == 8) fmode = 1;
    dv[20] = 0xeeee; dv[21] = 0xeeee; dv[22] = 0xeeee; dv[23] = 0xeeee;
    if (fmode >= 0) {
        dv[20] = far_test(1, fmode);
        dv[21] = fbuf[0];
        dv[22] = far_test(2, fmode);
        dv[23] = fbuf[0];
        mu_restart();
        mu_ok = 1;
    }
    dv[24] = fmode;
    dv[25] = mu_shi;
    dv[26] = mu_slo;
    dv[27] = pt_hi[2];
    dv[28] = pt_lo[2];
    dv[29] = pt_hi[0];
    dv[30] = selftest();
    dv[31] = 0x1234;
}

int dv_marker(int n)                            /* 0x2000 | (k & 15) << 8 | high, then 0x3000 | ... | low */
{
    int k = n >> 1;
    if (n & 1) return 0x3000 | (k & 15) << 8 | (dv[k] & 255);
    return 0x2000 | (k & 15) << 8 | dv[k] >> 8;
}

int send_dv(void)                               /* one marker a tick */
{
    if (dn < 2 * NDV) {
        trace(dv_marker(dn));
        dn++;
        return 0;
    }
    st_val = selftest();
    st_ok = st_val == SELFTEST_EXPECT;
    trace(0x300 + st_ok);
    ticks = 0;
    return 1;
}

void rc_start(void)
{
    px = 384;
    py = 384;
    pa = 0;
    stage = 0;
}

void rc_tick(void)
{
    if (stage == 0) {                           /* one step per tick, each followed by a marker */
        adiag();
        cdiag();
        dn = 0;
        stage = 1;
        return;
    }
    if (stage == 1) {
        if (send_dv()) stage = 2;
        return;
    }
    mu_tick();
    if (drew) {                                 /* the clock moved past the part drawn last tick */
        dt = now() - t0;
        drew = 0;
    }
    t0 = now();
    drew = 1;
    if (ticks == 0) steer();
    trace(0x500 + ticks);                       /* part ticks starts */
    render_part(ticks);
    ticks++;
    if (ticks == PARTS) {
        finish();
        ticks = 0;
    }
}

void rc_key(int note, int vel)
{
    int k = note - 47;
    if (note == 108 && vel) ljtest();           /* C8 */
    if (k < 0 || k > 15) return;
    if (vel) held = held | (1 << k);
    else held = held & ~(1 << k);
}
