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
# ffmpeg's own limit on `noise=alls=`: 0-100. Grain used to skip `_bounded`
# entirely, so `{"grain": 500}` and `{"grain": -5}` went straight to ffmpeg —
# 500 as an unrecognised-value parse error at render time, -5 silently as 0.
GRAIN_RANGE = (0, 100)

# How much bigger than the output the geometry stage may be asked to build.
# PUNCH_IN_RANGE allows 4.0, but the intermediate's AREA — and so the encode
# cost — grows with the square of the headroom: 2.0 is a 2160x3840 frame (4x
# the output's pixels), 4.0 is 4320x7680 (16x). Past 2x there is nothing left
# to recover either, because even 4K source only carries ~2160 lines through a
# 9:16 crop; the extra pixels would be interpolation billed at full price.
SCALE_HEADROOM_CAP = 2.0

# setpts coefficients are emitted at six decimals, so that — not `==` — is the
# precision the ramp guard has to ask at. `speed_ramp=1.0000001` passes an
# exact-inequality test, then formats k to "0.000000" and hands ffmpeg an
# expression that divides by zero.
_EMITTED_DECIMALS = 6

OPERATOR_FOOTAGE = "operator_footage"


class PolishError(ValueError):
    """A polish or look request that must not reach ffmpeg."""


def _number(name: str, value: object) -> float:
    """Coerce a polish value, raising PolishError rather than a bare ValueError.

    `cut_filters` used to call `float()` directly on `punch_in` and
    `speed_ramp`, so a hand-built cut carrying a string escaped this module as
    a `ValueError` that no caller was catching. Everything this module refuses,
    it refuses as `PolishError`.
    """
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise PolishError(f"{name} must be a number, got {value!r}") from None


def _bounded(name: str, value: object, bounds: tuple[float, float]) -> float:
    number = _number(name, value)
    low, high = bounds
    if not low <= number <= high:
        raise PolishError(f"{name} must be within {low}-{high}, got {number}")
    return number


# ---- per-cut motion ----

def is_ramp(speed_from: float, speed_to: float) -> bool:
    """Is this a ramp at the precision the setpts expression is written to?

    Asked here rather than as `speed_to != speed_from` because the expression
    carries `k = s1 - s0` at six decimals: a delta that rounds away there is
    not a slow ramp, it is a `/0.000000` inside the string ffmpeg parses.
    """
    return float(f"{speed_to - speed_from:.{_EMITTED_DECIMALS}f}") != 0.0


def scale_headroom(cut: dict) -> float:
    """How much bigger than the output this cut's geometry stage should build.

    `punch_in` crops a region of its *input* and blows it back up to the output
    size. Scaled to the output size first, that crop magnifies pixels thrown
    away one filter earlier, and every punch-in lands soft — on a beat hit,
    which is exactly where the eye is. Handing the geometry stage the punch-in's
    headroom instead lets the same zoompan crop real detail. Measured through
    `_compose` on a 2s z=1.6 cut of 3840x2160 source
    (`projects/gym-footage/raw/IMG_1384.MOV`) at 1080x1920/cover, Laplacian
    variance of the final — most zoomed — frame went 37.1 -> 54.8, a 1.48x
    gain, for 1.82s -> 1.81s of wall clock and no extra ffprobe calls.

    A cut with no punch-in reports 1.0, so it renders byte-identically to what
    `_compose` built before this existed. `punch_in` itself is unchanged — it
    still lands on the output size, which is what closes the loop.
    """
    zoom_end = (cut.get("polish") or {}).get("punch_in")
    if zoom_end is None:
        return 1.0
    return min(_bounded("punch_in", zoom_end, PUNCH_IN_RANGE), SCALE_HEADROOM_CAP)


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
    if not is_ramp(speed_from, speed_to):
        raise PolishError("speed_ramp equal to speed is not a ramp")
    k = speed_to - speed_from
    return (
        f"setpts='{duration / k:.6f}"
        f"*log(({speed_from:.6f}+{k:.6f}*T/{duration:.6f})/{speed_from:.6f})/TB'"
    )


