import asyncio

from httpx import ASGITransport, AsyncClient

from app.main import app


def test_public_api_flow_has_no_audio_upload_path() -> None:
    async def exercise() -> None:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            health = await client.get("/api/health")
            assert health.json() == {"ok": True}
            room = (await client.get("/api/listen/room")).json()["room"]
            assert room["current_song"]["id"] == "demo-signal"

            started = await client.post(
                "/api/listen/room/singing/start",
                json={"room_id": "demo", "song_id": "demo-signal", "song_position_ms": 0},
            )
            session = started.json()["session"]
            assert session["audio_shared"] is False
            assert "samples" not in session

            updated = await client.post(
                "/api/listen/room/singing/update",
                json={
                    "room_id": "demo",
                    "session_id": session["session_id"],
                    "elapsed_ms": 800,
                    "samples": [
                        {"t_ms": 0, "hz": 220},
                        {"t_ms": 180, "hz": 225},
                        {"t_ms": 360, "hz": 230},
                        {"t_ms": 540, "hz": 235},
                        {"t_ms": 720, "hz": 240},
                    ],
                },
            )
            assert updated.status_code == 200
            stopped = await client.post(
                "/api/listen/room/singing/stop",
                json={"room_id": "demo", "session_id": session["session_id"], "elapsed_ms": 900},
            )
            body = stopped.json()
            assert body["reply"]["role"] == "assistant"
            assert body["session"]["audio_shared"] is False

            chat = await client.post("/api/chat/messages", json={"text": "现在唱到哪一句歌词？"})
            assert chat.status_code == 200
            assert chat.json()["listening_context_attached"] is True

    asyncio.run(exercise())
