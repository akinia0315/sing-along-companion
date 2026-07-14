"""Load compact, operator-generated full-mix reference contours.

The API never fetches music, decodes source audio, or accepts provider cookies.
Run the local Node analyzer separately on audio you are authorized to use, then
point ``REFERENCE_CONTOUR_DIRECTORY`` at its derived JSON artifacts.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import ReferenceFrame


MAX_ARTIFACT_BYTES = 2 * 1024 * 1024
MAX_REFERENCE_FRAMES = 4_000


def _hz(midi: float) -> float:
    return round(440 * (2 ** ((midi - 69) / 12)), 1)


def _safe_song_id(value: str) -> str:
    candidate = str(value or "")
    return candidate if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", candidate) else ""


def _safe_profile(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    # JSON round-tripping enforces a simple data-only object and removes any
    # custom mapping subclasses from an integration adapter.
    try:
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > 160_000:
            return None
        decoded = json.loads(encoded)
    except (TypeError, ValueError):
        return None
    return decoded if isinstance(decoded, dict) else None


@dataclass(frozen=True)
class ReferenceAnalysis:
    source: str
    frames: list[ReferenceFrame]
    profile: dict[str, Any] | None = None


class ReferenceContourRepository:
    """Read only derived reference JSON; source audio never enters this API."""

    def __init__(self, directory: str | Path | None = None) -> None:
        configured = directory if directory is not None else os.getenv("REFERENCE_CONTOUR_DIRECTORY")
        self._directory = Path(configured).expanduser() if configured else None
        shape = (57, 59, 61, 64, 62, 59, 57, 59, 62, 64, 66, 64, 61, 59)
        self._demo = ReferenceAnalysis(
            source="synthetic_demo",
            frames=[
                ReferenceFrame(t_ms=index * 700, hz=_hz(midi), confidence=0.7)
                for index, midi in enumerate(shape)
            ],
        )

    def _read_artifact(self, song_id: str) -> ReferenceAnalysis | None:
        if not self._directory:
            return None
        safe_id = _safe_song_id(song_id)
        if not safe_id:
            return None
        candidate = self._directory / f"{safe_id}.json"
        try:
            if not candidate.is_file() or candidate.stat().st_size > MAX_ARTIFACT_BYTES:
                return None
            raw = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(raw, dict) or raw.get("song_id") != safe_id:
            return None
        source = str(raw.get("source") or "authorized_reference")[:80]
        if source != "authorized_local_audio_full_mix":
            return None
        raw_frames = raw.get("frames")
        if not isinstance(raw_frames, list):
            return None
        frames: list[ReferenceFrame] = []
        for item in raw_frames[:MAX_REFERENCE_FRAMES]:
            try:
                frames.append(ReferenceFrame.model_validate(item))
            except (TypeError, ValueError):
                continue
        if not frames:
            return None
        frames.sort(key=lambda frame: frame.t_ms)
        return ReferenceAnalysis(source=source, frames=frames, profile=_safe_profile(raw.get("profile")))

    async def analysis(self, song_id: str) -> ReferenceAnalysis | None:
        # Artifacts are capped at 2 MB, so a short synchronous read keeps this
        # adapter simple and avoids retaining executor threads in small hosts.
        artifact = self._read_artifact(song_id)
        if artifact:
            return artifact
        return self._demo if song_id == "demo-signal" else None

    async def get(self, song_id: str) -> list[ReferenceFrame]:
        result = await self.analysis(song_id)
        return [frame.model_copy(deep=True) for frame in result.frames] if result else []

    async def profile(self, song_id: str) -> dict[str, Any] | None:
        result = await self.analysis(song_id)
        return json.loads(json.dumps(result.profile)) if result and result.profile else None
