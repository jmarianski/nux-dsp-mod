/* E1M1 BSP renderer for the P16 (16-bit int, static frames), shared with the browser.
 * Map records live in far program memory, not RAM. The builder supplies the sine table,
 * map addresses, root and player start. Collision uses linedefs and a far blockmap.
 * Window bounds use one word per column; no full-screen depth buffer or recursion.
 */
extern unsigned framebuffer[];
#define LCD_FLAG (*(unsigned *)0x6a50)
#define CLOCK_LO (*(unsigned *)0x6d78)
#define CLOCK_HI (*(unsigned *)0x6d79)
#define NEAR 17

unsigned fr_dst, fr_hi, fr_lo, fr_n, fr_mode;
int fmode;
void farcopy(void);
void fr_init(void);
void synth(int status, int data);
void trace(unsigned value);

/* MUSIC_SOURCE: inserted by ray.py / doom.py, shared by both engines. */

int px, py, pz, pa, eye, cs, sn;
int view_x, view_y, render_context, render_height[8];
unsigned render_state, render_seg, render_last, render_end;
int render_actor, render_row, render_kind, render_pass, render_previous, render_previous_i;
unsigned logic_epoch, callback_stage;
unsigned callback_count;
unsigned held, nframe, ticks;
unsigned windows[128], stack[32], sp, open_columns;
unsigned map_hi[13], map_lo[13], buf[6];
unsigned prod_hi, prod_lo;
unsigned work;                                  /* frame_work's budget counter, ~64 instructions a unit */
int move_x, move_y, move_floor, move_ceiling;
int vx, vz;

/* GAME_SOURCE: inserted by doom.py. */

/* The arithmetic is three quarters of a frame, so it is hand-written P16 (firmware/mathasm.py, inserted by
 * doom.py): four hardware 8x8 multiplies per 32-bit product, an unrolled 32/16 division. Semantics as the C it
 * replaced (git history), checked against Python in tests/test_mathasm.py. */
void umul32(unsigned a, unsigned b) { /* ASM umul32 */ }   /* prod_hi:prod_lo = a * b */
void smul32(int a, int b) { /* ASM smul32 */ }             /* prod_hi:prod_lo = a * b, signed */
int fmul(int a, int b) { /* ASM fmul */ return 0; }       /* (a*b)/256, toward zero */
int muldiv(int a, int b, int c) { /* ASM muldiv */ return 0; }   /* a*b/c, toward zero, saturated to +-32767 */

int isin(int a)
{
    int n, neg;
    a = a & 255;
    neg = a >= 128;
    n = a & 127; if (n > 64) n = 128 - n;
    readmap(7, n, 1);
    return neg ? -(int)buf[0] : (int)buf[0];
}

int clamp(int x, int lo, int hi) { return x < lo ? lo : x > hi ? hi : x; }

/* table: vertices=0, nodes=1, subsecs=2, segs=3, sectors=4; at is a word offset */
void readmap(int table, unsigned at, int count)
{
    fr_lo = map_lo[table] + at;
    fr_hi = map_hi[table] + (fr_lo < map_lo[table]);
    fr_dst = (unsigned)buf; fr_n = count; fr_mode = 0;
    farcopy();
    work++;
}

void read_sector(unsigned k)
{
    readmap(4, k * 3, 3);
    sector_override();
}

int side_of(int x, int y, int dx, int dy)        /* which side of an oriented line through (0,0)? */
{
    int ah;
    unsigned al;
    smul32(y, dx);
    ah = prod_hi; al = prod_lo;
    smul32(dy, x);
    if (ah != (int)prod_hi) return ah > (int)prod_hi;
    return al >= prod_lo;
}

int point_side_at(int x, int y)                 /* node record already in buf */
{
    return side_of(x - (int)buf[0], y - (int)buf[1], (int)buf[2], (int)buf[3]);
}

int sector_at(int x, int y)
{
    unsigned n = MAP_ROOT;
    while (!(n & 0x8000)) {
        readmap(1, n * 14, 6);
        n = buf[4 + point_side_at(x, y)];
    }
    readmap(2, (n & 0x7fff) * 3, 3);
    return buf[2];
}

