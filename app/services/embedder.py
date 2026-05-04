"""
Late-chunking ONNX embedder.

Standard fastembed pools the entire chunk independently — each chunk is
embedded as if it exists in a vacuum.  Late chunking instead embeds the
*full page/segment* first (preserving cross-chunk context such as pronoun
references and shared definitions), then extracts per-chunk embeddings by
mean-pooling each chunk's token span.

Fall-back: when a segment exceeds MAX_SEQ_LEN tokens the chunks on that
segment are embedded independently (the standard approach).

Only document ingestion uses late chunking.  Query embedding is standard
mean-pooled embedding (no change to retrieval quality).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

_embedder_instance: "LateChunkingEmbedder | None" = None
_init_attempted = False


def get_embedder() -> "LateChunkingEmbedder | None":
    """Lazy-init singleton; returns None if ONNX/tokenizers unavailable."""
    global _embedder_instance, _init_attempted
    if _init_attempted:
        return _embedder_instance
    _init_attempted = True
    try:
        from app.core.config import settings
        _embedder_instance = LateChunkingEmbedder(settings.embedding_model)
    except Exception:
        logger.exception("late_chunking_embedder_init_failed — falling back to no embeddings")
    return _embedder_instance


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class LateChunkingEmbedder:
    """ONNX-based embedder with late-chunking support for document ingestion."""

    MAX_SEQ_LEN = 512

    def __init__(self, model_name: str) -> None:
        from tokenizers import Tokenizer

        # Pin the fastembed cache to a persistent directory.
        # By default fastembed uses /tmp/fastembed_cache which macOS/Linux
        # clears on reboot, causing "model file not found" errors on restart.
        _pin_cache()

        from fastembed import TextEmbedding

        logger.info("loading_onnx_embedder", extra={"model": model_name})

        # Let fastembed handle download + ONNX initialization entirely.
        # Warm-up call forces the download to complete before we proceed.
        fe = TextEmbedding(model_name=model_name)
        list(fe.embed(["warmup"]))

        # Reuse fastembed's already-loaded internals rather than recomputing paths.
        # fe.model       → OnnxTextEmbedding (fastembed internal)
        # fe.model.model → ort.InferenceSession
        # fe.model.tokenizer → tokenizers.Tokenizer
        inner = getattr(fe, "model", None)
        if inner is None:
            raise RuntimeError(
                f"Cannot access fastembed internals (fe.model not found). "
                f"fastembed attrs: {[a for a in dir(fe) if not a.startswith('_')]}"
            )

        tokenizer = getattr(inner, "tokenizer", None)
        onnx_session = getattr(inner, "model", None)

        if tokenizer is None or onnx_session is None:
            raise RuntimeError(
                f"Unexpected fastembed structure — "
                f"inner.tokenizer={tokenizer!r}, inner.model={onnx_session!r}. "
                f"inner attrs: {[a for a in dir(inner) if not a.startswith('_')]}"
            )

        # Clone tokenizer twice via JSON round-trip so we can configure each
        # independently (padding/truncation settings are mutable per instance).
        tok_json = tokenizer.to_str()

        self._tok = Tokenizer.from_str(tok_json)
        self._tok.enable_padding(pad_id=0, pad_token="[PAD]")
        self._tok.enable_truncation(max_length=self.MAX_SEQ_LEN)

        # Used only to measure token length before committing to late chunking
        self._tok_notrunc = Tokenizer.from_str(tok_json)
        self._tok_notrunc.no_padding()
        self._tok_notrunc.no_truncation()

        self._session = onnx_session
        self._input_names = {inp.name for inp in self._session.get_inputs()}
        # Output 0 is last_hidden_state for all BERT-style models
        self._hidden_output = self._session.get_outputs()[0].name

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def embed_query(self, text: str) -> np.ndarray:
        """Standard mean-pooled embedding for a single query string."""
        enc = self._tok.encode(text)
        hidden = self._run([enc.ids], [enc.attention_mask])  # (1, seq, dim)
        pooled = _mean_pool(hidden, np.array([enc.attention_mask], dtype=np.float32))
        return _normalize(pooled[0])

    def embed_independently(self, texts: list[str]) -> list[np.ndarray]:
        """Embed each text in isolation — standard fallback, no late chunking."""
        results = []
        for text in texts:
            enc = self._tok.encode(text)
            hidden = self._run([enc.ids], [enc.attention_mask])
            pooled = _mean_pool(hidden, np.array([enc.attention_mask], dtype=np.float32))
            results.append(_normalize(pooled[0]))
        return results

    def embed_late(
        self,
        segment_text: str,
        chunk_texts: list[str],
        chunk_char_starts: list[int],
    ) -> list[np.ndarray]:
        """
        Late chunking: embed the full segment_text at token level, then
        extract per-chunk embeddings by pooling each chunk's token span.

        chunk_char_starts[i] is the character offset of chunk_texts[i]
        within segment_text (as returned by langchain with add_start_index=True).

        Falls back to independent embedding when segment exceeds MAX_SEQ_LEN.
        """
        if not chunk_texts:
            return []

        # Measure token length without truncation
        enc_check = self._tok_notrunc.encode(segment_text)
        if len(enc_check.ids) > self.MAX_SEQ_LEN:
            logger.debug(
                "late_chunk_fallback_segment_too_long",
                extra={"tokens": len(enc_check.ids), "max": self.MAX_SEQ_LEN},
            )
            return self.embed_independently(chunk_texts)

        # Run the full segment through the model
        enc = self._tok_notrunc.encode(segment_text)
        hidden = self._run([enc.ids], [enc.attention_mask])  # (1, seq, dim)
        token_hidden = hidden[0]  # (seq, dim)
        offsets = enc.offsets   # list of (char_start, char_end) per token

        results: list[np.ndarray] = []
        for chunk_text, char_start in zip(chunk_texts, chunk_char_starts):
            char_end = char_start + len(chunk_text)

            # Tokens that overlap [char_start, char_end).
            # Special tokens ([CLS], [SEP]) have offset (0, 0) — ts == te == 0 → skipped.
            token_indices = [
                i for i, (ts, te) in enumerate(offsets)
                if ts < te and ts < char_end and te > char_start
            ]

            if not token_indices:
                # Chunk position not found in token offsets — embed independently
                emb = self.embed_independently([chunk_text])[0]
            else:
                span = token_hidden[token_indices, :].mean(axis=0).astype(np.float32)
                emb = _normalize(span)

            results.append(emb)

        return results

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run(self, ids_batch: list, mask_batch: list) -> np.ndarray:
        """Run ONNX session; returns last_hidden_state (batch, seq, dim)."""
        inputs: dict[str, np.ndarray] = {
            "input_ids": np.array(ids_batch, dtype=np.int64),
            "attention_mask": np.array(mask_batch, dtype=np.int64),
        }
        if "token_type_ids" in self._input_names:
            inputs["token_type_ids"] = np.zeros_like(inputs["input_ids"])
        outputs = self._session.run([self._hidden_output], inputs)
        return outputs[0]


# ---------------------------------------------------------------------------
# Module helpers
# ---------------------------------------------------------------------------

def _pin_cache() -> None:
    """Set FASTEMBED_CACHE_PATH to a persistent directory if not already set.

    fastembed defaults to /tmp/fastembed_cache (or equivalent) which the OS
    clears on reboot.  Pinning to ~/.cache/fastembed means the model survives
    restarts and only downloads once.
    """
    persistent = str(Path.home() / ".cache" / "fastembed")
    os.environ.setdefault("FASTEMBED_CACHE_PATH", persistent)


def _mean_pool(hidden: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Attention-mask-weighted mean pooling: (batch, seq, dim) → (batch, dim)."""
    mask_f = mask[:, :, np.newaxis]
    return (hidden * mask_f).sum(axis=1) / mask_f.sum(axis=1).clip(min=1e-9)


def _normalize(v: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(v)
    return (v / norm) if norm > 1e-9 else v
