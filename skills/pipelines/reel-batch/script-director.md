# Script Director — Reel Batch Pipeline

## When To Use

Gate 1 is closed. The pool is indexed, the reel count is agreed, and the operator's tracks
are named in the brief. This stage turns those tracks into **timing**: one beat grid and
one word-level transcript per track, a measured verdict on how much of each grid is
actually the voice, and — per planned reel — a hook line, a caption line, and the snap grid
the cut list will be built on. Nothing here is creative writing: the words already exist in
the track, and your job is to find which ten seconds of them can carry a reel.

Caption work splits three ways in this pipeline. **This stage owns the transcript** — what
the words are and when they happen. `edit` owns the caption *style*, `compose` owns the
*burn*. Do not pick fonts, presets or safe zones here.

## Prerequisites

| Layer | Resource | Purpose |
|-------|----------|---------|
| Schema | `schemas/artifacts/script.schema.json` | Artifact validation |
| Prior artifact | `state.artifacts["idea"]["brief"]` | Reel count, track list, pool measurement |
| Tools | `transcriber`, `beat_grid` | Word timestamps, then the grid |
| Tool (rarely) | `scene_detect` | Only if a "track" arrived as a video file |
| Reference | `skills/meta/checkpoint-protocol.md` | Checkpointing and cost-ledger rules |

Neither required tool spends — `BeatGrid.estimate_cost` returns `0.0`
(`tools/analysis/beat_grid.py:262-263`) and `transcriber` runs local faster-whisper
(`tools/analysis/transcriber.py:39`). **This stage books nothing;** the ledger opened by the
cost gate in `idea-director.md` is read only for the checkpoint snapshot.

## Mental Model

A reel is a ten-second window cut out of one track. Three measurements decide whether that
window works:

1. **Where the beats are** — `grid.beats_sec` and `grid.downbeats_sec`.
2. **How much of the grid is voice rather than drums.** There is **no stem separation
   anywhere in this repo** (`tools/video/remotion_caption_burn.py:240-242`), and a spoken
   voice lands squarely in the analyser's snare band, 150-900 Hz
   (`tools/analysis/beat_grid.py:13-14`) — so some of the "drums" are syllables.
3. **How sure the transcriber is of each word** — the per-word `probability`. A caption is
   a printed claim about what the track says; printing a guess is worse than printing
   nothing.

## Process

### 0. Read The Batch Shape Off The Brief

`brief` closes its top level (`schemas/artifacts/brief.schema.json` ends
`additionalProperties: false`), so everything batch-shaped the `idea` gate measured lives on
`brief["metadata"]`. Read these by name — do not go hunting for equivalents:

- `brief["metadata"]["reel_ids"]` — `["reel_01", "reel_02", ...]`, minted once at `idea` and
  **never re-minted here**. Every `sections[].id` and every `metadata.reels[].reel_id` you
  write is one of those strings spelled exactly as it arrived; `reel_count` is its length.
- `brief["metadata"]["tracks"]` — one `{"track_id", "path"}` per operator track, `track_01`
  onwards. `path` is what you hand `transcriber` and `beat_grid`. If the list is absent or
  empty, stop and ask; do not go looking for audio files on disk.
- `brief["metadata"]["usable_segments"]` and `["max_reels"]` — the pool measurement
  `footage_library` returned (`tools/video/footage_library.py:225`, `:234`), under exactly
  those names. `max_reels` is the reel ceiling the indexed pool supports.
- `brief["metadata"]["cuts_per_reel"]` (`:233`) — the cut count each reel is planned for,
  and therefore the number of holds its snap grid is trying to supply.

**One track per reel, never shared** (`executive-producer.md` → Definition Of Done). Fewer
tracks than reels is a shortfall, not a puzzle: escalate as a structured blocker with the
two real options — fewer reels, or more tracks — and send back to `idea` if the operator
chooses fewer. Never quietly cut two reels from one track.

### 1. Transcribe Each Track First

Order matters and is not negotiable: `beat_grid` only produces its speech report when word
timestamps are handed to it (`tools/analysis/beat_grid.py:355` — `if words else None`).
Transcribe first, grid second.