void view_point(int x, int y)
{
    int dx, dy;
    dx = x - view_x; dy = y - view_y;
    vx = fmul(dx, sn) - fmul(dy, cs);
    vz = fmul(dx, cs) + fmul(dy, sn);
}

void view_vertex(unsigned v)
{
    readmap(0, v * 2, 2); view_point((int)buf[0], (int)buf[1]);
}

int x1, z1, x2, z2, sx1, sx2, s1, s2;
int ff, fc, fl, bf, bc, corner;
unsigned back_sector;
int tex_u1, tex_u2, tex_top, tex_width, tex_height;
unsigned tex_base, tex_runs[8];
int tex_on, tex_count, tex_scale, tex_fill;
unsigned middle_material, upper_material, lower_material;
/* A descriptor is valid only for this segment's clipped endpoints and sector heights. */
unsigned cached_material;
int clip_u1, clip_u2;

void seg_data(unsigned k)
{
    unsigned v1, v2, front, material;
    readmap(3, k * 5, 5);
    v1 = buf[0]; v2 = buf[1]; front = buf[2]; back_sector = buf[3]; corner = buf[4] & 1; material = buf[4] >> 1;
    view_vertex(v1); x1 = vx; z1 = vz;
    view_vertex(v2); x2 = vx; z2 = vz;
    read_sector(front); ff = buf[0]; fc = buf[1]; fl = buf[2];
    if (back_sector != 0xffff) {
        read_sector(back_sector); bf = buf[0]; bc = buf[1];
    }
    middle_material = upper_material = lower_material = 0;
    cached_material = 0;
    if (material) {
        readmap(12, material, 3);
        middle_material = buf[0]; upper_material = buf[1]; lower_material = buf[2];
    }
}

int project(void)
{
    if (z1 < NEAR && z2 < NEAR) return 0;
    clip_u1 = 0; clip_u2 = 16384;
    if (z1 < NEAR) {
        clip_u1 = muldiv(NEAR - z1, 16384, z2 - z1);
        x1 += muldiv(x2 - x1, NEAR - z1, z2 - z1); z1 = NEAR;
    } else if (z2 < NEAR) {
        clip_u2 -= muldiv(NEAR - z2, 16384, z1 - z2);
        x2 += muldiv(x1 - x2, NEAR - z2, z1 - z2); z2 = NEAR;
    }
    sx1 = 64 + clamp(muldiv(x1, 64, z1), -16000, 16000);
    sx2 = 64 + clamp(muldiv(x2, 64, z2), -16000, 16000);
    if (sx1 >= sx2 || sx2 <= 0 || sx1 >= 128) return 0;
    s1 = muldiv(8192, 64, z1); s2 = muldiv(8192, 64, z2);
    return 1;
}

int screen_y(int h, int s)
{
    int q;
    /* ASM screen_y */
    smul32(h - eye, s);                         /* |h - eye| >= 256: the full product */
    q = (prod_lo >> 13) | (prod_hi << 3);  /* arithmetic product >> 13 */
    return 32 - clamp(q, -1000, 1000);
}

int shade(int light, unsigned s)
{
    int b = ((light - 128) >> 4) + ((s >> 9) > 8 ? 8 : (s >> 9));
    return b >= 10 ? 3 : b >= 6 ? 2 : b >= 3 ? 1 : 0;
}

unsigned span(int lo, int hi)
{
    lo = clamp(lo, 0, 8); hi = clamp(hi, 0, 8);
    if (lo >= hi) return 0;
    return (255 << lo) & (255 >> (8 - hi));
}

int col, top, bot, sh, edge;
void wall_page(int p, int a, int b, int lo, int hi)
{
    unsigned bits;
    bits = 0;
    if (tex_on) {
        if (tex_fill && !(col & 1)) bits = span(lo - p * 8, hi - p * 8) & 0x55;
    }
    else if (sh == 3 || (sh == 2 && (col & 3)) || (sh == 1 && !(col & 1)) || (sh == 0 && !(col & 3)))
        bits = span(lo - p * 8, hi - p * 8);
    if (a >= lo && a < hi && (a >> 3) == p) bits |= 1 << (a & 7);
    if (b - 1 >= lo && b - 1 < hi && ((b - 1) >> 3) == p) bits |= 1 << ((b - 1) & 7);
    framebuffer[p * 128 + col] |= bits;
}

