from __future__ import annotations

import argparse
import asyncio
import json

from app.container import build_container
from app.domain.models import Exchange, normalize_ticker
from app.repositories.base import ResearchRepository


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Refresh followed Indian-equity sources"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--all-followed", action="store_true")
    group.add_argument("--ticker", action="append", dest="tickers")
    return parser.parse_args()


async def _run(args: argparse.Namespace) -> int:
    container = build_container()
    await container.repository.initialize()
    tickers = (
        await container.repository.list_followed_tickers()
        if args.all_followed
        else tuple(args.tickers or ())
    )
    results = []
    for ticker in tickers:
        refresh_ticker = await _refresh_ticker(container.repository, ticker)
        result = await container.ingestion.ingest(refresh_ticker)
        results.append(result.model_dump(mode="json"))
    print(
        json.dumps(
            {"processed": len(results), "results": results}, separators=(",", ":")
        )
    )
    return 0


async def _refresh_ticker(repository: ResearchRepository, raw_ticker: str) -> str:
    ticker, requested_exchange = normalize_ticker(raw_ticker)
    stock = await repository.get_stock(ticker)
    exchange = stock.exchange if stock is not None else requested_exchange
    return f"{ticker}.BO" if exchange is Exchange.BSE else ticker


def main() -> int:
    return asyncio.run(_run(_arguments()))


if __name__ == "__main__":
    raise SystemExit(main())
