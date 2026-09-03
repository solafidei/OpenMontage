"""Tests for the `beat_grid` tool — the wrapper around the repo's only beat analyser.

Three things are policed here:

  1. The wrapper adds **no drift**. On an instrumental track it must return
     exactly what `analyze-beatgrid.py` returns when run directly, because the
     music-to-video skill forbids a rival detector (`SKILL.md:18`, `:49`).
  2. The speech contamination is **measured**, not estimated — the counts move
     with the word list they are cross-checked against.
  3. The de-voiced proxy **reduces roll false-positives** against the raw mix.
     The assertion is on roll SECONDS inside speech, not roll count: de-voicing
     typically fragments one bogus sustained fill into several short ones, so
     the count can rise while the damage falls.

The synthetic track is a 120 BPM percussive bed (60 Hz kick on the beat, a
noise hat on the off-beat) with a band-limited "voice" — 300 / 700 / 2500 Hz,
~5.2 syllables per second with a 15 ms attack — laid over the middle ten
seconds only, so speech covers about half the timeline and contamination can
be told apart from chance.
"""

from __future__ import annotations

import importlib.util
import json
import math
import shutil
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from tools.analysis.beat_grid import BeatGrid  # noqa: E402
from tools.base_tool import ToolStatus  # noqa: E402

ANALYZER = (
    PROJECT_ROOT / ".agents" / "skills" / "music-to-video" / "scripts" / "analyze-beatgrid.py"
)
SR = 22050
DURATION = 20.0
SPEECH_START, SPEECH_END = 4.0, 14.0
SYLLABLE_RATE = 5.2

needs_deps = pytest.mark.skipif(
    shutil.which("ffmpeg") is None
    or shutil.which("ffprobe") is None
    or importlib.util.find_spec("librosa") is None
    or importlib.util.find_spec("soundfile") is None,
    reason="beat_grid needs ffmpeg/ffprobe plus librosa and soundfile",
)


# ----------------------------------------------------------------------
# synthetic audio
# ----------------------------------------------------------------------
def _render(with_speech: bool) -> np.ndarray:
    n = int(DURATION * SR)
    y = np.zeros(n)

    # percussive bed: kick every 0.5s (120 BPM) + a hat on the off-beat
    length = int(0.25 * SR)
    tt = np.arange(length) / SR
    for i in range(int(DURATION / 0.5)):
        kick = int(i * 0.5 * SR)
        y[kick:kick + length] += 0.6 * np.sin(2 * np.pi * 60 * tt) * np.exp(-22 * tt)
        hat = kick + length
        if hat + length < n:
            noise = np.random.default_rng(i).standard_normal(length) * np.exp(-70 * tt)
            y[hat:hat + length] += 0.15 * np.diff(noise, prepend=0.0)

    if with_speech:
        length = int(0.16 * SR)
        tt = np.arange(length) / SR
        env = (1 - np.exp(-tt / 0.015)) * np.exp(-tt / 0.05)
        # Formants sit INSIDE the ducked bands but deliberately off their
        # bell centres (300/700/2500), and each is noise-excited rather than a
        # pure tone — otherwise the test would only prove that a notch cancels
        # a matched sinusoid, which is not the claim being made.
        rng = np.random.default_rng(7)
        excitation = rng.standard_normal(length) * 0.35
        carrier = np.zeros(length)
        for freq, gain, bw in ((215.0, 1.0, 45.0), (780.0, 0.8, 110.0), (2260.0, 0.5, 320.0)):
            phase = 2 * np.pi * freq * tt
            jitter = np.cumsum(excitation) * (bw / SR)
            carrier += gain * np.sin(phase + jitter)
        for t in _syllable_times():
            s = int(t * SR)
            if s + length >= n:
                break
            y[s:s + length] += (0.7 + 0.08 * math.sin(t)) * env * carrier

    return y / (np.abs(y).max() + 1e-9) * 0.9


def _syllable_times() -> list[float]:
    step = 1 / SYLLABLE_RATE
    count = int((SPEECH_END - SPEECH_START) / step)
    return [SPEECH_START + i * step for i in range(count)]


