import asyncio
import json

from app.reference import ReferenceContourRepository


def test_repository_loads_only_a_derived_reference_artifact(tmp_path) -> None:
    artifact = {
        "analysis_version": 1,
        "song_id": "legal-demo",
        "source": "authorized_local_audio_full_mix",
        "frames": [
            {"t_ms": 0, "hz": 220.0, "confidence": 0.8},
            {"t_ms": 240, "hz": 233.1, "confidence": 0.8},
        ],
        "profile": {"source": "authorized_local_audio_full_mix", "melody": {"presence": "present"}},
    }
    (tmp_path / "legal-demo.json").write_text(json.dumps(artifact), encoding="utf-8")

    async def exercise() -> None:
        repository = ReferenceContourRepository(tmp_path)
        result = await repository.analysis("legal-demo")
        assert result is not None
        assert result.source == "authorized_local_audio_full_mix"
        assert [frame.hz for frame in result.frames] == [220.0, 233.1]
        assert result.profile and result.profile["melody"]["presence"] == "present"
        assert await repository.analysis("../../outside") is None

    asyncio.run(exercise())
