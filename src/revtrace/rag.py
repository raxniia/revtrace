from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


@dataclass(frozen=True)
class Chunk:
    doc: str
    title: str
    section: str
    text: str

    @property
    def citation(self) -> str:
        return f"{self.title} › {self.section}" if self.section else self.title


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> np.ndarray: ...


class FastEmbedEmbedder:
    def __init__(self, model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"):
        from fastembed import TextEmbedding

        self._model = TextEmbedding(model)

    def embed(self, texts: list[str]) -> np.ndarray:
        return np.array(list(self._model.embed(texts)))


def chunk_markdown(path: Path, max_chars: int = 900) -> list[Chunk]:
    text = path.read_text(encoding="utf-8")
    title_match = re.search(r"^#\s+(.+)$", text, flags=re.M)
    title = title_match.group(1).strip() if title_match else path.stem.replace("_", " ")
    chunks: list[Chunk] = []
    section, buffer = "", []

    def flush():
        body = "\n".join(buffer).strip()
        if not body:
            return
        for start in range(0, len(body), max_chars):
            chunks.append(Chunk(path.name, title, section, body[start : start + max_chars]))

    for line in text.splitlines():
        heading = re.match(r"^#{2,4}\s+(.+)$", line)
        if heading:
            flush()
            section, buffer = heading.group(1).strip(), []
        elif not line.startswith("# "):
            buffer.append(line)
    flush()
    return chunks


class PolicyIndex:
    def __init__(self, chunks: list[Chunk], embedder: Embedder | None = None):
        self.chunks = chunks
        self.embedder = embedder
        self._words = self._chars = self._word_matrix = self._char_matrix = self._dense = None
        if chunks:
            corpus = [f"{c.title} {c.section} {c.text}" for c in chunks]
            self._words = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True)
            self._chars = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True)
            self._word_matrix = self._words.fit_transform(corpus)
            self._char_matrix = self._chars.fit_transform(corpus)
            if embedder is not None:
                self._dense = _normalise(embedder.embed(corpus))

    @classmethod
    def from_paths(cls, paths: list[Path], embedder: Embedder | None = None) -> PolicyIndex:
        return cls([chunk for path in paths for chunk in chunk_markdown(path)], embedder)

    def __len__(self) -> int:
        return len(self.chunks)

    def search(self, query: str, k: int = 3) -> list[dict]:
        if not self.chunks or not query.strip():
            return []
        lexical = 0.5 * cosine_similarity(self._words.transform([query]), self._word_matrix)[0]
        lexical += 0.5 * cosine_similarity(self._chars.transform([query]), self._char_matrix)[0]
        scores = lexical
        if self._dense is not None:
            dense = self._dense @ _normalise(self.embedder.embed([query]))[0]
            scores = 0.4 * lexical + 0.6 * dense
        order = np.argsort(-scores)[:k]
        return [
            {
                "doc": self.chunks[i].doc,
                "citation": self.chunks[i].citation,
                "text": self.chunks[i].text,
                "score": round(float(scores[i]), 3),
            }
            for i in order
            if scores[i] > 0.02
        ]

    def outline(self) -> list[dict]:
        seen: dict[str, list[str]] = {}
        for chunk in self.chunks:
            sections = seen.setdefault(chunk.title, [])
            if chunk.section and chunk.section not in sections:
                sections.append(chunk.section)
        return [{"document": title, "sections": sections} for title, sections in seen.items()]


def _normalise(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix / np.where(norms == 0, 1, norms)


def build_index(paths: list[Path], embeddings: str = "") -> PolicyIndex:
    embedder = FastEmbedEmbedder() if embeddings == "fastembed" else None
    return PolicyIndex.from_paths(paths, embedder)
