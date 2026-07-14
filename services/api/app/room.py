"""Ephemeral room state and SSE fan-out for the standalone demo.

The seed content is synthetic. A production app should replace the catalog and
lyrics adapters with an authorized source; do not commit their responses.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator
from typing import Any

from .models import RoomSnapshot, Song, TimedLyric


DEMO_SONG = Song(
    id="demo-signal",
    title="Demo Signal",
    artist="Local sample",
    duration_ms=42_000,
)

DEMO_LRC = """[00:00.00]示例时间轴内容，请接入有授权的歌词来源
[00:07.00]这一句展示播放位置如何进入聊天背景
[00:15.00]跟唱只分享音高走势，不分享原始录音
[00:24.00]原曲参考线应当来自已获授权的音频分析
[00:33.00]示例结束，欢迎替换成你的合法内容
"""

DEMO_PROFILE: dict[str, Any] = {
    "source": "synthetic_demo",
    "energy": {
        "segments": [
            {"start_ms": 0, "end_ms": 5_250, "level": 34},
            {"start_ms": 5_250, "end_ms": 10_500, "level": 45},
            {"start_ms": 10_500, "end_ms": 15_750, "level": 57},
            {"start_ms": 15_750, "end_ms": 21_000, "level": 66},
            {"start_ms": 21_000, "end_ms": 26_250, "level": 72},
            {"start_ms": 26_250, "end_ms": 31_500, "level": 62},
            {"start_ms": 31_500, "end_ms": 36_750, "level": 49},
            {"start_ms": 36_750, "end_ms": 42_000, "level": 38},
        ],
        "start": "low",
        "end": "medium",
        "peak": "middle",
        "movement": "arch",
        "dynamics": "moderate",
    },
    "motion": {"label": "moderate"},
    "timbre": {"label": "balanced"},
    "melody": {
        "presence": "present",
        "range_semitones": 9.5,
        "movement": "steady",
        "peak": "middle",
    },
}


def clean_text(value: object, limit: int = 500) -> str:
    text = re.sub(r"[\x00-\x1f]", " ", str(value or ""))
    return re.sub(r"\s+", " ", text).strip()[:limit]


class RoomEventHub:
    def __init__(self) -> None:
        self._queues: set[asyncio.Queue[dict[str, Any]]] = set()
        self._lock = asyncio.Lock()

    async def publish(self, event: str, payload: dict[str, Any]) -> None:
        frame = {"event": event, "payload": payload}
        async with self._lock:
            queues = tuple(self._queues)
        for queue in queues:
            try:
                queue.put_nowait(frame)
            except asyncio.QueueFull:
                # A slow browser receives the next state snapshot after it
                # reconnects; never let one client block the room.
                pass

    async def subscribe(self) -> AsyncIterator[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=24)
        async with self._lock:
            self._queues.add(queue)
        try:
            while True:
                yield await queue.get()
        finally:
            async with self._lock:
                self._queues.discard(queue)


class RoomStore:
    def __init__(self) -> None:
        self.events = RoomEventHub()
        self._lock = asyncio.Lock()
        self._snapshot = RoomSnapshot(
            room_id="demo",
            current_song=DEMO_SONG,
            is_playing=True,
            position_ms=0,
            revision=1,
        )
        self._notes: list[dict[str, Any]] = []

    async def snapshot(self, room_id: str = "demo") -> RoomSnapshot:
        async with self._lock:
            if room_id != self._snapshot.room_id:
                return RoomSnapshot(room_id=room_id)
            return self._snapshot.model_copy(deep=True)

    async def control(self, room_id: str, action: str, position_ms: int | None) -> RoomSnapshot:
        async with self._lock:
            if room_id != self._snapshot.room_id:
                raise ValueError("unknown room")
            next_state = self._snapshot.model_copy(deep=True)
            if action == "play":
                next_state.is_playing = True
            elif action == "pause":
                next_state.is_playing = False
            elif action == "seek":
                duration = next_state.current_song.duration_ms if next_state.current_song else 0
                next_state.position_ms = max(0, min(int(position_ms or 0), duration or int(position_ms or 0)))
            else:
                raise ValueError("unsupported action")
            next_state.revision += 1
            self._snapshot = next_state
            result = next_state.model_copy(deep=True)
        await self.events.publish("room", {"room": result.model_dump()})
        return result

    async def set_position(self, room_id: str, position_ms: int) -> RoomSnapshot:
        return await self.control(room_id, "seek", position_ms)

    async def lyrics(self, song_id: str) -> list[TimedLyric]:
        if song_id != DEMO_SONG.id:
            return []
        from .context import parse_timed_lyrics

        return [TimedLyric(**line) for line in parse_timed_lyrics(DEMO_LRC)]

    async def profile(self, song_id: str) -> dict[str, Any] | None:
        return json.loads(json.dumps(DEMO_PROFILE)) if song_id == DEMO_SONG.id else None

    async def add_note(self, body: str, *, author: str = "Companion") -> dict[str, Any]:
        note = {
            "id": f"note-{len(self._notes) + 1}",
            "author": clean_text(author, 40),
            "body": clean_text(body, 500),
        }
        async with self._lock:
            self._notes.append(note)
            self._notes = self._notes[-20:]
        await self.events.publish("note", {"note": note})
        return note

    async def recent_notes(self, limit: int = 2) -> list[dict[str, Any]]:
        async with self._lock:
            return [dict(note) for note in self._notes[-max(0, limit):]]
