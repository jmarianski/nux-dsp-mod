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
int light_factor(int light, unsigned s);
void sprite_column(int x);

/* game_mode: 0 playing, 1 dead, 2 the exit reached, 3 the title, 4 the skill menu. skill: Doom's 0..4, 2 (hurt me
 * plenty) the game as tuned. */
int game_visible, game_mode, health, ammo, armor, kills, weapon, skill;
/* Four slots for the nearest monsters of the skill (slot_tick). enemy_state: bit 15 in pain until its next turn,
 * 10..14 its record in the entities table (31: an empty slot), 5..9 the turns to its next attack or, dead, its death
 * frame, 0..4 health in 2-point units. roster_bits: a record met (in a slot, or killed). */
#define SLOTS 4
#define EMPTY 0x7c00
int enemy_x[SLOTS], enemy_y[SLOTS];
unsigned enemy_state[SLOTS], pickup_bits[4], roster_bits[2];
int dynamic_height[DYN_SLOTS], moving_actor;
/* The imp's fireball, one at a time: position, velocity (x << 8 | y, signed bytes a logic tick), ticks of flight
 * left, or 0x8000 | ticks of its burst. */
int ball_x, ball_y;
unsigned ball_v, ball_t;
unsigned dynamic_open, lift_timer, prev_held, shot_cd, flash, hurt, ai_index, sfx_timer, sfx_note;
unsigned bob;                                   /* walking ticks: the weapon's sway */
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
    for (i = 0; i < SLOTS; i++)
        if (i != moving_actor && (enemy_state[i] & 31) &&
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

/* Effects on channel 7 (GM gunshot, applause at the exit; the music keeps off it and the style's drums 8): the
 * pitch picks the sound, played low it is slower and deeper (the fireball). */
#if SFX_DRUMS
/* builddemo --sfx drums (a soundbank without the gunshot): GM drums on channel 9 with the music's, one per sound. */
int drum(int note)
{
    if (note == 60) return 40;                 /* the pistol: electric snare */
    if (note == 52) return 38;                 /* shotguns: acoustic snare */
    if (note == 62) return 37;                 /* the zombie: side stick */
    if (note == 42) return 41;                 /* the fireball thrown: low floor tom */
    if (note == 30) return 49;                 /* its burst: crash cymbal */
    if (note == 36) return 39;                 /* claws: hand clap */
    if (note == 48) return 45;                 /* a door: low tom */
    return 81;                                 /* a pickup: open triangle */
}
#endif

void sound_at(int note, int velocity)
{
#if SILENT_AUDIO
    (void)note; (void)velocity;
#else
#if SFX_DRUMS
    synth(0x0999, (drum(note) << 8) | velocity);
#else
    if (sfx_timer) synth(0x0887, sfx_note << 8);
    synth(0x0997, (note << 8) | velocity);
    sfx_note = note; sfx_timer = note < 48 ? 10 : 3;   /* a low, slow one rings longer */
#endif
#endif
}

void sound(int note)
{
    sound_at(note, 100);
}

/* Fainter with the distance (map units, Manhattan): 110 alongside, 20 from 720 on. */
int far_velocity(int distance)
{
    distance = 110 - (distance >> 3);
    return distance < 20 ? 20 : distance;
}

/* The exit: GM applause (program 126) for ~4 s; audio_restart sets the gunshot back. */
void applause(void)
{
#if !SILENT_AUDIO
    if (sfx_timer) synth(0x0887, sfx_note << 8);
    synth(0x0cc7, 126 << 8); synth(0x0997, (60 << 8) | 127);
    sfx_note = 60; sfx_timer = 140;
#endif
}

void activate(int action)
{
    if (action == 255) { game_mode = 2; mu_stop(); applause(); return; }
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
    if (!skill) amount >>= 1;                  /* I'm too young to die: half the damage */
    saved = amount / 3; if (saved > armor) saved = armor;
    armor -= saved; health -= amount - saved; hurt = 12;    /* ~0.35 s: three frames or so */
    if (health <= 0) { health = 0; game_mode = 1; mu_stop(); }
}

int target_distance(int i)
{
    int dx, dz, c, sn;
    if (!(enemy_state[i] & 31)) return 1025;
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
    ammo--; shot_cd = weapon ? 12 : 7; flash = 2; sound_at(weapon ? 52 : 60, 127);   /* ours: loud */
    best = -1; distance = 1025;
    for (i = 0; i < SLOTS; i++) {
        dz = target_distance(i);
        if (dz < distance) { best = i; distance = dz; }
    }
    if (best < 0) return;
    hp = enemy_state[best] & 31; hit = weapon ? 15 : 5;                     /* 30 and 10 points */
    hp = hp > hit ? hp - hit : 0;
    if (hp) enemy_state[best] = (enemy_state[best] & 0x7fe0) | 0x8000 | hp;   /* in pain until its next turn */
    else { enemy_state[best] &= 0x7c00; kills++; }                           /* dying: the step counts up */
}

/* Logic turns between a monster's attacks: slower on the easy skills, faster on the hard ones. */
int attack_rest(void)
{
    return skill < 2 ? 16 : skill == 2 ? 12 : skill == 3 ? 9 : 6;
}

int skill_bit(void)
{
    return skill < 2 ? 1 : skill == 2 ? 2 : 4;
}

/* 1 zombie, 2 imp, 3 shotgun guy: from the slot's record. */
int enemy_kind(int i)
{
    readmap(8, ((enemy_state[i] >> 10) & 31) * 3 + 2, 1);
    return buf[0] & 255;
}

int roster_met(int k)
{
    return roster_bits[k >> 4] & (1 << (k & 15));
}

/* How readily slot i gives way: empty, else a finished corpse, else a live one well beyond the fog (2048); 0: it stays. */
int slot_yield(int i, int near)
{
    unsigned st;
    int d;
    st = enemy_state[i];
    if ((st & EMPTY) == EMPTY) return 30000;
    if (!(st & 31)) return ((st >> 5) & 31) >= 4 ? 20000 : 0;
    d = absval(enemy_x[i] - px) + absval(enemy_y[i] - py);
    return d > 2048 && d > near + 512 ? (d < 19999 ? d : 19999) : 0;
}

/* The nearest monster of the skill not yet met, within the fog's 1536, takes the slot that gives way most readily. An evicted
 * live one goes back to its start, whole, and can come again. */
void slot_tick(void)
{
    int i, k, d, best, near, slot, most;
    best = -1; near = 1536;
    for (k = 0; k < ENEMY_N; k++) {
        if (roster_met(k)) continue;
        readmap(8, k * 3, 3);
        if (!((buf[2] >> 8) & skill_bit())) continue;
        d = absval(buf[0] - px) + absval(buf[1] - py);
        if (d < near) { best = k; near = d; }
    }
    if (best < 0) return;
    slot = -1; most = 0;
    for (i = 0; i < SLOTS; i++) {
        d = slot_yield(i, near);
        if (d > most) { slot = i; most = d; }
    }
    if (slot < 0) return;
    if (most < 20000) { k = (enemy_state[slot] >> 10) & 31; roster_bits[k >> 4] &= ~(1 << (k & 15)); }
    readmap(8, best * 3, 3); enemy_x[slot] = buf[0]; enemy_y[slot] = buf[1];
    k = buf[2] & 255;
    enemy_state[slot] = (best << 10) | (k == 2 ? 30 : k == 3 ? 15 : 10);   /* 60, 30, 20 points */
    roster_bits[best >> 4] |= 1 << (best & 15);
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

/* Doom's imp fireball: 10 units a tic (20 on nightmare) toward where the player stood. It flies to there and a little past (walls
 * behind the player hide it), bursting on the player within 20 units. */
void ball_launch(int i)
{
    int dx, dy, ax, ay, len, vx, vy, speed;
    speed = skill == 4 ? 20 : 10;              /* nightmare: the fast fireball */
    dx = px - enemy_x[i]; dy = py - enemy_y[i];
    ax = absval(dx); ay = absval(dy);
    len = ax > ay ? ax + (ay >> 1) : ay + (ax >> 1);             /* ~ the distance */
    if (len < 1) return;
    vx = muldiv(dx, speed, len); vy = muldiv(dy, speed, len);
    ball_x = enemy_x[i]; ball_y = enemy_y[i];
    ball_v = ((vx & 255) << 8) | (vy & 255);
    ball_t = len / speed + 8;
    sound_at(42, far_velocity(len));          /* the gunshot played low: slower, a whoosh */
}

void ball_tick(void)
{
    int vx, vy;
    if (!ball_t) return;
    if (ball_t & 0x8000) { ball_t--; if (!(ball_t & 0x7fff)) ball_t = 0; return; }
    vx = ball_v >> 8; if (vx > 127) vx -= 256;
    vy = ball_v & 255; if (vy > 127) vy -= 256;
    ball_x += vx; ball_y += vy;
    if (absval(ball_x - px) < 20 && absval(ball_y - py) < 20) {
        damage(10); ball_t = 0x8006; sound_at(30, 127); return;      /* lower still: the burst */
    }
    if (!--ball_t) { ball_t = 0x8006; sound_at(30, far_velocity(absval(ball_x - px) + absval(ball_y - py))); }
}

int ball_frame(void)
{
    if (ball_t & 0x8000) return BALL_BASE + 2 + ((6 - (ball_t & 7)) >> 1);
    return BALL_BASE + ((logic_epoch >> 2) & 1);
}

void enemy_attack(int i, int distance)
{
    int kind;
    kind = enemy_kind(i);
    if (kind == 1) { damage(8); sound_at(62, far_velocity(distance)); }                   /* zombie */
    else if (kind == 3) { damage(distance < 256 ? 15 : 9); sound_at(52, far_velocity(distance)); }   /* 3 pellets */
    else if (distance < 64) { damage(10); sound_at(36, 100); }                           /* imp, close: its claws */
    else if (!ball_t) ball_launch(i);                                                    /* imp: a fireball to dodge */
    else return;
    enemy_state[i] = (enemy_state[i] & 0x7c1f) | (attack_rest() << 5);
}

void enemy_tick(void)
{
    int i, cooldown, distance;
    if (!(logic_epoch & 7)) slot_tick();
    i = ai_index++; if (ai_index >= SLOTS) ai_index = 0;
    if ((enemy_state[i] & EMPTY) == EMPTY) return;
    if (!(enemy_state[i] & 31)) {
        if (((enemy_state[i] >> 5) & 31) < 4) enemy_state[i] += 32;    /* the death frames, one a turn */
        return;
    }
    enemy_state[i] &= 0x7fff;
    distance = absval(enemy_x[i] - px) + absval(enemy_y[i] - py);
    if (distance > 1024 || !ray_clear(enemy_x[i], enemy_y[i], 0)) return;
    cooldown = (enemy_state[i] >> 5) & 31;
    if (!cooldown && distance < 640) enemy_attack(i, distance);
    else if (cooldown) enemy_state[i] -= 32;
    if (distance > 52) enemy_move(i);
}

void pickup_step(int i)
{
    int kind, x, y, more;
    unsigned bit;
    bit = 1 << (i & 15); if (pickup_bits[i >> 4] & bit) return;
    readmap(8, (ENEMY_N + i) * 3, 3); x = buf[0]; y = buf[1]; kind = buf[2];
    if (absval(x - px) > 24 || absval(y - py) > 24) return;
    if (kind <= 5 && health >= (kind == 5 ? 200 : 100)) return;
    if (kind == 6 && armor >= 200) return;
    if ((kind == 7 || kind == 8) && ammo >= 200) return;
    more = !skill || skill == 4;               /* ammo doubled, as Doom's easiest and nightmare */
    if (kind == 3) health += 10;
    if (kind == 4) health += 25;
    if (kind == 5) health++;
    if (kind == 6) armor++;
    if (kind == 7) ammo += 10 << more;
    if (kind == 8) ammo += 50 << more;
    if (kind == 9) { weapon = 1; ammo += 8 << more; }
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
    synth(0x0887, sfx_note << 8);              /* the applause, if it still rings */
    synth(0x0cc7, 127 << 8);
    mu_restart(); mu_ok = 1; mu_last = CLOCK_LO; mu_us = 0;
#endif
}

void game_init(void)
{
    int i;
    game_visible = 0; game_mode = 0; health = 100; ammo = 50; armor = kills = weapon = 0;
    dynamic_open = lift_timer = prev_held = pressed = shot_cd = flash = hurt = ai_index = sfx_timer = bob = ball_t = 0;
    moving_actor = -1; held = 0;
    for (i = 0; i < 4; i++) pickup_bits[i] = 0;
    roster_bits[0] = roster_bits[1] = 0;
    for (i = 0; i < SLOTS; i++) enemy_state[i] = EMPTY;
    for (i = 0; i < SLOTS; i++) slot_tick();
    for (i = 0; i < DYNAMIC_N; i++) { readmap(9, i * 4, 4); dynamic_height[i] = buf[1]; }
    game_visible = 1;
#if !SILENT_AUDIO
    synth(0x0cc7, 127 << 8);                   /* GM gunshot on a channel the music leaves free */
#endif
}

int key_hit(int k)
{
    return (pressed & k) || ((held & k) && !(prev_held & k));
}

/* The title or the menu, drawn once by render state 6 (screen_draw), again whenever the cursor moves. */
void show_screen(int mode)
{
    game_mode = mode; render_state = 6;
}

/* A new game at the chosen skill: the menu's choice, and the harnesses' start. */
void start_game(void)
{
    px = START_X; py = START_Y; pa = START_A; game_init();
    read_sector(sector_at(px, py)); pz = buf[0]; audio_restart();
    render_state = 0;
}

/* The title waits for any key; the menu moves with forward/back and starts on fire, use or enter. */
void menu_tick(void)
{
    if (game_mode == 3) { if (pressed | (held & ~prev_held)) show_screen(4); return; }
    if (key_hit(20) && skill) { skill--; render_state = 6; }
    if (key_hit(8) && skill < 4) { skill++; render_state = 6; }
    if (key_hit(128 | 256 | 512)) start_game();
}

void sfx_tick(void)
{
#if !SILENT_AUDIO
    if (sfx_timer && !--sfx_timer) synth(0x0887, sfx_note << 8);
#endif
}

void game_tick(void)
{
    if (game_mode >= 3) { menu_tick(); prev_held = held; pressed = 0; return; }
    if (game_mode) {
        sfx_tick();
        if (key_hit(512)) show_screen(4);      /* dead or out: back to the skill menu */
        prev_held = held; pressed = 0; return;
    }
    if (shot_cd) shot_cd--; if (flash) flash--; if (hurt) hurt--;
    sfx_tick();
    dynamic_tick();
    if (held & 0x5d) bob++; else bob = 0;      /* moving or strafing */
    steer();
    if (can_move(px, py)) pz = move_floor;
    if ((pressed & 256) || ((held & 256) && !(prev_held & 256))) use_game();
    if (game_mode) { prev_held = held; pressed = 0; return; }
    if ((held | pressed) & 128) fire_game();
    pickup_tick(); enemy_tick(); ball_tick();
    if (held & 0x7f) touch_specials();
    prev_held = held; pressed = 0;
}

/* Drawing is below; the BSP's closed columns retain wall depth in the same word
 * that held their clip window. No second 128-word depth buffer is allocated. */
int spr_left, spr_right, spr_u, spr_dz, spr_top, spr_bot, spr_v0, spr_scale, spr_base, spr_cols, spr_light;

/* A sprite frame at (x, y), facing the view: its screen columns and rows, texel steps (1/256 texel a pixel, the
 * same both ways), the light where it stands. 0 when it is behind, too far or off the screen. */
int sprite_setup(int x, int y, int frame)
{
    int z, rows, left, top;
    view_point(x, y);
    if (vz < NEAR || vz > 1024) return 0;
    readmap(10, frame, 1); spr_base = buf[0];
    readmap(10, spr_base, 4); spr_cols = buf[0]; rows = buf[1]; left = buf[2]; top = buf[3];
    spr_base += 4;
    spr_scale = muldiv(8192, 64, vz);
    spr_left = 64 + muldiv(vx - left, 64, vz); spr_right = 64 + muldiv(vx - left + spr_cols * 2, 64, vz);
    if (spr_left >= 128 || spr_right <= 0 || spr_left >= spr_right) return 0;
    spr_dz = vz * 2;                            /* map units a pixel vz / 64, a texel 2 units */
    read_sector(sector_at(x, y)); z = buf[0]; spr_light = light_factor(buf[2], spr_scale);
    if (frame >= BALL_BASE) { z += 32; spr_light = GAIN; }    /* the fireball: in the air, full bright */
    spr_top = screen_y(z + top, spr_scale); spr_bot = screen_y(z + top - rows * 2, spr_scale);
    spr_v0 = -spr_top * spr_dz;
    spr_u = spr_left < 0 ? muldiv(-spr_left, spr_dz, 1) : 0;
    return 1;
}

/* Column x of the set-up sprite (sprite_column, in doom.c), then the next. -> 0 past its right edge. */
int sprite_step(int x)
{
    sprite_column(x);
    spr_u += spr_dz;
    return x + 1 < spr_right && x + 1 < 128;
}

void sprite(int x, int y, int frame)
{
    int col;
    if (sprite_setup(x, y, frame)) for (col = spr_left < 0 ? 0 : spr_left; sprite_step(col); col++) ;
}

void draw_pickup(int i)
{
    int x, y, kind;
    if (pickup_bits[i >> 4] & (1 << (i & 15))) return;
    readmap(8, (ENEMY_N + i) * 3, 3); x = buf[0]; y = buf[1]; kind = buf[2];
    if (absval(x - px) + absval(y - py) < 768) sprite(x, y, PICKUP_BASE + kind - 3);
}

void draw_pickups(void)
{
    int i;
    for (i = 0; i < PICKUP_N; i++) draw_pickup(i);
}

/* Dead ones too: their corpses stay (until the slot is wanted). */
int enemy_depth(int i, int previous, int previous_i)
{
    if ((enemy_state[i] & EMPTY) == EMPTY) return 0;
    view_point(enemy_x[i], enemy_y[i]);
    return vz > 0 && (vz < previous || (vz == previous && i > previous_i)) ? vz : 0;
}

/* Walking (four frames), shooting just now, hurt since its last turn, or dying (five frames, then the corpse). */
int enemy_frame(int i)
{
    unsigned st, step;
    int base;
    st = enemy_state[i]; step = (st >> 5) & 31;
    base = enemy_kind(i); base = base == 2 ? IMP_BASE : base == 3 ? SERGEANT_BASE : 0;
    if (!(st & 31)) return base + DEATH + (step > 4 ? 4 : step);
    if (st & 0x8000) return base + PAIN;
    if (step > attack_rest() - 3) return base + ATTACK;
    return base + (((logic_epoch >> 3) + i) & 3);
}

void draw_enemy(int i)
{
    sprite(enemy_x[i], enemy_y[i], enemy_frame(i));
}

void draw_enemies(void)
{
    int pass, i, best, distance, previous, previous_i, z;
    previous = 32767; previous_i = -1;
    for (pass = 0; pass < SLOTS; pass++) {
        best = -1; distance = 0;
        for (i = 0; i < SLOTS; i++) {
            z = enemy_depth(i, previous, previous_i);
            if (z > distance) { best = i; distance = z; }
        }
        if (best < 0) return;
        draw_enemy(best);
        previous = distance; previous_i = best;
    }
}

int actor_row_work(void)                       /* render_row is the sprite's next screen column */
{
    if (!render_kind) return 0;
    if (!sprite_step(render_row++)) render_kind = 0;
    return 1;
}

void actor_start(void)
{
    render_kind = 1; render_row = spr_left < 0 ? 0 : spr_left;
}

void pickup_draw_work(void)
{
    int i, x, y, kind;
    if (actor_row_work()) return;
    if (render_actor >= PICKUP_N) { render_state = 3; return; }
    i = render_actor++;
    if (pickup_bits[i >> 4] & (1 << (i & 15))) return;
    readmap(8, (ENEMY_N + i) * 3, 3); x = buf[0]; y = buf[1]; kind = buf[2];
    if (absval(x - view_x) + absval(y - view_y) < 768 && sprite_setup(x, y, PICKUP_BASE + kind - 3)) actor_start();
}

/* Then the fireball, last: it flies in front of the imp that threw it. render_pass 255: done. */
void enemy_draw_work(void)
{
    int i, best, distance, z;
    if (actor_row_work()) return;
    if (render_pass == 255) { render_state = 4; return; }
    best = -1; distance = 0;
    if (render_pass < SLOTS)
        for (i = 0; i < SLOTS; i++) {
            z = enemy_depth(i, render_previous, render_previous_i);
            if (z > distance) { best = i; distance = z; }
        }
    if (best >= 0) {
        render_previous = distance; render_previous_i = best; render_pass++;
        if (sprite_setup(enemy_x[best], enemy_y[best], enemy_frame(best))) actor_start();
        return;
    }
    render_pass = 255;
    if (ball_t && sprite_setup(ball_x, ball_y, ball_frame())) actor_start();
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
    x = skill < 2 ? ENEMY_EASY : skill == 2 ? ENEMY_MEDIUM : ENEMY_HARD;
    glyph(68, 7, x / 10); glyph(72, 7, x % 10);
}

void end_overlay(void)
{
    rect(45, 23, 38, 18, 0); rect(45, 23, 38, 1, 1); rect(45, 40, 38, 1, 1);
    if (game_mode == 2) { glyph(57, 4, 13); glyph(61, 4, 14); glyph(65, 4, 15); }
    else { glyph(55, 4, 16); glyph(59, 4, 17); glyph(63, 4, 11); glyph(67, 4, 16); }
}

/* Hit: an inked frame round the view, narrowing as hurt counts down. */
void hurt_frame(void)
{
    int w;
    w = (hurt + 3) >> 2;
    rect(0, 0, 128, w, 1); rect(0, 56 - w, 128, w, 1);
    rect(0, w, w, 56 - 2 * w, 1); rect(128 - w, w, w, 56 - 2 * w, 1);
}

/* The weapon sways on an arc while walking, as vanilla's: sideways 0, 1, 2, 1, 0, -1, -2, -1, lower at the sides. */
void draw_weapon(void)
{
    int k, dx, dy;
    k = (bob >> 2) & 7;
    dx = k < 4 ? (k < 3 ? k : 1) : (k < 7 ? 4 - k : -1);
    dy = dx < 0 ? -dx : dx;
    rect(57 + dx, 48 + dy, 14, 8 - dy, 0); rect(59 + dx, 50 + dy, 10, 6 - dy, 1); rect(61 + dx, 42 + dy, weapon ? 6 : 4, 12 - dy, 1);
    if (flash) { rect(58 + dx, 39 + dy, 12, 2, 1); rect(63 + dx, 36 + dy, 2, 8, 1); }
}

void draw_overlay(void)
{
    rect(61, 29, 5, 5, 0); rect(63, 30, 1, 3, 1); rect(62, 31, 3, 1, 1);
    if (hurt) hurt_frame();
    draw_weapon();
    draw_hud();
    if (game_mode) end_overlay();
}

/* The title (game_mode 3) or the menu (4): a whole framebuffer from the font table, the menu's cursor drawn on it. */
void screen_draw(void)
{
    int y;
    fr_lo = map_lo[11] + SCREENS_AT + (game_mode - 3) * 1024;
    fr_hi = map_hi[11] + (fr_lo < map_lo[11]);
    fr_dst = (unsigned)framebuffer; fr_n = 1024; fr_mode = 0;
    farcopy();
    if (game_mode == 4) {
        y = MENU_Y + MENU_STEP * skill;
        rect(MENU_X - 6, y, 1, 5, 1); rect(MENU_X - 5, y + 1, 1, 3, 1); rect(MENU_X - 4, y + 2, 1, 1, 1);
    }
}

void game_draw(void)
{
    draw_pickups(); draw_enemies();
    if (ball_t) sprite(ball_x, ball_y, ball_frame());
    draw_overlay();
}
