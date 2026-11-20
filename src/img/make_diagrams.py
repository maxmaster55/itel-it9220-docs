#!/usr/bin/env python3
"""Generate the SVG diagrams used in this book.

    python3 src/img/make_diagrams.py        # writes src/img/*.svg

Standard library only. Every address and name drawn here is taken from the
chapter text; when a chapter changes, change the matching data below and
re-run. The SVGs have a solid background so they read the same on light and
dark GitHub/mdBook themes.

Text widths are estimated (no font metrics), so keep some slack in boxes.
"""

from __future__ import annotations

import html
import re
from pathlib import Path

OUT = Path(__file__).resolve().parent

SANS = "system-ui,-apple-system,'Segoe UI',Helvetica,Arial,sans-serif"
MONO = "ui-monospace,SFMono-Regular,Menlo,Consolas,'DejaVu Sans Mono',monospace"

INK = "#1f2328"
MUTED = "#59636e"
BG = "#ffffff"
BORDER = "#d0d7de"

# One palette for every diagram: kind -> (fill, stroke).
KINDS = {
    "rom": ("#f6f8fa", "#6e7781"),  # boot ROM, generic hardware, unlisted space
    "ap": ("#ddf4ff", "#0969da"),  # AP kernel / KernelImg / AP-side blocks
    "user": ("#dafbe1", "#1a7f37"),  # UserImg, Linux user space
    "modem": ("#fff8c5", "#9a6700"),  # DSPs, CM4, modem I/O
    "shared": ("#fbefff", "#8250df"),  # shared memory, queues, mailbox
    "linux": ("#d8f5f0", "#0f766e"),  # Linux kernel side
    "danger": ("#ffebe9", "#cf222e"),  # never write / fatal
    "plain": ("#ffffff", "#8c959f"),
}

CSS = f"""
text{{font-family:{SANS};fill:{INK}}}
.m{{font-family:{MONO}}}
.mu{{fill:{MUTED}}}
.b{{font-weight:600}}
.h{{font-size:20px;font-weight:700}}
.sub{{font-size:13px;fill:{MUTED}}}
"""


def esc(s: str) -> str:
    return html.escape(s, quote=False)


def rich(s: str) -> str:
    """`code` spans become monospace tspans."""
    parts = re.split(r"(`[^`]*`)", s)
    out = []
    for p in parts:
        if p.startswith("`") and p.endswith("`") and len(p) >= 2:
            out.append(f'<tspan class="m">{esc(p[1:-1])}</tspan>')
        elif p:
            out.append(esc(p))
    return "".join(out)


def est_width(s: str, size: float) -> float:
    """Rough rendered width: sans ~0.56em, mono ~0.61em per character."""
    w = 0.0
    for i, p in enumerate(re.split(r"`", s)):
        w += len(p) * size * (0.61 if i % 2 else 0.56)
    return w


