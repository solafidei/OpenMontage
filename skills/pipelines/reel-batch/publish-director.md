# Publish Director - Reel Batch Pipeline

## When To Use

Five reels are rendered and `final_review` says they are presentable. Your job is to turn a
`renders/` folder into a week of posts: caption copy and a hashtag set written **per reel**, a
posting order with a spacing rule, a credit line wherever a track needs one, and an export bundle
the operator can work from on his phone. Output is one `publish_log` plus the export tree.

## This Stage Prepares And Records. It Does Not Post.

There is no social API in this repo. The only `ToolTier.PUBLISH` tool that exists is
`export_bundle` (`tools/publishers/export_bundle.py:42`); it declares `"uploads": False` (`:59`)
and its docstring says the packaging is local — "no external account, no upload" (`:8-9`).

So the honest terminal status for an entry is `"exported"`: the file is packaged and the copy is
written, and **the operator posts it**. Write `"published"` with a `url` only if he later comes
back and says he posted — that is a revision of this artifact, never something you predict.

This stage's `tools_available` is `[]`, and `export_bundle` would not fit anyway: one `video_path`
per call, a fixed `video/output.<ext>` filename (`:188`), one entry per `publish_log` (`:267`) —
five reels through it on the default export dir overwrite each other. Lay the tree out directly.

## Prerequisites

| Layer | Resource | Purpose |
|-------|----------|---------|
| Schema | `schemas/artifacts/publish_log.schema.json` | Artifact validation |
| Prior artifact | `state.artifacts["compose"]["render_report"]` | One `outputs[]` entry per reel, plus the `metadata.reels[]` reel↔path join |
| Prior artifact | `state.artifacts["compose"]["final_review"]` | The verdict you are not allowed to launder |
| Prior artifact | `state.artifacts["edit"]["reel_plan"]` | The per-reel axes — `reel_id`, `track_id`, `hook`, `music_asset_id`, the subtitle sources, `cut_ids[]` |
| Prior artifact | `state.artifacts["edit"]["edit_decisions"]` | The cut spine — what each reel actually shows |
| Prior artifact | `state.artifacts["assets"]["asset_manifest"]` | The track's `provider` / `license` / `original_url` |
| Prior artifact (optional) | `state.artifacts["idea"]["brief"]` | Batch tone, `cta`, `target_platform` |
| Library | `lib/clip_ledger.py` — `ClipLedger.for_project(project_id)` | The segment trail behind each reel; settles on approval |

`edit_decisions` and `asset_manifest` are not in this stage's `optional_artifacts_in`. Read them
from their own checkpoints anyway: those keys are declarations for the orchestrator, not access
control — no Python reads either one, they exist only in
`schemas/pipelines/pipeline_manifest.schema.json:85-93`.

## Mental Model

**Five reels, five captions, five hashtag sets, five slots.** One caption pasted across a batch is
the failure this stage exists to prevent — the reels already share a grade, a pool and a sitting,
so identical copy makes five posts read as one post shown five times.

The other half is the trail: each reel points back at the track it used and the segments it
consumed, because "which of these five used the licensed track" has a real answer and this is
where it gets written down.

## Process

### 1. Rebuild The Batch Roster

`render_report.outputs[]` is `additionalProperties: false` and carries **no `reel_id` field**
(`schemas/artifacts/render_report.schema.json:13-26`), so compose writes the join itself:
`render_report.metadata.reels[]`, one entry per reel carrying `reel_id` and that reel's output
`path`. **That array is the join.** Fall back to matching the filename stem only when it is absent —
and when you do, say in the gate summary that reel identity was *inferred* from filenames, not read.

The fallback matches `stem == rid` and nothing looser. `outputs[]` lists only the captioned masters;
compose's picture intermediates at `renders/<reel_id>-picture.mp4` are never listed, and a prefix
match is exactly what would bind one to a reel — and, on an unconditional assignment, let the
intermediate overwrite the master. Two outputs for one reel is a send-back, not a last-write-wins.

