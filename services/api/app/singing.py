"""Short-lived, opt-in F0 sharing with a non-scoring contour observation."""

from __future__ import annotations

import asyncio
import math
import re
import secrets
import time
from bisect import bisect_left
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from .models import PitchSample, PublicSingingSession, ReferenceFrame


ACTIVE_TIMEOUT_SECONDS = 18
FINISHED_RETENTION_SECONDS = 12 * 60
MAX_RECENT_SAMPLES = 96
MAX_SESSION_MS = 15 * 60 * 1_000
REFERENCE_MAX_DISTANCE_MS = 760
MIN_REFERENCE_PAIRS = 5
NOTE_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")


def note_for_hz(value: float | None) -> str:
    if value is None or not math.isfinite(value) or value <= 0:
        return ""
    midi = round(69 + 12 * math.log2(value / 440))
    return f"{NOTE_NAMES[midi % 12]}{midi // 12 - 1}"


def midi_for_hz(value: float) -> float | None:
    if not math.isfinite(value) or value <= 0:
        return None
    return 69 + 12 * math.log2(value / 440)


def median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[len(ordered) // 2]


def motion(values: list[float]) -> str:
    if len(values) < 3:
        return "unknown"
    third = max(1, len(values) // 3)
    beginning = median(values[:third])
    ending = median(values[-third:])
    if beginning is None or ending is None:
        return "unknown"
    if ending - beginning > 0.85:
        return "rising"
    if beginning - ending > 0.85:
        return "falling"
    return "steady"


def contour_relation(user: list[float], reference: list[float]) -> str:
    """Compare shape after removing a constant transposition; never score."""
    if len(user) < 3 or len(user) != len(reference):
        return "unknown"
    offsets = [left - right for left, right in zip(user, reference)]
    baseline = median(offsets)
    if baseline is None:
        return "unknown"
    residual = median([abs(offset - baseline) for offset in offsets])
    if residual is None:
        return "unknown"
    if residual <= 0.65:
        return "closely_followed"
    if residual <= 1.45:
        return "mostly_followed"
    if residual <= 2.6:
        return "partly_followed"
    return "unclear"


def key_relation(offset_semitones: float | None) -> str:
    """Describe a consistent key shift without turning it into a grade."""
    if offset_semitones is None:
        return "unknown"
    if abs(offset_semitones) <= 0.7:
        return "near_reference_key"
    return "higher_than_reference" if offset_semitones > 0 else "lower_than_reference"


def build_reference_observation(
    samples: list[PitchSample],
    song_position_ms: int,
    reference_frames: list[ReferenceFrame],
) -> dict[str, Any]:
    """Align sparse user F0 points to the same song timeline.

    The reference may come from a full mix, so the result deliberately carries
    the scope in every response and does not claim stem-level precision.
    """
    if not samples or not reference_frames:
        return {
            "available": False,
            "reference_kind": "full_mix_dominant_pitch",
            "scope": "relative_contour_only",
        }
    ordered_reference = sorted(reference_frames, key=lambda frame: frame.t_ms)
    times = [frame.t_ms for frame in ordered_reference]
    pairs: list[tuple[int, float, float]] = []
    for sample in samples:
        target = song_position_ms + sample.t_ms
        index = bisect_left(times, target)
        candidates = [ordered_reference[index]] if index < len(ordered_reference) else []
        if index:
            candidates.append(ordered_reference[index - 1])
        if not candidates:
            continue
        closest = min(candidates, key=lambda frame: abs(frame.t_ms - target))
        if abs(closest.t_ms - target) > REFERENCE_MAX_DISTANCE_MS:
            continue
        user_midi = midi_for_hz(sample.hz)
        reference_midi = midi_for_hz(closest.hz)
        if user_midi is not None and reference_midi is not None:
            pairs.append((sample.t_ms, user_midi, reference_midi))
    if len(pairs) < MIN_REFERENCE_PAIRS:
        return {
            "available": False,
            "reference_kind": "full_mix_dominant_pitch",
            "scope": "relative_contour_only",
            "reason": "not_enough_aligned_pitch",
        }
    user_values = [item[1] for item in pairs]
    reference_values = [item[2] for item in pairs]
    baseline = median([user - reference for user, reference in zip(user_values, reference_values)])
    parts: list[dict[str, str]] = []
    for index, label in enumerate(("opening", "middle", "closing")):
        start = round(len(pairs) * index / 3)
        end = round(len(pairs) * (index + 1) / 3)
        chunk = pairs[start:end]
        if len(chunk) < 3:
            continue
        users = [item[1] for item in chunk]
        refs = [item[2] for item in chunk]
        parts.append(
            {
                "part": label,
                "user_motion": motion(users),
                "reference_motion": motion(refs),
                "contour_relation": contour_relation(users, refs),
            }
        )
    return {
        "available": True,
        "reference_kind": "full_mix_dominant_pitch",
        "scope": "relative_contour_only",
        "paired_samples": len(pairs),
        "overall": {
            "user_motion": motion(user_values),
            "reference_motion": motion(reference_values),
            "contour_relation": contour_relation(user_values, reference_values),
            # A constant offset is a musical key choice, not an accuracy score.
            "median_key_offset_semitones": round(baseline, 1) if baseline is not None else None,
            "key_relation": key_relation(baseline),
        },
        "parts": parts,
    }


@dataclass
class _Session:
    session_id: str
    room_id: str
    song_id: str
    song_position_ms: int
    status: str = "active"
    started_at: float = field(default_factory=time.monotonic)
    updated_at: float = field(default_factory=time.monotonic)
    ended_at: float | None = None
    elapsed_ms: int = 0
    last_sample_t_ms: int = -1
    sample_count: int = 0
    low_hz: float | None = None
    high_hz: float | None = None
    current_hz: float | None = None
    samples: deque[PitchSample] = field(default_factory=lambda: deque(maxlen=MAX_RECENT_SAMPLES))
    delivery_status: str = "sharing"
    delivery_reason: str = ""
    reference_observation: dict[str, Any] | None = None


class SingingSessionService:
    def __init__(self) -> None:
        self._sessions: dict[str, _Session] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def _room_id(value: str) -> str:
        clean = re.sub(r"[^a-zA-Z0-9_-]+", "-", value).strip("-")[:40]
        return clean or "demo"

    def _prune(self, now: float) -> None:
        expired: list[str] = []
        for room_id, session in self._sessions.items():
            if session.status == "active" and now - session.updated_at > ACTIVE_TIMEOUT_SECONDS:
                session.status = "finished"
                session.ended_at = session.updated_at
                session.current_hz = None
                session.delivery_status = "interrupted"
                session.delivery_reason = "capture_timeout"
            finished_at = session.ended_at or session.updated_at
            if session.status != "active" and now - finished_at > FINISHED_RETENTION_SECONDS:
                expired.append(room_id)
        for room_id in expired:
            self._sessions.pop(room_id, None)

    def _public(self, session: _Session) -> PublicSingingSession:
        active = session.status == "active" and time.monotonic() - session.updated_at <= ACTIVE_TIMEOUT_SECONDS
        values = [sample.hz for sample in list(session.samples)[-18:]]
        midi_values = [midi_for_hz(value) for value in values]
        return PublicSingingSession(
            session_id=session.session_id,
            room_id=session.room_id,
            song_id=session.song_id,
            status="active" if active else "finished",
            elapsed_ms=session.elapsed_ms,
            sample_count=session.sample_count,
            low_hz=round(session.low_hz, 1) if session.low_hz else None,
            high_hz=round(session.high_hz, 1) if session.high_hz else None,
            low_note=note_for_hz(session.low_hz),
            high_note=note_for_hz(session.high_hz),
            current_hz=round(session.current_hz, 1) if active and session.current_hz else None,
            current_note=note_for_hz(session.current_hz) if active else "",
            recent_movement=motion([value for value in midi_values if value is not None]),
            audio_shared=False,
            delivery={"status": session.delivery_status, "reason": session.delivery_reason},
        )

    async def start(self, room_id: str, song_id: str, song_position_ms: int) -> PublicSingingSession:
        now = time.monotonic()
        session = _Session(
            session_id=secrets.token_urlsafe(18),
            room_id=self._room_id(room_id),
            song_id=re.sub(r"[^a-zA-Z0-9_-]", "", song_id)[:64],
            song_position_ms=max(0, min(int(song_position_ms), 24 * 60 * 60 * 1_000)),
            started_at=now,
            updated_at=now,
        )
        if not session.song_id:
            raise ValueError("invalid song id")
        async with self._lock:
            self._prune(now)
            self._sessions[session.room_id] = session
            return self._public(session)

    async def update(
        self,
        room_id: str,
        session_id: str,
        elapsed_ms: int,
        samples: list[PitchSample],
    ) -> PublicSingingSession | None:
        now = time.monotonic()
        async with self._lock:
            self._prune(now)
            session = self._sessions.get(self._room_id(room_id))
            if not session or session.session_id != session_id or session.status != "active":
                return None
            session.elapsed_ms = max(session.elapsed_ms, min(MAX_SESSION_MS, max(0, int(elapsed_ms))))
            for sample in samples[:32]:
                if sample.t_ms <= session.last_sample_t_ms:
                    continue
                session.last_sample_t_ms = sample.t_ms
                session.samples.append(sample)
                session.sample_count += 1
                session.current_hz = sample.hz
                session.low_hz = sample.hz if session.low_hz is None else min(session.low_hz, sample.hz)
                session.high_hz = sample.hz if session.high_hz is None else max(session.high_hz, sample.hz)
            session.updated_at = now
            return self._public(session)

    async def finish(self, room_id: str, session_id: str, elapsed_ms: int) -> PublicSingingSession | None:
        now = time.monotonic()
        async with self._lock:
            self._prune(now)
            session = self._sessions.get(self._room_id(room_id))
            if not session or session.session_id != session_id:
                return None
            session.elapsed_ms = max(session.elapsed_ms, min(MAX_SESSION_MS, max(0, int(elapsed_ms))))
            session.status = "finished"
            session.current_hz = None
            session.updated_at = now
            session.ended_at = now
            if session.delivery_status == "sharing":
                session.delivery_status = "preparing"
                session.delivery_reason = ""
            return self._public(session)

    async def get(self, room_id: str) -> PublicSingingSession | None:
        async with self._lock:
            self._prune(time.monotonic())
            session = self._sessions.get(self._room_id(room_id))
            return self._public(session) if session else None

    async def attach_reference(
        self,
        room_id: str,
        session_id: str,
        reference_frames: list[ReferenceFrame],
    ) -> dict[str, Any] | None:
        async with self._lock:
            self._prune(time.monotonic())
            session = self._sessions.get(self._room_id(room_id))
            if not session or session.session_id != session_id:
                return None
            samples = list(session.samples)
            anchor = session.song_position_ms
        observation = build_reference_observation(samples, anchor, reference_frames)
        async with self._lock:
            session = self._sessions.get(self._room_id(room_id))
            if not session or session.session_id != session_id:
                return None
            session.reference_observation = observation
            return dict(observation)

    async def model_context(self, room_id: str, session_id: str) -> dict[str, Any] | None:
        async with self._lock:
            self._prune(time.monotonic())
            session = self._sessions.get(self._room_id(room_id))
            if not session or session.session_id != session_id:
                return None
            return {
                "reference_observation": dict(session.reference_observation)
                if isinstance(session.reference_observation, dict)
                else {
                    "available": False,
                    "reference_kind": "full_mix_dominant_pitch",
                    "scope": "relative_contour_only",
                    "reason": "reference_not_ready",
                }
            }

    async def mark_delivery(self, room_id: str, session_id: str, status: str, reason: str = "") -> PublicSingingSession | None:
        allowed = {"sharing", "preparing", "replied", "unavailable", "too_short", "song_changed", "interrupted"}
        if status not in allowed:
            return None
        async with self._lock:
            self._prune(time.monotonic())
            session = self._sessions.get(self._room_id(room_id))
            if not session or session.session_id != session_id:
                return None
            session.delivery_status = status
            session.delivery_reason = re.sub(r"[^a-z0-9_-]+", "_", reason.lower())[:80]
            return self._public(session)
