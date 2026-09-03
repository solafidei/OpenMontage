"""The motion half of the CapCut vocabulary, as FFmpeg filter strings.

Reel-batch spec R6: the picture plane belongs to FFmpeg, inside the per-segment
re-encode `video_compose._compose` already runs (`vf_parts`). Four per-cut
operations, read from the closed `polish` block on a cut:

- ``punch_in``       — an eased ``zoompan`` push across the cut
- ``speed_ramp``     — a *continuous* ``setpts`` curve, not a constant factor
- ``transition_out`` — ``flash`` (blow out to white) or ``whip`` (directional blur)

plus the batch-wide look — one colour grade, one grain, one sharpen — stamped
identically on every reel of a sitting from a single ``look`` setting.

Nothing here reinvents a grade: `color_grade.PROFILES` and `face_enhance.PRESETS`
are already plain ``-vf`` strings and splice straight in. `face_enhance` is the
identity-safe beautify path and is the **only** enhancement reachable on a cut
whose ``provenance`` is ``operator_footage`` — anything else is refused loudly
rather than silently dropped, so a batch cannot quietly grade the operator's
own face with a look it never approved.

A cut with no ``polish`` block and no ``look`` yields no filters at all, so it
renders byte-identically to what `_compose` produced before this module existed.
"""

from __future__ import annotations

import math

from tools.enhancement.color_grade import PROFILES as GRADE_PROFILES
from tools.enhancement.face_enhance import PRESETS as FACE_PRESETS

# Tail length of the two accent transitions, in seconds of *output* time. Both
# are beat-hit accents on the outgoing cut — segments are concat-copied, so a
# transition cannot straddle the cut boundary and must live inside its own cut.
FLASH_SECONDS = 0.10
WHIP_SECONDS = 0.12

# Schema bounds, restated so a hand-built cut that never went through
# validate_artifact still cannot smuggle a nonsense zoom or ramp into ffmpeg.
PUNCH_IN_RANGE = (1.0, 4.0)
SPEED_RAMP_RANGE = (0.1, 10.0)

OPERATOR_FOOTAGE = "operator_footage"


class PolishError(ValueError):
    """A polish or look request that must not reach ffmpeg."""


def _bounded(name: str, value: object, bounds: tuple[float, float]) -> float:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise PolishError(f"{name} must be a number, got {value!r}") from None
    low, high = bounds
    if not low <= number <= high:
        raise PolishError(f"{name} must be within {low}-{high}, got {number}")
    return number


# ---- per-cut motion ----

def punch_in(zoom_end: float, duration: float, width: int, height: int, fps: int = 30) -> str:
    """Eased zoompan push from 1.0 to `zoom_end` across the whole cut.

    Eased with a smoothstep on normalised progress (``p*p*(3-2p)``) so the push
    starts and lands softly — a linear zoom reads as a machine, not an edit.
    `zoompan` counts *input* frames via ``on``, so the frame count is the cut's
    own length regardless of any speed ramp applied earlier in the chain.
    """
    zoom_end = _bounded("punch_in", zoom_end, PUNCH_IN_RANGE)
    last = max(int(round(duration * fps)) - 1, 1)
    progress = f"min(on/{last},1)"
    zoom = f"1+{zoom_end - 1.0:.6f}*pow({progress},2)*(3-2*{progress})"
    return (
        f"zoompan=z='{zoom}'"
        ":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        f":d=1:s={int(width)}x{int(height)}:fps={int(fps)}"
    )


def speed_ramp_setpts(speed_from: float, speed_to: float, duration: float) -> str:
    """A continuous setpts curve, not a constant factor.

    Speed varies linearly across the cut, ``s(t) = s0 + (s1-s0)*t/D``, so the
    output timestamp is the integral of ``1/s(t)``:
    ``PTS_out = (D/k) * ln(s(t)/s0)`` with ``k = s1 - s0``. The expression is
    written in source seconds (``T``) and divided by ``TB`` to land back in
    timebase units.
    """
    speed_from = _bounded("speed", speed_from, SPEED_RAMP_RANGE)
    speed_to = _bounded("speed_ramp", speed_to, SPEED_RAMP_RANGE)
    k = speed_to - speed_from
    if k == 0:
        raise PolishError("speed_ramp equal to speed is not a ramp")
    return (
        f"setpts='{duration / k:.6f}"
        f"*log(({speed_from:.6f}+{k:.6f}*T/{duration:.6f})/{speed_from:.6f})/TB'"
    )


def ramp_average_speed(speed_from: float, speed_to: float) -> float:
    """Effective (logarithmic-mean) speed of the ramp.

    The video's output length is fixed by the integral above; feeding this to
    `atempo` keeps the audio exactly as long as the picture, which the
    concat-copy step needs.
    """
    if speed_from == speed_to:
        return float(speed_from)
    return (speed_to - speed_from) / math.log(speed_to / speed_from)


