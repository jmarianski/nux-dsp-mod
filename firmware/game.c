/* E1M1 demo state. Static bounds are checked by doommap.py and p16cc. */
void readmap(int table, unsigned at, int count);
void read_sector(unsigned k);
int side_of(int x, int y, int dx, int dy);
void umul32(unsigned a, unsigned b);
void smul32(int a, int b);
int fmul(int a, int b);
int muldiv(int a, int b, int c);
int isin(int a);
int clamp(int x, int lo, int hi);
int sector_at(int x, int y);
int screen_y(int h, int s);
unsigned span(int lo, int hi);
void move_player(int dx, int dy);
int can_move(int x, int y);
void steer(void);
void view_point(int x, int y);

int game_visible, game_mode, health, ammo, armor, kills, weapon;
int enemy_x[4], enemy_y[4];
unsigned enemy_state[4], pickup_bits[4];
int dynamic_height[8], moving_actor;
unsigned dynamic_open, lift_timer, prev_held, shot_cd, flash, hurt, ai_index, sfx_timer, sfx_note;
unsigned pressed;
int ray_x, ray_y, ray_dx, ray_dy, ray_use, ray_action, ray_z, ray_dz;

int absval(int x) { return x < 0 ? -x : x; }

void sector_override(void)
{
    unsigned slot = (buf[2] >> 8) & 15;
    if (slot && game_visible) {
        if (buf[2] & 0x1000) buf[0] = render_context ? render_height[slot - 1] : dynamic_height[slot - 1];
        else buf[1] = render_context ? render_height[slot - 1] : dynamic_height[slot - 1];
    }
    buf[2] = buf[2] & 255;
}

int actors_allow(int x, int y)
{
    int i;
    if (!game_visible) return 1;
    for (i = 0; i < ENEMY_N; i++)
        if (i != moving_actor && (enemy_state[i] & 127) &&
            absval(x - enemy_x[i]) < 28 && absval(y - enemy_y[i]) < 28) return 0;
    return 1;
}

/* Line intersections and a grid walk for sight, hitscan and use. Open portals
 * transmit sight; one-sided walls and closed sector openings stop it. */
int ray_intersects(int x1, int y1, int x2, int y2)
{
    int xend, yend;
    xend = ray_x + ray_dx; yend = ray_y + ray_dy;
    if ((x1 < x2 ? x1 : x2) > (ray_x > xend ? ray_x : xend)) return 0;
    if ((x1 > x2 ? x1 : x2) < (ray_x < xend ? ray_x : xend)) return 0;
    if ((y1 < y2 ? y1 : y2) > (ray_y > yend ? ray_y : yend)) return 0;
    if ((y1 > y2 ? y1 : y2) < (ray_y < yend ? ray_y : yend)) return 0;
    if (side_of(ray_x - x1, ray_y - y1, x2 - x1, y2 - y1) ==
        side_of(xend - x1, yend - y1, x2 - x1, y2 - y1)) return 0;
    return side_of(x1 - ray_x, y1 - ray_y, ray_dx, ray_dy) !=
           side_of(x2 - ray_x, y2 - ray_y, ray_dx, ray_dy);
}

void cross32(int ax, int ay, int bx, int by)
{
    unsigned hi, lo, borrow;
    smul32(ax, by); hi = prod_hi; lo = prod_lo;
    smul32(ay, bx); borrow = lo < prod_lo;
    prod_lo = lo - prod_lo; prod_hi = hi - prod_hi - borrow;
}

/* Q14 intersection fraction: 32-bit cross products divided without overflowing
 * a 16-bit coordinate. This is only needed for two-sided line height clipping. */
int ray_fraction(int x1, int y1, int x2, int y2)
{
    unsigned dh, dl, rh, rl, carry, q, borrow;
    int n;
    cross32(ray_dx, ray_dy, x2 - x1, y2 - y1); dh = prod_hi; dl = prod_lo;
    cross32(x1 - ray_x, y1 - ray_y, x2 - x1, y2 - y1); rh = prod_hi; rl = prod_lo;
    if (dh & 0x8000) {
        dh = ~dh + (dl == 0); dl = -dl;
        rh = ~rh + (rl == 0); rl = -rl;
    }
    if (rh > dh || (rh == dh && rl >= dl)) return 16384;
    q = 0;
    for (n = 0; n < 14; n++) {
        carry = rh >> 15; rh = (rh << 1) | (rl >> 15); rl <<= 1; q <<= 1;
        if (carry || rh > dh || (rh == dh && rl >= dl)) {
            borrow = rl < dl; rl -= dl; rh -= dh + borrow; q++;
        }
    }
    return q;
}

