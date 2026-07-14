from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from .context import build_listening_context, context_options_for_text
from .conversation import ConversationService
from .models import (
    ChatMessageRequest,
    RoomControlRequest,
    SingingStartRequest,
    SingingStopRequest,
    SingingUpdateRequest,
)
from .reference import ReferenceContourRepository
from .room import RoomStore
from .singing import SingingSessionService


def _cors_origins() -> list[str]:
    raw = os.getenv("CORS_ORIGINS", "http://127.0.0.1:5173,http://localhost:5173")
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


app = FastAPI(title="Sing Along Companion API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

rooms = RoomStore()
references = ReferenceContourRepository()
singing = SingingSessionService()
conversation = ConversationService()


async def _context_for_room(room_id: str, *, lyrics: bool, analysis: bool, notes: bool) -> dict[str, Any]:
    room = await rooms.snapshot(room_id)
    song_id = room.current_song.id if room.current_song else ""
    lyric_lines = await rooms.lyrics(song_id) if lyrics else []
    profile = (await references.profile(song_id) or await rooms.profile(song_id)) if analysis else None
    recent_notes = await rooms.recent_notes() if notes else []
    return build_listening_context(
        room,
        lyric_lines,
        profile,
        recent_notes,
        include_lyrics=lyrics,
        include_analysis=analysis,
        include_notes=notes,
    )


def _receipt_body(session: dict[str, Any]) -> str:
    seconds = max(0, int(session.get("elapsed_ms") or 0)) // 1_000
    duration = f"{seconds // 60}:{seconds % 60:02d}" if seconds else "a short"
    low = str(session.get("low_note") or "").strip()
    high = str(session.get("high_note") or "").strip()
    span = f"{low}–{high}" if low and high else "a sparse pitch trace"
    movement = str(session.get("recent_movement") or "")
    movement_text = f", {movement}" if movement in {"rising", "falling", "steady"} else ""
    return f"Sing-along receipt: shared {duration} of pitch movement ({span}{movement_text})."


@app.get("/api/health")
async def health() -> dict[str, bool]:
    return {"ok": True}


@app.get("/api/listen/room")
async def get_room(room_id: str = "demo") -> dict[str, Any]:
    return {"room": (await rooms.snapshot(room_id)).model_dump()}


@app.post("/api/listen/room/control")
async def control_room(request: RoomControlRequest, room_id: str = "demo") -> dict[str, Any]:
    try:
        room = await rooms.control(room_id, request.action, request.position_ms)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"room": room.model_dump()}


@app.get("/api/listen/events")
async def listen_events(request: Request, room_id: str = "demo") -> StreamingResponse:
    async def frames() -> AsyncIterator[str]:
        snapshot = await rooms.snapshot(room_id)
        yield _sse("snapshot", {"room": snapshot.model_dump()})
        async for frame in rooms.events.subscribe():
            if await request.is_disconnected():
                break
            yield _sse(str(frame["event"]), dict(frame["payload"]))

    return StreamingResponse(
        frames(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _sse(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}\n\n"


@app.get("/api/listen/songs/{song_id}/lyrics")
async def lyrics(song_id: str) -> dict[str, Any]:
    return {"lines": [line.model_dump() for line in await rooms.lyrics(song_id)]}


@app.get("/api/listen/songs/{song_id}/reference-pitch")
async def reference_pitch(song_id: str) -> dict[str, Any]:
    analysis = await references.analysis(song_id)
    frames = analysis.frames if analysis else []
    return {
        "status": "ready" if frames else "missing",
        "source": analysis.source if analysis else None,
        "pitch": {"frames": [frame.model_dump() for frame in frames]} if frames else None,
    }


@app.get("/api/listen/songs/{song_id}/profile")
async def profile(song_id: str) -> dict[str, Any]:
    result = await references.profile(song_id) or await rooms.profile(song_id)
    return {"status": "ready" if result else "missing", "profile": result}


@app.post("/api/listen/room/singing/start")
async def start_singing(request: SingingStartRequest) -> dict[str, Any]:
    session = await singing.start(request.room_id, request.song_id, request.song_position_ms)
    await rooms.events.publish("singing", {"session": session.model_dump()})
    return {"session": session.model_dump()}


@app.post("/api/listen/room/singing/update")
async def update_singing(request: SingingUpdateRequest) -> dict[str, Any]:
    session = await singing.update(request.room_id, request.session_id, request.elapsed_ms, request.samples)
    if not session:
        raise HTTPException(status_code=404, detail="singing session not found")
    await rooms.events.publish("singing", {"session": session.model_dump()})
    return {"session": session.model_dump()}


@app.get("/api/listen/room/singing")
async def get_singing(room_id: str = "demo") -> dict[str, Any]:
    session = await singing.get(room_id)
    return {"session": session.model_dump() if session else None}


@app.post("/api/listen/room/singing/stop")
async def stop_singing(request: SingingStopRequest) -> dict[str, Any]:
    session = await singing.finish(request.room_id, request.session_id, request.elapsed_ms)
    if not session:
        raise HTTPException(status_code=404, detail="singing session not found")
    if session.sample_count < 3:
        session = await singing.mark_delivery(request.room_id, request.session_id, "too_short", "not_enough_pitch")
        return {"session": session.model_dump() if session else None, "reply": None}
    room = await rooms.snapshot(request.room_id)
    if not room.current_song or room.current_song.id != session.song_id:
        session = await singing.mark_delivery(request.room_id, request.session_id, "song_changed", "song_changed")
        return {"session": session.model_dump() if session else None, "reply": None}
    await singing.attach_reference(
        request.room_id,
        request.session_id,
        await references.get(session.song_id),
    )
    context = await _context_for_room(request.room_id, lyrics=True, analysis=True, notes=True)
    curve_context = await singing.model_context(request.room_id, request.session_id) or {}
    result = await conversation.submit_singing_receipt(_receipt_body(session.model_dump()), context, curve_context)
    session = await singing.mark_delivery(request.room_id, request.session_id, "replied")
    if result.messages:
        await rooms.add_note(result.messages[-1].content)
    if session:
        await rooms.events.publish("singing", {"session": session.model_dump()})
    return {
        "session": session.model_dump() if session else None,
        "reply": result.messages[-1].model_dump() if result.messages else None,
    }


@app.get("/api/chat/messages")
async def chat_messages() -> dict[str, Any]:
    return {"messages": [message.model_dump() for message in await conversation.visible_messages()]}


@app.post("/api/chat/messages")
async def send_chat_message(request: ChatMessageRequest) -> dict[str, Any]:
    options = context_options_for_text(request.text)
    context = (
        await _context_for_room(
            "demo",
            lyrics=bool(options and options["lyrics"]),
            analysis=bool(options and options["analysis"]),
            notes=bool(options and options["notes"]),
        )
        if options
        else None
    )
    result = await conversation.submit_user_message(request.text, context)
    return result.model_dump()
