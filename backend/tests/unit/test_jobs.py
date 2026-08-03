from __future__ import annotations

from app.jobs import ingest as ingest_job


async def test_scheduled_refresh_restores_bse_provider_suffix(container) -> None:
    await container.ingestion.ingest("TCS.BO")
    await container.repository.follow_stock("investor@example.com", "TCS")

    refresh_ticker = await ingest_job._refresh_ticker(container.repository, "TCS")

    assert refresh_ticker == "TCS.BO"