```python
from pathlib import Path
from lib.checkpoint import PROJECTS_DIR, read_checkpoint

compose_cp = read_checkpoint(PROJECTS_DIR, project_id, "compose")
edit_cp = read_checkpoint(PROJECTS_DIR, project_id, "edit")
assets_cp = read_checkpoint(PROJECTS_DIR, project_id, "assets")

render_report, final_review = compose_cp["artifacts"]["render_report"], compose_cp["artifacts"]["final_review"]
spine, reel_plan = edit_cp["artifacts"]["edit_decisions"], edit_cp["artifacts"]["reel_plan"]
asset_manifest = assets_cp["artifacts"]["asset_manifest"]

by_reel = {r["reel_id"]: r for r in render_report.get("metadata", {}).get("reels", [])}
plan_by_reel = {r["reel_id"]: r for r in reel_plan["reels"]}
out_by_path = {o["path"]: o for o in render_report["outputs"]}

unlisted = [rid for rid, r in by_reel.items() if r["path"] not in out_by_path]
if unlisted:
    raise RuntimeError(f"metadata.reels[] names paths absent from outputs[]: {unlisted}")

output_for = {}                       # only built when metadata.reels[] is missing
if not by_reel:
    for out in render_report["outputs"]:
        stem = Path(out["path"]).stem
        hits = [rid for rid in plan_by_reel if stem == rid]
        if len(hits) != 1:
            raise RuntimeError(f"{out['path']!r} maps to {hits} — send back to compose for reel-named outputs")
        if hits[0] in output_for:
            raise RuntimeError(f"{hits[0]} resolves to two outputs — one captioned master per reel")
        output_for[hits[0]] = out

missing = [rid for rid in plan_by_reel if rid not in (by_reel or output_for)]
if missing:
    raise RuntimeError(f"reel_plan reels with no rendered output: {missing}")
```

**`reel_plan` is not yet a registered artifact.** It is absent from `ARTIFACT_NAMES`
(`schemas/artifacts/__init__.py:13-35`), and `lib/checkpoint.py:156-158` skips validation for any
artifact name it does not know — so `reel_plan` rode into the edit checkpoint **unvalidated**. It is
the last hand-guard before publish, so check the whole shape, not the four keys you happen to use:
every entry needs `reel_id`, `track_id`, `music_asset_id`, `subtitle_source`, `subtitle_srt_source`,
`hook`, `cut_ids`, `corrections` and `caption_confidence`, `reel_id` values are unique, and the
`cut_ids` partition `edit_decisions.cuts[]` exactly.

```python
REEL_PLAN_KEYS = ("reel_id", "track_id", "music_asset_id", "subtitle_source",
                  "subtitle_srt_source", "hook", "cut_ids", "corrections", "caption_confidence")

for rid, plan in plan_by_reel.items():
    absent = [k for k in REEL_PLAN_KEYS if k not in plan]
    assert not absent, f"{rid}: reel_plan entry is missing {absent}"
assert len(plan_by_reel) == len(reel_plan["reels"]), "duplicate reel_id in reel_plan"

planned = [cid for plan in plan_by_reel.values() for cid in plan["cut_ids"]]
assert sorted(planned) == sorted(c["id"] for c in spine["cuts"]), \
    "reel_plan cut_ids do not partition edit_decisions.cuts[] exactly"

roster = {}
for rid, plan in plan_by_reel.items():
    rr = by_reel.get(rid)                        # authoritative join; stem match only if absent
    roster[rid] = {
        "output": out_by_path[rr["path"]] if rr else output_for[rid],
        "hook": plan["hook"],                    # a string — script's hook.text, carried by edit
        "cut_ids": plan["cut_ids"],
        "music_asset_id": plan["music_asset_id"],
        "caption": None,           # written in step 3
        "hashtags": [],            # written in step 3
        "credit": None,            # written in step 4
        "posting_slot": None,      # written in step 5
    }
```

**Those eight keys are the whole of `roster`, and every later fence in this file reads only them.**
Two more locals join it as the run goes on: **`posting_order`** is step 5's strength ordering — a
list of reel ids over `roster`, not `reel_plan` order — and **`shipped_reel_ids`** is the operator's
answer at step 8, the reels he approved, which is the list step 9 settles.

If `reel_plan` is missing entirely, derive the reel ids from the `reel_NN-` prefixes on
`spine["cuts"][*]["id"]` (`cid.rsplit("-", 1)[0]`, keeping the canonical `reel_01` spelling) and say
so in your gate summary — but you will then be reconstructing hooks and asset ids by hand, so prefer
sending back to `edit` for a `reel_plan`.

### 2. Refuse To Package A Reel That Did Not Render

