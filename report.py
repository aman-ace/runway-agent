"""
Turns the computed figures into something a founder would forward to a board.

The model gets a compact fact sheet and is asked to write commentary. It is
never asked to do arithmetic, and it never sees the raw transactions, only the
monthly aggregates. That keeps the prompt small, keeps customer names out of
the call, and means every figure in the report is identical whether or not a
model was available.
"""

from html import escape as h

import charts

MONEY = "${:,.0f}"

KIND_LABEL = {
    "step_up": "Step-ups (this is the new run rate)",
    "one_off": "One-offs (exclude from the run rate)",
    "creep": "Creeping up (no bad month, bad year)",
}

KIND_ORDER = ["step_up", "one_off", "creep"]


def _fmt_months(x):
    if x == float("inf"):
        return "n/a (cash flow positive)"
    return f"{x:.1f} months"


def _clean(cat):
    return cat.replace("_", " ")


def _join(items):
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def _line(f):
    if f["kind"] == "creep":
        return (f"**{_clean(f['category'])}** {MONEY.format(f['baseline'])} to "
                f"{MONEY.format(f['actual'])} over {f.get('window', 12)} months, "
                f"about {f['pct']*100:.0f}% a month")
    if f["kind"] == "step_up":
        return (f"**{_clean(f['category'])}** from {f['month']}: "
                f"{MONEY.format(f['baseline'])} to {MONEY.format(f['actual'])} a month "
                f"(+{f['pct']*100:.0f}%, {MONEY.format(f['delta'])} per month)")
    return (f"**{_clean(f['category'])}** in {f['month']}: {MONEY.format(f['actual'])} "
            f"against a {MONEY.format(f['baseline'])} baseline")


def _line_html(f):
    """Same content as _line(), but with **bold** rendered as <strong> and
    every field escaped - category/month strings are internal, but escaping
    is free and one fewer thing to have to prove safe later."""
    cat = h(_clean(f["category"]))
    if f["kind"] == "creep":
        return (f"<strong>{cat}</strong> {MONEY.format(f['baseline'])} to "
                f"{MONEY.format(f['actual'])} over {f.get('window', 12)} months, "
                f"about {f['pct']*100:.0f}% a month")
    if f["kind"] == "step_up":
        return (f"<strong>{cat}</strong> from {h(f['month'])}: "
                f"{MONEY.format(f['baseline'])} to {MONEY.format(f['actual'])} a month "
                f"(+{f['pct']*100:.0f}%, {MONEY.format(f['delta'])} per month)")
    return (f"<strong>{cat}</strong> in {h(f['month'])}: {MONEY.format(f['actual'])} "
            f"against a {MONEY.format(f['baseline'])} baseline")


def fact_sheet(summary, flags, months=6):
    """Compact text block. This is the entire model input."""
    recent = summary.tail(months)
    lines = ["MONTHLY (USD):"]
    for month, row in recent.iterrows():
        lines.append(
            f"{month}: gross_burn={row['gross_burn']:,.0f} "
            f"cash_in={row['cash_in']:,.0f} "
            f"net_burn={row['net_burn']:,.0f} "
            f"closing_cash={row['closing_cash']:,.0f} "
            f"runway={row['runway_months']:.1f}mo"
        )
    if not flags:
        lines.append("\nNo variances cleared the thresholds.")
        return "\n".join(lines)

    lines.append("\nVARIANCES, already classified:")
    for kind in KIND_ORDER:
        for f in [x for x in flags if x["kind"] == kind]:
            if kind == "creep":
                lines.append(f"CREEP {f['category']}: {f['baseline']:,.0f} to "
                             f"{f['actual']:,.0f} over {f.get('window', 12)} months "
                             f"({f['pct']*100:.1f}% per month)")
            elif kind == "step_up":
                lines.append(f"STEP-UP {f['category']} from {f['month']}: "
                             f"{f['baseline']:,.0f} to {f['actual']:,.0f} per month")
            else:
                lines.append(f"ONE-OFF {f['category']} in {f['month']}: "
                             f"{f['actual']:,.0f} vs {f['baseline']:,.0f} normal")
    return "\n".join(lines)


