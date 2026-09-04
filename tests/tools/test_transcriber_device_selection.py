from pathlib import Path
import sys
from types import SimpleNamespace

from tools.analysis.transcriber import Transcriber


class _Info:
    language = "en"
    duration = 1.0


def test_transcriber_uses_ctranslate2_cuda_without_torch(monkeypatch, tmp_path) -> None:
    devices = []

    class FakeWhisperModel:
        def __init__(self, model_size, *, device, compute_type):
            devices.append((device, compute_type))

        def transcribe(self, *args, **kwargs):
            return iter(()), _Info()

    monkeypatch.setitem(
        sys.modules,
        "faster_whisper",
        SimpleNamespace(WhisperModel=FakeWhisperModel),
    )
    monkeypatch.setitem(
        sys.modules,
        "ctranslate2",
        SimpleNamespace(
            get_cuda_device_count=lambda: 1,
            get_supported_compute_types=lambda device: {"float16", "float32"},
        ),
    )
    input_path = tmp_path / "audio.wav"
    input_path.write_bytes(b"fake")

    result = Transcriber().execute({"input_path": str(input_path), "output_dir": str(tmp_path)})

    assert result.success, result.error
    assert devices == [("cuda", "float16")]
    assert result.data["device"] == "cuda"


def test_transcriber_falls_back_when_cuda_fails_during_iteration(monkeypatch, tmp_path) -> None:
    devices = []

    class FakeWhisperModel:
        def __init__(self, model_size, *, device, compute_type):
            self.device = device
            devices.append((device, compute_type))

        def transcribe(self, *args, **kwargs):
            if self.device == "cuda":
                def broken_iterator():
                    raise RuntimeError("cublas64_12.dll not found")
                    yield

                return broken_iterator(), _Info()
            return iter(()), _Info()

    monkeypatch.setitem(
        sys.modules,
        "faster_whisper",
        SimpleNamespace(WhisperModel=FakeWhisperModel),
    )
    monkeypatch.setitem(
        sys.modules,
        "ctranslate2",
        SimpleNamespace(
            get_cuda_device_count=lambda: 1,
            get_supported_compute_types=lambda device: {"float16"},
        ),
    )
    input_path = tmp_path / "audio.wav"
    input_path.write_bytes(b"fake")

    result = Transcriber().execute({"input_path": str(input_path), "output_dir": str(tmp_path)})

    assert result.success, result.error
    assert devices == [("cuda", "float16"), ("cpu", "int8")]
    assert result.data["device"] == "cpu"
    assert "cublas64_12.dll" in result.data["gpu_fallback_reason"]


def test_transcriber_never_writes_beside_the_source_media(monkeypatch, tmp_path) -> None:
    """The operator's footage pool is a curated folder, not a scratch dir.

    `transcriber` defaulted `output_dir` to the input file's own directory, so
    transcribing a clip in place dropped `<stem>_transcript.json` next to it.
    Same defect and same remedy as beat_grid (#51). Asserted by running with no
    `output_dir` at all — the only way to reach the default.
    """
    class FakeWhisperModel:
        def __init__(self, model_size, *, device, compute_type):
            pass

        def transcribe(self, *args, **kwargs):
            return iter(()), _Info()

    monkeypatch.setitem(
        sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=FakeWhisperModel)
    )
    monkeypatch.setitem(
        sys.modules,
        "ctranslate2",
        SimpleNamespace(
            get_cuda_device_count=lambda: 0,
            get_supported_compute_types=lambda device: {"int8"},
        ),
    )
    pool = tmp_path / "raw"
    pool.mkdir()
    input_path = pool / "IMG_1384.wav"
    input_path.write_bytes(b"fake")

    # Run from a scratch cwd so the relative default lands somewhere disposable
    # rather than in the real repo tree.
    monkeypatch.chdir(tmp_path)
    result = Transcriber().execute({"input_path": str(input_path)})

    assert result.success, result.error
    assert sorted(p.name for p in pool.iterdir()) == ["IMG_1384.wav"], (
        "transcriber wrote into the operator's media folder: "
        f"{sorted(p.name for p in pool.iterdir())}"
    )
    written = Path(result.artifacts[0])
    assert written.is_absolute(), (
        f"the artifact path is relative ({written}) — beat_grid consumes it as "
        "transcript_path and a later stage runs from a different cwd"
    )
    assert written.is_relative_to((tmp_path / "projects" / "_analysis").resolve()), written


def test_vad_filter_defaults_on_but_can_be_turned_off(monkeypatch, tmp_path) -> None:
    """reel-batch's captions come from a music track's own sung words.

    `vad_filter` was hardcoded True, and a VAD scores sung vocals under a bed as
    non-speech: measured on a 186s track with continuous vocals it returned 10
    words at large-v3 with the language forced, and the words it DID return were
    correct — so the model hears the vocal, the VAD discards it. The default
    stays True for every speech caller; the pipeline that needs it off can now
    ask.
    """
    seen: list[bool] = []

    class FakeWhisperModel:
        def __init__(self, model_size, *, device, compute_type):
            pass

        def transcribe(self, *args, **kwargs):
            seen.append(kwargs["vad_filter"])
            return iter(()), _Info()

    monkeypatch.setitem(
        sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=FakeWhisperModel)
    )
    monkeypatch.setitem(
        sys.modules,
        "ctranslate2",
        SimpleNamespace(
            get_cuda_device_count=lambda: 0,
            get_supported_compute_types=lambda device: {"int8"},
        ),
    )
    audio = tmp_path / "track.mp3"
    audio.write_bytes(b"fake")

    Transcriber().execute({"input_path": str(audio), "output_dir": str(tmp_path)})
    Transcriber().execute(
        {"input_path": str(audio), "output_dir": str(tmp_path), "vad_filter": False}
    )

    assert seen == [True, False], (
        f"vad_filter reached faster-whisper as {seen}; it must default True and "
        "be switchable off for sung vocals"
    )
