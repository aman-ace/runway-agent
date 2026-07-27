# Changelog

All notable changes to this project are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.1.0] - 2026-07-27

### Added
- Burn and runway analysis from a bank transactions CSV (`burn.py`): gross
  burn, net burn, trailing 3-month average, runway, and a straight-line
  cash-zero date projection.
- Variance detection that separates spend changes into step-ups, one-offs,
  and creep instead of flagging every anomalous category-month the same way.
- Rules-first vendor categorization (`categorize.py`): a regex table handles
  the bulk of a typical bank export for free; only unmatched descriptions are
  sent to the model, batched into one call.
- Markdown and HTML report output (`report.py`, `charts.py`); the HTML report
  is self-contained, dependency-free SVG charts, no external assets or JS.
- Top vendors section (`--top-vendors N`) for the latest month's biggest
  cash outflows, in both report formats.
- `pytest` suite (23 tests) covering burn/runway math, variance
  classification, categorization edge cases, and the chart SVG helpers.
- GitHub Actions workflow running the test suite and an end-to-end
  `--provider none` smoke test on every push.

### Changed
- LLM backend is Gemini-only. Anthropic support was removed entirely -
  `LLM_PROVIDER=anthropic` is recognized only so the agent can explain it
  isn't supported and fall back to templated commentary, rather than
  silently calling a different vendor's API.
- Model calls now use JSON mode and low temperature for vendor
  categorization (a classification task) and a higher temperature for board
  commentary (a writing task), with exponential backoff on transient
  failures (rate limits, brief outages).
- HTML report redesigned around a ledger-paper concept: ruled paper texture,
  a red margin rule, monospace figures, and real shadow depth. It stays
  light regardless of the reader's OS theme, on purpose - a board memo
  shouldn't flip dark because of someone's system settings.
