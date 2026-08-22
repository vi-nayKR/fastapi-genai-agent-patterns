"""Small deterministic embedding implementation for local cache demonstrations."""

import hashlib
import math
import re
import struct
import unicodedata

TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


def canonical_prompt(prompt: str) -> str:
    """Normalize semantically irrelevant differences for an exact cache key."""

    normalized = unicodedata.normalize("NFKC", prompt).casefold().strip()
    return " ".join(normalized.split())


class HashingEmbedder:
    """Convert text to a normalized fixed-size vector with no model download.

    Word features capture shared concepts and character trigrams make the vector
    tolerant of small spelling and inflection changes. The class is intentionally
    replaceable with a provider embedding model through the same ``embed`` method.
    """

    def __init__(self, dimensions: int = 128) -> None:
        if dimensions < 8:
            raise ValueError("Embedding dimensions must be at least 8")
        self.dimensions = dimensions

    def embed(self, text: str) -> list[float]:
        normalized = canonical_prompt(text)
        features = TOKEN_PATTERN.findall(normalized)
        compact = f"  {normalized}  "
        features.extend(compact[index : index + 3] for index in range(len(compact) - 2))

        vector = [0.0] * self.dimensions
        for feature in features:
            digest = hashlib.blake2b(feature.encode(), digest_size=8).digest()
            bucket = int.from_bytes(digest[:4], "little") % self.dimensions
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[bucket] += sign

        magnitude = math.sqrt(sum(component * component for component in vector))
        if magnitude:
            return [component / magnitude for component in vector]
        return vector

    def pack(self, text: str) -> bytes:
        """Encode a vector as little-endian FLOAT32 for Redis Query Engine."""

        vector = self.embed(text)
        return struct.pack(f"<{len(vector)}f", *vector)
