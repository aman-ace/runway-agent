# runway-agent

Point it at a startup's bank CSV. It works out burn and runway, separates the
spend changes that matter from the ones that don't, and writes the cash section
of a board update.

```
$ python agent.py data/sample_transactions.csv

model:   gemini / gemini-2.5-flash
loaded:  439 transactions, 14 months
flagged: 2 step_up, 2 one_off, 1 creep

closing cash    $371,171
net burn (3mo)  $79,527/mo
runway          4.7 months
cash zero       ~2026-11-20

report written to reports/runway_report.md
```

Full sample output: [`reports/example_report.md`](reports/example_report.md)

## The idea

Most burn analysis stops at "spend went up 12% this month," which is not useful,
because it does not tell you whether that 12% is coming back. Three different
things move a spend line, and they mean completely different things:

| | what it is | what to do |
|---|---|---|
| **One-off** | a month spikes, then reverts | exclude it from the run rate |
| **Step-up** | the level shifts and holds | this *is* the new run rate |
| **Creep** | no bad month, but it climbs all year | renegotiate before it compounds |

The tool detects each separately and labels them. On the sample data that means
it says *payroll stepped up permanently in March, the $51k legal bill in
February was a one-off, and cloud spend has been growing 7% a month all year* —
rather than flagging eleven category-months and leaving you to sort it out.

## Quick start

```bash
git clone https://github.com/<you>/runway-agent
cd runway-agent
pip install -r requirements.txt

python agent.py data/sample_transactions.csv --provider none
```

`--provider none` runs the whole thing with no API key and no network. Every
number is identical with or without a model. Try that first.

To get written commentary instead of templated commentary:

```bash
cp .env.example .env      # add your key
python agent.py data/sample_transactions.csv
```

## Your own data

Any CSV with `date`, `description`, `amount`. Negative amounts are money out.
A `balance` column is used if present, otherwise pass `--opening-cash`.

```bash
python agent.py exports/mercury_2026.csv --opening-cash 250000 -o reports/july.md
```

Most bank and Mercury/Brex/Ramp exports work as-is. QuickBooks needs the columns
renamed.

## HTML report

Output format follows the `-o` extension. Ask for `.html` instead of `.md` and
you get a self-contained page — stat tiles, a net burn trend chart, a closing
cash trend, and a category breakdown, all inline SVG with no external assets
and no JS, so it opens fine offline or as an email attachment. It respects
light/dark from the OS.

```bash
python agent.py data/sample_transactions.csv -o reports/june.html
```

The markdown report gets a "top vendors" section too, the biggest cash outflows
by name for the latest month. `--top-vendors N` controls how many (default 8,
`--top-vendors 0` to skip it).

## How it works

```
agent.py          CLI, wires the pieces together
├── burn.py       every calculation. No model touches this file.
├── categorize.py regex vendor table, model only sees what the rules miss
├── report.py     fact sheet in, markdown or HTML out
├── charts.py     dependency-free SVG line/bar charts for the HTML report
└── llm.py        gemini | ollama | none, one interface
```

Two decisions worth calling out, because they are the whole design:

**The model does not do arithmetic.** It writes prose and it categorizes
unrecognised vendor names. Burn, runway and variance classification are
deterministic pandas in `burn.py`, covered by tests. If the model is
unavailable, rate limited, or returns nonsense, the report still comes out with
the same figures.

**Rules before the model.** A bank export is the same forty vendors over and
over, so a regex table handles ~100% of the sample file in microseconds for
free. Only genuinely unknown descriptions go to the model, batched into one
call. A typical run costs a fraction of a cent.

### Definitions

- **gross burn** — total operating cash out
- **net burn** — gross burn less customer collections
- **runway** — closing cash / trailing 3-month average net burn

Financing inflows are excluded from burn and included in the cash balance. A
SAFE landing in the account is not revenue, and counting it as one makes the
month a round closes look like the best month the company ever had.

## Swapping models

This build only calls Google's API. One environment variable:

```bash
LLM_PROVIDER=gemini      # default, free tier, needs GEMINI_API_KEY
LLM_PROVIDER=ollama      # local, no key, no network
LLM_PROVIDER=none        # skip it
```

There is no Anthropic path and no `ANTHROPIC_API_KEY` is ever read. If
`LLM_PROVIDER=anthropic` is set, the agent notices, explains it is not
supported, and falls back to templated commentary rather than silently
calling a different vendor.

`LLM_MODEL` picks the model (default `gemini-2.5-flash`); set it to something
heavier, like `gemini-2.5-pro`, if you want deeper commentary and don't mind
the extra latency and cost.

**On the Gemini free tier, Google may use your prompts to improve their
models.** Do not point the free tier at real company financials. Use the
included synthetic data, or enable billing, or run `ollama` locally where
nothing leaves the machine. The tool never sends raw transactions anywhere
regardless: the model sees monthly aggregates and unmatched vendor strings, not
your customer list.

Under the hood, `llm.py` asks Gemini for JSON-mode, low-temperature output
when categorizing vendors (a classification task, where the same vendor
should map to the same category every run) and a higher-temperature free-text
call for the board commentary (a writing task). Transient failures - rate
limits, brief outages - get retried with exponential backoff before the tool
falls back to templated commentary; a bad key or bad request fails
immediately instead of retrying the same error three times.

## Tests

```bash
pytest -q
```

23 tests, no network, no key. They cover the things that would be embarrassing
to get wrong: a SAFE classified as revenue, runway computed off a spike month
instead of the trailing average, a step-up reported in the wrong month, the
same change flagged six times, and the SVG chart helpers producing valid,
correctly-escaped markup.

## Limitations

- Straight-line runway. No seasonality, no hiring plan, no assumed change in
  run rate.
- Cash basis only. It reads a bank account, so it knows nothing about accruals,
  deferred revenue, or committed spend that has not cleared yet.
- The variance thresholds (`--min-flag-dollars`, `--flag-pct`) are tuned for a
  company burning roughly $50k to $150k a month. Scale them for anything much
  bigger or smaller.
- Vendor rules are US and SaaS flavoured. Add to `RULES` in `categorize.py`.

## Sample data

`data/sample_transactions.csv` is generated by `make_sample_data.py`, not real.
Fourteen months for a fictional seed-stage SaaS company, with a hiring step-up,
a SAFE, a legal dispute, and quietly compounding cloud costs deliberately baked
in so the detectors have something to find.
