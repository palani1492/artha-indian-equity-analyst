from decimal import Decimal

from app.agent import EquityResearchAgent
from app.domain.models import Exchange, Stock


def test_requested_tickers_support_company_aliases_and_explicit_scope() -> None:
    stocks = (
        Stock(
            ticker="TCS",
            exchange=Exchange.NSE,
            name="Tata Consultancy Services",
            price_inr=Decimal(4100),
        ),
        Stock(
            ticker="INFY",
            exchange=Exchange.NSE,
            name="Infosys",
            price_inr=Decimal(1500),
        ),
        Stock(
            ticker="RELIANCE",
            exchange=Exchange.NSE,
            name="Reliance Industries",
            price_inr=Decimal(1400),
        ),
    )

    requested = EquityResearchAgent._requested_tickers(
        "Compare Infosys with Tata",
        followed=("TCS", "INFY", "RELIANCE"),
        stocks=stocks,
        explicit="RELIANCE",
    )

    assert requested == ("INFY", "TCS")
    assert EquityResearchAgent._requested_tickers(
        "Show the selected stock",
        followed=("TCS", "INFY", "RELIANCE"),
        stocks=stocks,
        explicit="RELIANCE",
    ) == ("RELIANCE",)