void wall(int a, int b)
{
    int lo, hi, p;
    if (edge) return;
    lo = a > top ? a : top; hi = b < bot ? b : bot;
    if (lo >= hi) return;
    work += (hi - lo) >> 2;
    for (p = lo >> 3; p <= (hi - 1) >> 3; p++) wall_page(p, a, b, lo, hi);
}

void load_material(unsigned material)
{
    int u, du, anchor;
    readmap(12, material, 6);
    tex_base = buf[0]; u = buf[1]; du = (int)buf[2] - u;
    tex_u1 = clip_u1 ? u + muldiv(du, clip_u1, 16384) : u;               /* clipped by the near plane: rare */
    tex_u2 = clip_u2 != 16384 ? u + muldiv(du, clip_u2, 16384) : u + du;
    tex_width = buf[4] & 127; tex_height = buf[4] >> 8; tex_fill = buf[4] & 128; anchor = buf[5];
    tex_top = (anchor == 1 ? bc + tex_height * 4 : anchor == 2 ? ff + tex_height * 4 : anchor == 3 ? bf : fc) + (int)buf[3];
    cached_material = material;
}

void material_column(unsigned material, int s)
{
    int u, n;
    work++;
    if (cached_material != material) { load_material(material); work += 2; }
    tex_on = 1; tex_scale = s;
    if (s < 1024) return;                       /* far: texture_runs draws no detail, the fill needs no column */
    u = tex_u1 + muldiv(tex_u2 - tex_u1, muldiv(col - sx1, s2, sx2 - sx1), s);
    n = tex_base + ((u >> 2) & tex_width) * 9;
    readmap(12, n, 6); tex_count = buf[0];
    for (u = 0; u < 5; u++) tex_runs[u] = buf[u + 1];
    if (tex_count > 5) {
        readmap(12, n + 6, 3);
        for (u = 0; u < 3; u++) tex_runs[u + 5] = buf[u];
    }
    tex_on = 1; tex_scale = s;
}

void texture_run(int tile, int run, int lo, int hi)
{
    int a, b, p;
    work++;
    a = screen_y(tile - (tex_runs[run] & 255) * 4, tex_scale);
    b = screen_y(tile - (tex_runs[run] >> 8) * 4, tex_scale);
    if (a < lo) a = lo; if (b > hi) b = hi;
    if (a >= b) return;
    for (p = a >> 3; p <= (b - 1) >> 3; p++) framebuffer[p * 128 + col] |= span(a - p * 8, b - p * 8);
}

void texture_runs(int a, int b)
{
    int lo, hi, tile, v, n, run;
    lo = a > top ? a : top; hi = b < bot ? b : bot;
    if (lo >= hi || tex_scale < 1024) return; /* subpixel detail: keep a calm base tone */
    v = tex_top - eye + muldiv(lo - 32, 8192, tex_scale);
    tile = tex_top - (v >> 7) * 128;
    for (n = 0; n < 6 && screen_y(tile, tex_scale) < hi; n++) {
        for (run = 0; run < tex_count; run++) texture_run(tile, run, lo, hi);
        tile -= 128;
    }
}

void material_wall(int a, int b, unsigned material, int s)
{
    if (a >= bot || b <= top || edge) return;
    if (material) material_column(material, s);
    wall(a, b);
    if (material) texture_runs(a, b);
    tex_on = 0;
}