`final_review.status` is an enum of `pass | needs_verification | revise | fail`
(`schemas/artifacts/final_review.schema.json:22-31`), and the artifact's own top-level description
(`:5`) is explicit: on `needs_verification`, `revise` or `fail` the agent **must not present the
video as complete**. A clean-looking bundle around an unverified file launders exactly that verdict.

```python
if final_review["status"] != "pass":
    raise RuntimeError(
        f"final_review.status={final_review['status']!r} — send back to compose "
        f"(recommended_action={final_review.get('recommended_action')!r})"
    )

def under_root(p):
    """Rebase a project-relative render path onto the absolute PROJECTS_DIR.

    `render_report` writes `projects/<id>/renders/...`; PROJECTS_DIR is absolute and honours
    OPENMONTAGE_PROJECTS_DIR, so neither this check nor the step 6 copy depends on the cwd.
    """
    q = Path(p)
    if q.is_absolute():
        return q
    assert q.parts[0] == "projects", f"{p!r} is neither absolute nor under projects/"
    return PROJECTS_DIR.joinpath(*q.parts[1:])

for rid, r in roster.items():
    out = r["output"]
    path = under_root(out["path"])
    assert path.is_file() and path.stat().st_size > 0, f"{rid}: {path} missing or empty"
    assert out["resolution"] == "1080x1920", f"{rid}: {out['resolution']} is not a 9:16 reel"
    assert out["duration_seconds"] <= 10.0, f"{rid}: {out['duration_seconds']}s breaks the 10s promise"
    assert out.get("file_size_bytes", 0) <= 250 * 1024 * 1024, f"{rid}: over the 250 MB reels ceiling"
```

250 MB is the profile's number — `INSTAGRAM_REELS` sets `max_file_size_mb=250`
(`lib/media_profiles.py:70-79`). The 10s ceiling is this pipeline's own promise; the profile's
`max_duration_seconds=90` is Instagram's limit, not the bar here.

### 3. Write The Copy, One Reel At A Time

Open one reel and finish it before opening the next — drafting five captions in one pass from the
brief is how a batch ends up with five paraphrases of one sentence. The inputs for reel `rid` are
its own: `roster[rid]["hook"]`, the cuts named by `roster[rid]["cut_ids"]`, and the batch `cta` from
`brief`.

A cut does not carry a filename. `edit_decisions.cuts[].source` is an **asset id**; resolve it
through `asset_manifest.assets[]` before you write a word about what the reel shows, or the copy
describes an id.

```python
asset_by_id = {a["id"]: a for a in asset_manifest["assets"]}
cut_by_id = {c["id"]: c for c in spine["cuts"]}

def shows(rid):
    """(cut_id, clip path, how it was sourced, provenance) per cut, in reel order."""
    for cid in roster[rid]["cut_ids"]:
        cut = cut_by_id[cid]
        asset = asset_by_id[cut["source"]]      # source is an asset id, never a path
        yield cid, asset["path"], asset.get("generation_summary", ""), cut.get("provenance")
```

**Caption — four lines, in this order:**

1. **The hook, re-voiced for reading.** The card is *watched*, the caption is *read*; repeating it
   word for word makes the post look duplicated.
2. **What this reel actually shows**, read off `shows(rid)`. Never name a movement absent from
   `cut_ids`.
3. **A CTA, varied across the batch.** Five identical closers read as automation; rotate the
   phrasing of `brief["cta"]` per reel.
4. **The credit line** when step 4 says the track needs one — last, so the operator sees it
   survived the copy-paste.

**Hashtags — three rings:**

- **Broad (2-3)** — shared across the batch. Overlap here is correct.
- **Movement-specific (3-4)** — from *this reel's* cuts. This ring is what makes the sets differ,
  because the cut lists differ.
- **Owned (1-2)** — the operator's own tag, constant.

Each reel's copy lands on its own roster entry as you finish it — `roster[rid]["caption"]` is the
four lines joined by newlines, `roster[rid]["hashtags"]` the three rings concatenated. Then check
what you actually promised, rather than trusting yourself:

```python
assert all(r["caption"] and r["hashtags"] for r in roster.values()), "a reel was left without copy"
captions = {rid: r["caption"] for rid, r in roster.items()}
tagsets = {rid: tuple(sorted(r["hashtags"])) for rid, r in roster.items()}
assert len(set(captions.values())) == len(captions), "two reels share caption copy"
assert len(set(tagsets.values())) == len(tagsets), "identical hashtag sets — one was not written from its own cut list"
```

