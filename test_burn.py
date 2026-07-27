"""
Tests for the parts where a silent error would be embarrassing.

The model is not tested here on purpose. It does not touch any number, so
these run offline with no API key.

    pytest -q
"""

import pandas as pd
import pytest

import burn
from categorize import classify_one


def mk(rows):
    """rows: list of (date, description, amount)"""
    df = pd.DataFrame(rows, columns=["date", "description", "amount"])
    df["date"] = pd.to_datetime(df["date"])
    df["month"] = df["date"].dt.to_period("M")
    from categorize import classify_all
    return classify_all(df, verbose=False)


# --- categorization ---------------------------------------------------------

def test_safe_is_financing_not_revenue():
    cat, flow = classify_one("WIRE IN - SAFE - VERTEX SEED FUND I LP", 1_030_000)
    assert cat == "financing"
    assert flow == "financing_in"


def test_customer_wire_is_revenue():
    cat, flow = classify_one("WIRE IN - HOOLI ENTERPRISES", 12_400)
    assert cat == "revenue"
    assert flow == "operating_in"


def test_refund_flips_direction():
    """A credit from a vendor is money in, not a negative outflow."""
    cat, flow = classify_one("AWS EMEA BILLING", 900)
    assert cat == "cloud"
    assert flow == "operating_in"


def test_unknown_vendor_is_not_guessed():
    assert classify_one("ZZQQ HOLDINGS 4471", -800) == (None, None)


# --- burn and runway --------------------------------------------------------

def test_financing_excluded_from_burn():
    """The month a round closes must not look like the best month ever."""
    df = mk([
        ("2026-01-05", "GUSTO PAYROLL RUN", -50_000),
        ("2026-01-20", "STRIPE PAYOUT - ACME CORP", 10_000),
        ("2026-01-25", "WIRE IN - SAFE - SOME FUND LP", 2_000_000),
    ])
    s = burn.monthly_summary(df, opening_cash=100_000)
    assert s.iloc[0]["gross_burn"] == pytest.approx(50_000)
    assert s.iloc[0]["net_burn"] == pytest.approx(40_000)
    assert s.iloc[0]["financing"] == pytest.approx(2_000_000)
    assert s.iloc[0]["closing_cash"] == pytest.approx(2_060_000)


def test_runway_uses_trailing_average_not_last_month():
    rows = []
    for m in (1, 2, 3):
        rows.append((f"2026-0{m}-05", "GUSTO PAYROLL RUN", -30_000))
    rows.append(("2026-03-06", "COOLEY LLP", -60_000))  # one-off spike
    s = burn.monthly_summary(mk(rows), opening_cash=300_000)
    last = s.iloc[-1]
    assert last["net_burn"] == pytest.approx(90_000)
    assert last["avg_net_burn_3mo"] == pytest.approx(50_000)
    # runway off the average, not off the spike
    assert last["runway_months"] == pytest.approx(last["closing_cash"] / 50_000)


def test_balance_column_wins_over_computed_cash():
    df = mk([("2026-01-05", "GUSTO PAYROLL RUN", -50_000)])
    df["balance"] = [12_345.0]
    s = burn.monthly_summary(df, opening_cash=999_999)
    assert s.iloc[0]["closing_cash"] == pytest.approx(12_345.0)


def test_missing_balance_and_no_opening_cash_raises():
    df = mk([("2026-01-05", "GUSTO PAYROLL RUN", -50_000)])
    with pytest.raises(ValueError, match="opening-cash"):
        burn.monthly_summary(df)


def test_cash_positive_company_has_infinite_runway():
    df = mk([
        ("2026-01-05", "GUSTO PAYROLL RUN", -10_000),
        ("2026-01-20", "STRIPE PAYOUT - ACME CORP", 40_000),
    ])
    s = burn.monthly_summary(df, opening_cash=50_000)
    assert s.iloc[0]["runway_months"] == float("inf")
    assert burn.zero_cash_date(s)[0] is None


# --- variance classification ------------------------------------------------

def pivot_from(series_by_cat, n):
    months = pd.period_range("2025-06", periods=n, freq="M")
    return pd.DataFrame(series_by_cat, index=months).T


def test_step_up_reports_the_onset_month():
    p = pivot_from({"payroll": [50_000] * 6 + [70_000] * 6}, 12)
    flags = burn.find_variances(p)
    step = [f for f in flags if f["kind"] == "step_up"]
    assert len(step) == 1
    assert step[0]["month"] == "2025-12"  # first elevated month


def test_one_off_is_not_called_a_step_up():
    p = pivot_from({"legal_admin": [400] * 5 + [50_000] + [400] * 6}, 12)
    kinds = {f["kind"] for f in burn.find_variances(p)}
    assert kinds == {"one_off"}


def test_creep_is_not_called_a_step_up():
    p = pivot_from({"cloud": [3_000 * 1.07 ** i for i in range(12)]}, 12)
    flags = burn.find_variances(p)
    assert [f["kind"] for f in flags] == ["creep"]


def test_flat_line_produces_nothing():
    p = pivot_from({"facilities": [4_500] * 12}, 12)
    assert burn.find_variances(p) == []


def test_step_up_suppresses_duplicate_spikes_after_it():
    """Every month after a step looks like a spike. Say it once."""
    p = pivot_from({"marketing": [6_000] * 6 + [15_000] * 6}, 12)
    flags = burn.find_variances(p)
    assert [f["kind"] for f in flags] == ["step_up"]


def test_small_moves_stay_below_the_floor():
    p = pivot_from({"software": [1_000] * 6 + [1_800] * 6}, 12)
    assert burn.find_variances(p) == []
