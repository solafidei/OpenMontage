# Edit Director - Reel Batch Pipeline

## When To Use

Every cut slot has a real file and the batch is approved. This stage turns five
reels' worth of claimed segments into two artifacts: the **spine**
(`edit_decisions`) that every reel shares, and the **per-reel plan**
(`reel_plan`) carrying the axes the spine structurally cannot hold. It spends
nothing and calls no tools — the manifest gives it `tools_available: []` — and
reads the libraries directly in python fences.

## Prerequisites

| Layer | Resource | Purpose |
|-------|----------|---------|
| Schema | `schemas/artifacts/edit_decisions.schema.json` | Artifact validation |
| Prior artifact | `state.artifacts["scene_plan"]["scene_plan"]` | `metadata.reels[].cuts[]`, `scenes[].description`, `metadata.renderer_family` |
| Prior artifact | `state.artifacts["assets"]["asset_manifest"]` | `metadata.cut_index[cut_id]` (asset id + resolved in/out) and `metadata.reel_index[reel_id]` |
| Prior artifact (optional in the manifest, binding here) | `state.artifacts["script"]["script"]` | `metadata.reels[].hook.text`, `corrections`, `caption_confidence`. Step 6 subscripts `sr["hook"]["text"]` and `sr["caption_confidence"]` directly, so a run without `script` raises rather than degrading |
| Library | `lib/polish_filters.py` | Dry-run the batch look before you emit it |
| Library | `lib/clip_ledger.py` | `assert_no_reuse()` — the batch-wide audit |

## Mental Model — Why This Stage Emits Two Artifacts

`edit_decisions` is a single-deliverable schema, and the ceiling is visible in
the file:

- `audio.music` is one object with one `asset_id`
  (`schemas/artifacts/edit_decisions.schema.json:145-169`, `asset_id` at `:148`).
- `subtitles` is one object, closed to a fixed key set
  (`:185-200`, `additionalProperties: false` at `:199`).
- The root is `additionalProperties: false` (`:273`), so no `reels[]` array can
  be bolted on.

Five reels means five tracks and five subtitle files, and there is no honest
way to write that into one music object. So:

- **`edit_decisions` = the batch spine.** What the reels genuinely share:
  `renderer_family`, `render_runtime`, the effect vocabulary, the one batch
  look, and one flat `cuts[]` holding every cut of every reel. This satisfies
  `CANONICAL_STAGE_ARTIFACTS["edit"]` (`lib/checkpoint.py:31-41`,
  `"edit": "edit_decisions"` at `:38`) and keeps the validated cut schema.
- **`reel_plan` = the per-reel axes.** `reel_id`, `track_id`,
  `music_asset_id`, `subtitle_source`, `subtitle_srt_source`, `hook`,
  `cut_ids[]`, `corrections`, `caption_confidence`.

`compose-director` rebuilds each reel's own `edit_decisions` **in memory** by
filtering `cuts[]` on the reel prefix and merging that reel's `reel_plan`
entry. Nothing on disk ever claims to be a single-reel edit.

### `reel_plan` is not a registered artifact yet

`ARTIFACT_NAMES` (`schemas/artifacts/__init__.py:13-35`) does not list
`reel_plan`, and `_validate_artifacts_for_stage` skips any artifact name it
does not know — `if artifact_name not in ARTIFACT_NAMES: continue`
(`lib/checkpoint.py:157-158`). So today `reel_plan` is persisted but validated
by nobody: a typo, a missing `cut_ids`, a `music_asset_id` naming no asset all
pass the write silently. Registration in `ARTIFACT_NAMES` is what makes an
artifact real; declaring it in the manifest only makes it expected. Issue #47
registers it — until then **this director is the only guard on its shape**, so
assert it by hand (step 7).

## Process

### 0. Guardrails — What You May Not Change Silently

