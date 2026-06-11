# Phase 8 — Monitoring + evals

**Status: planned.** This is the original SPEC's Phase 4, renumbered. It lands
last because monitoring runs in the worker built in phase 5 and summarizes via
`compare_filings` built in phase 6.

**Outcome:** proactive, and measurable.

## Build

1. **Monitoring:** a scheduled job (arq cron in the phase-5 worker) that polls
   EDGAR for new filings on tracked companies, ingests them, runs
   `compare_filings` vs. the prior period, and emits a "what changed" summary.
   Pull becomes push. With phase 7 in place, monitoring covers 8-Ks too — new
   material events are detected within the polling interval.
2. **Evals:** `evals/` holds a test set (`test_set.example.json` is a starter). A
   script runs each question through `/ask` and scores the answer — keyword
   presence to start, optionally an LLM-as-judge later. Treat AI output as
   software with measurable quality, not vibes. By now the agent has many tools
   and sources, so regression-checking answer quality stops being optional —
   include multi-tool and coverage-guidance cases in the test set.
3. **Cost evals:** the per-request token usage logged since phase 3 joins the
   scorecard — track tokens per answered question alongside quality, so a
   regression in cost (e.g. a prompt change that breaks caching or re-triggers
   redundant searches) is caught the same way a quality regression is.

## Definition of done

New filings are detected automatically and summarized; the eval script produces
a quality score and a cost-per-question figure over the test set.
