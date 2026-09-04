"""Beat grid + measured speech contamination for footage cut to music.

Wraps the repo's ONLY beat analyser — `.agents/skills/music-to-video/scripts/
analyze-beatgrid.py` — verbatim through its documented CLI. This tool never
re-measures tempo, beats, onsets or rolls itself: the music-to-video skill
states the analyser is the single source of timing truth and must not be
second-guessed (`SKILL.md:18`, `:49`). Everything here is around it, not
inside it.

Two things it adds:

  1. A **de-voiced percussive proxy**. The analyser was built for instrumental
     BGM. A spoken voice lands squarely in its snare band (150-900 Hz,
     `analyze-beatgrid.py:79`), and `detect_rolls` accepts any run of >=4
     onsets whose mean spacing is under `0.42 x beat_dur` (`:227`) — ordinary
     speech at ~5 syllables/sec reads as one sustained fill. One ffmpeg EQ
     chain ducks the speech fundamental / first formant / presence bands while
     leaving the kick (<150 Hz) and hats (>6 kHz) the drum typing needs.
  2. A **measured** speech-contamination cross-check against `transcriber`
     word timestamps: how many `events[]` and how much of `rolls[]` actually
     land inside speech, plus a per-word `peak_rms` of the audio that was
     analysed. Nothing is estimated and nothing is a constant — this is the
     evidence a director downgrades a grid on, instead of downgrading on vibes.

The trust call itself (beat-cut vs phrase-pace) stays with the agent. This
tool only reports numbers.
"""

from __future__ import annotations

import bisect
import importlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

from tools.analysis.audio_probe import AudioProbe
from tools.base_tool import (
    BaseTool,
    Determinism,
    ExecutionMode,
    ResourceProfile,
    RetryPolicy,
    ToolResult,
    ToolRuntime,
    ToolStability,
    ToolStatus,
    ToolTier,
)

# tools/analysis/beat_grid.py -> parents[2] is the repo root
_REPO_ROOT = Path(__file__).resolve().parents[2]
_ANALYZER = (
    _REPO_ROOT / ".agents" / "skills" / "music-to-video" / "scripts" / "analyze-beatgrid.py"
)

# One EQ chain, three bells on the bands a spoken voice lives in: fundamental
# (~300 Hz), first formant (~700 Hz), presence/consonants (~2.5 kHz). Measured
# response: 60 Hz -0.6 dB, 150 Hz -4.2 dB, 300 Hz -22 dB, 700 Hz -23 dB,
# 2.5 kHz -18 dB, 6 kHz -1.9 dB — so the kick and the hats the analyser types
# drums from survive while the syllable transients that fake a roll do not.
_DEVOICE_CHAIN = (
    "equalizer=f=300:t=o:w=0.8:g=-18,"
    "equalizer=f=700:t=o:w=1.0:g=-20,"
    "equalizer=f=2500:t=o:w=1.0:g=-16"
)
_PROXY_SR = 22050  # the analyser's own working rate (analyze-beatgrid.py:35)
_RMS_FRAME = 0.02  # seconds — peak_rms is the loudest 20 ms inside a word

# Answers of the real `import`, kept for the life of the process. See
# _importable() for why the import has to be real and why the cache is here.
_IMPORT_PROBE: dict[str, bool] = {}


def _importable(module: str) -> bool:
    """Can this module actually be imported, not merely located?

    find_spec only proves the module is INSTALLED. The common librosa failure
    is installed-but-unimportable — a numba/llvmlite/numpy ABI mismatch — where
    the spec is found, preflight reports the dependency satisfied, and the
    failure resurfaces much later as an opaque "analyze-beatgrid.py failed:
    ..." out of the subprocess, pointing at the analyser instead of at the
    broken install. So the probe imports.

    The original concern was real: librosa costs seconds to import and
    get_status() runs for every tool at preflight. Hence the cache — the import
    is paid at most once per process, and every later get_status() is a dict
    lookup. Any exception counts as unimportable: a half-built native extension
    raises plenty of things that are not ImportError.
    """
    if module not in _IMPORT_PROBE:
        try:
            importlib.import_module(module)
        except Exception:
            _IMPORT_PROBE[module] = False
        else:
            _IMPORT_PROBE[module] = True
    return _IMPORT_PROBE[module]


