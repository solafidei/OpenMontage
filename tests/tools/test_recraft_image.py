"""Regression tests: recraft_image must fail closed on a bad colour palette.

Covers:
- 3-digit shorthand hex ("#F53") expands instead of raising ValueError
- 6-digit hex converts to a fal RGBColor object
- Already-formed {"r","g","b"} objects pass through untouched
- Garbage entries return ToolResult(success=False) and never reach fal
"""

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


class _FakeResponse:
    def __init__(self, json_data: dict | None = None, status_code: int = 200, content: bytes = b""):
        self._json_data = json_data or {}
        self.status_code = status_code
        self.content = content

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._json_data


@pytest.fixture
def recraft_tool(monkeypatch):
    monkeypatch.setenv("FAL_KEY", "test-fal-key")
    from tools.graphics.recraft_image import RecraftImage
    return RecraftImage()


@pytest.fixture
def mock_requests(monkeypatch):
    mock_post = MagicMock(
        return_value=_FakeResponse(
            {"images": [{"url": "http://img.url/0", "content_type": "image/png"}]}
        )
    )
    mock_get = MagicMock(return_value=_FakeResponse(content=b"RECRAFT_IMAGE"))
    fake_requests = types.ModuleType("requests")
    fake_requests.post = mock_post
    fake_requests.get = mock_get
    fake_requests.HTTPError = type("HTTPError", (Exception,), {})
    monkeypatch.setitem(sys.modules, "requests", fake_requests)
    return mock_post, mock_get


def _sent_colors(mock_post) -> list:
    return mock_post.call_args.kwargs["json"]["colors"]


# ========== Colour palette conversion ==========

class TestColorConversion:
    def test_three_digit_shorthand_expands(self, recraft_tool, tmp_path, mock_requests):
        mock_post, _ = mock_requests

        result = recraft_tool.execute({
            "prompt": "logo", "colors": ["#F53"],
            "output_path": str(tmp_path / "out.png"),
        })

        assert result.success, result.error
        assert _sent_colors(mock_post) == [{"r": 0xFF, "g": 0x55, "b": 0x33}]

    def test_six_digit_hex_converts(self, recraft_tool, tmp_path, mock_requests):
        mock_post, _ = mock_requests

        result = recraft_tool.execute({
            "prompt": "logo", "colors": ["#FF5733", "2E86C1"],
            "output_path": str(tmp_path / "out.png"),
        })

        assert result.success, result.error
        assert _sent_colors(mock_post) == [
            {"r": 255, "g": 87, "b": 51},
            {"r": 46, "g": 134, "b": 193},
        ]

    def test_rgb_object_passes_through(self, recraft_tool, tmp_path, mock_requests):
        mock_post, _ = mock_requests

        result = recraft_tool.execute({
            "prompt": "logo", "colors": [{"r": 1, "g": 2, "b": 3}],
            "output_path": str(tmp_path / "out.png"),
        })

        assert result.success, result.error
        assert _sent_colors(mock_post) == [{"r": 1, "g": 2, "b": 3}]

    @pytest.mark.parametrize("value", ["#GGGGGG", "#12345", "not-a-color", 12345, {"r": 1}])
    def test_garbage_returns_error_without_calling_fal(
        self, recraft_tool, tmp_path, mock_requests, value
    ):
        mock_post, _ = mock_requests

        result = recraft_tool.execute({
            "prompt": "logo", "colors": [value],
            "output_path": str(tmp_path / "out.png"),
        })

        assert not result.success
        assert "color" in (result.error or "").lower()
        mock_post.assert_not_called()


# ========== Idempotency key ==========

class TestIdempotencyKey:
    def test_colors_change_the_idempotency_key(self, recraft_tool):
        # colors is materially forwarded to fal as RGBColor objects and
        # changes the generated image, so it must be part of the cache key —
        # otherwise a resume/cache layer would serve the wrong image.
        base = {"prompt": "logo", "colors": ["#FF5733"]}
        other = {"prompt": "logo", "colors": ["#2E86C1"]}

        assert recraft_tool.idempotency_key(base) != recraft_tool.idempotency_key(other)