int ray_line(unsigned k)
{
    unsigned front, back, action;
    int floor, ceiling, z;
    readmap(5, k * 6, 6); front = buf[4] & 255; action = buf[4] >> 8; back = buf[5];
    if (!ray_intersects((int)buf[0], (int)buf[1], (int)buf[2], (int)buf[3])) return 1;
    if (ray_use && action) { ray_action = action; return 0; }
    if (back == 0xffff) return 0;
    z = ray_z + muldiv(ray_dz, ray_fraction((int)buf[0], (int)buf[1], (int)buf[2], (int)buf[3]), 16384);
    read_sector(front); floor = buf[0]; ceiling = buf[1];
    read_sector(back);
    if ((int)buf[0] > floor) floor = buf[0];
    if ((int)buf[1] < ceiling) ceiling = buf[1];
    return ceiling > z && floor < z;
}

int ray_block(int x, int y)
{
    unsigned at, k;
    readmap(6, y * BLOCK_W + x, 1); at = buf[0];
    while (1) {
        readmap(6, at++, 1); k = buf[0];
        if (k == 0xffff) return 1;
        if (!ray_line(k)) return 0;
    }
}

int product_le(unsigned a, unsigned b, unsigned c, unsigned d)
{
    unsigned hi, lo;
    umul32(a, b); hi = prod_hi; lo = prod_lo;
    umul32(c, d);
    return hi == prod_hi ? lo <= prod_lo : hi < prod_hi;
}

int ray_safe_block(int x, int y)
{
    if (x < 0 || y < 0 || x >= BLOCK_W || y >= BLOCK_H) return 0;
    return ray_block(x, y);
}

int ray_clear(int tx, int ty, int use)
{
    int bx, by, ex, ey, sx, sy, n;
    unsigned nx, ny, ax, ay;
    ray_x = px; ray_y = py; ray_dx = tx - px; ray_dy = ty - py; ray_use = use; ray_action = 0;
    ray_z = pz + 41; ray_dz = 0;
    if (!use) { read_sector(sector_at(tx, ty)); ray_dz = (int)buf[0] + 28 - ray_z; }
    bx = (px - BLOCK_X) >> 7; by = (py - BLOCK_Y) >> 7;
    ex = (tx - BLOCK_X) >> 7; ey = (ty - BLOCK_Y) >> 7;
    sx = ray_dx < 0 ? -1 : 1; sy = ray_dy < 0 ? -1 : 1;
    ax = absval(ray_dx); ay = absval(ray_dy);
    nx = sx > 0 ? BLOCK_X + (bx + 1) * 128 - px : px - BLOCK_X - bx * 128;
    ny = sy > 0 ? BLOCK_Y + (by + 1) * 128 - py : py - BLOCK_Y - by * 128;
    for (n = 0; n < BLOCK_W + BLOCK_H + 2; n++) {
        if (!ray_safe_block(bx, by)) return 0;
        if (bx == ex && by == ey) return 1;
        if (!ay || (ax && product_le(nx, ay, ny, ax))) { bx += sx; nx += 128; }
        else { by += sy; ny += 128; }
    }
    return 0;
}

void sound(int note)
{
#if SILENT_AUDIO
    (void)note;
#else
    if (sfx_timer) synth(0x0888, sfx_note << 8);
    synth(0x0998, (note << 8) | 100);
    sfx_note = note; sfx_timer = 3;
#endif
}

void activate(int action)
{
    if (action == 255) { game_mode = 2; mu_stop(); return; }
    if (action > 0 && action <= DYNAMIC_N) { dynamic_open |= 1 << (action - 1); sound(48); }
}