PROMPT = """You are a finance analyst writing the cash section of a board update for an early-stage startup.

{facts}

Write the commentary. Requirements:
- Three short paragraphs. No headers, no bullet points.
- Paragraph 1: where cash and runway stand.
- Paragraph 2: what drove it. The variances are already classified, so treat step-ups as permanent changes to the run rate and one-offs as items to exclude from it. Say which is which.
- Paragraph 3: the two or three questions the board should be asking, phrased as questions.
- Use only the figures given. Do not compute new ones and do not invent any.
- Plain language. No em dashes. No filler words like "leverage", "strategic" or "robust".
"""


def commentary(llm, summary, flags):
    facts = fact_sheet(summary, flags)
    if llm is not None and llm.available:
        text = llm.complete(PROMPT.format(facts=facts), temperature=0.6)
        if text:
            return text.strip(), True
    return _template(summary, flags), False


def _template(summary, flags):
    last = summary.iloc[-1]
    prev = summary.iloc[-2] if len(summary) > 1 else last
    month = summary.index[-1]
    direction = "up" if last["net_burn"] > prev["net_burn"] else "down"
    delta = abs(last["net_burn"] - prev["net_burn"])

    p1 = (
        f"Closing cash for {month} was {MONEY.format(last['closing_cash'])}. "
        f"Net burn was {MONEY.format(last['net_burn'])}, {direction} "
        f"{MONEY.format(delta)} on the prior month. Against a trailing three month "
        f"average net burn of {MONEY.format(last['avg_net_burn_3mo'])}, that leaves "
        f"{_fmt_months(last['runway_months'])} of runway."
    )

    steps = [f for f in flags if f["kind"] == "step_up"]
    ones = [f for f in flags if f["kind"] == "one_off"]
    creeps = [f for f in flags if f["kind"] == "creep"]

    bits = []
    if steps:
        added = sum(f["delta"] for f in steps)
        names = _join(_clean(f["category"]) for f in steps)
        bits.append(f"The run rate moved permanently in {names}, adding about "
                    f"{MONEY.format(added)} a month.")
    if ones:
        names = _join(f"{_clean(f['category'])} in {f['month']}" for f in ones)
        bits.append(f"One-off items that should not be read into the run rate: {names}.")
    if creeps:
        names = _join(f"{_clean(f['category'])} at roughly {f['pct']*100:.0f}% a month"
                      for f in creeps)
        bits.append(f"Lines drifting up without any single bad month: {names}.")
    p2 = " ".join(bits) if bits else "No spend line moved far enough from its baseline to flag."

    p3 = (
        "Questions for the board: does the step-up in the run rate come with a "
        "matching change in output, is anything in the creeping lines worth "
        "renegotiating now, and does the current runway leave enough time to "
        "raise before cash gets tight?"
    )
    return "\n\n".join([p1, p2, p3])


def _money_table(df):
    """Markdown table with numbers a person can actually read."""
    out = df.copy()
    for c in out.columns:
        if c == "Runway (mo)":
            out[c] = out[c].map(
                lambda v: "inf" if v == float("inf") else f"{v:,.1f}"
            )
        else:
            out[c] = out[c].map(lambda v: f"{v:,.0f}")
    return out.to_markdown()


def _vendor_lines(vendors):
    return "\n".join(f"- **{name}** {MONEY.format(amt)}" for name, amt in vendors.items())