void draw_column(void)
{
    int s, yc, yf, ybc, ybf, nt, nb;
    if (windows[col] & 0x8000) return;
    top = windows[col] & 127; bot = windows[col] >> 7;
    if (top >= bot) return;
    s = s1 + muldiv(s2 - s1, col - sx1, sx2 - sx1);
    yc = screen_y(fc, s); yf = screen_y(ff, s);
    work += 2;
    sh = shade(fl, s); edge = corner && col == sx1;
    tex_on = 0;
    if (back_sector == 0xffff) {
        material_wall(yc, yf, middle_material, s); windows[col] = 0x8000 | s; open_columns--; return;
    }
    ybc = screen_y(bc, s); ybf = screen_y(bf, s);
    if (bc < fc) material_wall(yc, ybc, upper_material, s);
    if (bf > ff) material_wall(ybf, yf, lower_material, s);
    nt = top > yc ? top : yc; if (ybc > nt) nt = ybc;
    nb = bot < yf ? bot : yf; if (ybf < nb) nb = ybf;
    if (bc <= bf || nt >= nb) { windows[col] = 0x8000 | s; open_columns--; }
    else windows[col] = nt | (nb << 7);
}

void draw_seg(unsigned k)
{
    int end;
    seg_data(k);
    if (!project()) return;
    end = sx2 > 128 ? 128 : sx2;
    for (col = sx1 < 0 ? 0 : sx1; col < end; col++) draw_column();
}

void subsec(unsigned n)
{
    unsigned first, end, k;
    readmap(2, n * 3, 3); first = buf[0]; end = first + buf[1];
    for (k = first; k < end; k++) draw_seg(k);
}

void frame_begin(void)
{
    unsigned k;
    view_x = px; view_y = py;
    cs = isin(pa + 64); sn = isin(pa);
    eye = pz + 41;
    for (k = 0; k < 8; k++) render_height[k] = dynamic_height[k];
    for (k = 0; k < 1024; k++) framebuffer[k] = 0;
    for (k = 0; k < 128; k++) windows[k] = 64 << 7;
    sp = 1; stack[0] = MAP_ROOT; open_columns = 128;
    render_seg = render_last = render_end = col = 0;
    render_actor = render_row = render_kind = render_pass = 0;
    render_previous = 32767; render_previous_i = -1;
    render_state = 1;
}

/* Yield only at complete operations: no C local frame or map buffer survives a tick. */
int bbox_lo, bbox_hi, bbox_near, bbox_mask;

void bbox_corner(int x, int y)
{
    view_point(x, y);
    if (vz >= NEAR) bbox_mask &= ~1;
    if (vx >= -vz) bbox_mask &= ~2;
    if (vx <= vz) bbox_mask &= ~4;
    if (vz < NEAR) bbox_near = 1;
    else {
        x = 64 + clamp(muldiv(vx, 64, vz), -16000, 16000);
        if (x < bbox_lo) bbox_lo = x; if (x > bbox_hi) bbox_hi = x;
    }
}

int bbox_visible(unsigned n, unsigned side)
{
    int left, right, bottom, top, x;
    readmap(1, n * 14 + 6 + side * 4, 4);
    top = buf[0]; bottom = buf[1]; left = buf[2]; right = buf[3];
    if (view_x >= left && view_x <= right && view_y >= bottom && view_y <= top) return 1;
    bbox_lo = 128; bbox_hi = 0; bbox_near = 0; bbox_mask = 7;
    bbox_corner(left, top); bbox_corner(right, top);
    bbox_corner(left, bottom); bbox_corner(right, bottom);
    if (bbox_mask) return 0;
    if (bbox_near) return 1;
    bbox_lo = clamp(bbox_lo - 1, 0, 127); bbox_hi = clamp(bbox_hi + 1, 0, 127);
    for (x = bbox_lo; x <= bbox_hi; x++) if (!(windows[x] & 0x8000)) return 1;
    return 0;
}

void bsp_work(void)
{
    unsigned n, side, front, back;
    while (col < render_end && (windows[col] & 0x8000)) col++;
    if (col < render_end && open_columns) { draw_column(); col++; return; }
    if (render_seg < render_last && open_columns) {
        seg_data(render_seg++);
        col = render_end = 0;
        if (project()) { col = sx1 < 0 ? 0 : sx1; render_end = sx2 > 128 ? 128 : sx2; }
        return;
    }
    if (!sp || !open_columns) { render_state = game_visible ? 2 : 5; return; }
    n = stack[--sp];
    if (n & 0x8000) {
        readmap(2, (n & 0x7fff) * 3, 3); render_seg = buf[0]; render_last = render_seg + buf[1];
    } else {
        readmap(1, n * 14, 6); side = point_side_at(view_x, view_y);
        front = buf[4 + side]; back = buf[4 + (side ^ 1)];
        if (bbox_visible(n, side ^ 1)) stack[sp++] = back;
        if (bbox_visible(n, side)) stack[sp++] = front;
    }
}

