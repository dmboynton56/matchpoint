"""
embedding_matrix.py — owns the (matrix, ids) artifact used to back `vector_search`
on the hot path.

Layout on disk (and on the data-cache branch):
    matrix.npy        — float32 ndarray of shape (N, 1536), L2-normalized per row
    matrix_ids.json   — JSON list of N job_id strings, index-aligned with matrix rows

This module is pure: it does no I/O itself, just encode/decode/validate. Callers
(pipeline write path, read path with source=local, tests) own the bytes.

The 1536-dim assumption is hard-coded because the embedding model is fixed
(text-embedding-3-small). If we ever swap models, change EMBEDDING_DIM and
re-validate the on-disk format.
"""

from __future__ import annotations

import io
import json
import math
from typing import Any

import numpy as np

EMBEDDING_DIM = 1536
MATRIX_FILENAME = "matrix.npy"
IDS_FILENAME = "matrix_ids.json"


class EmbeddingMatrixError(ValueError):
    """Raised when a matrix+ids payload fails validation. Read path should
    treat this as a signal to fall back to the Turso SELECT path."""


def _validate_matrix_array(matrix: np.ndarray) -> np.ndarray:
    if not isinstance(matrix, np.ndarray):
        raise EmbeddingMatrixError(
            f"matrix must be a numpy ndarray, got {type(matrix).__name__}"
        )
    if matrix.ndim != 2:
        raise EmbeddingMatrixError(
            f"matrix must be 2D, got {matrix.ndim}D with shape {matrix.shape}"
        )
    if matrix.shape[1] != EMBEDDING_DIM:
        raise EmbeddingMatrixError(
            f"matrix second dim must be {EMBEDDING_DIM}, got {matrix.shape[1]}"
        )
    if matrix.dtype != np.float32:
        raise EmbeddingMatrixError(
            f"matrix must be float32, got {matrix.dtype}"
        )
    if not np.all(np.isfinite(matrix)):
        raise EmbeddingMatrixError("matrix contains NaN or Inf values")
    return matrix


def _validate_ids(ids: Any, n_rows: int) -> list[str]:
    if not isinstance(ids, list):
        raise EmbeddingMatrixError(
            f"ids must be a JSON list, got {type(ids).__name__}"
        )
    if len(ids) != n_rows:
        raise EmbeddingMatrixError(
            f"ids length {len(ids)} does not match matrix rows {n_rows}"
        )
    out: list[str] = []
    seen: set[str] = set()
    for i, item in enumerate(ids):
        if not isinstance(item, str):
            raise EmbeddingMatrixError(
                f"ids[{i}] must be a string, got {type(item).__name__}"
            )
        if not item:
            raise EmbeddingMatrixError(f"ids[{i}] is empty")
        if item in seen:
            raise EmbeddingMatrixError(f"ids[{i}]='{item}' is duplicated")
        seen.add(item)
        out.append(item)
    return out


def normalize_rows(matrix: np.ndarray) -> np.ndarray:
    """L2-normalize each row in-place-safe (returns a new array if input
    is not float32). After this, M @ q is equivalent to cosine similarity
    as long as q is also unit-normalized.
    """
    matrix = _validate_matrix_array(matrix)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    # Guard against zero-norm rows (shouldn't happen for real embeddings,
    # but the validator above already caught NaN/Inf so this is the only
    # remaining edge case).
    safe_norms = np.where(norms == 0, 1.0, norms)
    return (matrix / safe_norms).astype(np.float32, copy=False)