def render(summary, pivot, flags, note, zero_date, months_left, source, model_used, vendors=None):
    last = summary.iloc[-1]

    disp = summary.copy()
    disp.index = disp.index.astype(str)
    disp.index.name = "Month"
    table = disp[["gross_burn", "cash_in", "net_burn", "financing",
                  "closing_cash", "runway_months"]].rename(columns={
        "gross_burn": "Gross burn", "cash_in": "Cash in", "net_burn": "Net burn",
        "financing": "Financing", "closing_cash": "Closing cash",
        "runway_months": "Runway (mo)",
    })

    cat = pivot.copy()
    cat.columns = [str(c) for c in cat.columns]
    cat.index.name = "Category"
    cat = cat.loc[cat.sum(axis=1).sort_values(ascending=False).index]

    if flags:
        blocks = []
        for kind in KIND_ORDER:
            group = [f for f in flags if f["kind"] == kind]
            if group:
                blocks.append(f"**{KIND_LABEL[kind]}**\n\n"
                              + "\n".join(f"- {_line(f)}" for f in group))
        flag_md = "\n\n".join(blocks)
    else:
        flag_md = "Nothing cleared the thresholds."

    zero_line = (f"projected to reach zero around **{zero_date}**"
                 if zero_date else "cash flow positive on a trailing basis")

    vendor_section = (
        f"\n## Top vendors, {summary.index[-1]}\n\n{_vendor_lines(vendors)}\n"
        if vendors is not None and len(vendors) else ""
    )

    return f"""# Cash and runway report

Source file: `{source}`
Period: {summary.index[0]} to {summary.index[-1]}
Commentary: {"written by model" if model_used else "templated, no model configured"}

## Headline

| | |
|---|---|
| Closing cash | {MONEY.format(last['closing_cash'])} |
| Gross burn, last month | {MONEY.format(last['gross_burn'])} |
| Net burn, last month | {MONEY.format(last['net_burn'])} |
| Net burn, 3mo average | {MONEY.format(last['avg_net_burn_3mo'])} |
| Runway | {_fmt_months(months_left)} |

At the trailing three month average net burn, cash is {zero_line}.

## Commentary

{note}

## What changed

{flag_md}

## Monthly detail

{_money_table(table)}

## Operating spend by category

{_money_table(cat)}
{vendor_section}
---

Runway is closing cash divided by trailing three month average net burn.
Financing inflows are excluded from burn and included in the cash balance.
Straight line projection. No seasonality, no assumed change in run rate.
"""