/* A tick's share of the frame, in work units of ~64 instructions: the asm arithmetic and the map reads count
 * themselves, the rest is a base price per operation (calibrated on E1M1 with tools/profile.cjs). The piano keeps
 * up with ~130k instructions a tick (the raycaster); beyond that the firmware falls behind on keys and the LCD. */
#define FRAME_BUDGET 1200

unsigned tick_start;                            /* work when this tick began: logic and render share the budget */

void frame_work(void)
{
    render_context = 1;
    while (render_state && work - tick_start < FRAME_BUDGET) {
        work += 2;
        if (render_state == 1) bsp_work();
        else if (render_state == 2) { if (render_kind) work += 60; pickup_draw_work(); }
        else if (render_state == 3) { if (render_kind) work += 60; enemy_draw_work(); }
        else if (render_state == 4) { draw_overlay(); render_state = 5; work += 270; }
        else { nframe++; LCD_FLAG = LCD_FLAG | 1; render_state = 0; }
    }
    render_context = 0;
}

/* Synchronous reference/screenshot entry. Hardware callbacks never call this. */
void frame(void)
{
    frame_begin();
    while (render_state) { tick_start = work; frame_work(); }
}

/* Doom-sized player box: radius 16, height 56, maximum step 24. Each attempted
 * position collects the highest floor / lowest ceiling under the whole box.
 * The box can straddle a portal before its centre changes subsector.
 */
int box_crosses(int x1, int y1, int x2, int y2)
{
    int dx, dy, a, b;
    if (move_x + 16 <= (x1 < x2 ? x1 : x2) || move_x - 16 >= (x1 > x2 ? x1 : x2)) return 0;
    if (move_y + 16 <= (y1 < y2 ? y1 : y2) || move_y - 16 >= (y1 > y2 ? y1 : y2)) return 0;
    dx = x2 - x1; dy = y2 - y1;
    /* Extreme corners along the line normal, no division or squared distances. */
    if ((dx < 0) == (dy < 0)) {
        a = side_of(move_x + 16 - x1, move_y - 16 - y1, dx, dy);
        b = side_of(move_x - 16 - x1, move_y + 16 - y1, dx, dy);
    } else {
        a = side_of(move_x - 16 - x1, move_y - 16 - y1, dx, dy);
        b = side_of(move_x + 16 - x1, move_y + 16 - y1, dx, dy);
    }
    return a != b;
}

int line_allows(unsigned k)
{
    unsigned front, back;
    readmap(5, k * 6, 6); front = buf[4] & 255; back = buf[5];
    if (!box_crosses((int)buf[0], (int)buf[1], (int)buf[2], (int)buf[3])) return 1;
    if (back == 0xffff) return 0;
    read_sector(front);
    if ((int)buf[0] > move_floor) move_floor = buf[0];
    if ((int)buf[1] < move_ceiling) move_ceiling = buf[1];
    read_sector(back);
    if ((int)buf[0] > move_floor) move_floor = buf[0];
    if ((int)buf[1] < move_ceiling) move_ceiling = buf[1];
    return 1;
}

int block_allows(int x, int y)
{
    unsigned at, k;
    readmap(6, y * BLOCK_W + x, 1); at = buf[0];
    while (1) {
        readmap(6, at++, 1); k = buf[0];
        if (k == 0xffff) return 1;
        if (!line_allows(k)) return 0;
    }
}