def ramp_average_speed(speed_from: float, speed_to: float) -> float:
    """Effective (logarithmic-mean) speed of the ramp.

    This is the speed that reproduces the *analytic* output length of the
    integral above, and that is the whole of the claim. It is NOT "exactly as
    long as the picture", which is what this docstring used to say: `-r 30`
    requantises the ramped PTS onto the CFR grid, so the rendered video stream
    ends on a whole frame the curve never lands on, and the AAC audio ends on a
    whole 1024-sample packet. Measured through `_compose` on a 2s cut, video
    stream duration minus audio stream duration: 1.0->2.0 +57ms, 1.0->3.0
    +43ms, 1.0->1.5 +21ms, 1.0->0.5 -56ms.

    Those residuals are the two grids, not a wrong tempo: one video frame
    (33ms) plus one AAC packet (21ms) is 55ms, and no atempo value removes
    either. What the log-mean buys is that the drift stays inside that floor
    instead of growing with the ramp — the arithmetic mean puts 1.0->3.0 at
    ~100ms and rising. The concat-copy step has to tolerate the floor.
    """
    if speed_from == speed_to:
        return float(speed_from)
    return (speed_to - speed_from) / math.log(speed_to / speed_from)


def output_duration(duration: float, speed: float = 1.0, speed_ramp: float | None = None) -> float:
    """How long the segment is *after* any speed change — the tail anchor."""
    speed = _number("speed", speed)
    if speed_ramp is not None and is_ramp(speed, _number("speed_ramp", speed_ramp)):
        return duration / ramp_average_speed(speed, float(speed_ramp))
    return duration / speed


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
        if grade not in FACE_PRESETS and grade not in GRADE_PROFILES:
            raise PolishError(f"Unknown grade {grade!r}")
        # The identity gate is asked BEFORE either name set resolves. Checking
        # FACE_PRESETS first skipped the gate entirely: the two sets are
        # disjoint today so nothing leaked, but a name added to both would have
        # taken the face-preset branch on an operator_footage cut while also
        # naming a colour grade — and a name that means two things is not
        # identity-safe whichever one it resolved to.
        if locked and (grade not in FACE_PRESETS or grade in GRADE_PROFILES):
            raise PolishError(
                f"grade {grade!r} is not identity-safe; an operator_footage cut "
                f"accepts face_enhance presets only: {sorted(FACE_PRESETS)}"
            )
        parts.append(
            (FACE_PRESETS if grade in FACE_PRESETS else GRADE_PROFILES)[grade]["vf"]
        )

    grain = look.get("grain") or 0
    if grain:
        if locked:
            raise PolishError("grain is not permitted on an operator_footage cut")
        parts.append(f"noise=alls={int(_bounded('grain', grain, GRAIN_RANGE))}:allf=t+u")

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
    speed = _number("speed", cut.get("speed", 1.0) or 1.0)
    ramp_to = polish.get("speed_ramp")
    parts: list[str] = []

    zoom_end = polish.get("punch_in")
    if zoom_end is not None and _number("punch_in", zoom_end) != 1.0:
        parts.append(punch_in(zoom_end, duration, width, height, fps))

    ramping = ramp_to is not None and is_ramp(speed, _number("speed_ramp", ramp_to))
    if ramping:
        parts.append(speed_ramp_setpts(speed, float(ramp_to), duration))
    elif speed != 1.0:
        parts.append(f"setpts={1.0/speed}*PTS")

    parts.extend(look_filters(look, cut.get("provenance")))

    accent = polish.get("transition_out")
    if accent:
        end = output_duration(duration, speed, ramp_to if ramping else None)
        if accent == "flash":
            parts.append(flash_out(end))
        elif accent == "whip":
            parts.append(whip_out(end))
        else:
            raise PolishError(f"Unknown polish transition_out {accent!r}")

    return parts
