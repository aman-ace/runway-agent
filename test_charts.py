"""
Tests for the SVG chart helpers behind the HTML report.

Pure functions, no model, no network - same spirit as test_burn.py.
"""

import xml.etree.ElementTree as ET

import charts


def _svg(html_snippet):
    start = html_snippet.index("<svg")
    end = html_snippet.index("</svg>") + len("</svg>")
    return html_snippet[start:end]


def test_line_chart_is_valid_svg():
    out = charts.line_chart(
        ["2026-01", "2026-02", "2026-03"],
        {"Net burn": [1000, 2000, 1500]},
    )
    ET.fromstring(_svg(out))  # raises if malformed


def test_line_chart_one_point_per_label():
    """One <circle> per data point, plus one emphasis ring around the endpoint."""
    labels = ["2026-01", "2026-02", "2026-03", "2026-04"]
    out = charts.line_chart(labels, {"A": [10, 20, 30, 40]})
    assert out.count("<circle") == len(labels) + 1


def test_line_chart_multiple_series_get_distinct_colors():
    out = charts.line_chart(["1", "2"], {"A": [1, 2], "B": [3, 4]})
    assert out.count("<polyline") == 2


def test_line_chart_flat_series_does_not_divide_by_zero():
    # every value identical: vmax == vmin, must not raise or produce NaN
    out = charts.line_chart(["1", "2", "3"], {"A": [500, 500, 500]})
    assert "nan" not in out.lower()


def test_bar_chart_is_valid_svg():
    out = charts.bar_chart(["payroll", "cloud"], [5000, 1200])
    ET.fromstring(_svg(out))


def test_bar_chart_bar_count_matches_labels():
    out = charts.bar_chart(["a", "b", "c"], [1, 2, 3])
    assert out.count("<rect") == 3


def test_bar_chart_zero_values_do_not_divide_by_zero():
    out = charts.bar_chart(["a", "b"], [0, 0])
    assert "nan" not in out.lower()


def test_labels_are_html_escaped():
    """A vendor description with '&' or '<' must not break the markup."""
    out = charts.bar_chart(["R&D <ops>"], [100])
    assert "R&amp;D &lt;ops&gt;" in out
    ET.fromstring(_svg(out))