def render_html(summary, pivot, flags, note, zero_date, months_left, source, model_used, vendors=None):
    """Self-contained HTML version of the same report: stat tiles, SVG trend
    charts and a category breakdown instead of plain markdown tables. No
    external assets, no JS - safe to open offline or attach to an email."""
    last = summary.iloc[-1]
    months = [str(m) for m in summary.index]

    # Colors are CSS custom properties, not hex - the SVG is inlined in this
    # document, so it inherits the page's cascade and repaints correctly when
    # the viewer's theme flips. No JS, no duplicate light/dark chart code.
    burn_chart = charts.line_chart(
        months,
        {"Net burn": summary["net_burn"].tolist(),
         "3mo average": summary["avg_net_burn_3mo"].tolist()},
        colors={"Net burn": "var(--chart-burn)", "3mo average": "var(--chart-avg)"},
    )
    cash_chart = charts.line_chart(
        months, {"Closing cash": summary["closing_cash"].tolist()},
        colors={"Closing cash": "var(--chart-cash)"}, area=True,
    )

    cat_totals = pivot.sum(axis=1).sort_values(ascending=False)
    cat_chart = charts.bar_chart(
        [_clean(c) for c in cat_totals.index], cat_totals.values.tolist(),
        color="var(--chart-cat)",
    )

    vendor_block = ""
    if vendors is not None and len(vendors):
        vendor_chart = charts.bar_chart(list(vendors.index), vendors.values.tolist(),
                                        color="var(--chart-vendor)")
        vendor_block = f"""
    <section class="card">
      <h2>Top vendors, {h(str(summary.index[-1]))}</h2>
      {vendor_chart}
    </section>"""

    if flags:
        flag_blocks = []
        for kind in KIND_ORDER:
            group = [f for f in flags if f["kind"] == kind]
            if group:
                items = "".join(f"<li>{_line_html(f)}</li>" for f in group)
                flag_blocks.append(f'<h3>{h(KIND_LABEL[kind])}</h3><ul>{items}</ul>')
        flag_html = "".join(flag_blocks)
    else:
        flag_html = "<p>Nothing cleared the thresholds.</p>"

    zero_line = (f"projected to reach zero around <strong>{zero_date}</strong>"
                 if zero_date else "cash flow positive on a trailing basis")

    def tile(label, value):
        return f'<div class="tile"><span class="tile-label">{h(label)}</span>' \
               f'<span class="tile-value">{h(value)}</span></div>'

    tiles = "".join([
        tile("Closing cash", MONEY.format(last["closing_cash"])),
        tile("Gross burn, last month", MONEY.format(last["gross_burn"])),
        tile("Net burn, 3mo average", MONEY.format(last["avg_net_burn_3mo"])),
        tile("Runway", _fmt_months(months_left)),
    ])

    # Prose from the model or the template renders one <p> per paragraph.
    commentary_html = "".join(f"<p>{h(p)}</p>" for p in note.split("\n\n") if p.strip())

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Cash and runway report - {h(source)}</title>
<style>
  :root {{
    --bg: #f0f3ec; --page: #f5f7f1; --fg: #1e2420; --muted: #5f6a5a; --card: #fbfcf8;
    --border: #d9ddd1; --accent: #205c40; --rule: rgba(30,36,32,.06); --margin: #a8402f;
    --chart-burn: #a8452c; --chart-avg: #3f5170; --chart-cash: #205c40;
    --chart-cat: #205c40; --chart-vendor: #6b4f8f;
    --shadow: 0 1px 1px rgba(30,40,30,.04), 0 10px 22px -14px rgba(30,40,30,.35);
    --serif: Georgia, "Iowan Old Style", "Times New Roman", serif;
    --sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    --mono: ui-monospace, "SF Mono", "Cascadia Mono", Consolas, "Courier New", monospace;
  }}
  /* This report deliberately stays paper-light regardless of the reader's
     OS theme - a board memo that flips dark with someone's system settings
     reads as an accident, not a choice. data-theme="dark" below is only for
     hosts (like an artifact viewer) with an explicit, user-driven toggle. */
  :root[data-theme="dark"] {{
    --bg: #0f1310; --page: #141910; --fg: #e9ede4; --muted: #97a08d; --card: #191f16;
    --border: #2b3226; --accent: #74bd97; --rule: rgba(255,255,255,.045); --margin: #c96a55;
    --chart-burn: #d3805f; --chart-avg: #8ea1c9; --chart-cash: #74bd97;
    --chart-cat: #74bd97; --chart-vendor: #b39bd6;
    --shadow: 0 1px 1px rgba(0,0,0,.3), 0 12px 26px -16px rgba(0,0,0,.6);
  }}
  :root[data-theme="light"] {{
    --bg: #f0f3ec; --page: #f5f7f1; --fg: #1e2420; --muted: #5f6a5a; --card: #fbfcf8;
    --border: #d9ddd1; --accent: #205c40; --rule: rgba(30,36,32,.06); --margin: #a8402f;
    --chart-burn: #a8452c; --chart-avg: #3f5170; --chart-cash: #205c40;
    --chart-cat: #205c40; --chart-vendor: #6b4f8f;
    --shadow: 0 1px 1px rgba(30,40,30,.04), 0 10px 22px -14px rgba(30,40,30,.35);
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding: 3rem 1.5rem 4rem 4.5rem; background: var(--bg); color: var(--fg);
    font: 16px/1.6 var(--sans); -webkit-font-smoothing: antialiased;
    background-image: repeating-linear-gradient(to bottom, transparent 0 27px, var(--rule) 27px 28px);
    position: relative;
  }}
  body::before {{
    content: ""; position: absolute; top: 0; left: 2.6rem; width: 1px; height: 100%;
    background: var(--margin); opacity: .5;
  }}
  @media (max-width: 640px) {{
    body {{ padding-left: 1.5rem; }}
    body::before {{ display: none; }}
  }}
  main {{ max-width: 780px; margin: 0 auto; }}
  h1 {{
    font-family: var(--serif); font-weight: 700; font-size: 2rem;
    letter-spacing: 0.005em; margin: 0 0 1rem; text-wrap: balance;
  }}
  h2 {{
    font-family: var(--serif); font-weight: 700; font-size: 1.15rem;
    margin: 0 0 1rem; text-wrap: balance;
  }}
  h3 {{
    font-size: 0.72rem; margin: 1.1rem 0 0.5rem; color: var(--muted);
    text-transform: uppercase; letter-spacing: 0.08em; font-weight: 600;
  }}
  .masthead {{
    border-bottom: 4px double var(--fg); padding-bottom: 1.1rem; margin-bottom: 1.75rem;
  }}
  .meta-row {{ display: flex; flex-wrap: wrap; gap: 1.75rem; }}
  .meta-field {{ display: flex; flex-direction: column; gap: 0.2rem; }}
  .meta-label {{
    font-size: 0.68rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.09em;
  }}
  .meta-value {{ font-family: var(--mono); font-size: 0.85rem; }}
  .card {{
    background: var(--card); border: 1px solid var(--border); box-shadow: var(--shadow);
    border-radius: 3px; padding: 1.4rem 1.65rem; margin-bottom: 1.25rem;
  }}
  .tiles {{
    display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    gap: 1rem; margin-bottom: 1.25rem;
  }}
  .tile {{
    background: var(--card); border: 1px solid var(--border); box-shadow: var(--shadow);
    border-radius: 3px; padding: 1.1rem 1.2rem; display: flex; flex-direction: column; gap: 0.45rem;
  }}
  .tile-label {{
    font-size: 0.7rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.06em;
  }}
  .tile-value {{
    font-family: var(--mono); font-size: 1.4rem; font-weight: 600;
    font-variant-numeric: tabular-nums;
  }}
  p {{ margin: 0 0 0.9rem; }}
  p:last-child {{ margin-bottom: 0; }}
  ul {{ margin: 0; padding-left: 1.2rem; }}
  li {{ margin-bottom: 0.4rem; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.88rem; }}
  td {{ font-family: var(--mono); font-variant-numeric: tabular-nums; }}
  th, td {{ text-align: right; padding: 0.45rem 0.6rem; border-bottom: 1px solid var(--border); }}
  th {{ font-family: var(--sans); font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted); font-weight: 600; }}
  th:first-child, td:first-child {{ text-align: left; font-family: var(--sans); }}
  .chart-wrap {{ overflow-x: auto; }}
  .chart {{ width: 100%; height: auto; display: block; }}
  .grid {{ stroke: var(--border); stroke-width: 1; }}
  .axis-label {{ fill: var(--muted); font-size: 11px; font-family: var(--mono); }}
  .legend {{ display: flex; gap: 1.1rem; margin-top: 0.6rem; font-size: 0.82rem; color: var(--muted); font-family: var(--mono); }}
  .legend-item {{ display: flex; align-items: center; gap: 0.4rem; }}
  .legend-item i {{ width: 9px; height: 9px; display: inline-block; }}
  footer {{ color: var(--muted); font-size: 0.8rem; margin-top: 2rem; line-height: 1.6; }}