If that fires, rewrite from the cut list; do not shuffle a tag to get past it.

### 4. Track Credit

The track is the reel's `music_asset_id` resolved against the manifest; the credit fields are
`provider`, `license` and `original_url` (`schemas/artifacts/asset_manifest.schema.json:34-36`).

```python
music_by_id = {a["id"]: a for a in asset_manifest["assets"] if a["type"] == "music"}

def credit_for(reel_entry):
    track = music_by_id.get(reel_entry["music_asset_id"])
    assert track is not None, f"{reel_entry['music_asset_id']} is not a type='music' asset — send back to edit"
    if not track.get("license"):
        return None  # unknown terms — ask, do not assume
    return " · ".join(p for p in (track.get("provider"), track["license"], track.get("original_url")) if p)

for r in roster.values():
    r["credit"] = credit_for(r)          # roster entries carry music_asset_id, so this reads them
```

A track with no `license` usually came out of `music_library/` — the operator's own drop
(AGENT_GUIDE.md → "Music Library"). **Absent terms are not permissive terms.** Ask him once per
track, record the answer in the caption and in `trace.json`, and reuse it for every reel on that
track. Two reels on one track carry the same credit line; that is the one string it is right to
repeat.

### 5. Posting Order And Spacing

**Order by strength, not by reel id.** Lead with the reel whose hook lands hardest and whose
opening cut is cleanest, and never put two reels with near-identical opening cuts next to each
other — one pool and one grade means adjacent lookalikes read as a re-upload.

**Spacing — the default this pipeline recommends:**

- one reel per day, five days, at the operator's usual posting hour;
- if he wants it compressed: no two reels inside **6 hours**, at most two in a day;
- never two reels in the same hour, under any compression.

`posting_order` is that ruling written down: a list of reel ids, strongest first, over the same keys
as `roster`. The slot it implies lands on each roster entry.

```python
from datetime import datetime, timedelta

posting_order = ["reel_01", "reel_04", "reel_02", "reel_05", "reel_03"]   # strongest first
assert sorted(posting_order) == sorted(roster), "posting_order must cover every reel exactly once"

first_slot = datetime.fromisoformat("2026-09-04T18:30:00")    # his usual posting hour, local time
for i, rid in enumerate(posting_order):
    roster[rid]["posting_slot"] = (first_slot + timedelta(days=i)).isoformat()
```

A five-reel sitting covers a week, not an afternoon. Put the rule and the resulting slots in the
gate summary as a recommendation — he overrides it there, and his override is what you write, both
into `posting_order` and into the slots. The repo schedules nothing: `posting_slot` is a local
ISO-8601 datetime he posts at himself; there is no timer, no queue and no job that fires.

### 6. Lay Out The Export Package

Renders stay where compose wrote them; the bundle **copies**. A re-render of one reel then does not
have to reconstruct the tree, and nothing under `renders/` is mutated by a packaging step.

```
projects/<project-id>/exports/
├── batch/
│   ├── posting_schedule.txt     # order, slot and hook per reel — readable on a phone
│   └── batch_manifest.json      # reel -> file, track, cut_ids, claim segments
├── reel_01/
│   ├── reel_01.mp4              # copied from renders/, named by reel id
│   ├── caption.txt              # the four lines, ready to paste
│   ├── hashtags.txt             # one tag per line
│   ├── credit.txt               # written only when the track needs one
│   └── trace.json               # reel_id, output path, cut_ids, claims, track asset
└── reel_02/ …
```

`projects/<id>/exports/` is what `export_bundle` itself defaults to for a render under
`projects/<id>/renders/` (`tools/publishers/export_bundle.py:288-299`), so the bundle lands where
the tooling already looks. The per-reel subdirectory is the deviation: one flat bundle cannot hold
five videos.