class Svg:
    def __init__(self, name: str, w: int, h: int, title: str, desc: str):
        self.name, self.w, self.h = name, w, h
        self.title, self.desc = title, desc
        self.items: list[str] = []
        self.markers: set[str] = set()

    # primitives -----------------------------------------------------------
    def add(self, s: str) -> None:
        self.items.append(s)

    def rect(self, x, y, w, h, kind="plain", rx=6, dash=False, sw=1.2, fill=None):
        f, st = KINDS[kind]
        d = ' stroke-dasharray="5 4"' if dash else ""
        self.add(
            f'<rect x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}" rx="{rx}" '
            f'fill="{fill or f}" stroke="{st}" stroke-width="{sw}"{d}/>'
        )

    def text(self, x, y, s, size=13, cls="", anchor="start", color=None):
        c = f' class="{cls}"' if cls else ""
        a = f' text-anchor="{anchor}"' if anchor != "start" else ""
        col = f' style="fill:{color}"' if color else ""
        if anchor != "start" and "`" in s:
            # Mixed-font tspans inside middle/end-anchored text are placed
            # inconsistently by some renderers: draw the whole string in mono.
            cls = (cls + " m").strip()
            c = f' class="{cls}"'
            body = esc(s.replace("`", ""))
        else:
            body = rich(s)
        self.add(f'<text x="{x:g}" y="{y:g}" font-size="{size}"{c}{a}{col}>{body}</text>')

    def box(self, x, y, w, h, kind, title, lines=(), size=13, title_size=14,
            dash=False, center=False, sw=1.2):
        """A rounded box with a bold title and smaller lines below."""
        self.rect(x, y, w, h, kind, dash=dash, sw=sw)
        _, st = KINDS[kind]
        anchor = "middle" if center else "start"
        tx = x + w / 2 if center else x + 12
        ty = y + 21 if lines else y + h / 2 + title_size * 0.36
        self.text(tx, ty, title, title_size, "b", anchor, color=st if kind != "plain" else None)
        self._check(title, title_size, w - 24, f"box '{title}'")
        for i, ln in enumerate(lines):
            self.text(tx, ty + 18 + i * 17, ln, size, anchor=anchor)
            self._check(ln, size, w - 24, f"line in '{title}'")
        need = (21 + 18 + (len(lines) - 1) * 17 + 9) if lines else 0
        if need > h:
            print(f"  ! {self.name}: box '{title}' needs height {need}, has {h}")

    def _check(self, s, size, room, what):
        if est_width(s, size) > room + 1:
            print(f"  ! {self.name}: {what} may overflow ({est_width(s, size):.0f} > {room:.0f})")

    def _marker(self, color: str) -> str:
        mid = "a" + color.lstrip("#")
        if mid not in self.markers:
            self.markers.add(mid)
        return mid

    def line(self, pts, color=MUTED, arrow_end=True, arrow_start=False, dash=False, sw=1.5):
        mid = self._marker(color)
        d = " ".join(f"{'M' if i == 0 else 'L'}{x:g},{y:g}" for i, (x, y) in enumerate(pts))
        attrs = f'fill="none" stroke="{color}" stroke-width="{sw}"'
        if dash:
            attrs += ' stroke-dasharray="5 4"'
        if arrow_end:
            attrs += f' marker-end="url(#{mid})"'
        if arrow_start:
            attrs += f' marker-start="url(#{mid})"'
        self.add(f'<path d="{d}" {attrs}/>')

    def heading(self, title: str, sub: str = "") -> None:
        self.text(24, 36, title, 20, "h")
        if sub:
            self.text(24, 56, sub, 13, "sub")

    def legend(self, x, y, entries, gap=26):
        """entries: [(kind, label, dashed)] laid out left to right."""
        cx = x
        for kind, label, dash in entries:
            self.rect(cx, y - 11, 22, 14, kind, rx=3, dash=dash)
            self.text(cx + 30, y, label, 12, "mu")
            cx += 30 + est_width(label, 12) + gap

    # output ---------------------------------------------------------------
    def write(self) -> None:
        defs = "".join(
            f'<marker id="{m}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
            f'markerHeight="7" orient="auto-start-reverse"><path d="M0,0L10,5L0,10z" '
            f'fill="#{m[1:]}"/></marker>'
            for m in sorted(self.markers)
        )
        body = "\n".join(self.items)
        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" height="{self.h}" '
            f'viewBox="0 0 {self.w} {self.h}" role="img" aria-labelledby="t d">\n'
            f'<title id="t">{esc(self.title)}</title>\n<desc id="d">{esc(self.desc)}</desc>\n'
            f"<style>{CSS.strip()}</style>\n<defs>{defs}</defs>\n"
            f'<rect width="{self.w}" height="{self.h}" rx="12" fill="{BG}" stroke="{BORDER}"/>\n'
            f"{body}\n</svg>\n"
        )
        (OUT / f"{self.name}.svg").write_text(svg)
        print(f"wrote {self.name}.svg ({len(svg.encode())} bytes)")


def stroke(kind: str) -> str:
    return KINDS[kind][1]


# ---------------------------------------------------------------------------
# Page 2: boot chain
# ---------------------------------------------------------------------------
def boot_chain() -> None:
    s = Svg("boot-chain", 960, 600, "IT9220 boot chain",
            "Boot ROM, BOOT0, BOOT1, KernelImg and UserImg, with the download-mode branches "
            "(FDL1/FDL2 and BOOT1 auto download). No stage checks a hash or signature.")
    s.heading("Boot chain", "No hash, CRC or signature check at any stage. Red outline: never write these.")

    x, w = 40, 440
    s.box(x, 76, w, 50, "rom", "SoC boot ROM", ["immutable, in silicon"])
    s.box(x, 156, w, 68, "ap", "BOOT0  ·  NAND blocks 0-1", [
        "payload base `0x6400`; read raw by the ROM",
        "reads BOOT1 raw to `0x80100000`, checks only ECC"], sw=2.2)
    s.rect(x, 156, w, 68, "danger", sw=2.2, fill="none")
    s.box(x, 254, w, 68, "ap", "BOOT1  ·  NAND blocks 2-3", [
        "payload base `0x80100200`",
        "reads the reset mode: ADI `0x40608E24` bits [8:4]"])
    s.rect(x, 254, w, 68, "danger", sw=2.2, fill="none")
    s.box(x, 360, w, 86, "ap", "KernelImg  ·  partition 3  (MOCOR, ThreadX)", [
        "DHTB header: checks only magic and version 1",
        "copied to `0x80E65E00`, jumps to `0x80E66000`",
        "sets up clocks, power, panel; hold-key listener"])
    s.rect(x, 360, w, 86, "danger", sw=2.2, fill="none")
    s.box(x, 484, w, 68, "user", "UserImg  ·  partition 4  (phone app, T_P_APP)", [
        "not loaded: window `0x88000000`, size `0x1200000`",
        "demand-paged from NAND, 4 KiB per fault"])

    cx = x + w / 2
    for y0, y1 in ((126, 156), (224, 254), (322, 360), (446, 484)):
        s.line([(cx, y0), (cx, y1 - 1)], stroke("ap"))
    s.text(cx + 10, 345, "other reset modes", 12, "mu")

    # download branches
    rx, rw = 560, 360
    s.box(rx, 76, rw, 86, "modem", "Download mode (from the ROM)", [
        "FDL1 runs from on-chip RAM `0x6200`",
        "FDL2 runs at `0x80100000`, does the NAND writes",
        "Unisoc BSL protocol over USB"])
    s.line([(x + w, 101), (rx - 1, 101)], stroke("modem"))
    s.text(x + w + 12, 94, "download", 12, "mu")

    s.box(rx, 234, rw, 68, "modem", "BOOT1 auto download", [
        "brings up USB, answers the BSL",
        "handshake with `SPRD3`"])
    s.line([(x + w, 280), (rx - 1, 280)], stroke("modem"))
    s.text(x + w + 8, 272, "mode `0x17`", 12, "mu")

    s.box(rx, 330, rw, 50, "rom", "TF_LOAD (TrustZone)", ["loaded only in reset mode 26"], size=12)
    s.line([(x + w, 304), (520, 304), (520, 355), (rx - 1, 355)], stroke("rom"), dash=True)

    s.box(rx, 408, rw, 68, "danger", "Failure behaviour", [
        "BOOT0 returns to the ROM on any failure",
        "BOOT1 hangs in `while(1)`: no fallback"], size=12)
    s.box(rx, 494, rw, 58, "plain", "No fastboot, no unlock", [
        "flashing is BSL over USB only (page 3)"], size=12)

    s.legend(40, 582, [("rom", "ROM / other", False), ("ap", "AP kernel side", False),
                       ("user", "user image", False), ("modem", "download / USB", False)])
    s.write()


