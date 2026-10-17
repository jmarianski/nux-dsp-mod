"""Hard word-address limits for the NEK-100 demo. End addresses are exclusive."""
RAM_START, RAM_END = 0x6448, 0x662a
GLUE_START = 0x6430
FRAMEBUFFER_WORDS = 1024
ROM_START, ROM_END = 0x1a280, 0x3ffc0   # target.map's far pool, preserving its end reserve
PARTITION_WORDS = 0x40000


def check_ram(used):
    capacity = RAM_END - RAM_START
    if used < 0 or used > capacity:
        raise ValueError(f"RAM budget exceeded: {used}/{capacity} words")
    return {"used": used, "limit": capacity, "free": capacity - used,
            "glue_reserved": RAM_START - GLUE_START, "framebuffer": FRAMEBUFFER_WORDS}


def check_regions(regions):
    """Reject overflow and overlap, including data running into compiled instructions."""
    occupied = sorted((a, a + n, name) for name, a, n in regions if n)
    for i, (a, b, name) in enumerate(occupied):
        if a < ROM_START or b > ROM_END:
            raise ValueError(f"program budget exceeded by {name}: {a:#x}..{b:#x}, allowed {ROM_START:#x}..{ROM_END:#x}")
        if i and a < occupied[i - 1][1]:
            raise ValueError(f"program regions overlap: {occupied[i - 1][2]} / {name}")
    end = max((b for _, b, _ in occupied), default=ROM_START)
    return {"used": sum(b - a for a, b, _ in occupied), "limit": ROM_END - ROM_START,
            "high_water": end, "free_after_end": ROM_END - end, "partition_words": PARTITION_WORDS}


def check_firmware(data):
    if len(data) % 2 or len(data) // 2 > PARTITION_WORDS:
        raise ValueError(f"firmware exceeds {PARTITION_WORDS} words / {PARTITION_WORDS * 2} bytes")
    from nuxdsp import container
    problems = container.validate(data)
    if problems:
        raise ValueError("invalid firmware: " + "; ".join(problems))
    return {"used": len(data) // 2, "limit": PARTITION_WORDS, "free": PARTITION_WORDS - len(data) // 2}
