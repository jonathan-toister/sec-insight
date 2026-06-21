# Phase 11 — Sector context

**Status: planned.** Depends on Phase 8 (facts) and the `sector`/`industry`
labels from Phase 6. A multiple is meaningless without its sector: banks live on
P/B + ROE, REITs on FFO, utilities on low P/E, tech on high P/E, energy is
cyclical. This phase makes every comparison sector-aware.

**Outcome:** answers read "P/E 12 vs. the software-sector median ~28 and its own
5-yr average," and model selection is sector-correct.

## Build

1. **`sectors` / `sector_profiles` tables** — per sector:
   `(sector, typical_multiples_json, key_metrics, preferred_models, watch_items)`.
   - `typical_multiples_json` — normal ranges for the multiples that matter in
     that sector.
   - `key_metrics` — the metrics analysts actually use there (e.g. FFO for
     REITs, ROE for banks).
   - `preferred_models` — which Phase 10 models apply / don't.
   - `watch_items` — sector-specific risks to surface.

   Seed statically; optionally refresh the multiple ranges from live peer
   aggregates computed off `financial_facts` via the XBRL Frames API (Phase 8).

2. **`company_peers` table** — `(company_id, peer_company_id, basis)`. The peer
   set used for relative valuation, derived from sector/industry + size band.

3. **`get_sector_context(ticker)` tool** — returns the company's
   `sector_profile` and peer set. Feeds Phase 10 model selection and computes
   peer-relative multiples on demand, so the profile isn't stuffed into every
   prompt (token discipline).

## Usage at answer time

The agent pulls sector context to (a) frame every multiple against sector median
+ the company's own history, (b) choose sector-appropriate valuation models, and
(c) surface sector `watch_items`. The verdict is always relative, never a
context-free number.

## Definition of done

For a company, the system returns its sector profile and peers, computes at least
one peer-relative multiple, and an answer frames valuation against both the
sector median and the company's own 5-yr range.
