"""Telemetry log of the extra_menu patch: decode the dump (see the Telemetry part of extra_menu.patch).

The USB side of the keyboard passes no SysEx, so the request and the dump are channel 16 messages: a page is
a pitch bend (the ring index, 0x7ff = the page in RAM, 0x7fe = the DIAG heartbeat) and 93 poly pressures, key k = 0..92, value = 7 bits
of word k // 3, high first.

Capture on Linux (find the port with `amidi -l`):
    amidi -p hw:1,0,0 -S 'AF 7D 4E' -r log.syx -t 30
then `nuxdsp telemetry log.syx`.
"""
import csv
import io

TICK = 0.01            # s, awake
RAM_PAGE = 0x7ff
DIAG_PAGE = 0x7fe
REQUEST = bytes([0xAF, 0x7D, 0x4E])
KEYS = 93


class LogError(ValueError):
    pass


def messages(data):
    """[(status, data bytes)] from a raw MIDI byte stream (running status; SysEx and real time skipped)."""
    out, st, cur, sysex = [], None, [], False
    for b in data:
        if b >= 0xF8:
            continue
        if b >= 0x80:
            sysex = b == 0xF0
            st = b if b < 0xF0 else None
            cur = []
            continue
        if sysex or st is None:
            continue
        cur.append(b)
        if len(cur) == (1 if st >> 4 in (0xC, 0xD) else 2):
            out.append((st, cur))
            cur = []
    return out


def pages(data):
    """[(ring index, 31 words)] in the order received. A page with a missing or stray key (a byte lost on the
    way, notes in between) is counted as damaged and skipped."""
    out, bad, cur = [], 0, None
    for st, d in messages(data):
        if st == 0xEF:
            if cur is not None:
                bad += 1
            cur = (d[0] | d[1] << 7, [])
        elif st == 0xAF and cur is not None:
            if d[0] != len(cur[1]):
                bad += 1
                cur = None
                continue
            cur[1].append(d[1])
            if len(cur[1]) == KEYS:
                v = cur[1]
                out.append((cur[0], [(v[3 * i] << 14 | v[3 * i + 1] << 7 | v[3 * i + 2]) & 0xFFFF for i in range(31)]))
                cur = None
    if cur is not None:
        bad += 1
    return out, bad


def entries(pgs, sleep_w=60):
    """One dict per window, oldest first. Pages are put in order by their sequence numbers (the RAM page
    last), so a dump that started while the ring was being written still comes out right."""
    flash = [(idx, ws) for idx, ws in pgs if idx not in (RAM_PAGE, DIAG_PAGE) and ws[0] != 0xFFFF]
    ram = [(idx, ws) for idx, ws in pgs if idx == RAM_PAGE]
    if flash:
        # the oldest page: the one after the biggest gap in sequence numbers (they wrap at 0x4000)
        seqs = [ws[0] & 0x3FFF for _, ws in flash]
        order = sorted(range(len(flash)), key=lambda i: seqs[i])
        gaps = [((seqs[order[(k + 1) % len(order)]] - seqs[order[k]]) & 0x3FFF, k) for k in range(len(order))]
        start = (max(gaps)[1] + 1) % len(order)
        flash = [flash[order[(start + k) % len(order)]] for k in range(len(order))]
        seen, uniq = set(), []
        for idx, ws in flash:
            if ws[0] & 0x3FFF not in seen:
                seen.add(ws[0] & 0x3FFF)
                uniq.append((idx, ws))
        flash = uniq
    out = []
    for idx, ws in flash + ram[-1:]:
        for k in range(5):
            e = ws[1 + 6 * k: 7 + 6 * k]
            st, play, vol, on, off, slp = e
            if e[1:] == [0xFFFF] * 5 or (st == 0xFFFF and e[1:] == [0] * 5):   # unused, or opened and empty
                continue
            closed = st != 0xFFFF
            out.append({
                "page": idx, "seq": ws[0] & 0x3FFF, "power_on": bool(ws[0] & 0x8000) and k == 0,
                "closed": closed,
                "batt_adc": st & 0x3FF if closed else None,
                "power_src": (st >> 10) & 3 if closed else None,
                "charge_full": (st >> 12) & 1 if closed else None,
                "out5": (st >> 13) & 1 if closed else None,
                "batt_low": (st >> 14) & 1 if closed else None,
                "play_s": play * TICK, "vol_avg": (vol * 16 / play) if play >= 16 else None,
                "silent_speaker_on_s": on * TICK, "silent_speaker_off_s": off * TICK,
                "asleep_s": slp * sleep_w * TICK, "asleep_ticks": slp,
            })
    return out


def summary(es):
    def t(s):
        return "%d h %02d min" % (s // 3600, s % 3600 // 60)
    play = sum(e["play_s"] for e in es)
    on = sum(e["silent_speaker_on_s"] for e in es)
    off = sum(e["silent_speaker_off_s"] for e in es)
    slp = sum(e["asleep_s"] for e in es)
    batt = [e for e in es if e["closed"] and e["power_src"] == 1]
    lines = [
        "windows: %d, power-ons: %d" % (len(es), sum(e["power_on"] for e in es)),
        "total (approx.): %s" % t(play + on + off + slp),
        "  playing:                  %s" % t(play),
        "  silence, speaker on:      %s" % t(on),
        "  silence, speaker off:     %s" % t(off),
        "  asleep (slow ticks x %s): %s" % ("SLEEP_W", t(slp)),
    ]
    vols = {}
    for e in es:
        if e["vol_avg"] is not None:
            v = round(e["vol_avg"])
            vols[v] = vols.get(v, 0) + e["play_s"]
    if vols:
        lines.append("playing by volume (window average): " +
                     ", ".join("%d: %s" % (v, t(s)) for v, s in sorted(vols.items())))
    if batt:
        lines.append("on battery: %d windows, ADC %d -> %d" % (len(batt), batt[0]["batt_adc"], batt[-1]["batt_adc"]))
    return "\n".join(lines)


def to_csv(es):
    f = io.StringIO()
    w = csv.DictWriter(f, fieldnames=list(es[0].keys()) if es else ["page"])
    w.writeheader()
    for e in es:
        w.writerow(e)
    return f.getvalue()