def output_duration(duration: float, speed: float = 1.0, speed_ramp: float | None = None) -> float:
    """How long the segment is *after* any speed change — the tail anchor."""
    if speed_ramp is not None and float(speed_ramp) != float(speed):
        return duration / ramp_average_speed(float(speed), float(speed_ramp))
    return duration / float(speed)


def flash_out(end_seconds: float, seconds: float = FLASH_SECONDS) -> str:
    """Blow the tail out to white — the outgoing half of a flash cut.

    The ramp finishes early and the rest of the tail holds full white, because
    a fade that lands exactly on the last frame's timestamp never actually gets
    there: the cut arrives mid-ramp and reads as a dip, not a flash.
    """
    seconds = min(seconds, end_seconds)
    start = max(end_seconds - seconds, 0.0)
    return f"fade=t=out:st={start:.4f}:d={seconds * 0.6:.4f}:color=white"


def whip_out(end_seconds: float, seconds: float = WHIP_SECONDS) -> str:
    """Horizontal-only blur ramping in over the tail — a whip-pan exit.

    Two timeline-gated `gblur` stages rather than one, because `gblur`'s sigma
    takes no time expression and a single constant blur snaps on rather than
    building.
    """
    half = seconds / 2.0
    return ",".join(
        f"gblur=sigma={sigma}:sigmaV=0:enable='gte(t,{max(end_seconds - span, 0.0):.4f})'"
        for sigma, span in ((8, seconds), (16, half))
    )


# ---- batch-wide look ----

def look_filters(look: dict | None, provenance: str | None = None) -> list[str]:
    """One grade, one grain, one sharpen — the same on every reel of a sitting.

    ``look = {"grade": <profile|preset>, "grain": <int>, "sharpen": <preset>}``.
    On an ``operator_footage`` cut only `face_enhance.PRESETS` resolve; a
    `color_grade` profile or any grain raises rather than being dropped, so a
    look that is not identity-safe fails the batch instead of applying to four
    fifths of it.
    """
    if not look:
        return []
    locked = provenance == OPERATOR_FOOTAGE
    parts: list[str] = []

    grade = look.get("grade")
    if grade:
        if grade in FACE_PRESETS:
            parts.append(FACE_PRESETS[grade]["vf"])
        elif grade not in GRADE_PROFILES:
            raise PolishError(f"Unknown grade {grade!r}")
        elif locked:
            raise PolishError(
                f"grade {grade!r} is not identity-safe; an operator_footage cut "
                f"accepts face_enhance presets only: {sorted(FACE_PRESETS)}"
            )
        else:
            parts.append(GRADE_PROFILES[grade]["vf"])

    grain = look.get("grain") or 0
    if grain:
        if locked:
            raise PolishError("grain is not permitted on an operator_footage cut")
        parts.append(f"noise=alls={int(grain)}:allf=t+u")

    sharpen = look.get("sharpen")
    if sharpen:
        if sharpen not in FACE_PRESETS:
            raise PolishError(f"Unknown sharpen preset {sharpen!r}")
        parts.append(FACE_PRESETS[sharpen]["vf"])

    return parts


# ---- the whole picture plane for one cut ----

def cut_filters(
    cut: dict,
    duration: float,
    width: int,
    height: int,
    look: dict | None = None,
    fps: int = 30,
) -> list[str]:
    """Every video filter for one cut, in chain order, including its speed.

    Order is the load-bearing part, and it is why the speed filter lives here
    rather than back in `_compose`: `zoompan` re-times its output at its own
    fps, so a punch-in placed *after* `setpts` silently throws the ramp away and
    the segment comes out its original length. Punch-in first, then speed, then
    the look, then the tail accent — whose anchor is in output time because it
    sits downstream of the speed change.

    A cut with no `polish` and no `look` yields exactly what `_compose` built
    before this module existed: nothing, or the same constant `setpts`.
    """
    polish = cut.get("polish") or {}
    speed = float(cut.get("speed", 1.0) or 1.0)
    ramp_to = polish.get("speed_ramp")
    parts: list[str] = []

    zoom_end = polish.get("punch_in")
    if zoom_end is not None and float(zoom_end) != 1.0:
        parts.append(punch_in(zoom_end, duration, width, height, fps))

    if ramp_to is not None and float(ramp_to) != speed:
        parts.append(speed_ramp_setpts(speed, float(ramp_to), duration))
    elif speed != 1.0:
        parts.append(f"setpts={1.0/speed}*PTS")

    parts.extend(look_filters(look, cut.get("provenance")))

    accent = polish.get("transition_out")
    if accent:
        end = output_duration(duration, speed, ramp_to)
        if accent == "flash":
            parts.append(flash_out(end))
        elif accent == "whip":
            parts.append(whip_out(end))
        else:
            raise PolishError(f"Unknown polish transition_out {accent!r}")

    return parts