```python
import json, shutil
from lib.clip_ledger import ClipLedger

ledger = ClipLedger.for_project(project_id)
ledger.assert_no_reuse()   # ClipReuseError if two live claims overlap on one source

exports = PROJECTS_DIR / project_id / "exports"
for rid, r in roster.items():
    d = exports / rid
    d.mkdir(parents=True, exist_ok=True)
    src = under_root(r["output"]["path"])
    shutil.copy2(src, d / f"{rid}{src.suffix}")
    (d / "caption.txt").write_text(r["caption"] + "\n", encoding="utf-8")
    (d / "hashtags.txt").write_text("\n".join(r["hashtags"]) + "\n", encoding="utf-8")
    if r["credit"]:
        (d / "credit.txt").write_text(r["credit"] + "\n", encoding="utf-8")
    (d / "trace.json").write_text(json.dumps({
        "reel_id": rid, "output_path": r["output"]["path"],
        "track_asset_id": r["music_asset_id"], "track_credit": r["credit"],
        "cut_ids": r["cut_ids"],
        "claims": ledger.claims_for_reel(rid),   # source + [in, out) per segment
    }, indent=2), encoding="utf-8")

batch = exports / "batch"                    # the two batch files the tree promises
batch.mkdir(parents=True, exist_ok=True)
(batch / "batch_manifest.json").write_text(json.dumps(
    {rid: {"output_path": roster[rid]["output"]["path"],
           "track_asset_id": roster[rid]["music_asset_id"],
           "cut_ids": roster[rid]["cut_ids"],
           "claims": ledger.claims_for_reel(rid)}
     for rid in posting_order}, indent=2), encoding="utf-8")
(batch / "posting_schedule.txt").write_text("\n".join(
    f"{roster[rid]['posting_slot']}  {rid}  {roster[rid]['hook']}" for rid in posting_order
) + "\n", encoding="utf-8")
```

The `batch/` pair is written here, after step 5 set every `posting_slot`, and keyed in
`posting_order` so both files read as the schedule. `batch_manifest.json` is the path
`publish_log.metadata.batch_manifest` points at in step 7 — write it or that key names nothing.

`claims_for_reel` returns every claim the reel ever made, live or settled
(`lib/clip_ledger.py:192-195`), each with `source`, `in_seconds`, `out_seconds` and `claim_id`
(`:250-259`). That list **is** the cut-list traceability: `cut_ids` says which cuts, the claims say
which frames of which file. `assert_no_reuse()` covers reconciled claims too — a reconciled claim
still holds its segment out of the pool (`:63-65`).

### 7. Build The publish_log

The entry object is **closed** (`schemas/artifacts/publish_log.schema.json:34`): `platform`,
`status`, `url`, `video_id`, `visibility`, `export_path`, `timestamp`, `metadata_used`, `error`,
nothing else. `metadata_used` is **open** — four declared properties, no
`additionalProperties: false` (`:23-31`) — and top-level `metadata` is a free object (`:37`). So
reel id, output path, credit and slot go *inside* `metadata_used`; a sibling key on the entry fails
validation at write time.

```python
from datetime import datetime, timezone
from schemas.artifacts import validate_artifact

now = datetime.now(timezone.utc).isoformat()
entries = [{
    "platform": "instagram_reels",
    "status": "pending_review",          # -> "exported" once the operator approves
    "export_path": f"projects/{project_id}/exports/{rid}",
    "timestamp": now,
    "metadata_used": {
        "title": roster[rid]["hook"], "description": roster[rid]["caption"],
        "hashtags": roster[rid]["hashtags"], "reel_id": rid,
        "output_path": roster[rid]["output"]["path"], "cut_ids": roster[rid]["cut_ids"],
        "track_credit": roster[rid]["credit"], "posting_slot": roster[rid]["posting_slot"],
    },
} for rid in posting_order]

publish_log = {"version": "1.0", "entries": entries, "metadata": {
    "posting_order": posting_order,
    "spacing_rule": "one reel per day; floor 6h apart, max two per day if compressed",
    "batch_manifest": f"projects/{project_id}/exports/batch/batch_manifest.json",
    "posted_by": "operator — this pipeline exports only",
}}
validate_artifact("publish_log", publish_log)
```

One entry per reel, in posting order, so the artifact reads top-to-bottom as the schedule.

### 8. Checkpoint And Present

Self-review against this stage's `review_focus`, then checkpoint `awaiting_human` and stop. The
cost snapshot passes straight through from the tracker, never hand-written — the checkpoint schema
closes it to four keys and rejects the legacy ones at write time.

```python
from lib.checkpoint import write_checkpoint
from tools.cost_tracker import CostTracker

tracker = CostTracker.for_project(project_id)
snapshot = tracker.cost_snapshot()
snapshot["budget_total_usd"] = tracker.budget_total_usd

write_checkpoint(
    PROJECTS_DIR, project_id, "publish", "awaiting_human",
    {"publish_log": publish_log},
    pipeline_type="reel-batch", cost_snapshot=snapshot,
)
```

