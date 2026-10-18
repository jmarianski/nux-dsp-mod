/* Music: the stream of tools/wad.py (two words an event: wait << 8 | status, d1 << 8 | d2; 0x00ff = again,
 * 0x00fe = stop). The level's song starts at mu_shi:mu_slo, the title's INTRO_OFF words after it. */
unsigned mu_shi, mu_slo, mu_hi, mu_lo, mu_wait;
unsigned mbuf[16];
int mu_i, mu_ok;

#define DEV_VOL (*(unsigned *)0x0145)          /* the piano's VOL, 0..10 */
unsigned mvol[16];                              /* each channel's volume as the song set it */
unsigned mu_dv;                                 /* VOL the channels were last scaled with */

#if SILENT_AUDIO
void mu_restart(void) { mu_ok = 0; }
void mu_intro(void) {}
void mu_clock(void) {}
void mu_stop(void) { mu_ok = 0; }
#else
unsigned mu_sum, mu_cnt;

unsigned mword(void)
{
    unsigned w;
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
    w = mbuf[mu_i++];
    mu_sum += w ^ mu_cnt;                       /* the words as read on the device, checked against the PC */
    mu_cnt++;
    if (!(mu_cnt & 255)) { trace(0x800 | (mu_cnt >> 8)); trace(0x1000 | (mu_sum & 0xfff)); }
    return w;
}

void mu_restart(void)
{
    int c;
    for (c = 0; c < 16; c++) mvol[c] = 100;     /* MIDI's default */
    mu_dv = 0xffff;                             /* mu_tick sends them all, scaled */
    mu_hi = mu_shi;
    mu_lo = mu_slo;
    mu_i = 16;
    mu_wait = 0;
    mu_sum = mu_cnt = 0;
}

void mu_intro(void)                             /* after mu_restart: the title's song instead */
{
    mu_lo += INTRO_OFF;
    if (mu_lo < INTRO_OFF) mu_hi++;
}


/* Channel c's volume under VOL: the music at 40% of what the song asks (the effects must be heard over it), the
 * effects' channel 8 at full. */
unsigned mu_scale(int c) { return c == 8 ? 127 * DEV_VOL / 10 : mvol[c] * DEV_VOL / 25; }

void mu_volumes(void)                           /* all channels' volume again, after VOL changed */
{
    int c;
    mu_dv = DEV_VOL;
    for (c = 4; c < 16; c++) synth(0x0bb0 | c, 0x0700 | mu_scale(c));
}

void mu_tick(void)
{
    unsigned w0, w1, st;
    int n;
    if (!mu_ok) return;
    if (DEV_VOL != mu_dv) mu_volumes();
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
        if (st == 254) {                        /* played once: silent until the next start */
            mu_ok = 0;
            return;
        }
        if ((st & 0xf0) == 0xb0 && (w1 >> 8) == 7) {    /* channel volume: kept, sent scaled by VOL */
            mvol[st & 15] = w1 & 127;
            w1 = 0x0700 | mu_scale(st & 15);
        }
        if (st) synth((st >> 4) << 8 | st, w1);
        mu_wait = w0 >> 8;
        if (mu_wait) return;
    }
}

unsigned mu_last, mu_us;                        /* the music follows the us clock, not the tick count */

void mu_clock(void)
{
    unsigned t, n;
    t = CLOCK_LO;
    mu_us += t - mu_last;
    mu_last = t;
    for (n = 0; n < 8 && mu_us >= 10000; n++) {
        mu_us -= 10000;
        mu_tick();
    }
    if (mu_us >= 10000) mu_us = 0;              /* far behind (a long stall): skip */
}

void mu_stop(void)                              /* a panel key leaves the game: all notes off */
{
    int c;
    mu_ok = 0;
    for (c = 4; c < 16; c++) {                  /* ours only: 0..3 are the keyboard's parts */
        synth(0x0bb0 | c, 123 << 8);
        synth(0x0bb0 | c, 120 << 8);
    }
}
#endif