void use_game(void)
{
    int x, y, k, action;
    x = isin(pa + 64); y = isin(pa);
    for (k = 8; k <= 72; k += 8) {
        if (!ray_clear(px + fmul(x, k), py + fmul(y, k), 1)) {
            action = ray_action;
            if (action) activate(action);
            return;
        }
    }
}

void dynamic_step(int i)
{
    int original, target, kind, h;
    readmap(9, i * 4, 4); original = buf[1]; target = buf[2]; kind = buf[3];
    h = dynamic_height[i];
    if (!(dynamic_open & (1 << i))) target = original;
    if (h < target) { h += 8; if (h > target) h = target; }
    if (h > target) { h -= 8; if (h < target) h = target; }
    dynamic_height[i] = h;
    if (kind == 2 && target != original && h == target) {
        lift_timer++;
        if (lift_timer >= 120) { dynamic_open &= ~(1 << i); lift_timer = 0; }
    }
}

void dynamic_tick(void)
{
    int i;
    for (i = 0; i < DYNAMIC_N; i++) dynamic_step(i);
}

void damage(int amount)
{
    int saved;
    saved = amount / 3; if (saved > armor) saved = armor;
    armor -= saved; health -= amount - saved; hurt = 4;
    sound(36);
    if (health <= 0) { health = 0; game_mode = 1; mu_stop(); }
}

int target_distance(int i)
{
    int dx, dz, c, sn;
    if (!(enemy_state[i] & 127)) return 1025;
    c = isin(pa + 64); sn = isin(pa);
    dx = enemy_x[i] - px; dz = enemy_y[i] - py;
    dz = fmul(dx, c) + fmul(dz, sn);
    dx = fmul(enemy_x[i] - px, sn) - fmul(enemy_y[i] - py, c);
    if (dz <= 0 || dz > 1024 || absval(dx) > (dz >> 4) + 12) return 1025;
    return ray_clear(enemy_x[i], enemy_y[i], 0) ? dz : 1025;
}

void fire_game(void)
{
    int i, best, distance, dz, hp, hit;
    if (shot_cd || !ammo) return;
    ammo--; shot_cd = weapon ? 12 : 7; flash = 2; sound(60);
    best = -1; distance = 1025;
    for (i = 0; i < ENEMY_N; i++) {
        dz = target_distance(i);
        if (dz < distance) { best = i; distance = dz; }
    }
    if (best < 0) return;
    hp = enemy_state[best] & 127; hit = weapon ? 30 : 10;
    hp = hp > hit ? hp - hit : 0;
    enemy_state[best] = (enemy_state[best] & 0xff80) | hp;
    if (!hp) kills++;
}

void enemy_move(int i)
{
    int oldx, oldy, oldz, dx, dy;
    oldx = px; oldy = py; oldz = pz;
    dx = oldx - enemy_x[i]; dy = oldy - enemy_y[i];
    px = enemy_x[i]; py = enemy_y[i];
    read_sector(sector_at(px, py)); pz = buf[0]; moving_actor = i;
    move_player(dx < -8 ? -8 : dx > 8 ? 8 : dx, dy < -8 ? -8 : dy > 8 ? 8 : dy);
    enemy_x[i] = px; enemy_y[i] = py;
    px = oldx; py = oldy; pz = oldz; moving_actor = -1;
}

void enemy_tick(void)
{
    int i, cooldown, distance;
    if (!ENEMY_N) return;
    i = ai_index++; if (ai_index >= ENEMY_N) ai_index = 0;
    if (!(enemy_state[i] & 127)) return;
    distance = absval(enemy_x[i] - px) + absval(enemy_y[i] - py);
    if (distance > 1024 || !ray_clear(enemy_x[i], enemy_y[i], 0)) return;
    cooldown = (enemy_state[i] >> 7) & 63;
    if (!cooldown && distance < 640) {
        damage(enemy_state[i] & 0x4000 ? 12 : 8); cooldown = 12;
    } else if (cooldown) cooldown--;
    enemy_state[i] = (enemy_state[i] & 0xc07f) | (cooldown << 7);
    if (distance > 52) enemy_move(i);
}