def _words() -> list[dict]:
    """Group the syllables into three-syllable words, transcriber-shaped."""
    times = _syllable_times()
    return [
        {"word": f"w{i // 3}", "start": round(times[i], 3), "end": round(times[i + 2] + 0.16, 3)}
        for i in range(0, len(times) - 2, 3)
    ]


def _write_wav(path: Path, samples: np.ndarray) -> None:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SR)
        handle.writeframes((np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())


@pytest.fixture(scope="module")
def music_only(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("music") / "bed.wav"
    _write_wav(path, _render(with_speech=False))
    return path


@pytest.fixture(scope="module")
def speech_over_music(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("speech") / "vo.wav"
    _write_wav(path, _render(with_speech=True))
    return path


@pytest.fixture(scope="module")
def speech_result(speech_over_music) -> dict:
    """One run with the de-voiced comparison on — shared by the contamination tests."""
    result = BeatGrid().execute(
        {
            "input_path": str(speech_over_music),
            "devoice": True,
            "word_timestamps": _words(),
        }
    )
    assert result.success, result.error
    return result.data


# ----------------------------------------------------------------------
# metadata and degradation — no heavy deps needed
# ----------------------------------------------------------------------
def test_estimate_cost_is_zero() -> None:
    assert BeatGrid().estimate_cost({"input_path": "anything.wav"}) == 0.0


def test_declares_every_dependency_it_actually_uses() -> None:
    """face_tracker.py:39 under-declares and preflight lies about it. Not here."""
    assert set(BeatGrid.dependencies) >= {
        "binary:ffmpeg",
        "python:librosa",
        "python:soundfile",
    }


def test_status_degrades_when_a_python_dep_is_missing(monkeypatch) -> None:
    real = importlib.util.find_spec
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        lambda name, *a, **k: None if name == "librosa" else real(name, *a, **k),
    )
    assert BeatGrid().get_status() is ToolStatus.UNAVAILABLE


def test_status_degrades_when_ffmpeg_is_missing(monkeypatch) -> None:
    monkeypatch.setattr(
        "tools.analysis.beat_grid.shutil.which",
        lambda name: None if name == "ffmpeg" else "/usr/bin/" + name,
    )
    assert BeatGrid().get_status() is ToolStatus.UNAVAILABLE


def test_discoverable_in_the_registry() -> None:
    from tools.tool_registry import registry

    registry.discover()
    assert "beat_grid" in registry._tools


@needs_deps
def test_status_available_when_deps_are_installed() -> None:
    assert BeatGrid().get_status() is ToolStatus.AVAILABLE


# ----------------------------------------------------------------------
# behaviour
# ----------------------------------------------------------------------
@needs_deps
def test_rejects_input_with_no_audio_stream(tmp_path) -> None:
    silent = tmp_path / "silent.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=black:s=64x64:d=1", str(silent)],
        capture_output=True, check=True, timeout=60,
    )

    result = BeatGrid().execute({"input_path": str(silent)})

    assert not result.success
    assert "No audio stream" in result.error


@needs_deps
def test_wrapper_reproduces_the_analyser_exactly(music_only, tmp_path) -> None:
    """No drift: on instrumental audio the wrapper is the analyser, verbatim."""
    direct = tmp_path / "direct.json"
    subprocess.run(
        [sys.executable, str(ANALYZER), str(music_only), "-o", str(direct)],
        capture_output=True, check=True, timeout=300,
    )
    expected = json.loads(direct.read_text(encoding="utf-8"))

    result = BeatGrid().execute({"input_path": str(music_only), "devoice": False})

    assert result.success, result.error
    assert result.data["bpm"] == expected["tempo"]["bpm"]
    assert result.data["grid"]["beats_sec"] == expected["grid"]["beats_sec"]
    assert result.data["rolls"] == expected["rolls"]
    assert result.data["phrases"] == expected["phrases"]


