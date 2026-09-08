"""Calibrated Okapi BM25 lexical ranking implementation with document length normalization."""

import math
import re

TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
STOPWORDS = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
        "has", "he", "in", "is", "it", "its", "of", "on", "that", "the",
        "to", "was", "were", "will", "with",
    }
)


def _stem(word: str) -> str:
    if word.endswith("ments") and len(word) > 8:
        return word[:-5]
    if word.endswith("ment") and len(word) > 7:
        return word[:-4]
    if word.endswith("ing") and len(word) > 5:
        return word[:-3]
    if word.endswith("ed") and len(word) > 4:
        return word[:-2]
    if word.endswith("es") and len(word) > 4:
        return word[:-2]
    if word.endswith("s") and not word.endswith("ss") and len(word) > 3:
        return word[:-1]
    return word


def tokenize(text: str) -> list[str]:
    """Tokenize text into lowercase alphanumeric terms excluding common stopwords."""
    terms = TOKEN_PATTERN.findall(text.lower())
    return [_stem(term) for term in terms if term not in STOPWORDS and len(term) > 1]


class BM25Index:
    """Okapi BM25 scorer with k1 and b normalization."""

    def __init__(
        self,
        corpus: list[str],
        k1: float = 1.5,
        b: float = 0.75,
    ) -> None:
        self.k1 = k1
        self.b = b
        self.corpus_size = len(corpus)
        self.doc_tokens: list[list[str]] = [tokenize(doc) for doc in corpus]
        self.doc_lengths: list[int] = [len(tokens) for tokens in self.doc_tokens]
        total_len = sum(self.doc_lengths)
        self.avg_doc_length: float = (total_len / self.corpus_size) if self.corpus_size > 0 else 1.0

        # Term frequencies per document and document frequencies
        self.doc_term_frequencies: list[dict[str, int]] = []
        self.doc_frequencies: dict[str, int] = {}

        for tokens in self.doc_tokens:
            tf: dict[str, int] = {}
            for token in tokens:
                tf[token] = tf.get(token, 0) + 1
            self.doc_term_frequencies.append(tf)

            for term in tf:
                self.doc_frequencies[term] = self.doc_frequencies.get(term, 0) + 1

        # Precompute IDF
        self.idf: dict[str, float] = {}
        for term, freq in self.doc_frequencies.items():
            # Standard Lucene/BM25 IDF formula with smoothing
            self.idf[term] = math.log(
                1.0 + (self.corpus_size - freq + 0.5) / (freq + 0.5)
            )

    def score(self, query: str, doc_index: int) -> float:
        """Calculate the BM25 relevance score for a document given a query."""
        if doc_index < 0 or doc_index >= self.corpus_size:
            return 0.0

        query_terms = tokenize(query)
        if not query_terms:
            return 0.0

        tf_map = self.doc_term_frequencies[doc_index]
        doc_len = self.doc_lengths[doc_index]
        len_norm = 1.0 - self.b + self.b * (doc_len / self.avg_doc_length)

        total_score = 0.0
        for term in query_terms:
            tf = tf_map.get(term, 0)
            if tf == 0:
                continue

            idf = self.idf.get(term, 0.0)
            numerator = tf * (self.k1 + 1.0)
            denominator = tf + self.k1 * len_norm
            total_score += idf * (numerator / denominator)

        return total_score

    def score_all(self, query: str) -> list[tuple[int, float]]:
        """Score all documents against the query and return ranked (index, score) pairs."""
        scored = [
            (idx, self.score(query, idx))
            for idx in range(self.corpus_size)
        ]
        return sorted(scored, key=lambda pair: pair[1], reverse=True)
