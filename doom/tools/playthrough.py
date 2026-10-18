#!/usr/bin/env python3
"""Plan and replay a keyboard-only route from spawn to the exit switch.

The planner assumes doors can open; the C replay must actually use them, fight,
walk each segment and win. No teleport or inventory/state cheats in the replay.
Generated route/frame data stays in the ignored build/ directory.
"""
import heapq
import copy
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import doommap


def exit_goal(m, start):
    """32 units east of the exit switch (the replay ends facing west), on the start's 16-unit grid."""
    (x1, y1, x2, y2) = next(m.collision[i][:4] for i, a in enumerate(m.actions) if a == 255)
    assert x1 == x2, "the replay expects the exit switch on a west wall"
    return x1 + 32 + (start[0] - x1) % 16, (y1 + y2) // 2 - ((y1 + y2) // 2 - start[1]) % 16


def route(goal=None, m=None, start=None):
    m = copy.copy(m or doommap.Map())
    m.sectors = list(m.sectors)
    # Only the plan sees open doors and lowered gates. The actual compiled game starts with them closed.
    for sec, _original, target, kind in m.dynamics:
        f, c, light = m.sectors[sec]
        if kind == 0:
            m.sectors[sec] = f, target, light
        elif kind == 1:
            m.sectors[sec] = target, c, light
    cache = {}
    ox, oy, bw, bh = m.block_info

    def bounds(x, y):
        key = x, y
        if key in cache:
            return cache[key]
        if x - 16 < ox or y - 16 < oy or x + 16 >= ox + bw * 128 or y + 16 >= oy + bh * 128:
            cache[key] = None; return None
        floor, ceiling, _ = m.sectors[doommap.find_sector(m, x, y)]
        candidates = set()
        for by in range((y - 16 - oy)//128, (y + 16 - oy)//128 + 1):
            for bx in range((x - 16 - ox)//128, (x + 16 - ox)//128 + 1):
                at = m.blockmap[by*bw+bx]
                while m.blockmap[at] != 65535:
                    candidates.add(m.blockmap[at]); at += 1
        for i in candidates:
            x1, y1, x2, y2, front, back = m.collision[i]
            if x+16 <= min(x1,x2) or x-16 >= max(x1,x2) or y+16 <= min(y1,y2) or y-16 >= max(y1,y2):
                continue
            sides = {(cy-y1)*(x2-x1) >= (y2-y1)*(cx-x1) for cx in (x-16,x+16) for cy in (y-16,y+16)}
            if len(sides) < 2:
                continue
            if back == 65535:
                cache[key] = None; return None
            floor = max(floor, m.sectors[front][0], m.sectors[back][0])
            ceiling = min(ceiling, m.sectors[front][1], m.sectors[back][1])
        cache[key] = (floor, ceiling) if ceiling-floor >= 56 else None
        return cache[key]

    start = tuple(start or m.start()[:2]); goal = tuple(goal or exit_goal(m, start))
    queue = [(0, 0, start)]; costs = {start:0}; previous = {}
    while queue:
        _f, cost, p = heapq.heappop(queue)
        if p == goal:
            path = [p]
            while p != start:
                p = previous[p]; path.append(p)
            return list(reversed(path))
        if costs[p] != cost:
            continue
        z, _c = bounds(*p)
        for dx,dy in ((16,0),(-16,0),(0,16),(0,-16)):
            q = p[0]+dx, p[1]+dy
            target = bounds(*q); middle = bounds(p[0]+dx//2,p[1]+dy//2)
            if not target or not middle:
                continue
            f,c = target; mf,mc = middle
            if mf-z>24 or mc-z<56 or f-mf>24 or c-mf<56:
                continue
            nc = cost+16
            if nc < costs.get(q,10**9):
                costs[q] = nc; previous[q] = p
                heapq.heappush(queue,(nc+abs(q[0]-goal[0])+abs(q[1]-goal[1]),nc,q))
    raise RuntimeError('no traversable route to the exit')


if __name__ == '__main__':
    import webbuild
    out = ROOT/'build'; out.mkdir(exist_ok=True)
    path = route(); (out/'route.json').write_text(json.dumps(path))
    webbuild.main([str(out/'playthrough-game.json')])
    print(f'Planned {len(path)-1} walking segments', flush=True)
    subprocess.run(['node',str(ROOT/'tools/playthrough.cjs'),str(ROOT/'web/p16.js'),
                    str(out/'playthrough-game.json'),str(out/'route.json')],check=True)