```python
from tools.analysis.transcriber import Transcriber
from tools.analysis.beat_grid import BeatGrid

track, work = "projects/<id>/audio/push_day.mp3", "projects/<id>/analysis"

tx = Transcriber().execute({
    "input_path": track,
    "model_size": "medium",  # the tool default is "base" (transcriber.py:59-63); reel
                             # words sit under music, so start two steps above it
    "vad_filter": False,     # NOT the tool default (transcriber.py:65-67) — see below
    "output_dir": work,
})
assert tx.success, tx.error
transcript_path = tx.artifacts[0]        # <stem>_transcript.json (transcriber.py:282, :285)
```

What comes back (`transcriber.py:263-280`): `segments`, `word_timestamps`, `language`,
`duration_seconds`, plus `model_size` / `vad_filter` / `device` / `compute_type` /
`gpu_fallback_reason`. All nine are declared on `output_schema` (`:81-99`) and a parity test
holds the two together. **`vad_filter` is the one G2 reads back** — it is what makes a reel's
`caption_source: "music_bed"` declaration checkable against how the track was actually
transcribed, and it is written into the transcript file itself, not just the return value.
Every word entry is `{"word", "start", "end", "probability"}`, probability rounded to three
places (`:216-221`) — exactly the shape `remotion_caption_burn` consumes at `compose`
(`tools/video/remotion_caption_burn.py:222-245`). **Do not reshape it.**

`word_timestamps=True` is the only kwarg this tool forces (`transcriber.py:208`).
`vad_filter` is an ordinary input — default `True` (`transcriber.py:65-68`), read at `:148`,
handed straight to `model.transcribe` at `:209`. **Reel-batch passes `False`, always.** The
schema says why in its own description (`:68-73`): the VAD scores sung vocals under a music
bed as non-speech and discards nearly all of them, and in this pipeline the captions *are*
the track's words. Measured on two operator tracks: `"small"` with the VAD on returned 10
and 11 words; `"medium"` with `vad_filter: False` returned 282 and 319 on the same audio.
A track returning a handful of words is a VAD casualty, not a silent track.

VAD off has a real cost — budget for it rather than trusting the extra words. With nothing
dropping non-speech, the model transcribes the instrumental passages too, and hallucinates
over them: one track opened with eight repetitions of `"RUMBLING"` before the first sung
line. So read the transcript as *words plus noise*. Hooks and caption lines come from
high-`probability` words inside a genuine vocal line (step 5, and the confidence gate in
step 7); a run of repeated words over an intro with no vocal is transcription noise and
never a hook, however well it reads.

### 2. Beat-Grid The Track With The Transcript In Hand

```python
bg = BeatGrid().execute({
    "input_path": track,
    "output_dir": work,
    "transcript_path": transcript_path,  # read as word_timestamps (beat_grid.py:405-409, :417)
    "devoice": True,                     # diagnostic second pass, default True (:131-137)
    "phrase_bars": 4,
})
assert bg.success, bg.error
```

`bg.data` carries the headline (`bpm`, `n_beats`, `n_bars`, `n_events`, `n_phrases`,
`n_rolls`, `roll_seconds` — `beat_grid.py:375-391`), the `grid` (`beats_sec`,
`downbeats_sec`), `phrases`, `rolls`, `energy_phases`, the `speech` report,
`speech_warning`, and `proxy_comparison`. **The canonical grid always comes from the raw mix.** The de-voiced
proxy is a diagnostic and never answers the timing question — on a clean track its EQ scoop
invents a confident tempo where the analyser honestly reported none
(`beat_grid.py:302-311`). The de-voiced pass surfaces **headline numbers plus its own
`audiomap_path` and speech report** in `proxy_comparison` — `bpm`, `n_beats`, `n_rolls`,
`roll_seconds` and the rest of `_headline`
(`beat_grid.py:356-362`); its beat and downbeat lists are never exposed in `bg.data` at all,
so there is no de-voiced grid to plan against even if you wanted one. Read it as a
diagnostic ratio and nothing else — the canonical grid is always `bg.data["grid"]`.

