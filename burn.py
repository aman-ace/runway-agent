"""
The numbers. No model touches anything in this file.

Definitions used here, stated plainly because people mean different things:

  gross burn  total operating cash out in the month
  cash in     operating cash in (customer collections), financing excluded
  net burn    gross burn less cash in. Positive means the company consumed cash.
  runway      closing cash / average net burn over the trailing 3 months

Financing inflows are stripped out of burn entirely. They change the cash
balance, which changes runway, but they are not operations and folding them in
makes the month a round closes look like the best month the company ever had.
"""

import numpy as np
import pandas as pd

OPERATING_OUT = "operating_out"
OPERATING_IN = "operating_in"
TRAILING_MONTHS = 3


def load(path):
    df = pd.read_csv(path, parse_dates=["date"])
    required = {"date", "description", "amount"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"CSV is missing required column(s): {sorted(missing)}")
    df["month"] = df["date"].dt.to_period("M")
    return df.sort_values("date").reset_index(drop=True)


def monthly_summary(df, opening_cash=None):
    """One row per month: gross burn, cash in, net burn, closing cash, runway."""
    out = df[df["flow"] == OPERATING_OUT].groupby("month")["amount"].sum().abs()
    inn = df[df["flow"] == OPERATING_IN].groupby("month")["amount"].sum()
    fin = df[df["flow"].str.startswith("financing")].groupby("month")["amount"].sum()

    m = pd.DataFrame({"gross_burn": out, "cash_in": inn, "financing": fin}).fillna(0.0)
    m = m.sort_index()
    m["net_burn"] = m["gross_burn"] - m["cash_in"]
    m["net_change"] = -m["net_burn"] + m["financing"]

    # Prefer the bank's own balance column when it is there. It is the truth.
    if "balance" in df.columns and df["balance"].notna().any():
        m["closing_cash"] = df.groupby("month")["balance"].last()
    else:
        if opening_cash is None:
            raise ValueError(
                "No balance column in the CSV, so --opening-cash is required."
            )
        m["closing_cash"] = opening_cash + m["net_change"].cumsum()

    m["avg_net_burn_3mo"] = m["net_burn"].rolling(TRAILING_MONTHS, min_periods=1).mean()
    m["runway_months"] = np.where(
        m["avg_net_burn_3mo"] > 0,
        m["closing_cash"] / m["avg_net_burn_3mo"],
        np.inf,
    )
    return m


def category_by_month(df):
    """Operating spend pivoted category x month, in positive dollars."""
    spend = df[df["flow"] == OPERATING_OUT]
    pivot = (
        spend.pivot_table(index="category", columns="month", values="amount", aggfunc="sum")
        .abs()
        .fillna(0.0)
    )
    return pivot.sort_index()


def find_variances(pivot, min_dollars=5_000, pct_threshold=0.35, creep_min_dollars=1_500):
    """
    Three different things can make a spend line move, and they mean different
    things to whoever reads the report:

      one_off   a single month spikes and then reverts. Legal fees on a
                financing, a conference, a hardware purchase. Ignore it when
                you set the run rate.
      step_up   the level shifts and stays shifted. A hire, a bigger office,
                a new contract. This IS the new run rate.
      creep     no single month looks bad but the line has been climbing all
                year. Cloud spend does this constantly and nobody notices
                until it is the third biggest cost.

    Lumping all three together as "anomalies" is what makes most variance
    reports useless, so they are detected separately and labelled.
    """
    steps = _step_ups(pivot, min_dollars, pct_threshold)
    stepped = {s["category"]: s["month"] for s in steps}

    # Once a line has been called a step-up, every month after the step will
    # also look like a spike against the old baseline. Reporting both says the
    # same thing twice and pads the report with noise.
    ones = [o for o in _one_offs(pivot, min_dollars)
            if o["month"] < stepped.get(o["category"], "9999")]
    creeps = [c for c in _creep(pivot, creep_min_dollars)
              if c["category"] not in stepped]

    order = {"step_up": 0, "one_off": 1, "creep": 2}
    return sorted(steps + ones + creeps, key=lambda f: (order[f["kind"]], f["month"]))