# ---------------------------------------------------------------------------
# Page 2: NAND layout
# ---------------------------------------------------------------------------
NAND = [  # (label, first block, last block inclusive, kind, range text)
    ("BOOT0", 0, 1, "ap", "0-1"),
    ("BOOT1", 2, 3, "ap", "2-3"),
    ("NV", 4, 11, "danger", "4-11"),
    ("gsmdsp", 0x15, 0x15 + 0x19 - 1, "modem", "`0x15`+`0x19`"),
    ("ltedsp", 0x2E, 0x2E + 0x3E - 1, "modem", "`0x2E`+`0x3E`"),
    ("KernelImg", 0xF0, 0xF0 + 0x70 - 1, "ap", "`0xF0`+`0x70`"),
    ("UserImg", 0x160, 0x1EB, "user", "`0x160`..`0x1EB`"),
    ("MMIRes", 0x1EC, 0x1EC + 0xC0 - 1, "shared", "`0x1EC`+`0xC0`"),
]


def nand_layout() -> None:
    s = Svg("nand-layout", 960, 380, "IT9220 SPI NAND layout",
            "SPI NAND blocks from the FDL2 partition table: BOOT0, BOOT1, NV, DSP images, "
            "KernelImg, UserImg, MMIRes, the file system and the 43 reserved top blocks.")
    s.heading("SPI NAND layout", "1024 blocks x 128 KiB, from the FDL2 partition table (first..last or first+count). "
              "Grey: not listed.")
    x0, bw = 40, 880

    def bar(y, h, lo, hi, scale_label):
        span = hi - lo + 1
        px = bw / span
        s.rect(x0, y, bw, h, "rom", rx=3)
        for label, a, b, kind, rng in NAND:
            if b < lo or a > hi:
                continue
            a2, b2 = max(a, lo), min(b, hi)
            s.rect(x0 + (a2 - lo) * px, y, (b2 - a2 + 1) * px, h, kind, rx=2,
                   sw=2 if label in ("BOOT0", "BOOT1", "KernelImg") and kind == "ap" else 1)
        s.text(x0, y - 8, scale_label, 12, "mu")
        return px

    # zoom on the first 0x6C blocks
    y1 = 102
    px = bar(y1, 44, 0, 0x6B, "blocks 0 .. 0x6B (zoomed)")
    for label, a, b, kind, rng in NAND[:5]:
        mid = x0 + (a + (b - a + 1) / 2) * px
        if (b - a + 1) * px > 40:
            s.text(mid, y1 + 27, label, 13, "b", "middle", color=stroke(kind))
            s.text(mid, y1 + 62, rng, 12, anchor="middle")
    # the two-block boot partitions are too narrow for labels inside
    s.text(x0 + 1 * px, y1 + 27, "B0", 11, "b", "middle", color=stroke("ap"))
    s.text(x0 + 3 * px, y1 + 27, "B1", 11, "b", "middle", color=stroke("ap"))
    s.text(x0, y1 + 62, "0-1, 2-3", 12)

    # whole device
    y2 = 232
    px = bar(y2, 44, 0, 1023, "whole device, blocks 0 .. 1023 (to scale)")
    # file system: start known, end not listed; fade it towards the reserved area
    fs_a, res_a = 0x2EE, 1024 - 43
    s.add('<defs><linearGradient id="fade" x1="0" x2="1"><stop offset="0" stop-color="#ddf4ff"/>'
          '<stop offset="1" stop-color="#f6f8fa"/></linearGradient></defs>')
    s.add(f'<rect x="{x0 + fs_a * px:g}" y="{y2}" width="{(res_a - fs_a) * px:g}" height="44" '
          f'fill="url(#fade)" stroke="{stroke("ap")}" stroke-dasharray="4 3"/>')
    s.rect(x0 + res_a * px, y2, 43 * px, 44, "danger", rx=2, dash=True)
    # zoom bracket from the zoomed bar to its slice of the whole device
    zx = x0 + 0x6C * px
    s.line([(x0, y1 + 70), (x0, y2 - 26)], MUTED, arrow_end=False, dash=True, sw=1)
    s.line([(x0 + bw, y1 + 70), (zx, y2 - 26)], MUTED, arrow_end=False, dash=True, sw=1)
    for label, a, b, kind, rng in NAND[5:]:
        mid = x0 + (a + (b - a + 1) / 2) * px
        s.text(mid, y2 + 27, label, 13, "b", "middle", color=stroke(kind))
        s.text(mid, y2 + 62, rng, 12, anchor="middle")
    fs_mid = x0 + (fs_a + res_a) / 2 * px
    s.text(fs_mid, y2 + 27, "file system (id 8)", 13, "b", "middle", color=stroke("ap"))
    s.text(fs_mid, y2 + 62, "from 0x2EE, end not listed", 12, anchor="middle")
    s.text(x0 + bw, y2 - 8, "top 43 blocks: VBM_BOOT + bad-block maps", 12, "mu", "end")
    s.line([(x0 + bw - 18, y2 - 4), (x0 + bw - 18, y2 - 1)], stroke("danger"), arrow_end=False)
    s.text(x0, y2 + 100, "UserImg: 140 blocks, `0x1180000` bytes, raw (attr `0x100`). "
           "Thick outline: BOOT0, BOOT1, KernelImg: never write.", 12, "mu")
    s.text(x0, y2 + 118, "Red: NV holds the IMEI and RF calibration: back it up before any write.", 12, "mu")
    s.write()


