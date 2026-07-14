from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class Song(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=180)
    artist: str = Field(default="", max_length=180)
    duration_ms: int = Field(default=0, ge=0, le=24 * 60 * 60 * 1000)


class TimedLyric(BaseModel):
    at_ms: int = Field(ge=0, le=24 * 60 * 60 * 1000)
    text: str = Field(default="", max_length=500)
    translation: str = Field(default="", max_length=500)


class ReferenceFrame(BaseModel):
    t_ms: int = Field(ge=0, le=24 * 60 * 60 * 1000)
    hz: float = Field(gt=0, le=2_000)
    confidence: float | None = Field(default=None, ge=0, le=1)


class PitchSample(BaseModel):
    t_ms: int = Field(ge=0, le=15 * 60 * 1000)
    hz: float = Field(ge=60, le=1_200)


class RoomSnapshot(BaseModel):
    room_id: str
    current_song: Song | None = None
    is_playing: bool = False
    position_ms: int = Field(default=0, ge=0)
    revision: int = Field(default=0, ge=0)


class RoomControlRequest(BaseModel):
    action: Literal["play", "pause", "seek"]
    position_ms: int | None = Field(default=None, ge=0)


class SingingStartRequest(BaseModel):
    room_id: str = Field(default="demo", min_length=1, max_length=40)
    song_id: str = Field(min_length=1, max_length=64)
    song_position_ms: int = Field(default=0, ge=0, le=24 * 60 * 60 * 1000)


class SingingUpdateRequest(BaseModel):
    room_id: str = Field(default="demo", min_length=1, max_length=40)
    session_id: str = Field(min_length=16, max_length=96)
    elapsed_ms: int = Field(default=0, ge=0, le=15 * 60 * 1000)
    samples: list[PitchSample] = Field(default_factory=list, max_length=32)


class SingingStopRequest(BaseModel):
    room_id: str = Field(default="demo", min_length=1, max_length=40)
    session_id: str = Field(min_length=16, max_length=96)
    elapsed_ms: int = Field(default=0, ge=0, le=15 * 60 * 1000)


class ChatMessageRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4_000)


class ChatMessage(BaseModel):
    id: str
    role: Literal["user", "assistant"]
    content: str
    created_at: str
    kind: str = "chat"


class ChatResult(BaseModel):
    messages: list[ChatMessage]
    listening_context_attached: bool
    context_fields: list[str] = Field(default_factory=list)


class PublicSingingSession(BaseModel):
    session_id: str
    room_id: str
    song_id: str
    status: Literal["active", "finished"]
    elapsed_ms: int
    sample_count: int
    low_hz: float | None = None
    high_hz: float | None = None
    low_note: str = ""
    high_note: str = ""
    current_hz: float | None = None
    current_note: str = ""
    recent_movement: str = "unknown"
    audio_shared: bool = False
    delivery: dict[str, Any]