### 3. Read The Contamination Verdict, Then Pick A Cut Policy

The speech report (`beat_grid.py:519-538`) is measured, not estimated:

| Field | What it says |
|---|---|
| `speech_coverage_pct` | share of the track's seconds that are speech |
| `events_in_speech_pct` | share of onset events that land inside speech |
| `enrichment_over_coverage` | the ratio of those two (`:505`). `> 1` means events *cluster* in speech beyond chance — the voice is driving the grid, not coinciding with it |
| `roll_seconds_in_speech` vs `roll_seconds` | how much of the detected fills are actually syllables (`:509-510`) |
| `rolls_majority_speech` | rolls that are at least half speech |
| `words[].peak_rms` | loudest 20 ms inside each word, on the analysed audio (`:512`, `:516-538`) |

`beat_grid` stops at reporting — *"The trust call itself (beat-cut vs phrase-pace) stays
with the agent"* (`beat_grid.py:25-26`). This pipeline's call:

```python
speech, proxy = bg.data["speech"], bg.data["proxy_comparison"]

enrichment = speech["enrichment_over_coverage"] or 0.0
roll_in_speech = (speech["roll_seconds_in_speech"] / speech["roll_seconds"]
                  if speech["roll_seconds"] else 0.0)
roll_lost_to_devoice = (1.0 - proxy["roll_seconds"] / bg.data["roll_seconds"]
                        if proxy and bg.data["roll_seconds"] else 0.0)

if enrichment <= 1.2 and roll_in_speech < 0.5:
    cut_policy = "beat"     # snap to grid.beats_sec
elif enrichment <= 1.6 and roll_lost_to_devoice < 0.5:
    cut_policy = "bar"      # snap to grid.downbeats_sec only
else:
    cut_policy = "phrase"   # snap to phrases[]; no event or roll accents at all
```

What a contaminated track means for cutting:

- **`bar`** — the kick (<150 Hz) and the hats (>6 kHz) survive the voice; the snare band
  does not (`beat_grid.py:63-72`). Bars are real, individual beats are not: cut on
  downbeats and accept a longer mean hold.
- **`phrase`** — the grid is mostly voice. Pace to `phrases[]` (four-bar spans off the
  downbeats) where a 10s window holds enough of them, and to downbeats where it does not —
  step 4's `snap_grid` makes that fallback. Either way, tell `scene_plan` in writing that
  the phrase ruling stands: `events[]` and `rolls[]` are unusable
  here. **A flash or whip hung on a "roll" that is really a fast line of speech fires on
  nothing an audience can hear.** No cleaner grid is available: no stem separation exists,
  and re-running `beat_grid` measures the same track again.
**The verdict is computed from unfiltered words, hallucinations included.** `beat_grid`
never looks at `probability` — `_load_words` keeps every entry with a numeric `start` and
`end` (`tools/analysis/beat_grid.py:463-467`) and nothing downstream of it filters on
confidence. So with `vad_filter=False`, the noise the model invents over instrumental
passages is counted as speech seconds and lands in `speech_coverage_pct`,
`enrichment_over_coverage`, `roll_seconds_in_speech` and `rolls_majority_speech` — the four
numbers the ladder above branches on. The confidence gate in step 7 protects the *caption*;
it runs later and it does not protect *this*.

Measured on the week-37 batch, the share of transcribed word-seconds carrying
`probability < 0.6` was 7.3% / 27.4% / 23.8% / 9.2% / 13.2% across the five tracks. All five
ruled `bar`, and all five did so on the second clause — `roll_in_speech` at 0.82-1.00
against a `< 0.5` threshold. On a vocal track that clause is close to unsatisfiable by
construction: coverage of 68-86% means almost any fill lands inside speech whether or not
the grid is contaminated, so the `beat` branch is nearly unreachable for exactly the tracks
this pipeline requires. Read a `bar` ruling as "not disproven" rather than "measured
contaminated", and when the reel count depends on it, report the enrichment figure
(1.04-1.22 here, i.e. barely above chance) beside the verdict so the operator can see how
thin the evidence is.