def encode(
    job_ids: list[str],
    embeddings: list[list[float]],
) -> tuple[bytes, bytes]:
    """Build (matrix_bytes, ids_bytes) ready to write to disk or upload.

    Validates inputs, stacks embeddings into a (N, 1536) float32 array,
    L2-normalizes per row, and serializes both artifacts. Raises
    EmbeddingMatrixError on any validation failure.
    """
    if len(job_ids) != len(embeddings):
        raise EmbeddingMatrixError(
            f"job_ids length {len(job_ids)} != embeddings length {len(embeddings)}"
        )
    if not job_ids:
        raise EmbeddingMatrixError("cannot encode empty matrix (0 jobs)")

    # Build the array. From-list is fine here (one-time per day).
    matrix = np.asarray(embeddings, dtype=np.float32)
    matrix = _validate_matrix_array(matrix)
    # Cross-check with the ids list — this catches shape mismatches
    # before the more expensive validation in _validate_ids.
    if matrix.shape[0] != len(job_ids):
        raise EmbeddingMatrixError(
            f"matrix rows {matrix.shape[0]} != job_ids length {len(job_ids)}"
        )
    ids = _validate_ids(job_ids, matrix.shape[0])

    normalized = normalize_rows(matrix)

    matrix_buf = io.BytesIO()
    np.save(matrix_buf, normalized, allow_pickle=False)
    matrix_bytes = matrix_buf.getvalue()

    ids_bytes = json.dumps(ids, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )

    return matrix_bytes, ids_bytes


def decode(matrix_bytes: bytes, ids_bytes: bytes) -> tuple[np.ndarray, list[str]]:
    """Inverse of encode. Validates everything; raises EmbeddingMatrixError
    on any mismatch. Read path catches and falls back to Turso."""
    try:
        matrix = np.load(io.BytesIO(matrix_bytes), allow_pickle=False)
    except Exception as exc:
        raise EmbeddingMatrixError(f"failed to load matrix.npy: {exc}") from exc
    matrix = _validate_matrix_array(matrix)

    try:
        ids_raw = json.loads(ids_bytes.decode("utf-8"))
    except Exception as exc:
        raise EmbeddingMatrixError(f"failed to parse matrix_ids.json: {exc}") from exc
    ids = _validate_ids(ids_raw, matrix.shape[0])

    return matrix, ids


def cos_scores(matrix: np.ndarray, query: np.ndarray) -> np.ndarray:
    """Compute cosine similarity for `query` against every row of `matrix`.

    Assumes matrix is already L2-normalized (encode() guarantees this) and
    query is also unit-normalized. Returns shape (N,) float32 array.
    """
    if query.ndim != 1:
        raise EmbeddingMatrixError(
            f"query must be 1D, got shape {query.shape}"
        )
    if query.shape[0] != matrix.shape[1]:
        raise EmbeddingMatrixError(
            f"query dim {query.shape[0]} != matrix dim {matrix.shape[1]}"
        )
    if matrix.dtype != np.float32:
        raise EmbeddingMatrixError(
            f"matrix must be float32 for cos_scores, got {matrix.dtype}"
        )
    q = query.astype(np.float32, copy=False)
    q_norm = np.linalg.norm(q)
    if q_norm == 0 or not math.isfinite(float(q_norm)):
        raise EmbeddingMatrixError("query has zero or non-finite norm")
    q = q / q_norm
    return matrix @ q


def top_k_ids(
    matrix: np.ndarray,
    ids: list[str],
    query: list[float],
    k: int,
) -> list[tuple[str, float]]:
    """Return the top-k (job_id, similarity) pairs by cosine similarity,
    descending. Ties broken by original index (stable)."""
    if k <= 0:
        return []
    if k >= len(ids):
        # argpartition with k >= n is undefined; just sort everything.
        scores = cos_scores(matrix, np.asarray(query, dtype=np.float32))
        order = np.argsort(-scores, kind="stable")
        return [(ids[int(i)], float(scores[int(i)])) for i in order]

    scores = cos_scores(matrix, np.asarray(query, dtype=np.float32))
    # argpartition is O(n); we only sort the top-k afterward.
    cand = np.argpartition(-scores, k)[:k]
    cand = cand[np.argsort(-scores[cand], kind="stable")]
    return [(ids[int(i)], float(scores[int(i)])) for i in cand]


__all__ = [
    "EMBEDDING_DIM",
    "MATRIX_FILENAME",
    "IDS_FILENAME",
    "EmbeddingMatrixError",
    "encode",
    "decode",
    "normalize_rows",
    "cos_scores",
    "top_k_ids",
]
