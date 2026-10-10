"""A compact standard Okapi BM25 index used by Retrieval v2."""

from __future__ import annotations

from collections import Counter
import math
import re
from typing import Iterable

from .models import CourseChunkV2


_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "can", "do", "does",
    "for", "from", "how", "i", "in", "is", "it", "me", "my", "of", "on",
    "or", "should", "the", "this", "to", "what", "where", "which", "with", "you", "your",
    "about", "course", "module", "material", "materials", "say", "says",
}


def tokenise(text: str) -> list[str]:
    tokens: list[str] = []
    for token in re.findall(r"[a-z0-9]+", str(text).casefold().replace("_", " ")):
        if len(token) <= 1 or token in _STOPWORDS:
            continue
        if len(token) > 4 and token.endswith("ies"):
            token = token[:-3] + "y"
        elif len(token) > 4 and token.endswith("s") and not token.endswith("ss"):
            token = token[:-1]
        tokens.append(token)
    return tokens


class BM25IndexV2:
    """Okapi BM25 with deterministic tie-breaking and no network dependency."""

    def __init__(self, chunks: Iterable[CourseChunkV2], k1: float = 1.5, b: float = 0.75) -> None:
        self.chunks = list(chunks)
        self.k1 = k1
        self.b = b
        self.documents = [
            tokenise(" ".join((chunk.title, " ".join(chunk.section_path), chunk.text)))
            for chunk in self.chunks
        ]
        self.term_frequencies = [Counter(tokens) for tokens in self.documents]
        self.lengths = [len(tokens) for tokens in self.documents]
        self.average_length = sum(self.lengths) / len(self.lengths) if self.lengths else 0.0
        document_frequency: Counter[str] = Counter()
        for tokens in self.documents:
            document_frequency.update(set(tokens))
        size = len(self.documents)
        self.idf = {
            term: math.log(1.0 + (size - frequency + 0.5) / (frequency + 0.5))
            for term, frequency in document_frequency.items()
        }

    def score(self, query: str, index: int) -> float:
        if not self.documents or not self.average_length:
            return 0.0
        score = 0.0
        frequencies = self.term_frequencies[index]
        length = self.lengths[index]
        for term in tokenise(query):
            frequency = frequencies.get(term, 0)
            if not frequency:
                continue
            denominator = frequency + self.k1 * (
                1.0 - self.b + self.b * length / self.average_length
            )
            score += self.idf.get(term, 0.0) * frequency * (self.k1 + 1.0) / denominator
        return score

    def search(self, query: str, top_k: int) -> list[tuple[CourseChunkV2, float]]:
        scored = [(chunk, self.score(query, index)) for index, chunk in enumerate(self.chunks)]
        scored = [item for item in scored if item[1] > 0]
        scored.sort(key=lambda item: (-item[1], item[0].chunk_id))
        return scored[: max(0, top_k)]