**What the operator is approving here** — list it in the summary in these words:

1. the caption copy and hashtag set on each reel, as written;
2. the posting order and the spacing;
3. the credit lines, including any track whose terms you had to ask about;
4. which reels ship at all — dropping one is a normal outcome of this gate;
5. the bundle as the hand-off. Approving posts nothing.

His answer to (4) is `shipped_reel_ids`: the reel ids he approved, a subset of `roster`. That list —
not the whole batch — is what step 9 settles.

### 9. After Approval — Settle The Clip Ledger

Approval is what makes a reel shipped, and shipped is what `reconciled` means: "its claims stay out
of the pool permanently" (`lib/clip_ledger.py:212-214`).

```python
for rid in shipped_reel_ids:            # step 8's answer — the reel ids he approved
    ledger.reconcile_reel(rid)

publish_log["entries"] = [e for e in publish_log["entries"]
                          if e["metadata_used"]["reel_id"] in shipped_reel_ids]
for entry in publish_log["entries"]:
    entry["status"] = "exported"
publish_log["metadata"]["posting_order"] = [rid for rid in posting_order if rid in shipped_reel_ids]

write_checkpoint(
    PROJECTS_DIR, project_id, "publish", "completed",
    {"publish_log": publish_log},
    pipeline_type="reel-batch", human_approved=True, cost_snapshot=snapshot,
)
```

`_settle_reel` only moves claims whose status is exactly `claimed` (`lib/clip_ledger.py:268-278`),
so a second call is a harmless no-op returning `[]`.

## Send-Backs — What Each One Changes

| The operator says | What changes | What does not |
|---|---|---|
| "rewrite this caption / these tags / this order / this credit" | Rewrite here, rebuild that reel's export directory, re-checkpoint `awaiting_human` | No re-render, no spend; the clip ledger is untouched |
| "drop this reel" | Remove its entry, renumber the remaining slots, delete its export directory. Call `release_reel(rid)` **only** if the reel is dead — that returns its segments to the pool (`lib/clip_ledger.py:204-210`). If it may come back, leave the claims `claimed` and say so | The other four keep their slots and their copy |
| "recut this reel" | You cannot recut here. `release_reel(rid)` first, then send back to `edit` — or to `scene_plan` if the cut slots themselves were wrong | Releasing first is what lets the recut pick different segments; without it the next `claim()` raises `SegmentAlreadyClaimedError` (`lib/clip_ledger.py:157-165`) |
| "the render is wrong" (size, audio, clipped captions) | Back to `compose`. Publish never re-renders and never edits a file under `renders/` | Captions and slots survive; re-attach them to the new render by reel id |

Never reconcile a reel the operator sent back. A reconciled claim is binding and cannot be
re-decided (`lib/clip_ledger.py:59-61`).

## Ledger Duty

This stage spends nothing — `tools_available: []`, and copying files is free. Your only ledger
duties are the snapshot in step 8 and, on a resume, the stranded-entry sweep; both live in
`skills/meta/checkpoint-protocol.md` → **Cost Ledger Governance**, so follow them there rather than
restating them. Do not open a ledger entry for packaging: a zero-cost entry for a filesystem copy
is noise in a log that must reconcile to what the run actually spent.

## Common Pitfalls

- **One caption, five posts.** The failure this stage exists to prevent — the step 3 assertion is
  cheap, run it.
- **Dumping the batch in an afternoon.** A week of content spent on one impression.
- **Packaging a `needs_verification` render.** It hides the verdict compose wrote down.
- **Naming a movement the cut list lacks.** `cut_ids` is the only authority on what the reel shows.
- **`status: "published"` because the files are ready.** Nothing was uploaded.
- **Extra keys on a `publish_log` entry.** The entry is closed; `metadata_used` is the open pocket.
- **Reconciling the whole batch when one reel was sent back.** Settle the shipped ones only.

---

## Gate Reminder (Binding)

This stage gates on human approval (`human_approval_default: true`). After review passes:
checkpoint with `status="awaiting_human"`, present the summary (the Backlot board renders
the artifact), and **END YOUR TURN**. Do not start the next stage in the same response.
Approval is per-gate — an earlier "go ahead" does not cover this gate.
