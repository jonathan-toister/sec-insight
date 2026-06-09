"""Tool-calling registry (Phase 2+).

Each tool = a JSON schema (name, description, input_schema) the model sees, plus
a Python handler your code executes when the model requests it.

Planned tools:
- search_filings(query, company?, form_type?, year?, k)  # wraps rag.retrieve
- get_filing(company, year, form_type)                    # fetch a specific doc
- compare_filings(company, year1, year2, section)         # year-over-year diff
- get_stock_price(ticker)                                 # market data (Phase 3)

The agent loop: send tools -> model asks for one -> validate args -> run handler
-> feed result back -> repeat until the model returns a final answer.

TODO (Phase 2): define TOOLS list + dispatch(name, args) with arg validation.
"""
