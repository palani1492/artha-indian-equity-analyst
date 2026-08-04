from __future__ import annotations

from dataclasses import dataclass

from app.domain.models import Exchange


@dataclass(frozen=True)
class TickerDirectoryEntry:
    ticker: str
    company_name: str
    sector: str
    exchange: Exchange
    bse_id: str | None
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class TickerDirectoryMetadata:
    source: str = "bundled-indian-equity-directory"
    description: str = "Deterministic bundled directory for Indian equity autocomplete"
    refresh_policy: str = "manual bundle update"


DIRECTORY_METADATA = TickerDirectoryMetadata()

# This intentionally stays in-process and deterministic. It is autocomplete data,
# not a per-keystroke market-data integration. Aliases are search-only metadata.
_DIRECTORY_COMPANIES: tuple[
    tuple[str, str, str, str | None, tuple[str, ...]], ...
] = (
    ("ASIANPAINT", "Asian Paints", "Consumer", "500820", ("asian paints",)),
    ("AXISBANK", "Axis Bank", "Private bank", "532215", ("axis",)),
    ("BAJAJ-AUTO", "Bajaj Auto", "Auto", "532977", ("bajaj auto",)),
    ("BAJFINANCE", "Bajaj Finance", "Finance", "500034", ("bajaj finserv finance",)),
    ("BAJAJFINSV", "Bajaj Finserv", "Finance", "532978", ("bajaj financial services",)),
    ("BANKBARODA", "Bank of Baroda", "Public bank", "532134", ("baroda bank",)),
    ("BHARTIARTL", "Bharti Airtel", "Telecom", "532454", ("airtel",)),
    ("BPCL", "Bharat Petroleum", "Energy", "500547", ("bharat petroleum corporation",)),
    ("BRITANNIA", "Britannia Industries", "FMCG", "500825", ("britannia",)),
    ("CIPLA", "Cipla", "Pharma", "500087", ("cipla limited",)),
    ("COALINDIA", "Coal India", "Energy", "533278", ("coal india limited",)),
    ("DIVISLAB", "Divi's Laboratories", "Pharma", "532488", ("divis", "divis labs")),
    ("DRREDDY", "Dr. Reddy's Laboratories", "Pharma", "500124", ("dr reddy", "dr reddys")),
    ("EICHERMOT", "Eicher Motors", "Auto", "505200", ("royal enfield",)),
    ("GAIL", "GAIL (India)", "Energy", "532155", ("gail india",)),
    ("GRASIM", "Grasim Industries", "Industrials", "500300", ("grasim",)),
    ("HCLTECH", "HCL Technologies", "IT services", "532281", ("hcl tech", "hcl technologies")),
    ("HDFCBANK", "HDFC Bank", "Private bank", "500180", ("hdfc", "hdfc bank")),
    ("HDFCLIFE", "HDFC Life Insurance", "Insurance", "540777", ("hdfc life",)),
    ("HEROMOTOCO", "Hero MotoCorp", "Auto", "500182", ("hero motocorp", "hero")),
    ("HINDALCO", "Hindalco Industries", "Industrials", "500440", ("hindalco",)),
    ("HINDUNILVR", "Hindustan Unilever", "FMCG", "500696", ("hul", "hindustan unilever")),
    ("ICICIBANK", "ICICI Bank", "Private bank", "532174", ("icici", "icici bank")),
    ("INDUSINDBK", "IndusInd Bank", "Private bank", "532187", ("indusind",)),
    ("INFY", "Infosys", "IT services", "500209", ("infosys limited",)),
    ("ITC", "ITC", "FMCG", "500875", ("itc limited",)),
    ("JSWSTEEL", "JSW Steel", "Industrials", "500228", ("jsw",)),
    ("KOTAKBANK", "Kotak Mahindra Bank", "Private bank", "500247", ("kotak", "kotak bank")),
    ("LT", "Larsen & Toubro", "Industrials", "500510", ("l&t", "larsen toubro")),
    ("M&M", "Mahindra & Mahindra", "Auto", "500520", ("mahindra", "mahindra and mahindra", "m and m")),
    ("MARUTI", "Maruti Suzuki India", "Auto", "532500", ("maruti", "maruti suzuki")),
    ("NESTLEIND", "Nestle India", "FMCG", "500790", ("nestle",)),
    ("NTPC", "NTPC", "Energy", "532555", ("ntpc limited",)),
    ("ONGC", "Oil & Natural Gas Corporation", "Energy", "500312", ("oil and natural gas", "ongc")),
    ("POWERGRID", "Power Grid Corporation of India", "Energy", "532898", ("power grid", "powergrid")),
    ("RELIANCE", "Reliance Industries", "Energy", "500325", ("ril", "reliance", "reliance industries")),
    ("SBIN", "State Bank of India", "Public bank", "500112", ("sbi", "state bank", "state bank of india")),
    ("SUNPHARMA", "Sun Pharmaceutical Industries", "Pharma", "524715", ("sun pharma", "sun pharmaceutical")),
    ("TATACONSUM", "Tata Consumer Products", "FMCG", "500800", ("tata consumer",)),
    ("TATAMOTORS", "Tata Motors", "Auto", "500570", ("tata motors",)),
    ("TATAPOWER", "Tata Power", "Energy", "500400", ("tata power",)),
    ("TATASTEEL", "Tata Steel", "Industrials", "500470", ("tata steel",)),
    ("TCS", "Tata Consultancy Services", "IT services", "532540", ("tata consultancy", "tata consultancy services")),
    ("TECHM", "Tech Mahindra", "IT services", "532758", ("tech mahindra",)),
    ("TITAN", "Titan Company", "Consumer", "500114", ("titan company",)),
    ("ULTRACEMCO", "UltraTech Cement", "Industrials", "532538", ("ultratech",)),
    ("WIPRO", "Wipro", "IT services", "507685", ("wipro limited",)),
    ("ZOMATO", "Zomato", "Consumer", "543320", ("eternal",)),
    ("PEIL", "PEIL", "Indian equity", None, ()),
)


TICKER_DIRECTORY: tuple[TickerDirectoryEntry, ...] = tuple(
    TickerDirectoryEntry(ticker, company_name, sector, exchange, bse_id, aliases)
    for ticker, company_name, sector, bse_id, aliases in _DIRECTORY_COMPANIES
    for exchange in (Exchange.NSE, Exchange.BSE)
)


def search_ticker_directory(
    query: str, exchange: Exchange | None = None
) -> tuple[TickerDirectoryEntry, ...]:
    normalized = query.strip().casefold()
    matches = []
    for entry in TICKER_DIRECTORY:
        if exchange is not None and entry.exchange is not exchange:
            continue
        fields = (
            entry.ticker.casefold(),
            entry.company_name.casefold(),
            *(alias.casefold() for alias in entry.aliases),
        )
        if not any(normalized in field for field in fields):
            continue
        if normalized == fields[0]:
            rank = 0
        elif normalized == fields[1]:
            rank = 1
        elif fields[0].startswith(normalized):
            rank = 2
        elif fields[1].startswith(normalized):
            rank = 3
        elif any(alias.startswith(normalized) for alias in fields[2:]):
            rank = 4
        elif normalized in fields[0]:
            rank = 5
        elif normalized in fields[1]:
            rank = 6
        else:
            rank = 7
        matches.append((rank, entry))
    return tuple(
        entry
        for _, entry in sorted(
            matches,
            key=lambda match: (
                match[0],
                match[1].ticker,
                0 if match[1].exchange is Exchange.NSE else 1,
            ),
        )
    )
