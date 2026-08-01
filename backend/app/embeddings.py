from __future__ import annotations

import asyncio
import hashlib
import math
import re
from collections import Counter, defaultdict
from typing import Protocol

from openai import AsyncOpenAI, OpenAIError

TOKEN_PATTERN = re.compile(r"[a-z0-9&]+")


class Embedder(Protocol):
    async def embed(self, text: str) -> tuple[float, ...]: ...


class DeterministicEmbedder:
    """Cheap local hashing embedder for deterministic demos and tests."""

    def __init__(self, dimensions: int = 1536) -> None:
        self.dimensions = dimensions
        self.embedded_count = 0

    async def embed(self, text: str) -> tuple[float, ...]:
        self.embedded_count += 1
        counts = Counter(TOKEN_PATTERN.findall(text.lower()))
        vector = [0.0] * self.dimensions
        for token, count in counts.items():
            digest = hashlib.sha256(token.encode()).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[index] += sign * (1.0 + math.log(count))
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return tuple(value / norm for value in vector)


class OpenAIEmbedder:
    def __init__(self, api_key: str, model: str) -> None:
        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model

    async def embed(self, text: str) -> tuple[float, ...]:
        response = await self._client.embeddings.create(model=self._model, input=text)
        return tuple(response.data[0].embedding)


class ResilientCachedEmbedder:
    """Content-addressed cache with a deterministic fallback for provider failures."""

    def __init__(
        self, primary: Embedder | None, fallback: DeterministicEmbedder
    ) -> None:
        self._primary = primary
        self._fallback = fallback
        self._cache: dict[str, tuple[float, ...]] = {}
        self._locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    @property
    def embedded_count(self) -> int:
        return self._fallback.embedded_count

    async def embed(self, text: str) -> tuple[float, ...]:
        key = hashlib.sha256(" ".join(text.split()).encode()).hexdigest()
        if key in self._cache:
            return self._cache[key]
        async with self._locks[key]:
            if key in self._cache:
                return self._cache[key]
            embedding = await self._embed_uncached(text)
            self._cache = {**self._cache, key: embedding}
            return embedding

    async def _embed_uncached(self, text: str) -> tuple[float, ...]:
        if self._primary is not None:
            try:
                return await self._primary.embed(text)
            except (OpenAIError, RuntimeError, TimeoutError, ValueError):
                return await self._fallback.embed(text)
        return await self._fallback.embed(text)