@needs_deps
def test_speech_contamination_is_measured(speech_result) -> None:
    speech = speech_result["speech"]

    assert speech["words_checked"] == len(_words())
    assert speech["events_in_speech"] > 0
    assert speech["events_total"] > speech["events_in_speech"], (
        "the music-only half of the track must contribute events too"
    )
    # Speech covers about half the timeline; if the voice were merely
    # coinciding with the grid, enrichment would sit near 1.0.
    assert 30 < speech["speech_coverage_pct"] < 70
    assert speech["enrichment_over_coverage"] > 1.0
    # The voice lands in the analyser's snare band (analyze-beatgrid.py:79).
    assert speech["events_in_speech_by_drum"]
    assert speech["rolls_overlapping_speech"] > 0
    assert speech["roll_seconds_in_speech"] > 0

    levels = speech["words"]
    assert len(levels) == len(_words())
    assert all(row["peak_rms"] > 0 for row in levels)


@needs_deps
def test_devoiced_proxy_reduces_roll_false_positives(speech_result) -> None:
    """Direction, not a magic number: the proxy must cut speech-borne rolls."""
    raw = speech_result["speech"]
    proxy = speech_result["proxy_comparison"]["speech"]

    assert raw["roll_seconds_in_speech"] > 0, "fixture must contaminate the raw mix"
    assert proxy["roll_seconds_in_speech"] < raw["roll_seconds_in_speech"]
    assert proxy["events_in_speech"] < raw["events_in_speech"]
    assert Path(speech_result["proxy_path"]).exists()
    assert Path(speech_result["proxy_comparison"]["audiomap_path"]).exists()


@needs_deps
def test_contamination_counts_track_the_word_list(music_only) -> None:
    """The numbers come from the two inputs — they are not a constant."""
    tool = BeatGrid()
    audiomap = {
        "audio": {"duration_sec": 20.0},
        "events": [{"t": t, "drum": "snare"} for t in (1.0, 5.0, 5.5, 9.0)],
        "rolls": [{"start": 5.0, "end": 6.0, "hits": 4, "drum": "snare", "kind": "fill"}],
    }
    inputs = {"speech_pad_seconds": 0.0}

    inside = tool._speech_report(
        audiomap, [{"word": "a", "start": 4.5, "end": 6.0}], music_only, inputs
    )
    elsewhere = tool._speech_report(
        audiomap, [{"word": "a", "start": 15.0, "end": 16.5}], music_only, inputs
    )

    assert inside["events_in_speech"] == 2
    assert inside["events_in_speech_by_drum"] == {"snare": 2}
    assert inside["roll_seconds_in_speech"] == pytest.approx(1.0)
    assert inside["rolls_majority_speech"] == 1
    assert elsewhere["events_in_speech"] == 0
    assert elsewhere["roll_seconds_in_speech"] == 0
    assert elsewhere["rolls_majority_speech"] == 0


@needs_deps
def test_canonical_grid_comes_from_the_raw_mix(music_only) -> None:
    """The proxy may never answer the tempo question.

    De-voicing scoops 300-2500 Hz, which is also the analyser's own snare band
    (analyze-beatgrid.py:79). On a track with no speech that invents a
    confident tempo where the analyser honestly reported none — the exact
    failure this tool exists to prevent. So the headline grid must match the
    analyser run on the untouched input, with de-voicing on or off.
    """
    tool = BeatGrid()
    with_devoice = tool.execute({"input_path": str(music_only), "devoice": True})
    without = tool.execute({"input_path": str(music_only), "devoice": False})
    assert with_devoice.success and without.success

    for field in ("bpm", "n_beats", "n_bars", "n_phrases", "summary"):
        assert with_devoice.data[field] == without.data[field], (
            f"{field} moved when de-voicing was enabled — the proxy has "
            "leaked into the canonical grid"
        )
    assert with_devoice.data["analysed_path"] == str(music_only)
    # The proxy is still produced, just demoted to a diagnostic.
    assert with_devoice.data["proxy_comparison"] is not None
    assert without.data["proxy_comparison"] is None