# ---------------------------------------------------------------------------
# Page 1: memory map
# ---------------------------------------------------------------------------
PHYS = [  # (address text, title, detail, kind)
    ("`0x00000000`", "On-chip RAM", "FDL1 loaded to `0x6200`; vectors `0x0..0x3C`", "rom"),
    ("`0x0000E400`", "LTE DSP rings", "to `0x10BFF`; mode word `0x10BF8`", "modem"),
    ("`0x00010C00`", "GSM DSP dual-port area", "FrameInst / RespQ queues", "shared"),
    ("`0x12001000`", "GIC v2", "GICD; GICC at `0x12002000`", "ap"),
    ("`0x20000000`", "AHB peripherals", "DMA, USB, SDIO, LCDC, NAND", "ap"),
    ("`0x40000000`", "APB, AON, PMU, ADI", "codec, VBC, mailbox, timers, GPIO", "ap"),
    ("`0x60810000`", "LTE security engine", "radio power (PMU) `0x60830000`", "modem"),
    ("`0x70000000`", "UART0 / UART1 / UART2", "`0x70000000`, `0x70100000`, `0x70200000`", "ap"),
    ("`0x80000000`", "DRAM, 64 MB", "to `0x83FFFFFF`  (detail on the right)", "user"),
    ("`0x88000000`", "UserImg window (virtual)", "`0x1200000`, demand-paged from NAND", "user"),
    ("`0xC0000000`", "Modem / baseband I/O windows", "to `0xEFFFFFFF`; not ordinary peripherals", "modem"),
]

DRAM = [  # (start, end, kind, label, detail)
    (0x80000000, 0x80020000, "rom", "zeroed by stock at start-up", "128 KiB"),
    (0x80020000, 0x800F4000, "modem", "CM4 firmware", "`0xD4000` bytes"),
    (0x80100000, 0x80120000, "shared", "GSM shared block A", "`0x20000`; BOOT1 / FDL2 also run here"),
    (0x80120000, 0x80420000, "modem", "GSM DSP image", "`0x300000` bytes"),
    (0x803A8000, None, "shared", "GSM shared block B", "voice rings (inside the DSP's range)"),
    (0x80468000, 0x80906000, "modem", "LTE DSP image", "`0x49E000` bytes"),
    (0x80E65E00, 0x81A92000, "ap", "KernelImg", "DHTB header; code from `0x80E66000`"),
    (0x81B00000, 0x81C00000, "ap", "page pool for UserImg", "1 MB"),
    (0x81C20000, 0x826B7340, "ap", "kernel data + BSS", "to about `0x826B7340`"),
    (0x826B7000, 0x83FE0000, "user", "stock heap / pool region", "about 25 MB; OSA pools at `0x8276D000`"),
    (0x83FE0000, 0x84000000, "rom", "zeroed by stock at start-up", "128 KiB"),
]


