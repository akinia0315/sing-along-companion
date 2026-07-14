import asyncio

from app.conversation import ConversationService


def test_singing_receipt_becomes_visible_assistant_turn_only() -> None:
    async def exercise() -> None:
        service = ConversationService()
        result = await service.submit_singing_receipt(
            "Sing-along receipt: shared a short pitch trace.",
            {"song": {"id": "demo"}, "room": {"position_ms": 1000}},
            {"reference_observation": {"scope": "relative_contour_only"}},
        )
        assert len(result.messages) == 1
        assert result.messages[0].role == "assistant"
        assert result.messages[0].kind == "singing_receipt"
        visible = await service.visible_messages()
        assert len(visible) == 1
        assert "receipt" not in visible[0].content.lower()

    asyncio.run(exercise())


def test_ordinary_chat_only_marks_context_when_one_was_provided() -> None:
    async def exercise() -> None:
        service = ConversationService()
        result = await service.submit_user_message("hello", None)
        assert result.listening_context_attached is False

    asyncio.run(exercise())