def _step_ups(pivot, min_dollars, pct_threshold):
    """Find a split point where the level shifts and holds."""
    out = []
    months = list(pivot.columns)
    for cat in pivot.index:
        s = pivot.loc[cat].values
        # need at least 2 months either side to call it sustained
        for i in range(2, len(s) - 1):
            before, after = s[:i], s[i:]
            b, a = np.median(before), np.median(after)
            if b <= 0:
                continue
            delta, pct = a - b, (a - b) / b
            if delta < min_dollars or pct < pct_threshold:
                continue
            # every month after the split must stay up, or it is not a step
            if after.min() < b * (1 + pct_threshold * 0.6):
                continue
            # and the step has to actually be a step. A line drifting up 7% a
            # month will satisfy everything above without ever jumping, and
            # that is creep, handled separately.
            if s[i - 1] <= 0 or (s[i] / s[i - 1] - 1) < 0.20:
                continue
            # take the earliest qualifying split. The onset month is what
            # someone reading this needs, not whichever split maximises the gap.
            out.append({"kind": "step_up", "category": cat, "month": str(months[i]),
                        "baseline": round(float(b), 2), "actual": round(float(a), 2),
                        "delta": round(float(delta), 2), "pct": round(float(pct), 3)})
            break
    return out


def _one_offs(pivot, min_dollars, spike_multiple=1.8):
    """A month far above its neighbours on both sides."""
    out = []
    months = list(pivot.columns)
    for cat in pivot.index:
        s = pivot.loc[cat]
        for i in range(1, len(s)):
            others = s.drop(s.index[i])
            baseline = others[others > 0].median()
            if not baseline or np.isnan(baseline):
                continue
            actual = s.iloc[i]
            delta = actual - baseline
            if delta < min_dollars or actual < baseline * spike_multiple:
                continue
            # if the next month stayed anywhere near the spike it is a step,
            # not a one-off. Measured against the spike rather than the
            # baseline, because a lumpy line like legal fees never returns
            # cleanly to its own median.
            if i + 1 < len(s) and s.iloc[i + 1] > actual * 0.5:
                continue
            out.append({"kind": "one_off", "category": cat, "month": str(months[i]),
                        "baseline": round(float(baseline), 2), "actual": round(float(actual), 2),
                        "delta": round(float(delta), 2), "pct": round(float(delta / baseline), 3)})
    return out


def _creep(pivot, min_dollars, max_window=12, monthly_rate=0.04):
    """
    Steady month-over-month growth with no single dramatic month.

    Lower dollar floor than the other two on purpose. A line adding 7% a month
    is adding 125% a year, so it deserves attention at a smaller absolute size
    than a one-off does.
    """
    out = []
    months = list(pivot.columns)
    window = min(len(months), max_window)
    if window < 6:
        return out
    for cat in pivot.index:
        s = pivot.loc[cat].iloc[-window:]
        if (s <= 0).any():
            continue
        rate = (s.iloc[-1] / s.iloc[0]) ** (1 / (window - 1)) - 1
        delta = s.iloc[-1] - s.iloc[0]
        # must be genuinely gradual: no month up more than 25% on the one before
        mom = s.pct_change().dropna()
        if rate >= monthly_rate and delta >= min_dollars and mom.max() < 0.25:
            out.append({"kind": "creep", "category": cat, "month": str(months[-1]),
                        "baseline": round(float(s.iloc[0]), 2),
                        "actual": round(float(s.iloc[-1]), 2),
                        "delta": round(float(delta), 2), "pct": round(float(rate), 3),
                        "window": window})
    return out


def top_vendors(df, month, n=8):
    spend = df[(df["flow"] == OPERATING_OUT) & (df["month"] == month)]
    return (
        spend.groupby("description")["amount"].sum().abs()
        .sort_values(ascending=False).head(n)
    )


def zero_cash_date(summary):
    """Straight-line projection off the trailing 3-month average net burn."""
    last = summary.iloc[-1]
    if last["avg_net_burn_3mo"] <= 0:
        return None, np.inf
    months = float(last["closing_cash"] / last["avg_net_burn_3mo"])
    # DateOffset will not take a fractional month, so convert to days.
    end = summary.index[-1].to_timestamp() + pd.Timedelta(days=months * 30.44)
    return end.date(), months
