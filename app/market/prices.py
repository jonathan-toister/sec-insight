"""Market data client (Phase 3).

Wraps a price/fundamentals API (e.g. Alpha Vantage, Finnhub, or yfinance for a
no-key start). Exposes get_stock_price(ticker) and, later, fundamentals used to
join structured numbers against filing text — the thing NotebookLM can't do.
"""