- Under any policy, `roll_lost_to_devoice > 0.5` means the fills are syllables — record it
  so `edit` does not hang a speed ramp on them. And a word with high `probability` but a
  `peak_rms` at the floor is **mis-timed**: its caption drifts off the mouth even though
  the text is right, so treat it as a window boundary, not caption content.

### 4. Derive The Snap Grid

A reel is at most 10 seconds with roughly five cuts, so the mean hold is 2.0 seconds. Turn
that into whole beats rather than free-running seconds. The grid you **store** is
**reel-local**: every boundary is rebased off `window_start` before it leaves this function,
so `snap_grid[0] == 0.0` and `scene_plan` can read it without knowing the window.

```python
def snap_grid(bg_data, cut_policy, window_start, window_end, cuts_per_reel=5):
    """Candidate cut boundaries inside a window, reel-local (already offset)."""
    if cut_policy == "phrase":
        grid = _rebase([p["start"] for p in bg_data["phrases"]], window_start, window_end)
        # phrases[] are four-bar spans, so a 10s window holds one or two of them —
        # short of the cuts_per_reel + 1 boundaries scene_plan needs. Fall back to
        # downbeats for the GRID and keep the phrase ruling where it actually bites:
        # events[] and rolls[] stay unusable, so no flash or whip is hung on speech.
        if len(grid) >= cuts_per_reel + 1:
            return grid
        cut_policy = "bar"
    line = bg_data["grid"]["downbeats_sec" if cut_policy == "bar" else "beats_sec"]
    beat_dur = 60.0 / bg_data["bpm"]
    step = 1 if cut_policy == "bar" else max(1, round(2.0 / beat_dur))
    i0 = next((i for i, t in enumerate(line) if t >= window_start), len(line))
    return _rebase(line[i0::step], window_start, window_end)


def _rebase(values, window_start, window_end):
    """Reel-local boundaries, always opening on an exact 0.0."""
    grid = [round(t - window_start, 3) for t in values if window_start <= t <= window_end]
    return grid if grid and grid[0] == 0.0 else [0.0] + grid
```

The reel opens at `0.0` whether or not `window_start` lands exactly on a grid line. Step 5
anchors it onto one of the same policy where it can, but rule 3 lets a `bar` reel open on a
plain beat when the downbeat anchor would put the hook more than a beat late — so `_rebase`
states the opening boundary rather than letting `scene_plan` infer it. The
absolute track time of any boundary is `snap_value + window["offset_seconds"]` — that
inverse, not a second grid, is what a cut records downstream as `beat_seconds`.

A reel needs `cuts_per_reel + 1` boundaries — six for the standard five-cut reel. At 125 BPM
a bar is 1.92s, so `bar` puts boundaries at 0.0, 1.92, 3.84, 5.76, 7.68 and 9.6: six, all
inside the 9.8-second cap. At 120 BPM a bar is 2.0s and the same cap holds only 0.0, 2.0,
4.0, 6.0 and 8.0 — the sixth boundary would be 10.0, past the cap, so this is the reel that
escalates rather than the one that plans. At 90 BPM a bar is 2.67s and the cap holds only
0.0, 2.67, 5.33 and 8.0 — four boundaries, three slots. `scene_plan` does not absorb that:
`cut_slots` raises `ValueError` on a grid shorter than `cuts_per_reel + 1`. Do not pass it
downstream and do not invent beats. Escalate here as a structured blocker with the two real
options — a lower `cuts_per_reel` for the batch (a brief-level number, so that is a
send-back to `idea`), or a different track for that reel whose grid supplies the boundaries
under its own policy.

### 5. Choose The Hook Line, Then Anchor The Window To It

The hook is **found**, not written, and the window is built around it. Reverse that order
and the hook lands mid-reel.

1. Scan the track's `segments` for lines that pass the **standalone test** — a cold viewer
   understands them with no earlier context: no unresolved pronoun, no callback, no lead-in
   before the point lands, and a finished thought inside the window.
