# Phase 10 — Valuation engine + model registry

**Status: planned.** Depends on Phase 8 (fundamentals) and Phase 9 (price +
discount rate). Turns raw numbers into intrinsic-value estimates, with the model
choice made explicit and self-explaining.

**Outcome:** for a company, the system runs sector-appropriate valuation models,
each returning a fair value, the inputs used, a confidence band, and a
plain-language interpretation — framed as decision-support, never a buy/sell
call.

## Models as data

Make models a first-class concept so the agent can explain *why* a model was
chosen and *what its output means*.

**`valuation_models` table** — `(name, description, applicability, required_inputs,
interpretation)`:

- `description` — plain-language explanation of the model.
- `applicability` — machine-readable rule for when it fits (sector, profitability,
  dividend status, FCF stability).
- `required_inputs` — the canonical metrics it consumes.
- `interpretation` — how to read the result; this text is surfaced in answers so
  the user learns the concept.

Seed rows:

- **DCF** — intrinsic value from projected free cash flow; discount rate from
  FRED (Phase 9). Use when FCF is positive and reasonably stable.
- **Reverse DCF** — solve for the growth rate the current price implies. Best
  single tool for "is the market too optimistic"; works when forward estimates
  are shaky.
- **Relative multiples** — P/E, P/S, P/B, EV/EBITDA, PEG vs. sector peers
  (Phase 11) and the company's own 5-yr range. The default.
- **DDM** — dividend payers with a stable payout.
- **Graham number** — conservative floor for profitable, asset-backed names.
- **Quality/safety screens** — ROIC, debt/equity, margin trend, Piotroski
  F-Score, Altman Z-Score. Not valuation; gating context that adjusts confidence.

## Build

1. **`valuations` table** — cached results: `(company_id, model, as_of,
   fair_value, inputs_json, confidence, rationale)`. Caching avoids recompute and
   feeds Phase 13 monitoring.

2. **`select_models(company)`** — deterministic selector applying each model's
   `applicability` rule against the company's sector + fundamentals (e.g.
   dividend payer → add DDM; financial sector → P/B + ROE, drop EV/EBITDA;
   negative-FCF high-growth → P/S + reverse DCF, drop DCF).

3. **`rag/valuation.py`** — implement each model as a small, testable function
   returning a structured result (fair value, inputs used, confidence,
   rationale). Pull inputs only from `financial_facts`/`prices`/`macro_series`.

4. **`run_valuation(ticker)` tool** — runs the selected models and returns their
   structured results so the agent reasons *across* them rather than trusting one
   number. Every answer presents fair value, the peer/historical context, the
   gap, and the not-investment-advice reminder.

5. **`analyze_company(ticker, focus=[])` compound tool** — batches the most
   common multi-tool sequence into one call: internally fetches financials, latest
   price, risk-free rate, sector context, and runs `run_valuation`. Returns a
   structured summary covering the requested focus areas (e.g. `["valuation",
   "quality", "sector"]`). The agent calls this once for the data-heavy part of
   an investment proposition, then supplements with targeted `search_filings`
   calls for qualitative text (risk factors, MD&A language). Without this, a
   full-analysis turn requires 8+ serial tool calls; this reduces it to 3–4.

6. **`investment_analysis` response type for `format_answer`.** Alongside the
   existing `"research"` and `"conversational"` types, add
   `"investment_analysis"` with required sub-fields: `summary` (2–3 sentence
   thesis), `valuation_section` (models + outputs), `risk_section` (key risks
   from filings), and `verdict` (relative attractiveness framed vs. sector,
   always with disclaimer). The agent uses this type when it has completed a
   full company analysis.

## Definition of done

A real company yields sector-appropriate models, each with inputs, a confidence
band, and an interpretation; results are cached; a unit test verifies at least
DCF and reverse-DCF math against a hand-checked example.
