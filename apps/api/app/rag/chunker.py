"""Deterministic whitespace-based chunker.

Preserves order; configurable chunk size and overlap. Token-aware chunking is
a future refinement.
"""

from dataclasses import dataclass

from app.rag.normalizer import normalize_text


@dataclass(frozen=True)
class TextChunk:
    chunk_index: int
    content: str
    metadata: dict


class Chunker:
    def __init__(self, chunk_size: int = 500, overlap: int = 50) -> None:
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        if overlap < 0 or overlap >= chunk_size:
            raise ValueError("overlap must be >= 0 and < chunk_size")
        self.chunk_size = chunk_size
        self.overlap = overlap

    def chunk(self, text: str) -> list[TextChunk]:
        normalized = normalize_text(text)
        words = normalized.split()
        chunks: list[TextChunk] = []
        index = 0
        start = 0
        while start < len(words):
            end = min(start + self.chunk_size, len(words))
            content = " ".join(words[start:end])
            chunks.append(TextChunk(chunk_index=index, content=content, metadata={}))
            index += 1
            if end >= len(words):
                break
            start = max(start + self.chunk_size - self.overlap, start + 1)
        return chunks