Per the Decision Communication Contract (`AGENT_GUIDE.md` → "Ask Before Major
Changes"), surface rather than fix quietly if a reel's cuts sum past **10
seconds of output time** (step 3 — ramps change the sum), a cut carries
`provenance: "operator_footage"` while its asset row says
`source_tool: "cutaway_gen"`, the approved look cannot be expressed
identity-safely (step 4), or you want to drop a cut the scene gate approved.

`renderer_family` and `render_runtime` were locked upstream and the schema says
edit MUST carry them forward unchanged
(`schemas/artifacts/edit_decisions.schema.json:228`, `:233`). Carry them.

### 1. Lock The Batch Spine

```python
scene_plan = state.artifacts["scene_plan"]["scene_plan"]
scene_meta = scene_plan["metadata"]
asset_manifest = state.artifacts["assets"]["asset_manifest"]
script_meta = state.artifacts["script"]["script"]["metadata"]

spine = {
    "version": "1.0",
    "renderer_family": scene_meta["renderer_family"],   # locked at idea, carried here
    "render_runtime": "ffmpeg",                          # the PICTURE plane
    "cuts": [],
    "subtitles": {...},                                  # step 5
    "metadata": {
        "pipeline": "reel-batch", "reel_count": 5,
        "identity_lock": True, "proposal_render_runtime": "ffmpeg",
        "batch_look": {...},                             # step 4
        "caption_style": {...},                          # step 5
    },
}
```

`render_runtime: "ffmpeg"` is not a downgrade — it is the R6 picture plane, and
it is load-bearing. Only that value routes to `_render_via_ffmpeg` → `_compose`
(`tools/video/video_compose.py:1706-1714`, `:1973`), and `_compose` is the
**only** path that calls `polish_filters.cut_filters` (`:623-626`). Set
`"remotion"` here and, **on a machine where Remotion is installed**, the render
takes the explicit Remotion path at `:1715-1716` — and `_needs_remotion` returns
`True` on these cuts because `transition_out` is set (`:1460`), not because of
any scene type, which `_REMOTION_SCENE_TYPES` (`:785-787`) would never match on
a cut carrying no `type` — so every punch-in, ramp, accent and the whole batch
look vanish silently. Where Remotion is absent
`_needs_remotion` returns `False` (`:1449-1451`) and the `else` branch calls
`_compose` anyway (`:1754-1775`), so the polish survives — by accident, on that
machine only. Write `ffmpeg`; do not rely on the accident. Captions are a
separate `remotion_caption_burn` pass `compose-director` runs over the finished
picture — the text plane never travels through this field.

`renderer_family` must be non-empty or compose blocks before rendering a frame
(`"No renderer_family in edit_decisions"` at `:1548-1554` is a hard block, not
a warning) even though the schema does not require it
(`schemas/artifacts/edit_decisions.schema.json:7`). You read it off
`scene_plan.metadata`, where `scene-director` copied it forward from
`brief.metadata`, so this stage never reaches back to the brief. The step 1
fence subscripts it: an absent key raises here, and an empty string sails
through to compose's hard block. Either way escalate rather than inventing a
value the closed enum (`:227`) would reject — for this pipeline the value is
`documentary-montage`, the only member describing cut-from-real-footage work.

Leave `metadata.compose_target` **unset**: `compose-director` renders at
`profile: instagram_reels` (1080x1920, `lib/media_profiles.py:70-79`) and a
portrait profile flips fit to `cover` on its own
(`tools/video/video_compose.py:510-515`), while an explicit
`compose_target.fit` beats the profile (`:502-504`) — a stray `"pad"` here
letterboxes all five reels.

### 2. Build One Flat `cuts[]` With Reel-Prefixed Ids

One array, every reel, in reel order then cut order. The ids were minted by
`scene-director` as `<reel_id>-<nn>`; copy them, never re-derive them by
enumeration — the ledger is already keyed on them, and the prefix is what
`compose-director` filters on.

Three producers feed one cut. The slot comes from `scene_plan`, the resolved
geometry and the asset id come from `asset_manifest.metadata.cut_index` (assets
do not exist at scene-plan time, and a substitute pick moves the in/out points),
and the one-line reason is the matching `scene_plan.scenes[].description`.

```python
cut_index = asset_manifest["metadata"]["cut_index"]
reason_for = {s["id"]: s["description"] for s in scene_plan["scenes"]}

for reel in scene_meta["reels"]:                  # reel_id: "reel_01" ...
    for slot in reel["cuts"]:                     # NOT "slots"
        cut_id = slot["id"]                       # minted at scene_plan; never re-derived
        idx = cut_index[cut_id]                   # KeyError here is the feature
        spine["cuts"].append({
            "id": cut_id,
            "source": idx["asset_id"],            # an asset_manifest assets[].id
            "in_seconds": idx["in_seconds"],      # resolved geometry, not the plan's
            "out_seconds": idx["out_seconds"],
            "speed": slot.get("speed", 1.0),
            "layer": "primary",
            "transition_in": "cut",
            "transition_out": "cut",
            "provenance": slot["provenance"],     # copied, never inferred
            "reason": reason_for[cut_id],
            "polish": {...},                      # step 3
        })
```

- **`source` is an asset id, not a path.** `video_compose` resolves ids through
  `asset_lookup` before rendering (`tools/video/video_compose.py:1630-1636`).
- **`in_seconds`/`out_seconds` come from `cut_index`, not from the slot.** The
  asset stage is what knows the geometry that actually shipped; an AI cutaway
  has no in/out on the slot at all.
- **`provenance` is copied forward from the scene slot**, per R5 — declared at
  ingest, never read off the pixels. `asset_manifest.assets[]` has no
  `provenance` field (its items are `additionalProperties: false`), so
  cross-check the slot's value against **both** `cut_index[cut_id]["provenance"]`
  and the asset's `source_tool`: `cutaway_gen` ⇒ `ai_generated`,
  `footage_library` ⇒ `operator_footage`. A mismatch escalates; it is not
  reconciled here.
- **Every cut gets a one-line `reason`.** Called without a `scene_plan`, the
  pre-compose slideshow scorer synthesises its scenes from `cuts[].reason`
  (`:1513-1526`) — blank reasons make a real edit score as a slideshow.
- Keep `transition_in`/`transition_out` at `"cut"`: segments are concat-copied,
  so a cross-boundary transition cannot exist (`lib/polish_filters.py:32-34`) —
  the accent lives in `polish` instead.

### 3. The Polish Vocabulary — Order Is Load-Bearing

The per-cut block is closed to exactly three keys
(`schemas/artifacts/edit_decisions.schema.json:70-93`):

| key | type | bounds | schema |
|---|---|---|---|
| `punch_in` | number | `1.0`–`4.0` (1.0 = none) | `:74-79` |
| `speed_ramp` | number | `0.1`–`10.0`, ramps from `speed` | `:80-85` |
| `transition_out` | string | `"flash"` \| `"whip"` | `:86-90` |

`additionalProperties: false` at `:92`; the same bounds are restated at
`lib/polish_filters.py:40-41` so a hand-built cut that skipped validation still
cannot smuggle a nonsense zoom into ffmpeg.

`cut_filters` emits the chain in exactly one order — **punch-in → speed → look
→ tail accent** (`lib/polish_filters.py:214-240`). That order is why the speed
filter lives in this module and not in `_compose`: `zoompan` re-times its own
output at its own fps, so a punch-in placed *after* `setpts` silently throws
the ramp away and the segment comes out its original length (`:202-213`).

**Ramps change the reel's wall length.** A 10-second reel is 10 seconds of
*output*, and `output_duration` divides by the ramp's logarithmic-mean speed,
not by the endpoint (`:114-118`, `:102-111`). Sum with the real function:

```python
from lib.polish_filters import output_duration

def reel_seconds(cuts):
    return sum(
        output_duration(
            c["out_seconds"] - c["in_seconds"],
            c.get("speed", 1.0),
            (c.get("polish") or {}).get("speed_ramp"),
        )
        for c in cuts
    )
```

A 2.0s cut ramped 1.0 → 2.0 lands at 1.386s, not 1.0s. Budget from
`reel_seconds`, never from `sum(out - in)`.

**Accent tails.** `flash` is a 0.10s blow-out to white, `whip` a 0.12s
directional blur (`:35-36`). `flash_out` clamps its tail to the cut it is on
(`:128`); `whip_out` does not (`:133-144`) — it gates its two `gblur` stages at
`max(end - span, 0)` for spans `0.12` and `0.06`, so the first gate opens at
`t=0` below ~0.12s and both collapse to `t=0` below ~0.06s: the tail smears
across most or all of the cut. Keep `whip` off anything under ~0.4s of output.
House vocabulary: punch-in
`1.10`–`1.25` on the hook cut and the last cut, at most one `speed_ramp` per
reel, `flash` on the beat hit, `whip` only between two moving shots. Three
effects in five cuts is an edit; five is a seizure.

### 4. One Look For The Whole Sitting — And The Identity Rule

The batch look is `{"grade": ..., "grain": ..., "sharpen": ...}`, stamped
identically on every cut of every reel. `edit_decisions` has no typed slot for
it, so it rides in `metadata.batch_look` — `metadata` is open (no
`additionalProperties: false`, `schemas/artifacts/edit_decisions.schema.json:263-271`),
the same route `compose_target`
already takes to the renderer (`tools/video/video_compose.py:496-503`).
`compose-director` hands it over as `video_compose`'s `batch_look` input
(`:205-219`, grade/grain/sharpen at `:215-217`), read at `:485` and applied per
cut at `:623-626`.

**The identity rule raises; it does not drop.** `look_filters` refuses a
`color_grade` profile on an `operator_footage` cut
(`lib/polish_filters.py:169-173`) and refuses any non-zero grain on one
(`:179-180`). A sitting is almost entirely operator footage, so a real grade
profile does not "mostly work" — it kills the render at the first operator cut,
by design, rather than grading four fifths of a batch the operator never
approved. So build the look from `face_enhance.PRESETS`, which resolve on
locked and unlocked cuts alike: `brighten`, `contrast_boost`, `cool`,
`denoise`, `sharpen`, `sharpen_light`, `soft_skin`, `talking_head_standard`,
`warm` (`tools/enhancement/face_enhance.py:26`). The `color_grade.PROFILES`
names — `bright_clean`, `cinematic_cool`, `cinematic_warm`, `high_contrast`,
`moody_dark`, `neutral`, `vintage_film` (`tools/enhancement/color_grade.py:25`)
— are reachable only on a batch with zero operator cuts, which this pipeline
never has. If the operator asked for one, say so and log it; do not downgrade
it quietly.

**Precedence trap:** `grade` is matched against `FACE_PRESETS` *first*
(`lib/polish_filters.py:163-175`), so `grade: "warm"` resolves to the face-enhance `warm` filter on
every cut and never raises — it is not a grade profile at all. Dry-run the look
against the strictest cut before emitting:

```python
from lib.polish_filters import look_filters, PolishError

look = {"grade": "talking_head_standard", "sharpen": "sharpen_light"}
try:
    look_filters(look, "operator_footage")   # the identity-locked case
except PolishError as exc:
    ...  # escalate: this look cannot ship on this batch
```

Leave `grain` out entirely: it is refused on every operator cut anyway, and
`look_filters` never bounds its magnitude — only `video_compose`'s input schema
declares `minimum: 0` (`tools/video/video_compose.py:216`).

### 5. Caption Style — `reel_pop` And The 9:16 Safe Zone

This stage owns caption **style**; the transcript came from `script` and the
burn happens at `compose`. Two places to write it, because the typed block is
closed:

```python
spine["subtitles"] = {          # typed — edit_decisions.schema.json:185-200
    "enabled": True,
    "style": "word-by-word",
    "position": "bottom-center",
    "max_words_per_line": 3,
}
spine["metadata"]["caption_style"] = {   # what the typed block cannot express
    "preset": "reel_pop",
    "safe_zone": {"bottom": 0.18, "sides": 0.08},
}
```

**3 is the batch's one caption density.** It is the same number as
`asset-director`'s `max_words_per_cue` and `compose-director`'s
`words_per_page`: three names for one figure, and they must not drift apart.
`safe_zone` is authored **here and only here** — `compose-director` reads it
back off `edit_decisions.metadata.caption_style.safe_zone` and passes it to the
burn rather than re-typing the literal.

`remotion_caption_burn` accepts `preset` from `["default", "reel_pop"]`
(`tools/video/remotion_caption_burn.py:115-124`, `PRESETS` at `:507`).
`reel_pop` is the 9:16 short-form look: per-word scale pop, heavy stroke,
uppercase, no pill, and a proportional safe zone (`:120-123`). `safe_zone` is
closed to `("bottom", "sides")` (`_SAFE_ZONE_KEYS` at `:511`, enforced at
`:538-545`) — an unknown key is rejected loudly here because the TS side would
ignore it silently and land the caption in the wrong place. `bottom` is
required (`:546-547`) and each value is a fraction of the frame in `[0, 0.5)`
(`:556-557`). `bottom: 0.18` is the documented figure for clearing Instagram's
own lower UI band (`:125-133`).

**Do not set `subtitles.source` on the spine.** One `source` cannot name five
subtitle files, and `_compose` reads `subtitles["source"]` *without* checking
`enabled` (`tools/video/video_compose.py:538-540`) — a source left here burns a
static SRT into the picture plane underneath the Remotion pop captions: two
caption tracks, one video. The per-reel caption asset id lives in
`reel_plan.subtitle_source`; for the same reason the per-reel track lives in
`reel_plan.music_asset_id` and `audio.music` stays off the spine. One note for
compose: without Remotion the tool falls back to a static SRT burn and reports
`degraded: True` with `unhonoured_inputs`
(`tools/video/remotion_caption_burn.py:614-640`) — a downgrade to surface, not
to swallow.

### 6. Emit `reel_plan`

```python
reel_index = asset_manifest["metadata"]["reel_index"]
script_by_reel = {r["reel_id"]: r for r in script_meta["reels"]}

reel_plan = {"version": "1.0", "reels": []}
for reel in scene_meta["reels"]:
    rid = reel["reel_id"]
    idx, sr = reel_index[rid], script_by_reel[rid]
    reel_plan["reels"].append({
        "reel_id": rid,
        "track_id": idx["track_id"],
        "music_asset_id": idx["music_asset_id"],              # an asset id
        "subtitle_source": idx["subtitle_json_asset_id"],     # an asset id
        "subtitle_srt_source": idx["subtitle_srt_asset_id"],  # an asset id
        "hook": sr["hook"]["text"],                           # a string
        "cut_ids": idx["cut_ids"],                            # reel order
        "corrections": sr.get("corrections", {}),
        "caption_confidence": sr["caption_confidence"],
    })
```

One entry per reel, in reel-id order — `publish-director` picks the posting
order later, from its own strength ranking.

- `track_id`, `music_asset_id`, `subtitle_source` and `subtitle_srt_source`
  come from `asset_manifest["metadata"]["reel_index"][reel_id]`. The last three
  are **asset ids**, not paths: `compose-director` resolves each through
  `asset_manifest.assets[].id` → `.path` and only then opens the file. Writing
  `assets/subtitles/reel_01.json` here is the mistake that makes the resolve
  fail silently.
- `hook` is a **string** — `script.metadata.reels[].hook.text`, not the hook
  object. Compose hands it straight to the `hero_title` overlay and
  `publish-director` reuses it as `metadata_used.title` rather than re-deriving
  caption copy.
- `cut_ids` are in reel order and, across the batch, partition
  `edit_decisions.cuts[]` exactly (asserted in step 7).
- `corrections` (`{wrong: right}`) and `caption_confidence` are carried from
  `script["metadata"]["reels"][i]` so compose can pass corrections to the burn
  and re-report confidence without opening an artifact its stage never
  declares.

### 7. Audit Before You Checkpoint

```python
from lib.clip_ledger import ClipLedger

ClipLedger.for_project(project_id).assert_no_reuse()   # raises ClipReuseError
asset_ids = {a["id"] for a in asset_manifest["assets"]}
cut_ids = [c["id"] for c in spine["cuts"]]
assert len(cut_ids) == len(set(cut_ids))
assert all(c["source"] in asset_ids for c in spine["cuts"])
planned = [cid for r in reel_plan["reels"] for cid in r["cut_ids"]]
assert sorted(planned) == sorted(cut_ids)              # exactly one reel each
for r in reel_plan["reels"]:
    prefix = f"{r['reel_id']}-"
    assert all(cid.startswith(prefix) for cid in r["cut_ids"])
    assert isinstance(r["hook"], str)                  # the text, not the object
    for key in ("music_asset_id", "subtitle_source", "subtitle_srt_source"):
        assert r[key] in asset_ids                     # nothing else checks this
    assert reel_seconds([c for c in spine["cuts"]
                         if c["id"].startswith(prefix)]) <= 10.0
```

`assert_no_reuse` walks the live claims and raises if two reels overlap on one
source (`lib/clip_ledger.py:216-228`). Run it here even though `scene_plan`
claimed the segments — this is the last stage that can fix a collision cheaply.

### 8. Quality Gate

- `edit_decisions` validates, `render_runtime == "ffmpeg"`, `renderer_family`
  non-empty.
- One flat `cuts[]` covering every reel; ids `<reel_id>-` prefixed and unique;
  every `source` an `asset_manifest` id; every cut has `provenance` and a
  one-line `reason`.
- Every `polish` value inside its bounds; no `whip` on a sub-0.4s cut.
- `reel_seconds(...) <= 10.0` for every reel.
- `metadata.batch_look` survives `look_filters(look, "operator_footage")`; no
  grain; no `color_grade` profile name.
- `subtitles` set, `subtitles.source` absent, `audio.music` absent.
- `reel_plan` has one entry per reel and its `cut_ids` partition `cuts[]`;
  `music_asset_id`, `subtitle_source` and `subtitle_srt_source` all resolve in
  `asset_manifest.assets[].id`; `hook` is a string; `corrections` and
  `caption_confidence` are present.

### 9. Checkpoint

`human_approval_default: false` here — write `completed` and carry on to
compose. Pull the cost snapshot from the ledger, never from memory: it is
closed to four number keys and hand-written legacy keys are rejected at write
time.

```python
from tools.cost_tracker import CostTracker
from lib.checkpoint import write_checkpoint, PROJECTS_DIR

tracker = CostTracker.for_project(project_id)
snapshot = tracker.cost_snapshot()
snapshot["budget_total_usd"] = tracker.budget_total_usd
write_checkpoint(
    PROJECTS_DIR, project_id, "edit", "completed",
    {"edit_decisions": spine, "reel_plan": reel_plan},
    pipeline_type="reel-batch",
    cost_snapshot=snapshot,
)
```

This stage books no spend of its own. Ledger hygiene — stranded entries,
corrupt ledgers, who resolves what — lives in
`skills/meta/checkpoint-protocol.md` → **Cost Ledger Governance**; read it
there rather than here. Which paid tools are armed at all is settled by the
cost gate in `idea-director.md`.

## Common Pitfalls

- **Writing `render_runtime: "remotion"` because the captions are Remotion.**
  The field routes the *picture* plane — on any machine with Remotion
  installed, that is the difference between a polished reel and five flat
  concats.
- **Summing `out - in` to check the 10-second rule.** Any ramped cut makes that
  number wrong.
- **A `color_grade` profile in the batch look.** It raises on the first
  operator cut and takes the sitting with it. That is the guarantee working.
- **Leaving `subtitles.source` or `audio.music` on the spine.** `audio.music`
  is the one that cannot honestly name five tracks; `subtitles.source` is the
  one that double-burns, because `_compose` reads `source` without checking
  `enabled`.
- **Smuggling per-reel values into `edit_decisions.metadata`.** The block is
  open, so it validates — and then nothing reads it and no gate asserts on it.
  Per-reel axes belong in `reel_plan`, whose shape only this stage checks.
- **Per-cut looks.** One grade across the batch is a product promise from the
  brief, not a default to vary because a clip looked flat.