def memory_map() -> None:
    s = Svg("memory-map", 960, 720, "UMS9117 memory map",
            "Physical address space of the UMS9117 as used by the stock firmware, and the "
            "64 MB DRAM drawn to scale with the regions the modem side and the stock kernel use.")
    s.heading("Memory map", "Addresses increase downwards. Left: not to scale. Right: DRAM to scale.")

    # left: physical overview
    x, w, rh, y = 24, 404, 52, 76
    for addr, title, detail, kind in PHYS:
        s.rect(x + 104, y, w - 104, rh - 6, kind)
        s.text(x + 96, y + 19, addr, 12, anchor="end")
        s.text(x + 116, y + 18, title, 13, "b", color=stroke(kind))
        s.text(x + 116, y + 36, detail, 12)
        s._check(detail, 12, w - 120, f"'{title}'")
        y += rh

    # right: DRAM to scale
    top, height = 76, 600
    bx, bwid = 520, 92
    lo, hi = 0x80000000, 0x84000000
    scale = height / (hi - lo)

    def ypos(a):
        return top + (a - lo) * scale

    s.rect(bx, top, bwid, height, "rom", rx=2, fill="#ffffff")
    for a, b, kind, *_ in DRAM:
        if b is None:
            continue
        s.rect(bx, ypos(a), bwid, max(ypos(b) - ypos(a), 1.5), kind, rx=1, sw=1)
    # block B marker
    yb = ypos(0x803A8000)
    s.add(f'<line x1="{bx}" y1="{yb:g}" x2="{bx + bwid}" y2="{yb:g}" stroke="{stroke("shared")}" '
          f'stroke-width="2.5"/>')
    s.text(bx - 6, top + 4, "`0x80000000`", 11, anchor="end")
    s.text(bx - 6, top + height + 4, "`0x84000000`", 11, anchor="end")
    for mb in range(8, 64, 8):
        yy = ypos(lo + mb * 0x100000)
        s.add(f'<line x1="{bx - 4}" y1="{yy:g}" x2="{bx}" y2="{yy:g}" stroke="{MUTED}"/>')
        s.text(bx - 8, yy + 4, f"{mb} MB", 10, "mu", "end")

    # labels with leader lines, pushed apart to avoid overlaps
    lx, gap = bx + bwid + 34, 52
    want = []
    for a, b, kind, label, detail in DRAM:
        mid = ypos(a) if b is None else (ypos(a) + ypos(b)) / 2
        want.append([mid, a, kind, label, detail])
    pos = [w_[0] for w_ in want]
    for _ in range(200):  # simple relaxation
        for i in range(1, len(pos)):
            if pos[i] - pos[i - 1] < gap:
                d = (gap - (pos[i] - pos[i - 1])) / 2
                pos[i - 1] -= d
                pos[i] += d
        pos = [min(max(p, top + 10), top + height - 30) for p in pos]
    for (mid, a, kind, label, detail), ly in zip(want, pos):
        s.line([(bx + bwid + 2, mid), (bx + bwid + 8, mid), (lx - 6, ly - 1)], stroke(kind),
               arrow_end=False, sw=1)
        s.text(lx, ly - 4, f"`{a:#010X}`".replace("0X", "0x") + f"  {label}", 13, "b", color=stroke(kind))
        s.text(lx, ly + 13, detail, 12)
    s.write()


# ---------------------------------------------------------------------------
# Page 1 / 4: peripheral map
# ---------------------------------------------------------------------------
def peripheral_map() -> None:
    s = Svg("peripheral-map", 960, 860, "UMS9117 peripheral map",
            "The UMS9117 register blocks with base addresses and GIC SPI numbers, and the "
            "off-chip parts they connect to on the IT9220: PMIC, LCD, SPI NAND, microSD, "
            "Marlin2 Wi-Fi/BT/FM, USB-C and the keypad.")
    s.heading("UMS9117 blocks on the IT9220", "Base address and GIC SPI number of each block "
              "(from stock driver code). Right and bottom: off-chip parts.")
    soc_x, soc_y, soc_w, soc_h = 24, 72, 650, 612
    s.rect(soc_x, soc_y, soc_w, soc_h, "rom", rx=10, dash=True)
    s.text(soc_x + 14, soc_y + 22, "UMS9117 SoC", 14, "b", color=stroke("rom"))

    s.box(44, 104, 190, 50, "ap", "Cortex-A7", ["one core, about 1 GHz"], size=12)
    s.box(250, 104, 190, 50, "ap", "GIC v2", ["`0x12001000` / `0x12002000`"], size=12)
    s.box(456, 104, 198, 50, "user", "DRAM 64 MB", ["`0x80000000`"], size=12)

    def column(x, y, w, header, rows, kind, pitch):
        """rows: (name, address, SPI); pitch(name) gives the vertical step."""
        s.text(x, y, header, 13, "b", color=stroke(kind))
        y += 10
        ys = {}
        for name, addr, spi in rows:
            s.rect(x, y, w, 26, kind, rx=4, sw=1)
            s.text(x + 8, y + 17, name, 12)
            if addr:
                s.text(x + w - 160, y + 17, f"`{addr}`", 11.5)
            if spi:
                s.text(x + w - 8, y + 17, f"SPI {spi}", 11.5, "mu", "end")
            s._check(name, 12, w - 172, f"row '{name}'")
            ys[name] = y + 13
            y += pitch(name)
        return ys

    apb = column(44, 186, 300, "APB / AON  (0x40000000+)", [
        ("Codec (digital)", "0x40000000", 20),
        ("VBC", "0x40020000", None),
        ("Mailbox in / out", "0x400A0000", "68/69"),
        ("AP timer 0", "0x40220000", 29),
        ("1 kHz counter", "0x4023000C", 31),
        ("Pin / strap", "0x40250000", None),
        ("GPIO (128 lines)", "0x40280000", 35),
        ("Pinmux", "0x402A0000", None),
        ("PMU / radio power", "0x402B0000", None),
        ("AON clock gates", "0x402E0000", None),
        ("Watchdog (AP)", "0x40310000", 123),
        ("UART0 / 1 / 2", "0x70000000", "18/3/17"),
        ("Keypad", "", 36),
        ("ADI (PMIC bus)", "0x40600000", 25),
    ], "ap", lambda n: 30)
    with_dev = {"MUSB (USB device)", "SDIO0", "SDIO1", "LCDC (SPI1)", "SPI-NAND ctrl"}
    ahb = column(364, 186, 290, "AHB  (0x20000000+)", [
        ("AP DMA", "0x20100000", 50),
        ("AHB clock gates", "0x20E00000", None),
        ("MUSB (USB device)", "0x20200000", 55),
        ("SDIO0", "0x20300000", 57),
        ("SDIO1", "0x20400000", 58),
        ("LCDC (SPI1)", "0x20800000", 19),
        ("SPI-NAND ctrl", "0x21A00000", 59),
    ], "ap", lambda n: 56 if n in with_dev else 30)

    # off-chip devices, each level with its AHB row
    ox, ow = 714, 222
    devs = [
        ("MUSB (USB device)", "USB Type-C", "charge + data"),
        ("SDIO0", "microSD slot", "card detect broken: poll"),
        ("SDIO1", "Marlin2 combo chip", "Wi-Fi, BT, FM (page 6)"),
        ("LCDC (SPI1)", "ST7789 panel", "240 x 320, SPI1, 48 MHz"),
        ("SPI-NAND ctrl", "SPI NAND", "128 MiB, 128 KiB blocks"),
    ]
    for src, name, detail in devs:
        cy = ahb[src]
        s.box(ox, cy - 24, ow, 48, "rom", name, [detail], size=12, title_size=13)
        s.line([(655, cy), (ox - 1, cy)], MUTED, arrow_start=True)

    # modem subsystem inside the SoC
    s.box(364, 548, 290, 120, "modem", "Modem subsystem", [
        "GSM DSP, CEVA TeakLite-4 (core 2)",
        "LTE DSP (core 3)",
        "Cortex-M4 (CM4) firmware",
        "I/O windows `0xC0000000`-`0xEFFFFFFF`"], size=12)
    my = apb["Mailbox in / out"]
    s.line([(345, my), (354, my), (354, 608), (363, 608)], stroke("shared"), arrow_start=True)

    # off-chip bottom: keypad (left) and PMIC (right)
    s.box(24, 712, 300, 132, "rom", "Keypad matrix", [
        "keymap `u16[64]`, col*8 + row",
        "GPIO mapping from strap `0x4025002C`",
        "End key = power key (via PMIC)",
        "no side or volume keys"], size=12)
    ky = apb["Keypad"]
    s.line([(43, ky), (34, ky), (34, 711)], MUTED, arrow_start=True)
    s.box(344, 712, 592, 132, "shared", "PMIC (SC27xx family), registers at `0x40608000`+", [
        "RTC · ADC (battery) · SC2720 audio codec with loudspeaker PA",
        "LDOs (`vddwcn`, `vddusb`, `vddsim0`, SD) · WLED backlight",
        "keypad light · vibrator · torch · power key",
        "EIC (headset detect) at `0x40608280`"], size=12)
    ay = apb["ADI (PMIC bus)"]
    s.line([(300, ay + 14), (300, 696), (420, 696), (420, 711)], MUTED, arrow_start=True)
    s.text(308, 652, "ADI bus", 12, "mu")
    s.write()


