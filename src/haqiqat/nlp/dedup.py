"""Near-duplicate detection with MinHash over word shingles.

Syndicated wire copy and republished agency stories are near-identical text. They must
collapse onto the original article so that fifty copies of one report never count as
fifty confirmations.
"""

from __future__ import annotations

import hashlib

import numpy as np

from .normalize import tokens

NUM_PERM = 64
_MERSENNE = np.uint64((1 << 61) - 1)
_MAX = np.uint64((1 << 32) - 1)

_rng = np.random.default_rng(20240601)
_A = _rng.integers(1, (1 << 31) - 1, size=NUM_PERM, dtype=np.uint64)
_B = _rng.integers(0, (1 << 31) - 1, size=NUM_PERM, dtype=np.uint64)


def _shingles(text: str, k: int = 3) -> set[int]:
    toks = tokens(text)
    if len(toks) < k:
        grams = [" ".join(toks)] if toks else []
    else:
        grams = [" ".join(toks[i : i + k]) for i in range(len(toks) - k + 1)]
    return {
        int.from_bytes(hashlib.blake2b(g.encode(), digest_size=4).digest(), "little")
        for g in grams
    }


def signature(text: str) -> np.ndarray:
    sh = _shingles(text)
    if not sh:
        return np.full(NUM_PERM, _MAX, dtype=np.uint32)
    x = np.fromiter(sh, dtype=np.uint64)
    # (a*x + b) mod p, truncated to 32 bits; min over shingles for each permutation.
    h = ((np.outer(_A, x) + _B[:, None]) % _MERSENNE) & _MAX
    return h.min(axis=1).astype(np.uint32)


def similarity(sig_a: np.ndarray, sig_b: np.ndarray) -> float:
    return float(np.mean(sig_a == sig_b))


def best_match(sig: np.ndarray, candidates: np.ndarray) -> tuple[int, float]:
    """Index and estimated Jaccard of the closest candidate signature (rows)."""
    if len(candidates) == 0:
        return -1, 0.0
    sims = (candidates == sig).mean(axis=1)
    i = int(np.argmax(sims))
    return i, float(sims[i])


def to_blob(sig: np.ndarray) -> bytes:
    return sig.astype(np.uint32).tobytes()


def from_blob(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.uint32)