void pickup_step(int i)
{
    int kind, x, y;
    unsigned bit;
    bit = 1 << (i & 15); if (pickup_bits[i >> 4] & bit) return;
    readmap(8, (ENEMY_N + i) * 3, 3); x = buf[0]; y = buf[1]; kind = buf[2];
    if (absval(x - px) > 24 || absval(y - py) > 24) return;
    if (kind <= 5 && health >= (kind == 5 ? 200 : 100)) return;
    if (kind == 6 && armor >= 200) return;
    if ((kind == 7 || kind == 8) && ammo >= 200) return;
    if (kind == 3) health += 10;
    if (kind == 4) health += 25;
    if (kind == 5) health++;
    if (kind == 6) armor++;
    if (kind == 7) ammo += 10;
    if (kind == 8) ammo += 50;
    if (kind == 9) { weapon = 1; ammo += 8; }
    if (kind < 5 && health > 100) health = 100;
    if (ammo > 200) ammo = 200;
    pickup_bits[i >> 4] |= bit; sound(72);
}

void pickup_tick(void)
{
    int i;
    for (i = 0; i < PICKUP_N; i++) pickup_step(i);
}

void touch_specials(void)
{
    int x, y, action;
    /* Floor specials may also be used by F; crossing their trigger activates them. */
    x = isin(pa + 64); y = isin(pa);
    ray_clear(px + fmul(x, 20), py + fmul(y, 20), 1);
    action = ray_action;
    if (action > 0 && action <= DYNAMIC_N) {
        readmap(9, (action - 1) * 4, 4);
        if (buf[3]) activate(action);
    }
}

void audio_restart(void)
{
#if !SILENT_AUDIO
    synth(0x0cc8, 127 << 8);
    mu_restart(); mu_ok = 1; mu_last = CLOCK_LO; mu_us = 0;
#endif
}

void game_init(void)
{
    int i;
    game_visible = 0; game_mode = 0; health = 100; ammo = 50; armor = kills = weapon = 0;
    dynamic_open = lift_timer = prev_held = pressed = shot_cd = flash = hurt = ai_index = sfx_timer = 0;
    moving_actor = -1; held = 0;
    for (i = 0; i < 4; i++) pickup_bits[i] = 0;
    for (i = 0; i < ENEMY_N; i++) {
        readmap(8, i * 3, 3); enemy_x[i] = buf[0]; enemy_y[i] = buf[1];
        enemy_state[i] = buf[2] == 2 ? 0x403c : 20;
    }
    for (i = 0; i < DYNAMIC_N; i++) { readmap(9, i * 4, 4); dynamic_height[i] = buf[1]; }
    game_visible = 1;
#if !SILENT_AUDIO
    synth(0x0cc8, 127 << 8);                   /* GM gunshot on an unused E1M1 channel */
#endif
}

void game_tick(void)
{
    if (game_mode) {
        if ((pressed & 512) || ((held & 512) && !(prev_held & 512))) {
            px = START_X; py = START_Y; pa = START_A; game_init();
            read_sector(sector_at(px, py)); pz = buf[0]; audio_restart();
        }
        prev_held = held; pressed = 0; return;
    }
    if (shot_cd) shot_cd--; if (flash) flash--; if (hurt) hurt--;
#if !SILENT_AUDIO
    if (sfx_timer && !--sfx_timer) synth(0x0888, sfx_note << 8);
#endif
    dynamic_tick();
    steer();
    if (can_move(px, py)) pz = move_floor;
    if ((pressed & 256) || ((held & 256) && !(prev_held & 256))) use_game();
    if (game_mode) { prev_held = held; pressed = 0; return; }
    if ((held | pressed) & 128) fire_game();
    pickup_tick(); enemy_tick();
    if (held & 0x7f) touch_specials();
    prev_held = held; pressed = 0;
}

/* Drawing is below; the BSP's closed columns retain wall depth in the same word
 * that held their clip window. No second 128-word depth buffer is allocated. */
int spr_left, spr_top, spr_width, spr_height, spr_scale;