int can_move(int x, int y)
{
    int bx, by, xlo, xhi, ylo, yhi;
    move_x = x; move_y = y;
    xlo = (x - 16 - BLOCK_X) >> 7; xhi = (x + 16 - BLOCK_X) >> 7;
    ylo = (y - 16 - BLOCK_Y) >> 7; yhi = (y + 16 - BLOCK_Y) >> 7;
    if (xlo < 0 || ylo < 0 || xhi >= BLOCK_W || yhi >= BLOCK_H) return 0;
    read_sector(sector_at(x, y)); move_floor = buf[0]; move_ceiling = buf[1];
    for (by = ylo; by <= yhi; by++)
        for (bx = xlo; bx <= xhi; bx++) if (!block_allows(bx, by)) return 0;
    if (move_floor - pz > 24) return 0;
    if (move_ceiling - move_floor < 56 || move_ceiling - pz < 56) return 0;
    return actors_allow(x, y);
}

void step_move(int dx, int dy)
{
    if (can_move(px + dx, py + dy)) { px += dx; py += dy; pz = move_floor; return; }
    /* Continue along an unblocked axis rather than stopping on a wall. */
    if (dx && can_move(px + dx, py)) { px += dx; pz = move_floor; }
    if (dy && can_move(px, py + dy)) { py += dy; pz = move_floor; }
}

void move_player(int dx, int dy)
{
    int n, sx, sy, rx, ry, ax, ay;
    n = dx < 0 ? -dx : dx; if ((dy < 0 ? -dy : dy) > n) n = dy < 0 ? -dy : dy;
    if (!n) return;
    n = (n + 7) >> 3;                          /* at most 8 units per substep: no tunnelling */
    sx = dx / n; sy = dy / n; rx = dx % n; ry = dy % n;
    while (n--) {
        ax = sx; ay = sy;
        if (rx > 0) { ax++; rx--; } else if (rx < 0) { ax--; rx++; }
        if (ry > 0) { ay++; ry--; } else if (ry < 0) { ay--; ry++; }
        step_move(ax, ay);
    }
}

void steer(void)
{
    int dx, dy, fwd, left;
    if (held & 2) pa += 4;
    if (held & 32) pa -= 4;
    pa = pa & 255;
    fwd = !!(held & 20) - !!(held & 8); left = !!(held & 1) - !!(held & 64);
    dx = fmul(isin(pa + 64), held & 1024 ? 16 : 8); dy = fmul(isin(pa), held & 1024 ? 16 : 8);
    if (fwd && left) { dx = fmul(dx, 181); dy = fmul(dy, 181); }
    move_player(dx * fwd - dy * left, dy * fwd + dx * left);
}

void rc_start(void)
{
    fr_init(); fmode = 0;
    px = START_X; py = START_Y; pa = START_A;
    game_init();
    read_sector(sector_at(px, py)); pz = buf[0];
    audio_restart();
    ticks = nframe = logic_epoch = callback_stage = callback_count = 0;
    frame_begin();
}

void rc_tick(void)
{
    callback_count++;
    callback_stage = 1;
    if (nframe < 3 || callback_count < 64) trace(0x601);
    mu_clock();
    ticks++;
    if (ticks >= 3) {
        ticks = 0; callback_stage = 2;
        if (nframe < 3 || callback_count < 64) trace(0x602);
        tick_start = work;
        game_tick(); logic_epoch++;
        work += 200;                            /* logic's uncounted part (~18k instructions) */
    } else tick_start = work;
    callback_stage = 3;                         /* the rest of the tick's budget renders */
    if (nframe < 3 || callback_count < 64) trace(0x603);
    if (!render_state) frame_begin();
    frame_work();
    callback_stage = 0;
    if (nframe < 3 || callback_count < 64) trace(0x600);
    else if (!(callback_count & 63)) trace(0x700 | (nframe & 255));   /* frames done, every 64 callbacks */
}

void rc_key(int note, int vel)
{
    int k = note - 47;
    if (note == 72) k = 7;
    else if (note == 74) k = 8;
    else if (note == 23) k = 9;
    else if (note == 76) k = 10;
    else if (k < 0 || k > 6) return;
    if (vel) { held |= 1 << k; pressed |= 1 << k; } else held &= ~(1 << k);
}