2. Anchor `window_start` to the last grid line of the cut policy at or before the hook's
   first word start, `hook_start`.
3. Require `hook_start - window_start <= 60.0 / bg.data["bpm"]` — one beat. If a downbeat
   anchor puts the hook more than a beat late, fall back to the nearest **beat** and record
   that the reel opens on a partial bar.
4. `window_end = min(window_start + 9.8, bg.data["duration_seconds"])` (the analyser's own
   duration, `beat_grid.py:380`; `tx.data["duration_seconds"]` is the same number),
   pulled back to the last snap boundary so the final cut lands on the grid rather than
   mid-hold — **then extended to the end of the word the line finishes on, when that word
   still ends inside the 9.8-second cap.** Only the LAST boundary moves; every other cut edge
   stays on the grid, so the reel gains a slightly longer final hold rather than a cut that
   drifts. The cap is 9.8, not 10.0 — the same rendered-length pad edit-director's own gate
   accounts for (step 8).

   The pull-back alone discards up to a whole bar, and at `bar` policy a bar is 2.4-2.7s on
   a 90-99 BPM track. Measured on the week-37 batch it cost 1.04s / 1.45s / 1.80s / 2.66s of
   a 10-second budget across four reels, and — worse than the waste — it truncated the sung
   line at the boundary: `reel_03` ended "I just say" with "I will" 0.30s outside the window,
   `reel_01` ended "walls come" without "down". The operator hears that as the track being
   cut early, because it is. The reel the same batch got right wasted 0.32s.

   ```python
   window_end = min(window_start + 9.8, bg.data["duration_seconds"])
   grid_abs = [t for t in line if window_start <= t <= window_end]
   window_end = grid_abs[-1]                       # on the grid, as before
   tail = [w for w in words                        # the line the reel ends mid-way through
           if w["start"] < window_end < w["end"] or
              (window_end <= w["start"] < window_start + 9.8)]
   for w in tail:                                  # extend only while the cap allows it
       if w["end"] <= window_start + 9.8 and w["probability"] >= 0.6:
           window_end = w["end"]
   # snap_grid is the function from step 4; the reel's actual boundary LIST only
   # exists once that function is called against the now-final window_end.
   grid = snap_grid(bg.data, cut_policy, window_start, window_end, cuts_per_reel)
   grid[-1] = round(window_end - window_start, 3)   # restate the boundary the
                                                     # extension just moved — the
                                                     # count of boundaries is unchanged
   ```

   Stop extending at the first word that would breach the 9.8 cap or fail the confidence
   gate — the loop's own guard (`w["end"] <= window_start + 9.8`) is what enforces this, so
   a reel overshooting it fails step 9's window bound here rather than dying at `edit` after
   `assets` has already spent money on it; 10.0 stays compose's own probe ceiling, unrelated
   to this budget. A sub-0.6 word is not caption content either way (step 7). If nothing
   follows the boundary, the pulled-back value stands. `grid` above is the list the
   `snap_grid` function actually returns, called only once `window_end` is final — call
   it before the extension and the boundary it hands back is the one the extension is
   about to undo. The restated `grid[-1]` is what keeps step 9's stored-artifact
   invariant, `snap_grid[-1] == window.end_seconds - window.start_seconds`, true when the
   extension fires: the extension moved `window_end` past the grid line `grid[-1]` still
   named, and nothing else corrects it.
5. Rebase the hook off `window_start` the way step 6 rebases the caption — the stored
   `hook` is reel-local, `{"text", "start_seconds", "end_seconds"}` — and require
   `hook["end_seconds"] <= snap_grid[2]`, both sides reel-local. Running past the first
   snap boundary is fine; past the second it is a caption, not a hook.

Gate 2 re-checks that same numeric bound — `hook["end_seconds"] <= snap_grid[2]`
(`executive-producer.md` → G3) — so check it twice here rather than once there. The bound is
`snap_grid[2]` and nothing tighter: a hook that ends after `snap_grid[1]` is still a passing
hook, and a reel sent back for crossing the first boundary is sent back for nothing.