/* Page p of columns x0..end-1: the mask m set (or cleared) where the sprite is in front of the wall. */
void sprite_page(int x0, int end, unsigned at, unsigned m, int ink)
{
    int x;
    for (x = x0; x < end; x++) {
        if ((windows[x] & 0x8000) && spr_scale < (windows[x] & 0x7fff)) continue;
        if (ink) framebuffer[at + x] |= m; else framebuffer[at + x] &= ~m;
    }
}

/* Columns of band u, rows a..b-1: a page's mask once, then the columns. */
void sprite_band(int u, int a, int b, int ink)
{
    int x0, end, p;
    x0 = spr_left + u * spr_width / 8; end = spr_left + (u + 1) * spr_width / 8;
    if (x0 < 0) x0 = 0; if (end > 128) end = 128;
    a = clamp(a, 0, 56); b = clamp(b, 0, 56);
    if (x0 >= end || a >= b) return;
    work += 1 + (((end - x0) * (((b - 1) >> 3) - (a >> 3) + 1)) >> 1);
    for (p = a >> 3; p <= (b - 1) >> 3; p++) sprite_page(x0, end, p * 128, span(a - p * 8, b - p * 8), ink);
}

/* Band u of a sprite row: at most an eighth of its width, so that one piece of work stays small up close.
 * -> 0 when the whole row is off screen (its other bands are too). */
int sprite_part(int row, int u, int kind)
{
    int a, b;
    work += 2;
    a = spr_top + row * spr_height / 16; b = spr_top + (row + 1) * spr_height / 16;
    if (a == b || b <= 0 || a >= 56) return 0;
    readmap(10, (kind - 1) * 32 + row * 2, 2);
    if (buf[0] & (1 << u)) sprite_band(u, a, b, buf[1] & (1 << u));
    return 1;
}

void sprite_row(int row, int kind)
{
    int u;
    for (u = 0; u < 8; u++) if (!sprite_part(row, u, kind)) return;
}

int sprite_setup(int x, int y, int kind)
{
    int z, h;
    view_point(x, y);
    if (vz < NEAR || vz > 1024) return 0;
    spr_scale = muldiv(8192, 64, vz);
    spr_width = muldiv(kind <= 2 ? 32 : 16, 64, vz);
    if (!spr_width) return 0;
    spr_left = 64 + muldiv(vx, 64, vz) - spr_width / 2;
    if (spr_left >= 128 || spr_left + spr_width <= 0) return 0;
    read_sector(sector_at(x, y)); z = buf[0]; h = kind <= 2 ? 56 : 16;
    spr_top = screen_y(z + h, spr_scale); spr_height = screen_y(z, spr_scale) - spr_top;
    return 1;
}

void sprite(int x, int y, int kind)
{
    int row;
    if (sprite_setup(x, y, kind)) for (row = 0; row < 16; row++) sprite_row(row, kind);
}

void draw_pickup(int i)
{
    int x, y, kind;
    if (pickup_bits[i >> 4] & (1 << (i & 15))) return;
    readmap(8, (ENEMY_N + i) * 3, 3); x = buf[0]; y = buf[1]; kind = buf[2];
    if (absval(x - px) + absval(y - py) < 768) sprite(x, y, kind);
}

void draw_pickups(void)
{
    int i;
    for (i = 0; i < PICKUP_N; i++) draw_pickup(i);
}

int enemy_depth(int i, int previous, int previous_i)
{
    if (!(enemy_state[i] & 127)) return 0;
    view_point(enemy_x[i], enemy_y[i]);
    return vz > 0 && (vz < previous || (vz == previous && i > previous_i)) ? vz : 0;
}

void draw_enemy(int i)
{
    sprite(enemy_x[i], enemy_y[i], enemy_state[i] & 0x4000 ? 2 : 1);
}

void draw_enemies(void)
{
    int pass, i, best, distance, previous, previous_i, z;
    previous = 32767; previous_i = -1;
    for (pass = 0; pass < ENEMY_N; pass++) {
        best = -1; distance = 0;
        for (i = 0; i < ENEMY_N; i++) {
            z = enemy_depth(i, previous, previous_i);
            if (z > distance) { best = i; distance = z; }
        }
        if (best < 0) return;
        draw_enemy(best);
        previous = distance; previous_i = best;
    }
}

