from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from src.ui.app_factory import (
    _cleanup_selected_audio,
    _extract_audio_id,
    _extract_detection_key,
    _fetch_selected_audio,
    _save_selected_validation,
)


@dataclass
class FakeFetchResult:
    cache_key: str
    local_path: str
    source: str


class FakeAudioService:
    def __init__(self) -> None:
        self.cleaned: list[str] = []

    def fetch(self, dataset_repo: str, audio_id: str) -> FakeFetchResult:
        _ = dataset_repo
        return FakeFetchResult(cache_key=f"key:{audio_id}", local_path=f"/tmp/{audio_id}.wav", source="remote")

    def cleanup_after_validation(self, cache_key: str) -> None:
        self.cleaned.append(cache_key)


class FakeValidationService:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def validate_detection(
        self,
        project_slug: str,
        detection_key: str,
        status: str,
        validator: str,
        notes: str = "",
        corrected_species: str | None = None,
    ) -> dict[str, str]:
        _ = corrected_species
        payload = {
            "project_slug": project_slug,
            "detection_key": detection_key,
            "status": status,
            "validator": validator,
            "notes": notes,
        }
        self.calls.append(payload)
        return payload


def test_extract_audio_id_from_list_rows() -> None:
    rows = [["k1", "audio_01", "sp", 0.9, 0.0, 1.0]]
    assert _extract_audio_id(rows, 0) == "audio_01"


def test_extract_audio_id_from_dataframe_rows() -> None:
    frame = pd.DataFrame([["k1", "audio_02", "sp", 0.9, 0.0, 1.0]])
    assert _extract_audio_id(frame, 0) == "audio_02"


def test_fetch_selected_audio_success() -> None:
    service = FakeAudioService()
    rows = [["k1", "audio_03", "sp", 0.9, 0.0, 1.0]]

    path, cache_key, status = _fetch_selected_audio(
        audio_service=service,
        dataset_repo="org/dataset",
        rows=rows,
        selected_index=0,
        previous_cache_key="",
    )

    assert path == "/tmp/audio_03.wav"
    assert cache_key == "key:audio_03"
    assert "Audio carregado" in status


def test_extract_detection_key_from_rows() -> None:
    rows = [["dkey_01", "audio_01", "sp", 0.9, 0.0, 1.0]]
    assert _extract_detection_key(rows, 0) == "dkey_01"


def test_fetch_selected_audio_validates_repo() -> None:
    service = FakeAudioService()
    rows = [["k1", "audio_03", "sp", 0.9, 0.0, 1.0]]

    path, cache_key, status = _fetch_selected_audio(
        audio_service=service,
        dataset_repo="   ",
        rows=rows,
        selected_index=0,
        previous_cache_key="old-key",
    )

    assert path is None
    assert cache_key == ""
    assert "Informe dataset repo" in status


def test_cleanup_selected_audio() -> None:
    service = FakeAudioService()

    status, player_value = _cleanup_selected_audio(service, "key:audio_03")

    assert "Cache de audio limpo" in status
    assert player_value is None
    assert service.cleaned == ["key:audio_03"]


def test_save_selected_validation_saves_and_cleans_audio_cache() -> None:
    audio_service = FakeAudioService()
    validation_service = FakeValidationService()
    rows = [["0000000000001111", "audio_11", "sp", 0.9, 0.0, 1.0]]

    status, cache_key, audio_path = _save_selected_validation(
        validation_service=validation_service,
        audio_service=audio_service,
        project_slug="demo-project",
        rows=rows,
        selected_index=0,
        status_value="positive",
        validator="validator-demo",
        notes="ok",
        cache_key="cache:audio_11",
    )

    assert "Validacao salva" in status
    assert cache_key == ""
    assert audio_path is None
    assert len(validation_service.calls) == 1
    assert validation_service.calls[0]["detection_key"] == "0000000000001111"
    assert audio_service.cleaned == ["cache:audio_11"]
