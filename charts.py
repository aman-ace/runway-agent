"""
Tiny, dependency-free SVG charts for the HTML report.

No matplotlib, no JS, no network. Everything here is a pure function that
takes numbers and returns an SVG string, which keeps the HTML report a single
self-contained file you can open offline or attach to an email.
"""

from html import escape

PALETTE = ["#2f6f63", "#b5502f", "#46577a", "#7a5aa3", "#c98a2c"]


def _money(v):
    return f"${v:,.0f}"


def line_chart(labels, series, colors=None, width=680, height=220, y_fmt=None, area=False):
    """series: {name: [values]}, one value per label, same length as labels.

    area=True fills under the line down to its zero baseline - reads well for
    a single reservoir-style series (cash on hand). Left off for multi-line
    charts, where overlapping fills just muddy the comparison.
    """
    y_fmt = y_fmt or _money
    colors = colors or {}

    all_vals = [v for vals in series.values() for v in vals] or [0]
    vmin, vmax = min(0, *all_vals), max(all_vals)
    if vmax == vmin:
        vmax = vmin + 1

    # Pad left enough for the widest y-axis label - a fixed pad clips wide
    # numbers (a missing leading "$" is a viewBox clip, not a font problem).
    y_labels = [y_fmt(vmax - (vmax - vmin) * gi / 4) for gi in range(5)]
    pad_left = max(48, 9 + 7 * max(len(s) for s in y_labels))
    # The rightmost x-axis label is center-anchored on the last data point,
    # so its right half needs room too, or its tail clips against the edge.
    pad_right = max(16, 3.1 * max(len(str(l)) for l in labels))
    pad_top, pad_bottom = 16, 28
    plot_w = width - pad_left - pad_right
    plot_h = height - pad_top - pad_bottom

    n = len(labels)

    def x(i):
        return pad_left + (i / max(n - 1, 1)) * plot_w

    def y(v):
        return pad_top + plot_h - (v - vmin) / (vmax - vmin) * plot_h

    parts = [f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" '
             f'class="chart" role="img" preserveAspectRatio="xMidYMid meet">']

    for gi, lbl in enumerate(y_labels):
        gy = pad_top + plot_h * gi / 4
        parts.append(f'<line x1="{pad_left}" y1="{gy:.1f}" x2="{width - pad_right}" '
                     f'y2="{gy:.1f}" class="grid"/>')
        parts.append(f'<text x="{pad_left - 8}" y="{gy + 4:.1f}" class="axis-label" '
                     f'text-anchor="end">{escape(lbl)}</text>')

    # Greedily keep labels from the right so the last (most recent, most
    # important) month is always shown and never crowded by its neighbour.
    step = max(1, n // 6)
    # Monospace axis font: ~6.2px/char at 11px is a safe estimate. Labels are
    # center-anchored, so the true collision distance is one label-width, not
    # half of one - a smaller gap here is what caused two month labels to
    # print on top of each other at the right edge.
    min_gap_px = max(40, 6.2 * max(len(str(l)) for l in labels) + 10)
    candidates = sorted(set(range(0, n, step)) | {n - 1}, reverse=True)
    kept = []
    for i in candidates:
        if kept and x(kept[-1]) - x(i) < min_gap_px:
            continue
        kept.append(i)
    for i in reversed(kept):
        parts.append(f'<text x="{x(i):.1f}" y="{height - 6}" class="axis-label" '
                     f'text-anchor="middle">{escape(str(labels[i]))}</text>')

    for idx, (name, vals) in enumerate(series.items()):
        color = colors.get(name, PALETTE[idx % len(PALETTE)])
        points = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(vals))

        if area and n > 1:
            baseline_y = y(max(vmin, 0))
            fill_pts = f"{x(0):.1f},{baseline_y:.1f} {points} {x(n - 1):.1f},{baseline_y:.1f}"
            parts.append(f'<polygon points="{fill_pts}" fill="{color}" opacity="0.14"/>')

        parts.append(f'<polyline points="{points}" fill="none" stroke="{color}" '
                     f'stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>')
        for i, v in enumerate(vals):
            is_last = i == n - 1
            r = 4 if is_last else 3
            parts.append(f'<circle cx="{x(i):.1f}" cy="{y(v):.1f}" r="{r}" fill="{color}">'
                         f'<title>{escape(str(labels[i]))}: {escape(y_fmt(v))}</title></circle>')
            if is_last:
                parts.append(f'<circle cx="{x(i):.1f}" cy="{y(v):.1f}" r="{r + 3}" '
                             f'fill="none" stroke="{color}" stroke-width="1.5" opacity="0.45"/>')

    parts.append("</svg>")

    legend = "".join(
        f'<span class="legend-item"><i style="background:'
        f'{colors.get(name, PALETTE[idx % len(PALETTE)])}"></i>'
        f'{escape(name)}</span>'
        for idx, name in enumerate(series.keys())
    )
    return f'<div class="chart-wrap">{"".join(parts)}<div class="legend">{legend}</div></div>'


def bar_chart(labels, values, width=680, bar_height=26, gap=10, color=None, value_fmt=None):
    """Horizontal bars, longest first if the caller pre-sorts. Labels + values same length."""
    value_fmt = value_fmt or _money
    color = color or PALETTE[0]
    pad_left = min(max((len(str(l)) for l in labels), default=8) * 7 + 12, 200)
    pad_right = 70
    n = len(labels)
    height = n * (bar_height + gap) + gap
    plot_w = width - pad_left - pad_right
    vmax = max(values) if values else 1
    if vmax <= 0:
        vmax = 1

    parts = [f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" '
             f'class="chart" role="img" preserveAspectRatio="xMidYMid meet">']
    for i, (lab, val) in enumerate(zip(labels, values)):
        top = gap + i * (bar_height + gap)
        w = (val / vmax) * plot_w
        mid = top + bar_height / 2 + 4
        parts.append(f'<text x="{pad_left - 8}" y="{mid:.1f}" text-anchor="end" '
                     f'class="axis-label">{escape(str(lab))}</text>')
        parts.append(f'<rect x="{pad_left}" y="{top}" width="{w:.1f}" height="{bar_height}" '
                     f'rx="4" fill="{color}"><title>{escape(str(lab))}: '
                     f'{escape(value_fmt(val))}</title></rect>')
        parts.append(f'<text x="{pad_left + w + 8:.1f}" y="{mid:.1f}" '
                     f'class="axis-label">{escape(value_fmt(val))}</text>')
    parts.append("</svg>")
    return f'<div class="chart-wrap">{"".join(parts)}</div>'
