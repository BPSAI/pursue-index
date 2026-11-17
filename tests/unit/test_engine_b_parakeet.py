"""The Parakeet second-engine client, with the model mocked (nothing downloads)."""

from __future__ import annotations

import subprocess
import sys
import types
from pathlib import Path

from pursue_index.transcribe import engine_b_parakeet as eb


def test_engine_name_and_revision_are_pinned() -> None:
    assert eb.ENGINE_B_REVISION == "541d1f99c6b0c3cd0b11a95167540bb8edefd82b"
    assert eb.ENGINE_B_NAME == "parakeet-tdt-0.6b-v3@541d1f99"


def test_importing_the_client_does_not_import_torch_or_transformers() -> None:
    code = (
        "import sys; import pursue_index.cli.commands, pursue_index.transcribe.engine_b_parakeet; "
        "print(any(m in sys.modules for m in ('torch', 'transformers')))"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "False"


def _engine(seconds: float, texts: list[str], seen: list) -> eb.ParakeetEngine:
    samples = list(range(int(seconds * eb.SAMPLE_RATE)))

    def chunk_fn(piece):
        seen.append(len(piece))
        return texts[len(seen) - 1]

    frames = int(seconds / eb.FRAME_S)
    return eb.ParakeetEngine(
        chunk_fn, decode=lambda _p: samples, energy=lambda _s: [1.0] * frames,
    )


def test_short_audio_is_one_call() -> None:
    seen: list = []
    engine = _engine(20, ["  hello world  "], seen)
    assert engine(Path("x.mp4")) == "hello world"
    assert seen == [20 * eb.SAMPLE_RATE]


def test_long_audio_is_decoded_in_bounded_chunks_and_stitched() -> None:
    seen: list = []
    engine = _engine(100, ["one two three four", "three four five six"], seen)
    assert engine(Path("x.mp4")) == "one two three four five six"
    assert len(seen) == 2
    assert max(seen) <= 60 * eb.SAMPLE_RATE


def test_loader_uses_the_pinned_revision(monkeypatch) -> None:
    calls = []

    class _Loaded:
        device, dtype = "cpu", "bf16"

        def eval(self):
            return self

        def generate(self, **_kw):
            return types.SimpleNamespace(sequences=[[1, 2]])

    class _Inputs(dict):
        def to(self, *_a, **_k):
            return self

    class _Proc:
        def __call__(self, samples, sampling_rate):
            assert sampling_rate == eb.SAMPLE_RATE
            return _Inputs()

        def decode(self, _seqs, skip_special_tokens):
            return ["decoded text"]

    def _from(kind):
        def load(repo, revision, **kw):
            calls.append((kind, repo, revision))
            return _Proc() if kind == "proc" else _Loaded()
        return load

    fake_tf = types.SimpleNamespace(
        AutoProcessor=types.SimpleNamespace(from_pretrained=_from("proc")),
        AutoModelForTDT=types.SimpleNamespace(from_pretrained=_from("model")),
    )

    class _NoGrad:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    fake_torch = types.SimpleNamespace(bfloat16="bf16", inference_mode=_NoGrad)
    monkeypatch.setitem(sys.modules, "transformers", fake_tf)
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    fn = eb.load_parakeet("cpu")
    assert fn([0.0] * 100) == "decoded text"
    assert calls == [("proc", eb.ENGINE_B_REPO, eb.ENGINE_B_REVISION),
                     ("model", eb.ENGINE_B_REPO, eb.ENGINE_B_REVISION)]


def test_make_engine_wraps_the_loader() -> None:
    engine = eb.make_parakeet_engine("cpu", loader=lambda device: (lambda _s: device))
    assert isinstance(engine, eb.ParakeetEngine)
