from __future__ import annotations

import hashlib
import re

from app.domain.models import GraphFact, SourceDocument, Stock, normalize_ticker

_METRIC_PATTERNS = (
    ("market_cap_crore", r"Market capitalisation is INR ([\d,.]+) crore"),
    ("pe_ratio", r"P/E ratio is ([\d,.]+)"),
    ("debt_to_equity", r"Debt-to-equity is ([\d,.]+)"),
    ("dividend_yield", r"Dividend yield is ([\d,.]+)%"),
    ("roe", r"Return on equity is ([\d,.]+)%"),
    ("revenue_growth", r"Revenue growth is ([\d,.]+)%"),
)


def extract_graph_facts(
    stock: Stock, documents: tuple[SourceDocument, ...]
) -> tuple[GraphFact, ...]:
    facts: list[GraphFact] = []
    for document in documents:
        facts.append(
            _fact(
                document,
                subject_type="company",
                subject_id=stock.ticker,
                predicate="event",
                object_type="event",
                object_id=document.event_tag,
                evidence=f"event_tag={document.event_tag}",
            )
        )
        for mentioned_ticker in document.mentioned_tickers:
            try:
                mentioned = normalize_ticker(mentioned_ticker)[0]
            except ValueError:
                continue
            facts.append(
                _fact(
                    document,
                    subject_type="document",
                    subject_id=document.id,
                    predicate="mentions_company",
                    object_type="company",
                    object_id=mentioned,
                    evidence=f"mentioned_tickers includes {mentioned}",
                )
            )
        for metric, pattern in _METRIC_PATTERNS:
            match = re.search(pattern, document.content, flags=re.IGNORECASE)
            if match is None:
                continue
            value = match.group(1).replace(",", "")
            facts.append(
                _fact(
                    document,
                    subject_type="company",
                    subject_id=stock.ticker,
                    predicate="metric_supported_by_source",
                    object_type="metric",
                    object_id=metric,
                    object_value=value,
                    evidence=match.group(0),
                )
            )
    fundamentals = next(
        (document for document in documents if document.kind.value == "fundamentals"),
        None,
    )
    if fundamentals is not None:
        facts.append(
            _fact(
                fundamentals,
                subject_type="company",
                subject_id=stock.ticker,
                predicate="sector",
                object_type="sector",
                object_id=stock.sector,
                evidence=f"sector={stock.sector} from the ingested stock snapshot",
            )
        )
    return tuple({fact.id: fact for fact in facts}.values())


def _fact(
    document: SourceDocument,
    *,
    subject_type: str,
    subject_id: str,
    predicate: str,
    object_type: str,
    object_id: str,
    evidence: str,
    object_value: str | None = None,
) -> GraphFact:
    identity = "|".join(
        (
            document.id,
            subject_type,
            subject_id,
            predicate,
            object_type,
            object_id,
            object_value or "",
        )
    )
    return GraphFact(
        id=hashlib.sha256(identity.encode()).hexdigest()[:32],
        subject_type=subject_type,
        subject_id=subject_id,
        predicate=predicate,
        object_type=object_type,
        object_id=object_id,
        object_value=object_value,
        source_document_id=document.id,
        source_url=document.url,
        evidence=evidence,
        observed_at=document.published_at,
    )