# ---------------------------------------------------------------------------
# Page 8: GSM DSP queues and mailbox
# ---------------------------------------------------------------------------
def gsm_dsp_flow() -> None:
    s = Svg("gsm-dsp-flow", 960, 640, "GSM DSP queue and mailbox flow",
            "How the AP's layer 1 control feeds the CEVA GSM DSP one frame instruction per TDMA "
            "frame through the FrameInst queue in the dual-port area, and how responses come back "
            "through RespQ and the mailbox interrupt.")
    s.heading("GSM DSP: queues and mailbox",
              "One frame instruction per TDMA frame (4.615 ms). The mailbox only wakes the other side; "
              "the data is in the queues.")

    # AP column
    ax, aw = 24, 290
    s.text(ax, 92, "AP (Cortex-A7), stock KernelImg", 14, "b", color=stroke("ap"))
    s.box(ax, 104, aw, 50, "ap", "Layers 2/3", ["RR, MM, CC, SMS"], size=12)
    s.box(ax, 178, aw, 68, "ap", "Layer 1 control (frame engine)", [
        "layer-1 task (task id `0x5D`)",
        "fills FrameInst in batches"], size=12)
    s.box(ax, 300, aw, 68, "ap", "HISR  (`dspintisr.c`)", [
        "reads RespQ until empty, posts",
        "signals to the layer-1 task"], size=12)
    s.box(ax, 392, aw, 68, "ap", "Mailbox ISR  (outbox, SPI 69)", [
        "only empties the outbox",
        "then queues the HISR"], size=12)
    s.line([(ax + aw / 2, 154), (ax + aw / 2, 177)], stroke("ap"), arrow_start=True)
    s.line([(ax + aw / 2, 392), (ax + aw / 2, 369)], stroke("ap"))
    s.line([(ax + aw / 2, 300), (ax + aw / 2, 247)], stroke("ap"))
    s.text(ax + aw / 2 + 8, 278, "signals", 12, "mu")

    # dual-port area in the middle
    mx, mw = 350, 260
    s.text(mx, 92, "Dual-port area `0x00010C00`", 14, "b", color=stroke("shared"))
    s.rect(mx, 104, mw, 356, "shared", rx=8)

    # FrameInst ring
    s.text(mx + 12, 126, "FrameInst  `+0x000`", 13, "b")
    s.text(mx + 12, 143, "26 slots x 36 bytes, AP writes", 12)
    slots, sx, sy, sw_ = 26, mx + 12, 154, (mw - 24) / 13
    for i in range(slots):
        r, c = divmod(i, 13)
        filled = 3 <= i <= 9
        free = i == 10
        fill = "#d8b9ff" if filled else ("#ffffff")
        dash = ' stroke-dasharray="3 2"' if free else ""
        s.add(f'<rect x="{sx + c * sw_:g}" y="{sy + r * 20:g}" width="{sw_ - 3:g}" height="16" rx="2" '
              f'fill="{fill}" stroke="{stroke("shared")}"{dash}/>')
    s.text(mx + 12, 212, "read index `+0x3A8` (DSP)", 12)
    s.text(mx + 12, 228, "write index `+0x3AA` (AP)", 12)
    s.text(mx + 12, 244, "one slot always stays free", 12, "mu")

    s.add(f'<line x1="{mx + 12}" y1="262" x2="{mx + mw - 12}" y2="262" stroke="{BORDER}"/>')
    s.text(mx + 12, 284, "Command queue  `+0x70C`", 13, "b")
    s.text(mx + 12, 301, "8 slots x 12 bytes, AP to DSP", 12)

    s.add(f'<line x1="{mx + 12}" y1="318" x2="{mx + mw - 12}" y2="318" stroke="{BORDER}"/>')
    s.text(mx + 12, 340, "RespQ  `+0x770`", 13, "b")
    s.text(mx + 12, 357, "8 slots x 12 bytes, DSP writes", 12)
    for i in range(8):
        fill = "#d8b9ff" if i in (2, 3) else "#ffffff"
        s.add(f'<rect x="{mx + 12 + i * 30:g}" y="368" width="26" height="16" rx="2" fill="{fill}" '
              f'stroke="{stroke("shared")}"/>')
    s.text(mx + 12, 402, "read `+0x7D0` (AP) / write `+0x7D2` (DSP)", 12)
    s.text(mx + 12, 420, "low byte = response number,", 12, "mu")
    s.text(mx + 12, 436, "then four 16-bit parameters", 12, "mu")

    # DSP column
    dx, dw = 646, 290
    s.text(dx, 92, "GSM DSP (CEVA TeakLite-4)", 14, "b", color=stroke("modem"))
    s.box(dx, 104, dw, 86, "modem", "Physical layer", [
        "executes one instruction per frame",
        "kinds seen: 0 idle, 11 power",
        "measurement (up to 6 carriers)"], size=12)
    s.box(dx, 300, dw, 68, "modem", "Results", [
        "writes RespQ, then raises the",
        "mailbox (core 2) to the AP"], size=12)
    s.box(dx, 392, dw, 68, "shared", "Mailbox  `0x400A0000` / `0x400A8000`", [
        "AP to DSP: ID 2, TRIGGER 1",
        "DSP to AP: outbox interrupt, SPI 69"], size=12)

    # flows
    s.line([(ax + aw, 212), (mx - 1, 212)], stroke("ap"))
    s.text(ax + aw + 6, 204, "write", 12, "mu")
    s.line([(mx + mw, 170), (dx - 1, 150)], stroke("modem"))
    s.text(mx + mw + 6, 150, "read", 12, "mu")
    s.line([(dx, 334), (mx + mw + 1, 360)], stroke("modem"))
    s.text(mx + mw + 6, 334, "write", 12, "mu")
    s.line([(mx - 1, 376), (ax + aw + 1, 340)], stroke("shared"))
    s.text(ax + aw + 6, 374, "read", 12, "mu")
    s.line([(dx + dw / 2, 368), (dx + dw / 2, 391)], stroke("modem"))
    s.line([(dx + dw / 2, 461), (dx + dw / 2, 482), (ax + aw + 18, 482), (ax + aw + 18, 426),
            (ax + aw + 1, 426)], stroke("shared"))
    s.text(474, 498, "interrupt, line 69", 12, "mu", "middle")

    # shared DRAM blocks and deadline
    s.box(24, 516, 440, 102, "shared", "Shared DRAM blocks", [
        "A `0x80100000` (`0x20000`): parameters; ready word: AP 1, DSP 2",
        "B `0x803A8000`: voice PCM rings (formats guessed)",
        "image at `0x80120000`, boot vector = byte address / 2"], size=12)
    s.box(484, 516, 452, 102, "danger", "Deadline: 1 to 3 TDMA frames (4.6 to 13.8 ms)", [
        "from the DSP's interrupt to new instructions in the queue",
        "a miss is fatal in stock: \"L1:dsp overrun\", \"FrameInst full!\",",
        "`dsp assert 0x1c20` on a loaded host"], size=12)
    s.write()


