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
#define FRAME_TICKS 5
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

void column(int x, int top, int bot, int side)
{
    int p, lo, hi;
    unsigned m, pat;
    pat = 0xff;
    if (side) pat = (x & 1) ? 0x55 : 0xaa;
    for (p = 0; p < 8; p++) {
        lo = top - p * 8;
        hi = bot - p * 8;
        if (lo < 0) lo = 0;
        if (hi > 8) hi = 8;
        m = 0;
        if (lo < hi) m = ((0xff << lo) & (0xff >> (8 - hi))) & pat;
        framebuffer[p * W + x] = m;
    }
}

void render(void)
{
    int x, dirx, diry, plx, ply, cam, rx, ry, mx, my, sx, sy, side, n, h, top;
    unsigned ddx, ddy, sdx, sdy, perp, ax, ay;
    dirx = icos(pa);
    diry = isin(pa);
    plx = fmul(-diry, 170);                     /* camera plane, 0.66 = a 66 degree view */
    ply = fmul(dirx, 170);
    for (x = 0; x < W; x++) {
        cam = x * 4 - 256;
        rx = dirx + fmul(plx, cam);
        ry = diry + fmul(ply, cam);
        mx = px >> 8;
        my = py >> 8;
        ax = rx < 0 ? -rx : rx;
        ay = ry < 0 ? -ry : ry;
        ddx = ax ? 65535u / ax : 0x7fff;
        ddy = ay ? 65535u / ay : 0x7fff;
        if (ddx > 0x7fff) ddx = 0x7fff;
        if (ddy > 0x7fff) ddy = 0x7fff;
        if (rx < 0) { sx = -1; sdx = fmul(px & 255, ddx); }
        else { sx = 1; sdx = fmul(256 - (px & 255), ddx); }
        if (ry < 0) { sy = -1; sdy = fmul(py & 255, ddy); }
        else { sy = 1; sdy = fmul(256 - (py & 255), ddy); }
        side = 0;
        for (n = 0; n < 40; n++) {
            if (sdx < sdy) { sdx += ddx; mx += sx; side = 0; }
            else { sdy += ddy; my += sy; side = 1; }
            if (wall(mx, my)) break;
        }
        perp = side ? sdy - ddy : sdx - ddx;
        if (perp < 256) h = H;
        else h = 16384u / perp;
        if (h > H) h = H;
        top = (H - h) >> 1;
        column(x, top, top + h, side);
    }
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

void frame(void)
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
    render();
    number(0, 0, dt, 3);                        /* last frame's time, ~ms */
    if (!st_ok) {
        number(0, 1, st_val, 5);
    }
    LCD_FLAG = LCD_FLAG | 1;
    nframe++;
}

int selftest(void)
{
    unsigned h = 1;
    int i, a = -1234;
    for (i = 0; i < 40; i++) {
        h = h * 31 + (unsigned)i;
        h = h ^ (h >> 5);
        a = a * 3 / 7 + i * 13 - a % 11;
        h += (unsigned)a;
        h += fmul(a, i * 37);
        h += (unsigned)(a >> 2);
        h += isin(i * 7) + (unsigned)(i << 9) / 3;
    }
    return h;
}

void rc_start(void)
{
    px = 384;
    py = 384;
    pa = 0;
    st_val = selftest();
    st_ok = st_val == SELFTEST_EXPECT;
    frame();
}

void rc_tick(void)
{
    if (drew) {                                 /* the clock moved past the frame drawn last tick */
        dt = now() - t0;
        drew = 0;
    }
    ticks++;
    if (ticks >= FRAME_TICKS) {
        ticks = 0;
        t0 = now();
        frame();
        drew = 1;
    }
}

void rc_key(int note, int vel)
{
    int k = note - 47;
    if (k < 0 || k > 15) return;
    if (vel) held = held | (1 << k);
    else held = held & ~(1 << k);
}
