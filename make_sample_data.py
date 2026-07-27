"""
Generates data/sample_transactions.csv - 14 months of bank activity for a
fictional seed-stage SaaS company. Shaped to look like a real bank export:
date, description, amount (negative = money out), balance.

Deliberate storylines baked in so the agent has something to find:
  - headcount step-up in Mar 2026 (payroll jumps ~40%)
  - a SAFE closes in Sep 2025 (financing inflow, must NOT count as revenue)
  - AWS creeping up every month
  - one-off legal spike in Feb 2026 (trademark dispute)
  - marketing spend doubles in May 2026 with no matching revenue lift
"""

import csv
import random
from datetime import date, timedelta

random.seed(7)

START = date(2025, 6, 1)
MONTHS = 14
OPENING_CASH = 400_000.00

VENDORS = {
    "payroll": ["GUSTO PAYROLL RUN", "GUSTO TAX DEBIT"],
    "contractors": ["DEEL INC CONTRACTOR", "UPWORK ESCROW"],
    "cloud": ["AWS EMEA BILLING", "VERCEL INC", "SUPABASE"],
    "software": [
        "SLACK T0X9", "NOTION LABS", "LINEAR ORBIT INC", "GITHUB INC",
        "FIGMA INC", "GOOGLE WORKSPACE", "ZOOM.US", "HUBSPOT INC",
    ],
    "marketing": ["GOOGLE ADS 8821", "LINKEDIN ADS", "REDDIT ADS", "SPONSOR - THE PRAGMATIC ENG"],
    "facilities": ["WEWORK NY", "CON EDISON"],
    "legal": ["COOLEY LLP", "STRIPE ATLAS", "CARTA INC"],
    "travel": ["UNITED AIRLINES", "AMTRAK NEC", "HOTEL INDIGO"],
    "other": ["AMAZON BUSINESS", "STAPLES 1187", "DOORDASH FOR BUSINESS"],
}

CUSTOMERS = [
    "STRIPE PAYOUT - ACME CORP", "STRIPE PAYOUT - NORTHWIND", "STRIPE PAYOUT - GLOBEX",
    "STRIPE PAYOUT - INITECH", "WIRE IN - HOOLI ENTERPRISES", "STRIPE PAYOUT - UMBRELLA",
]


def month_start(n):
    y = START.year + (START.month - 1 + n) // 12
    m = (START.month - 1 + n) % 12 + 1
    return date(y, m, 1)


def jitter(x, pct=0.06):
    return round(x * random.uniform(1 - pct, 1 + pct), 2)


rows = []


def add(d, desc, amt):
    rows.append({"date": d.isoformat(), "description": desc, "amount": round(amt, 2)})


for i in range(MONTHS):
    ms = month_start(i)

    # --- payroll: two runs a month, step-up when they hire in Mar 2026 ---
    base_payroll = 41_000 if ms < date(2026, 3, 1) else 58_000
    for day in (15, 28):
        add(ms + timedelta(days=day - 1), VENDORS["payroll"][0], -jitter(base_payroll / 2, 0.02))
    add(ms + timedelta(days=27), VENDORS["payroll"][1], -jitter(base_payroll * 0.19, 0.03))

    # --- contractors: lumpy, tapers off once they hire FTEs ---
    n_contract = 3 if ms < date(2026, 3, 1) else 1
    for _ in range(n_contract):
        add(ms + timedelta(days=random.randint(2, 25)),
            random.choice(VENDORS["contractors"]), -jitter(random.uniform(2200, 6800), 0.1))

    # --- cloud: creeping up ~7% a month ---
    aws = 2_400 * (1.07 ** i)
    add(ms + timedelta(days=2), "AWS EMEA BILLING", -jitter(aws, 0.04))
    add(ms + timedelta(days=4), "VERCEL INC", -jitter(320, 0.1))
    if i >= 4:
        add(ms + timedelta(days=6), "SUPABASE", -jitter(599, 0.02))

    # --- software subscriptions: steady, grows a little with headcount ---
    seats = 8 if ms < date(2026, 3, 1) else 13
    for v in VENDORS["software"]:
        add(ms + timedelta(days=random.randint(1, 12)), v,
            -jitter(seats * random.uniform(9, 46), 0.05))

    # --- marketing: flat, then doubles in May 2026 ---
    mkt = 6_500 if ms < date(2026, 5, 1) else 14_000
    for v in random.sample(VENDORS["marketing"], 2):
        add(ms + timedelta(days=random.randint(3, 26)), v, -jitter(mkt / 2, 0.15))

    # --- facilities ---
    add(ms + timedelta(days=1), "WEWORK NY", -jitter(4_200 if seats == 8 else 6_100, 0.01))
    add(ms + timedelta(days=9), "CON EDISON", -jitter(340, 0.15))

    # --- legal & admin: quiet, then a Feb 2026 spike ---
    if ms == date(2026, 2, 1):
        add(ms + timedelta(days=11), "COOLEY LLP", -38_400.00)
        add(ms + timedelta(days=20), "COOLEY LLP", -12_150.00)
    elif i % 3 == 0:
        add(ms + timedelta(days=14), random.choice(VENDORS["legal"]), -jitter(2_800, 0.3))
    add(ms + timedelta(days=17), "CARTA INC", -jitter(400, 0.05))

    # --- travel: bursty ---
    if random.random() < 0.55:
        for _ in range(random.randint(1, 3)):
            add(ms + timedelta(days=random.randint(3, 27)),
                random.choice(VENDORS["travel"]), -jitter(random.uniform(280, 1400), 0.2))

    # --- misc ---
    for _ in range(random.randint(2, 5)):
        add(ms + timedelta(days=random.randint(1, 27)),
            random.choice(VENDORS["other"]), -jitter(random.uniform(60, 900), 0.25))

    # --- revenue: growing ~9%/mo, flattening after the marketing bump ---
    growth = 1.09 ** i if i < 11 else 1.09 ** 11 * (1.015 ** (i - 11))
    mrr = 11_000 * growth
    n_pay = random.randint(4, 6)
    for _ in range(n_pay):
        add(ms + timedelta(days=random.randint(1, 27)),
            random.choice(CUSTOMERS), jitter(mrr / n_pay, 0.22))

    # --- financing: SAFE closes Sep 2025 ---
    if ms == date(2025, 9, 1):
        add(ms + timedelta(days=18), "WIRE IN - SAFE - VERTEX SEED FUND I LP", 1_030_000.00)
        add(ms + timedelta(days=21), "COOLEY LLP - FINANCING FEES", -21_000.00)

rows.sort(key=lambda r: r["date"])

# running balance
bal = OPENING_CASH
for r in rows:
    bal += r["amount"]
    r["balance"] = round(bal, 2)

with open("data/sample_transactions.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=["date", "description", "amount", "balance"])
    w.writeheader()
    w.writerows(rows)

print(f"wrote {len(rows)} rows, {rows[0]['date']} to {rows[-1]['date']}")
print(f"opening cash {OPENING_CASH:,.2f}  ending cash {bal:,.2f}")
