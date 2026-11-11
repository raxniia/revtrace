from __future__ import annotations

import numpy as np

from revtrace.rag import Chunk, PolicyIndex


def test_lexical_search_finds_the_response_rule(ctx):
    top = ctx.index.search("délai de première réponse", k=1)[0]
    assert "première réponse" in top["citation"]
    assert "30 minutes" in top["text"]


def test_outline_lists_documents_and_sections(ctx):
    outline = ctx.index.outline()
    assert len(outline) == 3
    assert any("Relances" in s for doc in outline for s in doc["sections"])


def test_dense_scores_can_override_lexical_ones():
    class Embedder:
        def embed(self, texts):
            return np.array([[1.0, 0.0] if "alpha" in t or "first" in t else [0.0, 1.0] for t in texts])

    chunks = [Chunk("a.md", "A", "one", "alpha"), Chunk("b.md", "B", "two", "first words")]
    index = PolicyIndex(chunks, Embedder())
    assert index.search("alpha", k=2)[0]["doc"] == "a.md"
    assert {r["doc"] for r in index.search("first", k=2)} == {"a.md", "b.md"}


def test_empty_index_returns_nothing():
    assert PolicyIndex([]).search("anything") == []