class BeatGrid(BaseTool):
    name = "beat_grid"
    version = "0.1.0"
    tier = ToolTier.CORE
    capability = "analysis"
    provider = "librosa"
    stability = ToolStability.PRODUCTION
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC
    runtime = ToolRuntime.LOCAL

    # All of them. Under-declaring is how face_tracker.py:39 ends up reported
    # as satisfied by preflight and then raising on import inside execute().
    dependencies = [
        "binary:ffmpeg",
        "binary:ffprobe",
        "python:librosa",
        "python:soundfile",
    ]
    install_instructions = (
        "Install ffmpeg and the analyser's Python deps:\n"
        "  Windows: winget install ffmpeg\n"
        "  macOS: brew install ffmpeg\n"
        "  Linux: sudo apt install ffmpeg\n"
        "  All:   pip install librosa soundfile"
    )

    agent_skills = ["music-to-video"]

    capabilities = [
        "beat_grid",
        "audiomap",
        "devoiced_percussive_proxy",
        "speech_contamination",
    ]
    best_for = [
        "getting a trustworthy beat grid off a track that has a voice over it",
        "measuring how much of a beat grid is actually speech before cutting to it",
        "deciding beat-cutting vs phrase-pacing on evidence",
    ]

    input_schema = {
        "type": "object",
        "required": ["input_path"],
        "properties": {
            "input_path": {
                "type": "string",
                "description": "Path to the audio (or video) file to analyse",
            },
            "output_dir": {
                "type": "string",
                "description": "Directory for the audiomap JSON and the proxy WAV "
                "(default: projects/_analysis/beat_grid_<stem>, never beside the "
                "input file)",
            },
            "devoice": {
                "type": "boolean",
                "description": "Also analyse a de-voiced percussive proxy and report the "
                "delta under proxy_comparison, so how much the voice is disturbing the "
                "grid is measured rather than guessed. The canonical grid always comes "
                "from the raw mix. Doubles the runtime; turn off for pure BGM.",
                "default": True,
            },
            "phrase_bars": {
                "type": "integer",
                "description": "Bars per phrase, passed straight to the analyser",
                "default": 4,
            },
            "word_timestamps": {
                "type": "array",
                "description": "Word timestamps from `transcriber` "
                "([{word, start, end}, ...]) for the speech cross-check",
            },
            "transcript_path": {
                "type": "string",
                "description": "Path to a `transcriber` transcript JSON — an "
                "alternative to passing word_timestamps inline",
            },
            "speech_pad_seconds": {
                "type": "number",
                "description": "Padding applied around each word before counting an "
                "event as speech-borne (default: 0.1)",
                "default": 0.1,
            },
        },
    }

    output_schema = {
        "type": "object",
        "properties": {
            "audiomap_path": {"type": "string"},
            "summary": {"type": "string"},
            "bpm": {"type": "number"},
            "tempo": {"type": "object"},
            "grid": {"type": "object"},
            "phrases": {"type": "array"},
            "rolls": {"type": "array"},
            "speech": {"type": "object"},
            "speech_warning": {"type": ["string", "null"]},
            "proxy_comparison": {"type": "object"},
        },
    }

    resource_profile = ResourceProfile(
        cpu_cores=2, ram_mb=1024, vram_mb=0, disk_mb=100, network_required=False
    )
    retry_policy = RetryPolicy(max_retries=0, retryable_errors=[])
    idempotency_key_fields = ["input_path", "devoice", "phrase_bars"]
    side_effects = ["writes audiomap JSON and a de-voiced proxy WAV to output_dir"]
    user_visible_verification = [
        "Check bpm against tapping along to the track",
        "Check the speech contamination percentage before trusting the grid",
    ]

    def get_status(self) -> ToolStatus:
        for binary in ("ffmpeg", "ffprobe"):
            if not shutil.which(binary):
                return ToolStatus.UNAVAILABLE
        for module in ("librosa", "soundfile"):
            if not _importable(module):
                return ToolStatus.UNAVAILABLE
        if not _ANALYZER.exists():
            return ToolStatus.UNAVAILABLE
        return ToolStatus.AVAILABLE

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        return 0.0

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        input_path = Path(inputs["input_path"])
        if not input_path.exists():
            return ToolResult(success=False, error=f"File not found: {input_path}")
        if self.get_status() != ToolStatus.AVAILABLE:
            return ToolResult(
                success=False,
                error=f"beat_grid dependencies missing. {self.install_instructions}",
            )

        start = time.time()

        # --------------------------------------------------------------
        # Step 1: gate the input through audio_probe
        # --------------------------------------------------------------
        probe = AudioProbe().execute({"input_path": str(input_path)})
        if not probe.success:
            return ToolResult(success=False, error=f"audio_probe rejected input: {probe.error}")
        if not probe.data.get("audio"):
            return ToolResult(
                success=False, error=f"No audio stream in {input_path.name} — nothing to analyse"
            )
        duration = float(probe.data.get("duration_seconds") or 0.0)
        if duration <= 0:
            return ToolResult(success=False, error=f"Zero-length audio: {input_path.name}")

        stem = input_path.stem
        # Never default INTO the operator's media folder. input_path is normally
        # someone's project asset or source track, and defaulting to its parent
        # dropped <stem>_devoiced.wav, <stem>_audiomap.json and
        # <stem>_audiomap_devoiced.json next to their footage. Every caller in
        # the repo passes an explicit output_dir already (the reel-batch
        # script-director hands us "projects/<id>/analysis"), so this default
        # only ever catches ad-hoc runs — and the tool is not told a project id,
        # so it uses the same unowned-analysis workspace video_analyzer.py:158
        # uses. Keyed by stem rather than a timestamp because this tool is
        # DETERMINISTIC and keyed on input_path: re-running the same track must
        # land on the same audiomap, not accumulate a new directory per run.
        output_dir = (
            Path(inputs["output_dir"])
            if inputs.get("output_dir")
            else Path("projects") / "_analysis" / f"beat_grid_{stem}"
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        devoice = inputs.get("devoice", True)
        phrase_bars = int(inputs.get("phrase_bars", 4))

        words, words_error, words_warning = self._load_words(inputs)
        if words_error:
            return ToolResult(success=False, error=words_error)

        artifacts: list[str] = []

        # --------------------------------------------------------------
        # Step 2: de-voiced percussive proxy
        # --------------------------------------------------------------
        proxy_path: Path | None = None
        if devoice:
            proxy_path = output_dir / f"{stem}_devoiced.wav"
            error = self._write_proxy(input_path, proxy_path, duration)
            if error:
                return ToolResult(success=False, error=error)
            artifacts.append(str(proxy_path))

        # --------------------------------------------------------------
        # Step 3: the analyser, verbatim, through its documented CLI.
        #
        # The canonical grid ALWAYS comes from the raw mix. De-voicing is a
        # diagnostic, never the source of tempo/beats/phrases: the EQ chain
        # scoops 300-2500 Hz, which is also the analyser's own snare band
        # (analyze-beatgrid.py:79), so on a track with no speech the proxy
        # invents a confident tempo where the analyser honestly reported
        # none. Manufacturing that confidence is the exact failure this tool
        # exists to prevent, so the proxy is not allowed to answer the
        # question -- only to say how much the voice is disturbing it.
        # --------------------------------------------------------------
        audiomap_path = output_dir / f"{stem}_audiomap.json"
        audiomap, error = self._run_analyzer(input_path, audiomap_path, phrase_bars, duration)
        if error:
            return ToolResult(success=False, error=error)
        artifacts.append(str(audiomap_path))

        # --------------------------------------------------------------
        # Step 4: measured speech cross-check against the canonical grid
        # --------------------------------------------------------------
        speech = self._speech_report(audiomap, words, input_path, inputs) if words else None

        data: dict[str, Any] = {
            "audiomap_path": str(audiomap_path),
            "proxy_path": str(proxy_path) if proxy_path else None,
            "devoiced": bool(devoice),
            "analysed_path": str(input_path),
            **self._headline(audiomap),
            "phrases": audiomap.get("phrases", []),
            "rolls": audiomap.get("rolls", []),
            "tempo": audiomap.get("tempo", {}),
            "grid": audiomap.get("grid", {}),
            "energy_phases": audiomap.get("energy_phases", []),
            "speech": speech,
            # null when nothing was supplied; a sentence when a transcript was
            # supplied and none of it could be used (_load_words).
            "speech_warning": words_warning,
            "proxy_comparison": None,
        }

        # --------------------------------------------------------------
        # Step 5: what de-voicing WOULD buy -- diagnostic only.
        #
        # A large drop in roll-seconds here is the evidence that the voice
        # is fabricating sustained fills in the canonical grid, which is
        # what lets the director downgrade to phrase pacing on measurement
        # rather than on vibes. It never overwrites the headline fields.
        # --------------------------------------------------------------
        if devoice and proxy_path:
            proxy_map_path = output_dir / f"{stem}_audiomap_devoiced.json"
            proxy_map, error = self._run_analyzer(
                proxy_path, proxy_map_path, phrase_bars, duration
            )
            if error:
                return ToolResult(success=False, error=f"de-voiced comparison failed: {error}")
            artifacts.append(str(proxy_map_path))
            data["proxy_comparison"] = {
                "audiomap_path": str(proxy_map_path),
                **self._headline(proxy_map),
                "speech": (
                    self._speech_report(proxy_map, words, proxy_path, inputs) if words else None
                ),
            }

        return ToolResult(
            success=True,
            data=data,
            artifacts=artifacts,
            duration_seconds=round(time.time() - start, 2),
        )

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _headline(audiomap: dict) -> dict[str, Any]:
        rolls = audiomap.get("rolls", [])
        return {
            "summary": audiomap.get("summary", ""),
            "bpm": audiomap.get("tempo", {}).get("bpm"),
            "duration_seconds": audiomap.get("audio", {}).get("duration_sec"),
            "n_beats": len(audiomap.get("grid", {}).get("beats_sec", [])),
            "n_bars": len(audiomap.get("grid", {}).get("downbeats_sec", [])),
            "n_events": len(audiomap.get("events", [])),
            "n_phrases": len(audiomap.get("phrases", [])),
            "n_rolls": len(rolls),
            # Roll SECONDS, not roll count: de-voicing typically fragments one
            # bogus sustained fill into several short ones, so the count can
            # rise while the damage falls. Coverage is the honest measure.
            "roll_seconds": round(sum(float(r.get("dur_sec", 0.0)) for r in rolls), 3),
        }

    @staticmethod
    def _load_words(inputs: dict[str, Any]) -> tuple[list[dict], str | None, str | None]:
        """Word timestamps from inline input or a transcriber transcript JSON.

        Returns (words, error, warning). The warning exists because a transcript
        with no usable entries and no transcript at all both end as
        `speech: None`, and the operator cannot tell the two apart: the
        cross-check that is the whole point of the tool silently does not
        happen, and the director reads "no verdict" as "nothing to worry
        about". It stays a WARNING, not an error — an unusable transcript is no
        reason to throw away an otherwise-good grid.
        """
        source: str | None = None
        words = inputs.get("word_timestamps")
        if words is not None:
            source = "word_timestamps"
        elif inputs.get("transcript_path"):
            path = Path(inputs["transcript_path"])
            source = f"transcript_path {path}"
            if not path.exists():
                return [], f"transcript_path not found: {path}", None
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                return [], f"Failed to read transcript {path}: {exc}", None
            words = loaded.get("word_timestamps") if isinstance(loaded, dict) else loaded
        if source is None:
            return [], None, None  # nothing was supplied — nothing to report
        entries = words if isinstance(words, list) else []
        clean = [
            w
            for w in entries
            if isinstance(w, dict) and w.get("start") is not None and w.get("end") is not None
        ]
        if not clean:
            return (
                [],
                None,
                f"{source} supplied {len(entries)} entries, none of them carrying both a "
                "start and an end — the speech cross-check was SKIPPED. `speech` is null "
                "because the transcript was unusable, not because no transcript was given.",
            )
        clean.sort(key=lambda w: float(w["start"]))
        return clean, None, None

    def _write_proxy(self, src: Path, dst: Path, duration: float) -> str | None:
        """One ffmpeg pass: mono, the analyser's rate, speech bands ducked."""
        try:
            result = subprocess.run(
                [
                    shutil.which("ffmpeg"), "-y",
                    "-i", str(src),
                    "-ac", "1",
                    "-ar", str(_PROXY_SR),
                    "-af", _DEVOICE_CHAIN,
                    str(dst),
                ],
                capture_output=True, text=True, timeout=max(120, int(duration * 4)),
            )
        except subprocess.TimeoutExpired:
            return "De-voicing pass timed out"
        if result.returncode != 0 or not dst.exists():
            return f"De-voicing pass failed: {result.stderr.strip()[-400:]}"
        return None

    def _run_analyzer(
        self, audio: Path, out_json: Path, phrase_bars: int, duration: float
    ) -> tuple[dict, str | None]:
        """Invoke analyze-beatgrid.py through its documented CLI (:511-527)."""
        try:
            result = subprocess.run(
                [
                    sys.executable, str(_ANALYZER), str(audio),
                    "-o", str(out_json),
                    "--phrase-bars", str(phrase_bars),
                ],
                capture_output=True, text=True, timeout=max(180, int(duration * 8)),
            )
        except subprocess.TimeoutExpired:
            return {}, "analyze-beatgrid.py timed out"
        if result.returncode != 0:
            return {}, f"analyze-beatgrid.py failed: {result.stderr.strip()[-600:]}"
        try:
            return json.loads(out_json.read_text(encoding="utf-8")), None
        except (OSError, json.JSONDecodeError) as exc:
            return {}, f"analyze-beatgrid.py wrote no readable audiomap: {exc}"

    @staticmethod
    def _decode_mono(path: Path) -> np.ndarray:
        """Decode to mono float32 at the analyser's rate, for RMS measurement."""
        result = subprocess.run(
            [
                shutil.which("ffmpeg"), "-v", "error",
                "-i", str(path),
                "-ac", "1", "-ar", str(_PROXY_SR),
                "-f", "f32le", "-",
            ],
            capture_output=True, timeout=300,
        )
        if result.returncode != 0:
            return np.zeros(0, dtype=np.float32)
        return np.frombuffer(result.stdout, dtype="<f4")

    @staticmethod
    def _merge_spans(words: list[dict], pad: float, duration: float) -> list[list[float]]:
        spans: list[list[float]] = []
        for word in words:
            lo = max(0.0, float(word["start"]) - pad)
            hi = min(duration, float(word["end"]) + pad)
            if hi <= lo:
                continue
            if spans and lo <= spans[-1][1]:
                spans[-1][1] = max(spans[-1][1], hi)
            else:
                spans.append([lo, hi])
        return spans

    @staticmethod
    def _overlap(spans: list[list[float]], starts: list[float], lo: float, hi: float) -> float:
        """Seconds of [lo, hi] that fall inside the merged speech spans."""
        total = 0.0
        i = max(0, bisect.bisect_right(starts, lo) - 1)
        while i < len(spans) and spans[i][0] < hi:
            total += max(0.0, min(hi, spans[i][1]) - max(lo, spans[i][0]))
            i += 1
        return total

    def _speech_report(
        self, audiomap: dict, words: list[dict], analysed: Path, inputs: dict[str, Any]
    ) -> dict[str, Any]:
        """Measured contamination — every number here comes from the two inputs."""
        pad = float(inputs.get("speech_pad_seconds", 0.1))
        duration = float(audiomap.get("audio", {}).get("duration_sec") or 0.0)
        spans = self._merge_spans(words, pad, duration)
        starts = [s[0] for s in spans]
        speech_seconds = sum(hi - lo for lo, hi in spans)
        coverage = (speech_seconds / duration * 100) if duration else 0.0

        events = audiomap.get("events", [])
        in_speech = 0
        by_drum: dict[str, int] = {}
        for event in events:
            t = float(event.get("t", 0.0))
            i = bisect.bisect_right(starts, t) - 1
            if 0 <= i < len(spans) and t <= spans[i][1]:
                in_speech += 1
                drum = event.get("drum", "unknown")
                by_drum[drum] = by_drum.get(drum, 0) + 1
        event_pct = (in_speech / len(events) * 100) if events else 0.0

        rolls = audiomap.get("rolls", [])
        roll_rows = []
        roll_seconds = 0.0
        roll_seconds_in_speech = 0.0
        for roll in rolls:
            lo, hi = float(roll.get("start", 0.0)), float(roll.get("end", 0.0))
            span = max(hi - lo, 1e-9)
            over = self._overlap(spans, starts, lo, hi)
            roll_seconds += hi - lo
            roll_seconds_in_speech += over
            roll_rows.append(
                {
                    "start": round(lo, 3),
                    "end": round(hi, 3),
                    "hits": roll.get("hits"),
                    "drum": roll.get("drum"),
                    "kind": roll.get("kind"),
                    "speech_overlap_pct": round(over / span * 100, 1),
                }
            )

        samples = self._decode_mono(analysed)
        return {
            "words_checked": len(words),
            "speech_seconds": round(speech_seconds, 3),
            "speech_coverage_pct": round(coverage, 1),
            "events_total": len(events),
            "events_in_speech": in_speech,
            "events_in_speech_pct": round(event_pct, 1),
            "events_in_speech_by_drum": by_drum,
            # >1 means events cluster in speech beyond what its share of the
            # timeline would produce by chance — i.e. the voice is driving the
            # grid rather than merely coinciding with it.
            "enrichment_over_coverage": round(event_pct / coverage, 2) if coverage else None,
            "rolls_total": len(rolls),
            "rolls_overlapping_speech": sum(1 for r in roll_rows if r["speech_overlap_pct"] > 0),
            "rolls_majority_speech": sum(1 for r in roll_rows if r["speech_overlap_pct"] >= 50),
            "roll_seconds": round(roll_seconds, 3),
            "roll_seconds_in_speech": round(roll_seconds_in_speech, 3),
            "rolls": roll_rows,
            "words": self._word_levels(words, samples),
        }

    @staticmethod
    def _word_levels(words: list[dict], samples: np.ndarray) -> list[dict[str, Any]]:
        """Per-word peak_rms: the loudest 20 ms window of the analysed audio."""
        frame = int(_RMS_FRAME * _PROXY_SR)
        rows = []
        for word in words:
            lo = max(0, int(float(word["start"]) * _PROXY_SR))
            hi = min(len(samples), int(float(word["end"]) * _PROXY_SR))
            peak = 0.0
            if hi - lo >= frame:
                chunk = samples[lo:hi]
                n = (len(chunk) // frame) * frame
                frames = chunk[:n].reshape(-1, frame).astype(np.float64)
                peak = float(np.sqrt((frames**2).mean(axis=1)).max())
            elif hi > lo:
                peak = float(np.sqrt((samples[lo:hi].astype(np.float64) ** 2).mean()))
            rows.append(
                {
                    "word": word.get("word"),
                    "start": round(float(word["start"]), 3),
                    "end": round(float(word["end"]), 3),
                    "peak_rms": round(peak, 5),
                }
            )
        return rows
