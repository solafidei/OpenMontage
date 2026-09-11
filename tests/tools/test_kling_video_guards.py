"""Contracts for the kling_video fal route guards and payload gating."""

from __future__ import annotations

import requests


class _Response:
    def __init__(self, payload=None, content=b"video", status_code=200):
        self.payload = payload or {}
        self.content = content
        self.status_code = status_code
        self.ok = status_code < 400
        self.text = str(self.payload)

    def json(self):
        return self.payload

    def raise_for_status(self):
        if not self.ok:
            raise RuntimeError(f"HTTP {self.status_code}")


def _queue_mocks(monkeypatch):
    calls = {"posts": []}

    def post(url, headers=None, json=None, timeout=None):
        calls["posts"].append((url, json))
        return _Response({"status_url": "https://status", "response_url": "https://result"})

    def get(url, headers=None, timeout=None, params=None):
        if url == "https://status":
            return _Response({"status": "COMPLETED"})
        if url == "https://result":
            return _Response({"video": {"url": "https://video"}})
        return _Response(content=b"fake mp4")

    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setattr(requests, "get", get)
    monkeypatch.setattr("time.sleep", lambda _: None)
    return calls


def test_legacy_v21_rejects_durations_fal_does_not_accept(monkeypatch, tmp_path):
    from tools.video.kling_video import KlingVideo

    monkeypatch.setenv("FAL_KEY", "test")
    calls = _queue_mocks(monkeypatch)
    result = KlingVideo().execute(
        {
            "prompt": "legacy clip",
            "model_variant": "v2.1/standard",
            "operation": "image_to_video",
            "image_url": "https://image",
            "duration": "7",
            "output_path": str(tmp_path / "kling.mp4"),
        }
    )
    assert not result.success
    assert "5 or 10" in result.error
    assert calls["posts"] == []


def test_legacy_v21_pro_and_standard_are_image_to_video_only(monkeypatch, tmp_path):
    from tools.video.kling_video import KlingVideo

    monkeypatch.setenv("FAL_KEY", "test")
    calls = _queue_mocks(monkeypatch)
    result = KlingVideo().execute(
        {
            "prompt": "legacy clip",
            "model_variant": "v2.1/pro",
            "duration": "5",
            "output_path": str(tmp_path / "kling.mp4"),
        }
    )
    assert not result.success
    assert "image-to-video" in result.error
    assert calls["posts"] == []


def test_v21_master_still_submits_text_to_video(monkeypatch, tmp_path):
    from tools.video.kling_video import KlingVideo

    monkeypatch.setenv("FAL_KEY", "test")
    calls = _queue_mocks(monkeypatch)
    result = KlingVideo().execute(
        {
            "prompt": "legacy master clip",
            "model_variant": "v2.1/master",
            "duration": "10",
            "output_path": str(tmp_path / "kling.mp4"),
        }
    )
    assert result.success, result.error
    url, payload = calls["posts"][0]
    assert url.endswith("/fal-ai/kling-video/v2.1/master/text-to-video")
    assert payload["duration"] == "10"


def test_aspect_ratio_is_sent_only_on_text_to_video(monkeypatch, tmp_path):
    from tools.video.kling_video import KlingVideo

    monkeypatch.setenv("FAL_KEY", "test")
    calls = _queue_mocks(monkeypatch)
    tool = KlingVideo()

    t2v = tool.execute(
        {
            "prompt": "vertical b-roll",
            "aspect_ratio": "9:16",
            "duration": "5",
            "output_path": str(tmp_path / "t2v.mp4"),
        }
    )
    assert t2v.success, t2v.error
    _, t2v_payload = calls["posts"][0]
    assert t2v_payload["aspect_ratio"] == "9:16"

    i2v = tool.execute(
        {
            "prompt": "animate the still",
            "operation": "image_to_video",
            "image_url": "https://image",
            "aspect_ratio": "9:16",
            "duration": "5",
            "output_path": str(tmp_path / "i2v.mp4"),
        }
    )
    assert i2v.success, i2v.error
    url, i2v_payload = calls["posts"][1]
    assert url.endswith("/fal-ai/kling-video/v3/standard/image-to-video")
    assert "aspect_ratio" not in i2v_payload
    assert i2v_payload["start_image_url"] == "https://image"


def test_generate_audio_is_part_of_the_idempotency_key():
    from tools.video.kling_video import KlingVideo

    tool = KlingVideo()
    assert "generate_audio" in tool.idempotency_key_fields
    audio_off = dict(prompt="p", model_variant="v3/standard", duration="5", generate_audio=False)
    audio_on = dict(audio_off, generate_audio=True)
    assert tool.estimate_cost(audio_off) != tool.estimate_cost(audio_on)