### 6. Take The Caption Line And Re-base It To Reel Time

`remotion_caption_burn` converts word times straight to milliseconds with no offset —
`int(w["start"] * 1000)` (`tools/video/remotion_caption_burn.py:236-237`), so track-relative
timings make every caption in the batch fire late by the window offset. Store **reel-local**
times and keep the offset separately. A word straddling either edge is dropped, not
stretched — half a word on screen reads as a bug.

```python
# tx is step 1's result; window_start / window_end are the bounds fixed in step 5.
words = [w for w in tx.data["word_timestamps"]
         if w["start"] >= window_start and w["end"] <= window_end]

caption_segment = {                       # one transcriber-shaped segment, reel-local
    "start": 0.0,
    "end": round(window_end - window_start, 3),
    "text": " ".join(w["word"].strip() for w in words),
    "words": [{"word": w["word"],
               "start": round(w["start"] - window_start, 3),
               "end": round(w["end"] - window_start, 3),
               "probability": w["probability"]} for w in words],
}

caption = {"segments": [caption_segment]}     # the shape the artifact and the burn read
```

`metadata.reels[].caption` is that wrapper, never the bare segment: `assets` hands
`reel["caption"]["segments"]` straight to `remotion_caption_burn`'s `segments` input.

### 7. The Confidence Gate — Never Print A Guess

`remotion_caption_burn` carries `probability` through as `confidence`
(`remotion_caption_burn.py:243-244`) and reports `mean` / `min` / `counted` /
`low_confidence_words` against `LOW_CONFIDENCE = 0.6` — *"Below this a word is more likely
wrong than right at reel speed"* (`:651-652`, `:655-666`). But the renderer treats
confidence as **"Purely informational"**
(`remotion-composer/src/components/CaptionOverlay.tsx:18-22`):
nothing downstream hides a weak word. **The gate is here or nowhere.**

For every word in a selected caption line with `probability < 0.6`, work the ladder in
order and stop at the first rung that resolves it:

1. **Re-transcribe the track** at a larger `model_size` (`"large-v3"`, above the `"medium"`
   this stage starts at — `transcriber.py:59-63`). `model_size` is part of the idempotency
   key (`:101`), so this is a genuinely new run rather than a cache hit.
2. **Ask the operator what the line says** and record the fix as a `corrections` entry —
   `{wrong: right}`, matched case-insensitively with trailing punctuation preserved
   (`remotion_caption_burn.py:148-155`, `:226-234`); carry it in the script so `compose`
   passes it to the burn. This is the only rung that puts a word on screen the model did
   not produce, and it needs a human source.
3. **Move the window** so the word falls outside it, or shorten the line to the clean span.
4. If none of those work, **this is not a caption line.** Pick another.

Record `caption_confidence` per reel — `min`, `mean`, and a `low_confidence_words` count
that must be **0** at hand-off. `compose` reports the same fields off what it actually
burned; a mismatch means a word changed between approval and render.

### 8. Write The `script` Artifact

The schema is closed at the root and in `sections[]`
(`schemas/artifacts/script.schema.json`, both `additionalProperties: false`), so the batch
structure lives in `metadata` — one `section` per reel, and everything `scene_plan` needs
to snap cuts without re-analysing alongside it.