</style>
</head>
<body>
<main>
  <div class="masthead">
    <h1>Cash and runway report</h1>
    <div class="meta-row">
      <div class="meta-field"><span class="meta-label">Source</span><span class="meta-value">{h(source)}</span></div>
      <div class="meta-field"><span class="meta-label">Period</span><span class="meta-value">{h(str(summary.index[0]))} &ndash; {h(str(summary.index[-1]))}</span></div>
      <div class="meta-field"><span class="meta-label">Commentary</span><span class="meta-value">{"model-written" if model_used else "templated"}</span></div>
    </div>
  </div>

  <div class="tiles">{tiles}</div>

  <section class="card">
    <h2>At the trailing three month average net burn, cash is {zero_line}.</h2>
    {commentary_html}
  </section>

  <section class="card">
    <h2>Net burn trend</h2>
    {burn_chart}
  </section>

  <section class="card">
    <h2>Closing cash</h2>
    {cash_chart}
  </section>

  <section class="card">
    <h2>What changed</h2>
    {flag_html}
  </section>

  <section class="card">
    <h2>Operating spend by category</h2>
    {cat_chart}
  </section>
{vendor_block}
  <footer>
    Runway is closing cash divided by trailing three month average net burn.
    Financing inflows are excluded from burn and included in the cash balance.
    Straight line projection. No seasonality, no assumed change in run rate.
  </footer>
</main>
</body>
</html>
"""
