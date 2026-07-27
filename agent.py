#!/usr/bin/env python3
"""
runway-agent

Reads a bank or accounting CSV, works out burn and runway, flags the spend
categories that broke pattern, and writes a board-ready report.

    python agent.py data/sample_transactions.csv
    python agent.py my_export.csv --opening-cash 250000 -o reports/june.md
    python agent.py data/sample_transactions.csv -o reports/june.html

Output format is picked from the -o extension: .md (default) or .html, the
latter a self-contained page with trend charts, no external assets or JS.

Expects columns: date, description, amount. A `balance` column is used if
present. Negative amounts are money out.
"""

import argparse
import os
import sys
from pathlib import Path

import burn
import categorize
import report
from llm import LLM, banner

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def main():
    ap = argparse.ArgumentParser(description="Burn and runway analysis from a transactions CSV.")
    ap.add_argument("csv", help="path to the transactions CSV")
    ap.add_argument("-o", "--out", default="reports/runway_report.md",
                    help="output path; .md or .html, picked from the extension")
    ap.add_argument("--opening-cash", type=float, default=None,
                    help="opening cash balance, required if the CSV has no balance column")
    ap.add_argument("--provider", default=None, help="gemini | ollama | none")
    ap.add_argument("--min-flag-dollars", type=float, default=5_000,
                    help="ignore variances smaller than this")
    ap.add_argument("--flag-pct", type=float, default=0.40,
                    help="flag when a month exceeds its baseline by this fraction")
    ap.add_argument("--top-vendors", type=int, default=8,
                    help="top vendors to list for the latest month, 0 to skip")
    args = ap.parse_args()

    if not Path(args.csv).exists():
        sys.exit(f"no such file: {args.csv}")

    llm = LLM(provider=args.provider)
    banner(llm)

    df = burn.load(args.csv)
    print(f"loaded:  {len(df):,} transactions, {df['month'].nunique()} months")

    df = categorize.classify_all(df, llm=llm)

    summary = burn.monthly_summary(df, opening_cash=args.opening_cash)
    pivot = burn.category_by_month(df)
    flags = burn.find_variances(pivot, min_dollars=args.min_flag_dollars,
                                pct_threshold=args.flag_pct)
    kinds = ", ".join(f"{sum(1 for f in flags if f['kind'] == k)} {k}"
                      for k in ("step_up", "one_off", "creep")) or "none"
    print(f"flagged: {kinds}")

    zero_date, months_left = burn.zero_cash_date(summary)
    note, model_used = report.commentary(llm, summary, flags)

    vendors = (burn.top_vendors(df, summary.index[-1], n=args.top_vendors)
              if args.top_vendors > 0 else None)

    out_path = Path(args.out)
    render_args = (summary, pivot, flags, note, zero_date, months_left,
                  os.path.basename(args.csv), model_used)
    if out_path.suffix.lower() == ".html":
        content = report.render_html(*render_args, vendors=vendors)
    else:
        content = report.render(*render_args, vendors=vendors)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(content)

    last = summary.iloc[-1]
    print()
    print(f"closing cash    ${last['closing_cash']:,.0f}")
    print(f"net burn (3mo)  ${last['avg_net_burn_3mo']:,.0f}/mo")
    print(f"runway          {months_left:.1f} months" if months_left != float("inf")
          else "runway          cash flow positive")
    if zero_date:
        print(f"cash zero       ~{zero_date}")
    print(f"\nreport written to {args.out}")


if __name__ == "__main__":
    main()
