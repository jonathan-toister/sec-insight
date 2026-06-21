# Phase 9 — Prices + macro

**Status: planned.** Adds the two external inputs the valuation engine needs:
a market price (to compare against intrinsic value) and a risk-free rate (to
discount cash flows). Both from free sources, both long-term friendly.

**Outcome:** for any covered company the system has a current/historical price
and a live discount rate — the missing pieces before Phase 10 can value
anything.

## Sources

- **Prices — Stooq.** Free EOD CSV, no key, no meaningful rate limit. End-of-day
  granularity is exactly right for a long-horizon tool; no intraday needed.
  (Tiingo / FMP are drop-in alternates if a fundamentals-bearing source is
  wanted later.)
- **Macro — FRED** (St. Louis Fed, free key). Pull the 10-year Treasury
  (`DGS10`) for the risk-free rate, plus the Treasury curve, CPI, and GDP for
  sector/macro context.

## Build

1. **`prices` table** — `(company_id, date, close, adj_close, volume,
   source_type)`. Idempotent on `(company_id, date)`. Store `adj_close` for
   long-run return math.

2. **`macro_series` table** — `(series_id, date, value)`. A thin cache of FRED
   series so the discount rate and macro context don't require a live call per
   valuation.

3. **`market/prices.py`** — Stooq client (fetch + upsert EOD history). Replaces
   the no-key price stub referenced in the original Phase 6.

4. **`market/macro.py`** — FRED client + a small accessor that returns the
   prevailing risk-free rate as of a given date (honoring Phase 6 point-in-time
   rules).

5. **Tools** — `get_price(ticker, date?)` and `get_macro(series_id, date?)`.

## Definition of done

A covered company returns its latest close and a price history, and the system
returns a point-in-time risk-free rate from FRED for an arbitrary date.
