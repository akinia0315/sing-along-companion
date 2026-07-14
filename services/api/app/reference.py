"""A provider-neutral repository for derived original-song reference contours."""

from __future__ import annotations

import math

from .models import ReferenceFrame


def _hz(midi: float) -> float:
    return round(440 * (2 ** ((midi - 69) / 12)), 1)


class ReferenceContourRepository:
    """The demo curve is synthetic; production should load authorized output."""

    def __init__(self) -> None:
        shape = (57, 59, 61, 64, 62, 59, 57, 59, 62, 64, 66, 64, 61, 59)
        self._demo_frames = [
            ReferenceFrame(t_ms=index * 700, hz=_hz(midi), confidence=0.7)
            for index, midi in enumerate(shape)
        ]

    async def get(self, song_id: str) -> list[ReferenceFrame]:
        if song_id != "demo-signal":
            return []
        return [frame.model_copy(deep=True) for frame in self._demo_frames]
