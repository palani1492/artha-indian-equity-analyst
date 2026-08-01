from __future__ import annotations

import re

from app.domain.models import Citation, GroundingResult, SourceDocument

CITATION_PATTERN = re.compile(r"\[(\d+)]")
NUMBER_PATTERN = re.compile(r"(?<![A-Za-z])\d[\d,]*(?:\.\d+)?%?")
NON_INR_CURRENCY_PATTERN = re.compile(r"(?:\$|US\$|USD|€|EUR|£|GBP)", re.IGNORECASE)
WORD_PATTERN = re.compile(r"[a-z][a-z-]+")
NON_CLAIM_WORDS = {
    "a",
    "an",
    "and",
    "at",
    "has",
    "inr",
    "is",
    "latest",
    "retrieved",
    "rs",
    "the",
    "tone",
    "with",
}


class GroundingGuard:
    FALLBACK = "I don't have that in the ingested data."

    def validate(
        self,
        answer: str,
        citations: tuple[Citation, ...],
        sources: tuple[SourceDocument, ...],
    ) -> GroundingResult:
        violations: list[str] = []
        citation_map = {citation.index: citation for citation in citations}
        source_map = {source.id: source for source in sources}
        if NON_INR_CURRENCY_PATTERN.search(answer):
            violations.append("non-INR currency notation")
        referenced_indexes = {int(value) for value in CITATION_PATTERN.findall(answer)}
        unknown = referenced_indexes.difference(citation_map)
        if unknown:
            violations.append("unknown citation index")
        for citation_index in referenced_indexes.intersection(citation_map):
            if citation_map[citation_index].document_id not in source_map:
                violations.append("citation does not reference a retrieved source")
        for sentence in self._sentences(answer):
            indexes = [int(value) for value in CITATION_PATTERN.findall(sentence)]
            numbers = NUMBER_PATTERN.findall(CITATION_PATTERN.sub("", sentence))
            if not indexes and sentence not in {
                self.FALLBACK,
                "I updated your investor persona and will use it for future research.",
            }:
                violations.append("claim without citation")
            if numbers and not indexes:
                violations.append("numeric claim without citation")
                continue
            if indexes and not self._sentence_supported(
                sentence, indexes, citation_map, source_map
            ):
                violations.append("claim is not supported by its cited source")
        return GroundingResult(
            answer=answer,
            citations=citations,
            is_grounded=not violations,
            violations=tuple(dict.fromkeys(violations)),
        )

    def enforce(
        self,
        answer: str,
        citations: tuple[Citation, ...],
        sources: tuple[SourceDocument, ...],
    ) -> GroundingResult:
        result = self.validate(answer, citations, sources)
        if result.is_grounded:
            return result
        return GroundingResult(answer=self.FALLBACK, is_grounded=True)

    @staticmethod
    def _sentences(answer: str) -> tuple[str, ...]:
        protected = re.sub(r"\bRs\.", "Rs<dot>", answer, flags=re.IGNORECASE)
        return tuple(
            part.replace("<dot>", ".").strip()
            for part in re.split(r"(?<=[.!?])\s+|\n+", protected)
            if part.strip()
        )

    @staticmethod
    def _sentence_supported(
        sentence: str,
        indexes: list[int],
        citation_map: dict[int, Citation],
        source_map: dict[str, SourceDocument],
    ) -> bool:
        numeric_claims = NUMBER_PATTERN.findall(CITATION_PATTERN.sub("", sentence))
        cited_text = " ".join(
            source_map[citation_map[index].document_id].content
            for index in indexes
            if index in citation_map and citation_map[index].document_id in source_map
        )
        valid_citations = all(
            index in citation_map and citation_map[index].document_id in source_map
            for index in indexes
        )
        if not valid_citations:
            return False
        normalized_source = cited_text.replace(",", "")
        numbers_supported = all(
            number.replace(",", "").rstrip("%") in normalized_source
            for number in numeric_claims
        )
        claim_words = {
            word
            for word in WORD_PATTERN.findall(sentence.lower())
            if word not in NON_CLAIM_WORDS
        }
        source_words = set(WORD_PATTERN.findall(cited_text.lower()))
        supported = claim_words.intersection(source_words)
        qualitative_supported = (
            not claim_words or len(supported) / len(claim_words) >= 0.5
        )
        return numbers_supported and qualitative_supported
