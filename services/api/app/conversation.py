"""An adapter seam that keeps singing receipts in the main chat timeline."""

from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from .context import prompt_block
from .models import ChatMessage, ChatResult
from .room import clean_text


@dataclass
class _StoredMessage:
    id: str
    role: str
    content: str
    created_at: str
    kind: str
    visible: bool

    def public(self) -> ChatMessage:
        return ChatMessage(
            id=self.id,
            role=self.role,  # type: ignore[arg-type]
            content=self.content,
            created_at=self.created_at,
            kind=self.kind,
        )


class ConversationGateway(Protocol):
    async def reply(self, user_text: str, context: dict[str, Any], *, kind: str) -> str:
        """Return the next assistant turn from the application's main chat."""


class DemoConversationGateway:
    """Deterministic demo gateway. It never sends data to a model provider."""

    async def reply(self, user_text: str, context: dict[str, Any], *, kind: str) -> str:
        if kind == "singing_receipt":
            return "我收到了这段跟唱。我们可以顺着这一句继续听，或者换一首。"
        active = context.get("active_lyric") if isinstance(context, dict) else None
        if isinstance(active, dict) and active.get("text"):
            return f"我看到了当前播放位置，也看到了这一句示例内容：{clean_text(active['text'], 80)}"
        if context.get("song"):
            return "我看到了你们正在一起听的房间状态。"
        return "这是一条普通聊天消息；提到歌曲或歌词时会按需附带一起听背景。"


class ConversationService:
    def __init__(self, gateway: ConversationGateway | None = None) -> None:
        self._gateway = gateway or DemoConversationGateway()
        self._lock = asyncio.Lock()
        self._messages: list[_StoredMessage] = []

    @staticmethod
    def _message(role: str, content: str, kind: str, *, visible: bool) -> _StoredMessage:
        return _StoredMessage(
            id=secrets.token_urlsafe(12),
            role=role,
            content=clean_text(content, 4_000),
            created_at=datetime.now(timezone.utc).isoformat(),
            kind=kind,
            visible=visible,
        )

    async def visible_messages(self) -> list[ChatMessage]:
        async with self._lock:
            return [message.public() for message in self._messages if message.visible]

    async def submit_user_message(
        self,
        text: str,
        context: dict[str, Any] | None,
    ) -> ChatResult:
        # Build the boundary even in the demo so production adapters get one
        # clear, testable integration point. It is intentionally not displayed.
        _context_boundary = prompt_block(context) if context else ""
        del _context_boundary
        user = self._message("user", text, "chat", visible=True)
        answer = await self._gateway.reply(user.content, context or {}, kind="chat")
        assistant = self._message("assistant", answer, "chat", visible=True)
        async with self._lock:
            self._messages.extend((user, assistant))
            self._messages = self._messages[-100:]
        return ChatResult(
            messages=[user.public(), assistant.public()],
            listening_context_attached=bool(context),
            context_fields=sorted(context.keys()) if context else [],
        )

    async def submit_singing_receipt(
        self,
        receipt_body: str,
        context: dict[str, Any],
        singing_curve_context: dict[str, Any],
    ) -> ChatResult:
        # This is the key integration point: the receipt is a hidden user input
        # in the same timeline, while the response is a normal visible turn.
        safe_curve = dict(singing_curve_context)
        combined_context = {**context, "shared_singing": safe_curve}
        _context_boundary = prompt_block(combined_context)
        del _context_boundary
        hidden = self._message("user", receipt_body, "singing_receipt", visible=False)
        answer = await self._gateway.reply(hidden.content, combined_context, kind="singing_receipt")
        assistant = self._message("assistant", answer, "singing_receipt", visible=True)
        async with self._lock:
            self._messages.extend((hidden, assistant))
            self._messages = self._messages[-100:]
        return ChatResult(
            messages=[assistant.public()],
            listening_context_attached=True,
            context_fields=sorted(combined_context.keys()),
        )