```json
{
  "version": "1.0",
  "title": "Reel batch — week of 2026-09-01",
  "total_duration_seconds": 48.6,
  "sections": [
    { "id": "reel_01", "label": "reel_01 — caption line",
      "text": "you don't rise to the level of your goals you fall to your systems",
      "start_seconds": 0.0, "end_seconds": 9.8 }
  ],
  "metadata": {
    "pipeline": "reel-batch", "timebase": "reel_local", "reel_count": 5,
    "tracks": [
      { "track_id": "track_01",
        "path": "projects/<id>/audio/push_day.mp3",
        "audiomap_path": "projects/<id>/analysis/push_day_audiomap.json",
        "transcript_path": "projects/<id>/analysis/push_day_transcript.json",
        "bpm": 122.0,
        "beats_sec": [0.51, 1.0, 1.5],
        "downbeats_sec": [0.51, 2.48, 4.44],
        "phrases": [{ "index": 0, "start": 0.51, "end": 8.38, "bars": 4 }],
        "cut_policy": "bar",
        "contamination": { "speech_coverage_pct": 41.2, "events_in_speech_pct": 58.9,
                           "enrichment_over_coverage": 1.43, "roll_seconds": 6.2,
                           "roll_seconds_in_speech": 3.9, "rolls_majority_speech": 2,
                           "verdict": "bar — beats contaminated; rolls unusable for accents" } }
    ],
    "reels": [
      { "reel_id": "reel_01", "track_id": "track_01", "cut_policy": "bar",
        "window": { "start_seconds": 12.44, "end_seconds": 22.24, "offset_seconds": 12.44 },
        "snap_grid": [0.0, 1.97, 3.94, 5.9, 7.87, 9.8],
        "hook": { "text": "you don't rise to the level of your goals",
                  "start_seconds": 0.06, "end_seconds": 2.31 },
        "caption": { "segments": [{ "start": 0.0, "end": 9.8, "text": "...", "words": [] }] },
        "caption_confidence": { "min": 0.71, "mean": 0.89, "low_confidence_words": 0 },
        "caption_source": "music_bed",
        "corrections": {} }
    ]
  }
}
```

- `total_duration_seconds` is the **sum of the planned reel durations** — delivered seconds,
  not a timeline length. Section times are reel-local and therefore overlap across sections;
  `metadata.timebase: "reel_local"` says so deliberately, so it does not read as a bug.
- `sections[].id` **is** the reel id, taken from `brief["metadata"]["reel_ids"]` —
  `scene_plan.scenes[].script_section_id` points straight at it, so it is spelled exactly as
  the brief spells it (underscore, zero-padded: `reel_01`) and never re-minted here.
- `snap_grid` is **reel-local and already offset**, so `snap_grid[0] == 0.0`, and it is the
  **only** grid `scene_plan` plans against. `beats_sec` / `downbeats_sec` are carried whole
  for audit and for a re-plan — a few hundred floats per track, and the reason `scene_plan`
  never re-runs the analyser — but slots are never re-derived from them. Absolute track time
  for any snap value is `snap_value + window["offset_seconds"]`, which is what a cut records
  downstream as `beat_seconds`.
- `caption.segments` is in the transcriber segment shape, ready for the burn's `segments`
  input.
- `caption_source` declares which audio these words came from. Write `"music_bed"` on every
  reel — it is the only member the schema accepts, and the only thing this pipeline can
  produce. Do not omit it on the grounds that it never varies: `edit` carries it onto the
  `reel_plan` entry by direct subscript, absence there reads as *undeclared* rather than as
  `music_bed`, and G5 checks for it. What the declaration is *for* is the pairing G2 can then
  assert — a reel declaring `music_bed` whose track was transcribed with `vad_filter: True`
  is a contradiction, because a VAD scores sung vocals as non-speech and throws them away.
  It does **not** prevent that; it makes it nameable after the fact.
  The other four candidates are refused for want of a producer and would fail validation:
  `speech_stem` (no stem separation exists in this repo), `video_sound` (the pool is never
  transcribed — `footage_library.py:323` passes `transcribe: False`, and `transcriber` is
  granted to this stage, which never sees the pool), `voice_over` (every track is music), and
  `none` (a captionless reel has no hook copy either, since `hook` is required on every
  `reel_plan` entry and its text is rebased off these words).
- This stage claims nothing against `lib/clip_ledger.py` — `claim()` (`:138`) belongs to
  `scene_plan`. Track windows are kept disjoint here by arithmetic and recorded above.

### 9. Quality Gate

- One `audiomap_path` and one `transcript_path` per track, both files on disk.
- Every reel carries `caption_source: "music_bed"`. A reel without it stops here rather than
  at `edit`, where the carry raises a `KeyError` with no useful message.
- `contamination` present for **every** track, with real numbers from `bg.data["speech"]` —
  a missing block means the transcript never reached `beat_grid` and the report was skipped.
