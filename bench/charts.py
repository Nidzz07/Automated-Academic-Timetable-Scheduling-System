"""Hand-written SVG charts for the evaluation figures (S15c).

No plotting library is installed and none is added, so :func:`chart` writes the SVG
text itself: one shared y axis (linear, or log10 with decade ticks), one marker
shape per series as well as one colour, and a legend, so no series is told apart
by colour alone.
"""

from __future__ import annotations

import math
from pathlib import Path
from xml.sax.saxutils import escape

# reference data-viz palette, categorical slots 1 and 2 (blue, orange), on its light surface
COLOURS = ("#2a78d6", "#eb6834")
SURFACE, INK, MUTED, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
W, H = 640, 400
LEFT, RIGHT, TOP, BOTTOM = 80, 20, 64, 56

Series = tuple[str, list[tuple[float, float]]]


def _ticks(lo: float, hi: float) -> list[float]:
    """1-2-5 ticks from at or below *lo* to at or above *hi*, about five steps."""
    if lo == hi:
        lo, hi = lo - 1, hi + 1
    raw = (hi - lo) / 5
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 5, 10) if m * mag >= raw)
    ticks = [math.floor(lo / step) * step]
    while ticks[-1] < hi - 1e-9:
        ticks.append(round(ticks[-1] + step, 10))
    return ticks


def _marker(shape: int, x: float, y: float, colour: str) -> str:
    ring = f'fill="{colour}" stroke="{SURFACE}" stroke-width="2"'
    if shape == 0:
        return f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" {ring}/>'
    return f'<rect x="{x - 5:.1f}" y="{y - 5:.1f}" width="10" height="10" {ring}/>'


def chart(path: Path, title: str, x_label: str, y_label: str, series: list[Series],
          *, log_y: bool = False, lines: bool = True) -> str:
    """Write a line (or, with ``lines=False``, dot) chart of *series* to *path*; return it.

    Every y value must be positive when *log_y*. At most two series (two palette slots).
    """
    xs = [x for _, pts in series for x, _ in pts]
    ys = [y for _, pts in series for _, y in pts]
    x_ticks = _ticks(min(xs), max(xs))
    if log_y:
        y_ticks = [10.0 ** k for k in range(math.floor(math.log10(min(ys))),
                                            math.ceil(math.log10(max(ys))) + 1)]
    else:
        y_ticks = _ticks(min(ys), max(ys))

    def fy(y: float) -> float:
        lo, hi, v = y_ticks[0], y_ticks[-1], y
        if log_y:
            lo, hi, v = math.log10(lo), math.log10(hi), math.log10(y)
        return H - BOTTOM - (v - lo) / (hi - lo) * (H - TOP - BOTTOM)

    def fx(x: float) -> float:
        return LEFT + (x - x_ticks[0]) / (x_ticks[-1] - x_ticks[0]) * (W - LEFT - RIGHT)

    def text(x: float, y: float, s: str, anchor: str = "middle", fill: str = MUTED,
             extra: str = "") -> str:
        return (f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}" fill="{fill}"{extra}>'
                f"{escape(s)}</text>")

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
           f'viewBox="0 0 {W} {H}" font-family="system-ui, sans-serif" font-size="12">',
           f"<title>{escape(title)}</title>",
           f'<rect width="{W}" height="{H}" fill="{SURFACE}"/>',
           text(LEFT, 22, title, "start", INK, ' font-size="15" font-weight="600"')]
    for y in y_ticks:
        out.append(f'<line x1="{LEFT}" x2="{W - RIGHT}" y1="{fy(y):.1f}" y2="{fy(y):.1f}" '
                   f'stroke="{GRID}"/>')
        out.append(text(LEFT - 8, fy(y) + 4, f"{y:,g}", "end"))
    for x in x_ticks:
        out.append(text(fx(x), H - BOTTOM + 18, f"{x:,g}"))
    out.append(f'<line x1="{LEFT}" x2="{W - RIGHT}" y1="{H - BOTTOM}" y2="{H - BOTTOM}" '
               f'stroke="{MUTED}"/>')
    out.append(text((LEFT + W - RIGHT) / 2, H - 14, x_label))
    out.append(text(18, (TOP + H - BOTTOM) / 2, y_label, extra=(
        f' transform="rotate(-90 18 {(TOP + H - BOTTOM) / 2:.1f})"')))
    legend_x = LEFT
    for i, (name, pts) in enumerate(series):
        colour = COLOURS[i]
        out.append(_marker(i, legend_x + 6, 44, colour))
        out.append(text(legend_x + 16, 48, name, "start", INK))
        legend_x += 24 + 7 * len(name)
        if lines and len(pts) > 1:
            d = " ".join(f"{fx(x):.1f},{fy(y):.1f}" for x, y in sorted(pts))
            out.append(f'<polyline points="{d}" fill="none" stroke="{colour}" '
                       f'stroke-width="2"/>')
        out += [_marker(i, fx(x), fy(y), colour) for x, y in pts]
    out.append("</svg>\n")
    svg = "\n".join(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(svg, encoding="utf-8")
    return svg