# ---------------------------------------------------------------------------
# Page 10: stock modem under Linux
# ---------------------------------------------------------------------------
def modem_under_linux() -> None:
    s = Svg("modem-under-linux", 960, 728, "Stock modem stack under Linux (mocord)",
            "Architecture of mocord: the stock KernelImg and UserImg are mapped at their own "
            "addresses inside a Linux process, a compatibility layer replaces ThreadX's port "
            "layer, and small kernel drivers forward interrupts and arbitrate shared hardware.")
    s.heading("Stock modem stack under Linux (\"mocord\")",
              "Stock images run unmodified at their own addresses inside one Linux process.")

    def band(y, h, label, kind):
        f, st = KINDS[kind]
        s.add(f'<rect x="16" y="{y}" width="928" height="{h}" rx="10" fill="{f}" fill-opacity="0.45" '
              f'stroke="{st}" stroke-opacity="0.5"/>')
        s.add(f'<text x="34" y="{y + h / 2:g}" font-size="13" class="b" text-anchor="middle" '
              f'transform="rotate(-90 34 {y + h / 2:g})" style="fill:{st}">{esc(label)}</text>')

    band(72, 330, "Linux user space", "user")
    band(414, 150, "Linux kernel", "linux")
    band(576, 108, "Hardware", "rom")

    # mocord process
    px, pw = 60, 560
    s.rect(px, 84, pw, 306, "plain", rx=10, sw=1.5)
    s.text(px + 14, 106, "mocord  (SCHED_FIFO, mlockall, pre-faulted)", 14, "b")
    s.box(px + 14, 118, 252, 86, "ap", "Stock KernelImg", [
        "at `0x80E65E00`",
        "ThreadX, 109 stock threads",
        "protocol stack, layer-1 control"], size=12)
    s.box(px + 294, 118, 252, 86, "user", "Stock UserImg", [
        "at `0x88000000`, `mmap(MAP_FIXED)`",
        "ATC (AT), tcpip / DSM glue, MMI",
        "calls in through 2003 veneers"], size=12)
    s.line([(px + 267, 161), (px + 293, 161)], MUTED, arrow_start=True)
    s.box(px + 14, 218, 532, 158, "linux", "Compatibility layer (replaces ThreadX's port layer)", [
        "scheduler: swap the signal handler's `ucontext` to switch threads",
        "signal = interrupt: call stock's handler, queue the HISR",
        "SIGSEGV: emulate modem I/O `0xC0000000`-`0xEFFFFFFF`; SIGILL: skip CP15, WFI",
        "about 25 hooks: trace, sleep, asserts, irq off/restore, ISR register",
        "NV served from a backup; stock's flash layer never writes NAND",
        "OS tick from a Linux timer (SPI 29 stays Linux's)"], size=12)

    # right side of user space
    rx, rw = 650, 280
    s.box(rx, 96, rw, 60, "plain", "Host side", ["control over AT, data over TUN"], size=12)
    s.box(rx, 182, rw, 60, "user", "AT over a pseudo-port", ["`+CREG`, `+COPS`, `+CSQ`, calls, SMS"], size=12)
    s.box(rx, 268, rw, 76, "user", "IP bridge", [
        "PDP context 1, cut at the DSM layer,",
        "bridged to a Linux TUN device"], size=12)
    s.line([(rx + rw / 2, 156), (rx + rw / 2, 181)], MUTED, arrow_start=True)
    s.line([(rx, 190), (px + pw - 13, 190)], stroke("user"), arrow_start=True)
    s.line([(rx, 306), (630, 306), (630, 198), (px + pw - 13, 198)], stroke("user"), arrow_start=True)

    # kernel band
    s.box(60, 426, 270, 126, "linux", "mocirq / ums9117-irqfwd", [
        "masks the line, signals mocord",
        "68/69 mailbox, 113/115 modem",
        "timers, 71 `DMA_LINK`,",
        "10/13 SIM, 93"], size=12)
    s.box(346, 426, 274, 126, "linux", "Shared-hardware driver", [
        "arbitrates what both sides touch:",
        "GIC, AP timer, ADI/PMIC,",
        "clock gates, AP DMA,",
        "watchdog, deep sleep"], size=12)
    s.box(650, 426, 280, 126, "linux", "Reserved memory (`no-map`)", [
        "`0x81B00000`-`0x826B8000`",
        "+ DSP ranges + two 128 KiB blocks",
        "physical addresses handed to",
        "DMA or a DSP stay valid"], size=12)
    s.line([(195, 425), (195, 377)], stroke("linux"))
    s.text(203, 410, "signal", 12, "mu")
    s.line([(483, 425), (483, 377)], stroke("linux"), arrow_start=True)

    # hardware band
    s.box(60, 590, 270, 80, "modem", "GSM DSP (CEVA TeakLite-4)", [
        "FrameInst / RespQ at `0x10C00`",
        "shared blocks A, B in DRAM"], size=12)
    s.box(346, 590, 274, 80, "shared", "Mailbox, timers, SIM0/1", [
        "interrupt lines into the GIC",
        "forwarded one by one"], size=12)
    s.box(650, 590, 280, 80, "modem", "LTE DSP", [
        "attach reached once,",
        "no user data (page 9)"], size=12)
    s.line([(483, 589), (483, 566), (280, 566), (280, 553)], stroke("shared"))
    # direct shared-memory path from stock code to the DSP (no copy, no driver)
    s.line([(px + 13, 161), (48, 161), (48, 640), (59, 640)], stroke("modem"), dash=True,
           arrow_start=True)
    s.line([(60, 708), (92, 708)], stroke("modem"), arrow_end=False, dash=True)
    s.text(100, 712, "stock code reads and writes the DSP's shared memory directly "
           "(physical addresses, hence the reserved ranges)", 12, "mu")
    s.write()


def main() -> None:
    for fn in (boot_chain, nand_layout, memory_map, peripheral_map, gsm_dsp_flow, modem_under_linux):
        fn()


if __name__ == "__main__":
    main()