- Every `window` is `<= 9.8` seconds and its `snap_grid` carries at least
  `cuts_per_reel + 1` boundaries — six for the standard five-cut reel. Fewer and
  `scene_plan`'s `cut_slots` raises `ValueError`. A `phrase`-policy reel reaches six only
  through the downbeat fallback in step 4's `snap_grid`; if even that is short, the track
  has no usable grid at this reel length and is escalated here rather than passed on.
- Every `snap_grid` is reel-local: `snap_grid[0] == 0.0` and `snap_grid[-1]` equals
  `window.end_seconds - window.start_seconds`, never a track-time value.
- Every hook is reel-local and opens within one beat — `hook["start_seconds"] <= 60.0 / bpm`
  — and closes on `hook["end_seconds"] <= snap_grid[2]`, the same bound as step 5 and the
  only bound: past `snap_grid[1]` is fine.
- Every caption line passes the standalone test and reports `low_confidence_words: 0`.
- No two reels share a `track_id`, and no two windows on one track overlap.
- Caption word times are reel-local — `words[0]["start"]` near `0.0`, not the track offset.

## Common Pitfalls

- **Grid before transcript.** `beat_grid` returns `speech: None` with no words to check
  against (`beat_grid.py:355`) — a grid and no verdict, and the verdict is the point.
- **Reading `speech: None` as "the track is clean."** It means *no verdict was reached*,
  which is a different thing, and there are two ways to get there. Check
  `bg.data["speech_warning"]`: it is `None` when no transcript was supplied, and a
  sentence naming the source and the entry count when one WAS supplied and not a single
  entry carried both a start and an end. That second case is a broken transcript wearing
  the same face as a clean instrumental — cut policy chosen from it is chosen from
  nothing. Fix the transcript and re-run rather than planning against the silence.
- **Cutting to the de-voiced proxy** because it looks cleaner. On a clean track it
  fabricates confidence (`beat_grid.py:302-311`).
- **Writing hook lines instead of finding them**, or choosing the window first and hunting
  for a hook inside it. A hook the track never says cannot be word-synced to it.
- **Storing track-relative caption times.** The burn adds no offset — every caption in the
  batch fires late by exactly the window start.
- **Passing a low-confidence word through because the sentence "reads fine".** Nothing
  downstream stops it; the renderer treats confidence as informational only.
- **Re-running `scene_detect` over the pool.** `footage_library` already ran it at `idea`
  and cached the boundaries under `<corpus_dir>/scene_cache/`
  (`tools/video/footage_library.py`) — read the resolved path from
  `index.data["corpus_dir"]` (it defaults to `projects/_footage_index/<pool>_<digest>`
  and is NOT under the project). Use `scene_detect` here only when a "track"
  arrived as a video file and you need its own shot boundaries.

## Checkpoint

`human_approval_default: false` for this stage — write it `completed` and continue to
`scene_plan` in the same turn. The next human gate is Gate 2.

```python
from lib.checkpoint import write_checkpoint
from lib.paths import PROJECTS_DIR
from tools.cost_tracker import CostTracker

# script is the artifact built in step 8; project_id is the run's project id.
tracker = CostTracker.for_project(project_id)
cost_snapshot = tracker.cost_snapshot()                       # the 3 canonical keys
cost_snapshot["budget_total_usd"] = tracker.budget_total_usd  # the 4th

write_checkpoint(PROJECTS_DIR, project_id, "script", "completed", {"script": script},
                 pipeline_type="reel-batch", cost_snapshot=cost_snapshot)
```

Pass the tracker's own snapshot straight through — `cost_snapshot` is closed to those four
number keys and the legacy `spent_usd` / `approved_budget_usd` names are rejected at write
time. Nothing was spent here, so the snapshot should match the one the `idea` checkpoint
carried; if it does not, something else wrote to the ledger — find out what before
continuing. Stranded entries and a corrupt ledger are handled the same way everywhere: see
`skills/meta/checkpoint-protocol.md` → **Cost Ledger Governance**, and do not improvise a
local variant of those rules here.
