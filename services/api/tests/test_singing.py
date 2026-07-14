import asyncio

from app.models import PitchSample, ReferenceFrame
from app.singing import SingingSessionService, build_reference_observation, contour_relation


def test_reference_comparison_is_relative_not_a_score() -> None:
    samples = [PitchSample(t_ms=index * 180, hz=220 * (2 ** (index / 48))) for index in range(8)]
    reference = [ReferenceFrame(t_ms=1000 + index * 180, hz=440 * (2 ** (index / 48))) for index in range(8)]
    observation = build_reference_observation(samples, 1000, reference)
    assert observation["available"] is True
    assert observation["scope"] == "relative_contour_only"
    assert observation["overall"]["contour_relation"] == "closely_followed"
    assert "score" not in observation
    assert contour_relation([60, 61, 62], [72, 73, 74]) == "closely_followed"


def test_public_singing_session_never_contains_raw_samples_or_audio() -> None:
    async def exercise() -> None:
        service = SingingSessionService()
        started = await service.start("demo", "demo-signal", 1_000)
        updated = await service.update(
            "demo",
            started.session_id,
            900,
            [PitchSample(t_ms=index * 180, hz=220 + index * 3) for index in range(6)],
        )
        assert updated is not None
        payload = updated.model_dump()
        assert payload["audio_shared"] is False
        assert "samples" not in payload
        assert "audio" not in payload
        await service.finish("demo", started.session_id, 1_000)
        observation = await service.attach_reference(
            "demo",
            started.session_id,
            [ReferenceFrame(t_ms=1000 + index * 180, hz=330 + index * 4) for index in range(6)],
        )
        assert observation and observation["scope"] == "relative_contour_only"
        model_context = await service.model_context("demo", started.session_id)
        assert model_context and "reference_observation" in model_context
        assert "raw_samples" not in str(model_context)
        assert "audio" not in str(model_context)

    asyncio.run(exercise())