int actor_row_work(void)                       /* render_row counts the bands: row * 8 + band */
{
    if (!render_kind) return 0;
    if (!sprite_part(render_row >> 3, render_row & 7, render_kind)) render_row |= 7;
    if (++render_row == 128) render_kind = 0;
    return 1;
}

void pickup_draw_work(void)
{
    int i, x, y, kind;
    if (actor_row_work()) return;
    if (render_actor >= PICKUP_N) { render_state = 3; return; }
    i = render_actor++;
    if (pickup_bits[i >> 4] & (1 << (i & 15))) return;
    readmap(8, (ENEMY_N + i) * 3, 3); x = buf[0]; y = buf[1]; kind = buf[2];
    if (absval(x - view_x) + absval(y - view_y) < 768 && sprite_setup(x, y, kind)) {
        render_kind = kind; render_row = 0;
    }
}

void enemy_draw_work(void)
{
    int i, best, distance, z, kind;
    if (actor_row_work()) return;
    if (render_pass >= ENEMY_N) { render_state = 4; return; }
    best = -1; distance = 0;
    for (i = 0; i < ENEMY_N; i++) {
        z = enemy_depth(i, render_previous, render_previous_i);
        if (z > distance) { best = i; distance = z; }
    }
    if (best < 0) { render_state = 4; return; }
    render_previous = distance; render_previous_i = best; render_pass++;
    kind = enemy_state[best] & 0x4000 ? 2 : 1;
    if (sprite_setup(enemy_x[best], enemy_y[best], kind)) { render_kind = kind; render_row = 0; }
}

void rect_page(int x0, int end, unsigned at, unsigned m, int ink)
{
    int col;
    for (col = x0; col < end; col++) if (ink) framebuffer[at + col] |= m; else framebuffer[at + col] &= ~m;
}

void rect(int x, int y, int w, int h, int ink)
{
    int a, b, p, x0, end;
    a = clamp(y, 0, 64); b = clamp(y + h, 0, 64);
    x0 = clamp(x, 0, 128); end = x + w < 128 ? x + w : 128;
    for (p = a >> 3; a < b && p <= (b - 1) >> 3; p++) rect_page(x0, end, p * 128, span(a - p * 8, b - p * 8), ink);
}

void glyph(int x, int page, int id)
{
    readmap(11, id * 3, 3);
    framebuffer[page * 128 + x] = buf[0] << 1;
    framebuffer[page * 128 + x + 1] = buf[1] << 1;
    framebuffer[page * 128 + x + 2] = buf[2] << 1;
}

void hud_number(int x, unsigned value)
{
    glyph(x, 7, value / 100 % 10); glyph(x + 4, 7, value / 10 % 10); glyph(x + 8, 7, value % 10);
}

void draw_hud(void)
{
    int x;
    for (x = 0; x < 128; x++) framebuffer[7 * 128 + x] = 0;
    glyph(0, 7, 10); hud_number(4, health);
    glyph(24, 7, 11); hud_number(28, ammo);
    glyph(48, 7, 12); hud_number(52, kills);
    glyph(64, 7, 18);
    glyph(68, 7, ENEMY_N);
    if (hurt) rect(0, 0, 128, 1, 1);
}

void end_overlay(void)
{
    rect(45, 23, 38, 18, 0); rect(45, 23, 38, 1, 1); rect(45, 40, 38, 1, 1);
    if (game_mode == 2) { glyph(57, 4, 13); glyph(61, 4, 14); glyph(65, 4, 15); }
    else { glyph(55, 4, 16); glyph(59, 4, 17); glyph(63, 4, 11); glyph(67, 4, 16); }
}

void draw_overlay(void)
{
    rect(61, 29, 5, 5, 0); rect(63, 30, 1, 3, 1); rect(62, 31, 3, 1, 1);
    rect(57, 48, 14, 8, 0); rect(59, 50, 10, 6, 1); rect(61, 42, weapon ? 6 : 4, 12, 1);
    if (flash) { rect(58, 39, 12, 2, 1); rect(63, 36, 2, 8, 1); }
    draw_hud();
    if (game_mode) end_overlay();
}

void game_draw(void)
{
    draw_pickups(); draw_enemies(); draw_overlay();
}
