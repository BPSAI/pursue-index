"""The second ASR engine for the AUD cross-check: NVIDIA Parakeet TDT 0.6B v3.

A local, open-weights model loaded from a pinned Hugging Face revision with
Transformers, so the comparison reproduces and costs nothing per minute.
``make_parakeet_engine()`` returns a ``SecondEngineFn`` (audio path ->
text) for ``asr_diff_runner.run_row``.

Long-form audio is decoded in bounded chunks cut on pauses
(``engine_b_chunks``): the Transformers port of this model exposes only
full attention (the NeMo toolkit's local-attention mode is not available
there), and its position embeddings cover a few minutes of audio, while the
AUD recordings run past 90 minutes.

Its output is a second opinion, never a correction: the comparison it feeds
reports where two engines differ, not which one is right.

torch, transformers and numpy are imported lazily, only when an engine is
built, so the rest of ``pursue`` runs without them. Install them with the
``asr-b`` extra.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pursue_index import get_logger
from pursue_index.transcribe.engine_b_chunks import Chunk, plan_chunks, stitch

log = get_logger(__name__)

ENGINE_B_REPO = "nvidia/parakeet-tdt-0.6b-v3"
ENGINE_B_REVISION = "541d1f99c6b0c3cd0b11a95167540bb8edefd82b"
#: Recorded as ``engine_b`` in every ``asr_diff.jsonl`` row this engine writes.
ENGINE_B_NAME = f"parakeet-tdt-0.6b-v3@{ENGINE_B_REVISION[:8]}"

SAMPLE_RATE = 16000
FRAME_S = 0.02

#: (audio samples for one chunk) -> that chunk's text.
ChunkFn = Callable[[Any], str]


def decode_audio(path: Path) -> Any:
    """``path`` as 16 kHz mono float32 samples (numpy), via ffmpeg."""
    import numpy as np

    proc = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-i", str(path), "-vn", "-ac", "1",
         "-ar", str(SAMPLE_RATE), "-f", "f32le", "pipe:1"],
        capture_output=True, check=True,
    )
    return np.frombuffer(proc.stdout, dtype=np.float32)


def frame_energy(samples: Any, frame_s: float = FRAME_S) -> list[float]:
    """RMS energy per ``frame_s`` frame (the tail shorter than a frame is dropped)."""
    import numpy as np

    hop = int(frame_s * SAMPLE_RATE)
    n = len(samples) // hop
    if n == 0:
        return [0.0]
    # A float32 view (no copy) and einsum keep a 90-minute file's peak memory low.
    frames = np.asarray(samples[: n * hop], dtype=np.float32).reshape(n, hop)
    return np.sqrt(np.einsum("ij,ij->i", frames, frames, dtype=np.float64) / hop).tolist()


class ParakeetEngine:
    """Audio path -> engine-B text, decoding one pause-cut chunk at a time."""

    def __init__(
        self, transcribe_chunk: ChunkFn, *,
        decode: Callable[[Path], Any] = decode_audio,
        energy: Callable[[Any], list[float]] = frame_energy,
    ) -> None:
        self._transcribe_chunk = transcribe_chunk
        self._decode = decode
        self._energy = energy

    def chunks_for(self, samples: Any) -> list[Chunk]:
        return plan_chunks(self._energy(samples), FRAME_S)

    def __call__(self, audio_path: Path) -> str:
        samples = self._decode(audio_path)
        chunks = self.chunks_for(samples)
        texts = []
        for chunk in chunks:
            a, b = int(chunk.start_s * SAMPLE_RATE), int(chunk.end_s * SAMPLE_RATE)
            piece = samples[a:b]
            texts.append(self._transcribe_chunk(piece).strip() if len(piece) else "")
        log.info("asr_diff.engine_b.decoded", path=audio_path.name, chunks=len(chunks),
                 overlapped=sum(c.overlaps_previous for c in chunks))
        return stitch(texts, chunks)


def load_parakeet(device: str = "cuda") -> ChunkFn:
    """Load the pinned model and return a greedy per-chunk transcriber."""
    import torch
    from transformers import AutoModelForTDT, AutoProcessor

    processor = AutoProcessor.from_pretrained(ENGINE_B_REPO, revision=ENGINE_B_REVISION)
    model = AutoModelForTDT.from_pretrained(
        ENGINE_B_REPO, revision=ENGINE_B_REVISION, dtype=torch.bfloat16, device_map=device,
    ).eval()

    def transcribe_chunk(samples: Any) -> str:
        inputs = processor([samples], sampling_rate=SAMPLE_RATE)
        inputs.to(model.device, dtype=model.dtype)
        with torch.inference_mode():
            out = model.generate(**inputs, return_dict_in_generate=True)
        return str(processor.decode(out.sequences, skip_special_tokens=True)[0])

    return transcribe_chunk


def make_parakeet_engine(
    device: str = "cuda", loader: Callable[[str], ChunkFn] = load_parakeet,
) -> ParakeetEngine:
    """The production ``SecondEngineFn``: Parakeet at the pinned revision."""
    return ParakeetEngine(loader(device))
