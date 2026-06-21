"""SIC code → GICS-style (sector, industry) lookup."""

# Each entry is (max_sic_int_inclusive, sector, industry).
# Scan linearly; first match wins.
_RANGES: list[tuple[int, str, str]] = [
    (999,  "Materials",                "Agriculture"),
    (1499, "Materials",                "Mining & Metals"),
    (1799, "Industrials",              "Construction"),
    (2099, "Consumer Staples",         "Food Products"),
    (2199, "Consumer Staples",         "Tobacco"),
    (2399, "Consumer Discretionary",   "Textiles & Apparel"),
    (2499, "Materials",                "Paper & Forest Products"),
    (2599, "Consumer Discretionary",   "Furniture"),
    (2699, "Materials",                "Packaging"),
    (2799, "Communication Services",   "Publishing & Printing"),
    (2899, "Materials",                "Chemicals"),
    (2999, "Energy",                   "Oil Refining & Chemicals"),
    (3099, "Materials",                "Rubber & Plastics"),
    (3199, "Consumer Discretionary",   "Leather Goods"),
    (3299, "Materials",                "Glass & Stone"),
    (3399, "Materials",                "Primary Metals"),
    (3499, "Industrials",              "Fabricated Metals"),
    (3569, "Industrials",              "Industrial Machinery"),
    (3579, "Information Technology",   "Computer Hardware"),      # 3571 Electronic Computers
    (3589, "Industrials",              "Industrial Machinery"),
    (3599, "Industrials",              "Industrial Machinery"),
    (3669, "Information Technology",   "Electronic Equipment"),
    (3679, "Information Technology",   "Semiconductors"),
    (3799, "Consumer Discretionary",   "Automobiles & Parts"),
    (3899, "Information Technology",   "Instruments & Controls"),
    (3999, "Consumer Discretionary",   "Miscellaneous Manufacturing"),
    (4099, "Industrials",              "Railroads"),
    (4299, "Industrials",              "Transit & Transportation"),
    (4599, "Industrials",              "Marine & Air Transport"),
    (4699, "Energy",                   "Pipelines"),
    (4799, "Industrials",              "Freight & Logistics"),
    (4899, "Communication Services",   "Telecommunications"),
    (4999, "Utilities",                "Electric, Gas & Water"),
    (5199, "Consumer Discretionary",   "Wholesale — Durable Goods"),
    (5999, "Consumer Discretionary",   "Retail"),
    (6099, "Financials",               "Banking"),
    (6199, "Financials",               "Consumer Finance"),
    (6299, "Financials",               "Securities & Brokerage"),
    (6399, "Financials",               "Insurance"),
    (6499, "Financials",               "Real Estate Finance"),
    (6599, "Real Estate",              "Real Estate"),
    (6799, "Financials",               "Investment Holding"),
    (6999, "Financials",               "Other Finance"),
    (7099, "Consumer Discretionary",   "Hotels & Lodging"),
    (7299, "Consumer Discretionary",   "Personal Services"),
    (7379, "Information Technology",   "Software & IT Services"),
    (7399, "Industrials",              "Business Services"),
    (7599, "Consumer Discretionary",   "Auto Services"),
    (7999, "Communication Services",   "Entertainment & Recreation"),
    (8099, "Health Care",              "Health Care Services"),
    (8299, "Consumer Staples",         "Education Services"),
    (8799, "Industrials",              "Engineering & Management"),
    (9999, "Industrials",              "Government & Public Services"),
]


def sic_to_sector_industry(sic: str | None) -> tuple[str | None, str | None]:
    """Return (sector, industry) for a SIC code string, or (None, None) if unknown."""
    if not sic:
        return None, None
    try:
        code = int(sic)
    except ValueError:
        return None, None
    for max_sic, sector, industry in _RANGES:
        if code <= max_sic:
            return sector, industry
    return None, None
