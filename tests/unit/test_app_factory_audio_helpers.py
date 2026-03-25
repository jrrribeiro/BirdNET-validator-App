from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from src.ui.app_factory import (
    _build_validation_report,
    _cleanup_selected_audio,
    _extract_audio_id,
    _extract_detection_key,
    _find_detection_row_index,
    _fetch_selected_audio,
    _page_to_table,
    _save_selected_validation,
    _save_selected_validation_with_refresh,
    _reapply_last_conflict_validation_with_refresh,
    _batch_validate_conflicts,
    create_app,
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
        expected_version: int | None = None,
    ) -> dict[str, str]:
        _ = corrected_species
        payload = {
            "project_slug": project_slug,
            "detection_key": detection_key,
            "status": status,
            "validator": validator,
            "notes": notes,
            "expected_version": str(expected_version),
        }
        self.calls.append(payload)
        return payload


class FakeConflictValidationService:
    def validate_detection(
        self,
        project_slug: str,
        detection_key: str,
        status: str,
        validator: str,
        notes: str = "",
        corrected_species: str | None = None,
        expected_version: int | None = None,
    ) -> dict[str, str]:
        _ = project_slug
        _ = detection_key
        _ = status
        _ = validator
        _ = notes
        _ = corrected_species
        _ = expected_version
        from src.repositories.append_only_validation_repository import OptimisticLockError

        raise OptimisticLockError("dkey_01", expected_version or 0, 3)


class FakeSnapshotReader:
    def __init__(self) -> None:
        self.snapshot: dict[str, dict[str, object]] = {
            "dkey_01": {
                "status": "positive",
                "validator": "validator-demo",
                "version": 2,
            }
        }
        self.events: list[dict[str, object]] = [
            {"detection_key": "dkey_01", "status": "positive"},
            {"detection_key": "dkey_01", "status": "negative"},
        ]

    def load_current_snapshot(self, project_slug: str) -> dict[str, dict[str, object]]:
        _ = project_slug
        return self.snapshot

    def list_events(self, project_slug: str) -> list[dict[str, object]]:
        _ = project_slug
        return self.events


class FakeQueueService:
    class _Page:
        def __init__(self) -> None:
            self.page = 1
            self.total_pages = 1
            self.total_items = 1
            self.items = [
                type(
                    "DetectionLike",
                    (),
                    {
                        "detection_key": "dkey_01",
                        "audio_id": "audio_01",
                        "scientific_name": "sp",
                        "confidence": 0.9,
                        "start_time": 0.0,
                        "end_time": 1.0,
                    },
                )()
            ]

    def get_page(self, **kwargs: object) -> "FakeQueueService._Page":
        _ = kwargs
        return FakeQueueService._Page()


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
    rows = [["0000000000001111", "audio_11", "sp", 0.9, 0.0, 1.0, "pending", 0]]

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
    assert validation_service.calls[0]["expected_version"] == "0"
    assert audio_service.cleaned == ["cache:audio_11"]


def test_save_selected_validation_returns_conflict_message() -> None:
    audio_service = FakeAudioService()
    validation_service = FakeConflictValidationService()
    rows = [["0000000000001111", "audio_11", "sp", 0.9, 0.0, 1.0, "pending", 0]]

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

    assert "Conflito de concorrencia" in status
    assert cache_key == "cache:audio_11"
    assert audio_path is None


def test_build_validation_report() -> None:
    report = _build_validation_report(FakeSnapshotReader(), "demo-project")

    assert "Projeto: demo-project" in report
    assert "Eventos append-only: 2" in report
    assert "Deteccoes com estado atual: 1" in report
    assert "positive=1" in report


def test_page_to_table_includes_validation_status() -> None:
    rows, status, page = _page_to_table(
        service=FakeQueueService(),
        snapshot_reader=FakeSnapshotReader(),
        project_slug="demo-project",
        page=1,
        scientific_name="",
        min_confidence=0.0,
    )

    assert page == 1
    assert "Pagina 1/1" in status
    assert rows[0][0] == "dkey_01"
    assert rows[0][6] == "positive"
    assert rows[0][7] == 2
    assert rows[0][8] == ""
    assert rows[0][9] == ""


def test_page_to_table_marks_conflict_row() -> None:
    rows, _, _ = _page_to_table(
        service=FakeQueueService(),
        snapshot_reader=FakeSnapshotReader(),
        project_slug="demo-project",
        page=1,
        scientific_name="",
        min_confidence=0.0,
        conflict_detection_key="dkey_01",
    )

    assert rows[0][8] == "CONFLICT"
    assert rows[0][9] == "HIGH"


def test_page_to_table_conflicts_only_filter_hides_non_conflicts() -> None:
    rows, status, _ = _page_to_table(
        service=FakeQueueService(),
        snapshot_reader=FakeSnapshotReader(),
        project_slug="demo-project",
        page=1,
        scientific_name="",
        min_confidence=0.0,
        show_conflicts_only=True,
    )

    assert rows == []
    assert "Apenas conflitos: 0 item(ns)" in status


def test_page_to_table_conflicts_only_filter_keeps_conflict_rows() -> None:
    rows, status, _ = _page_to_table(
        service=FakeQueueService(),
        snapshot_reader=FakeSnapshotReader(),
        project_slug="demo-project",
        page=1,
        scientific_name="",
        min_confidence=0.0,
        conflict_detection_key="dkey_01",
        show_conflicts_only=True,
    )

    assert len(rows) == 1
    assert rows[0][8] == "CONFLICT"
    assert "Apenas conflitos: 1 item(ns)" in status


def test_find_detection_row_index() -> None:
    rows = [["dkey_00", "audio_00"], ["dkey_01", "audio_01"]]

    assert _find_detection_row_index(rows, "dkey_01") == 1
    assert _find_detection_row_index(rows, "missing") == 0


def test_save_selected_validation_with_refresh_success() -> None:
    audio_service = FakeAudioService()
    validation_service = FakeValidationService()
    rows = [["dkey_01", "audio_11", "sp", 0.9, 0.0, 1.0, "pending", 0]]

    status, cache_key, audio_path, refreshed_rows, refreshed_page, refreshed_index, pending_status, conflict_key = _save_selected_validation_with_refresh(
        validation_service=validation_service,
        audio_service=audio_service,
        queue_service=FakeQueueService(),
        snapshot_reader=FakeSnapshotReader(),
        project_slug="demo-project",
        rows=rows,
        selected_index=0,
        status_value="positive",
        validator="validator-demo",
        notes="ok",
        cache_key="cache:audio_11",
        page=1,
        scientific_name="",
        min_confidence=0.0,
        show_conflicts_only=False,
    )

    assert "Validacao salva" in status
    assert cache_key == ""
    assert audio_path is None
    assert refreshed_page == 1
    assert refreshed_index == 0
    assert refreshed_rows[0][0] == "dkey_01"
    assert pending_status == ""
    assert conflict_key == ""


def test_save_selected_validation_with_refresh_conflict() -> None:
    audio_service = FakeAudioService()
    validation_service = FakeConflictValidationService()
    rows = [["dkey_01", "audio_11", "sp", 0.9, 0.0, 1.0, "pending", 0]]

    status, cache_key, audio_path, refreshed_rows, refreshed_page, refreshed_index, pending_status, conflict_key = _save_selected_validation_with_refresh(
        validation_service=validation_service,
        audio_service=audio_service,
        queue_service=FakeQueueService(),
        snapshot_reader=FakeSnapshotReader(),
        project_slug="demo-project",
        rows=rows,
        selected_index=0,
        status_value="positive",
        validator="validator-demo",
        notes="ok",
        cache_key="cache:audio_11",
        page=1,
        scientific_name="",
        min_confidence=0.0,
        show_conflicts_only=False,
    )

    assert "Conflito de concorrencia" in status
    assert "Tabela recarregada" in status
    assert cache_key == "cache:audio_11"
    assert audio_path is None
    assert refreshed_page == 1
    assert refreshed_index == 0
    assert refreshed_rows[0][0] == "dkey_01"
    assert refreshed_rows[0][8] == "CONFLICT"
    assert refreshed_rows[0][9] == "HIGH"
    assert pending_status == "positive"
    assert conflict_key == "dkey_01"


def test_reapply_last_conflict_validation_with_refresh() -> None:
    audio_service = FakeAudioService()
    validation_service = FakeValidationService()
    rows = [["dkey_01", "audio_11", "sp", 0.9, 0.0, 1.0, "pending", 2, "conflict"]]

    status, cache_key, audio_path, refreshed_rows, refreshed_page, refreshed_index, pending_status, conflict_key = _reapply_last_conflict_validation_with_refresh(
        validation_service=validation_service,
        audio_service=audio_service,
        queue_service=FakeQueueService(),
        snapshot_reader=FakeSnapshotReader(),
        project_slug="demo-project",
        rows=rows,
        selected_index=0,
        pending_status_value="positive",
        conflict_detection_key="dkey_01",
        validator="validator-demo",
        notes="retry",
        cache_key="",
        page=1,
        scientific_name="",
        min_confidence=0.0,
        show_conflicts_only=False,
    )

    assert "Validacao salva" in status
    assert cache_key == ""
    assert audio_path is None
    assert refreshed_page == 1
    assert refreshed_index == 0
    assert refreshed_rows[0][0] == "dkey_01"
    assert pending_status == ""
    assert conflict_key == ""


def test_reapply_last_conflict_without_pending_status() -> None:
    audio_service = FakeAudioService()
    validation_service = FakeValidationService()
    rows = [["dkey_01", "audio_11", "sp", 0.9, 0.0, 1.0, "pending", 2, ""]]

    status, _, _, _, _, _, pending_status, conflict_key = _reapply_last_conflict_validation_with_refresh(
        validation_service=validation_service,
        audio_service=audio_service,
        queue_service=FakeQueueService(),
        snapshot_reader=FakeSnapshotReader(),
        project_slug="demo-project",
        rows=rows,
        selected_index=0,
        pending_status_value="",
        conflict_detection_key="",
        validator="validator-demo",
        notes="retry",
        cache_key="",
        page=1,
        scientific_name="",
        min_confidence=0.0,
        show_conflicts_only=False,
    )

    assert "Nenhuma validacao pendente" in status
    assert pending_status == ""
    assert conflict_key == ""


def test_create_app_with_keyboard_shortcuts() -> None:
    """Test that create_app successfully creates the UI with keyboard shortcuts enabled."""
    app = create_app()
    assert app is not None
    # Verify the app is a Gradio Blocks instance
    assert hasattr(app, "queue")
    assert hasattr(app, "launch")


def test_batch_validate_conflicts_all_success() -> None:
    """Test batch approval of all conflicts in table."""
    audio_service = FakeAudioService()
    validation_service = FakeValidationService()
    rows = [
        ["dkey_01", "audio_11", "sp", 0.9, 0.0, 1.0, "pending", 1, "CONFLICT", "HIGH"],
        ["dkey_02", "audio_12", "sp", 0.85, 1.0, 2.0, "pending", 1, "CONFLICT", "HIGH"],
    ]

    status, cache_key, audio_path, refreshed_rows, refreshed_page = _batch_validate_conflicts(
        validation_service=validation_service,
        audio_service=audio_service,
        queue_service=FakeQueueService(),
        snapshot_reader=FakeSnapshotReader(),
        project_slug="demo-project",
        rows=rows,
        status_value="positive",
        validator="validator-demo",
        notes="batch approval",
        cache_key="",
        page=1,
        scientific_name="",
        min_confidence=0.0,
    )

    assert "Processados 2 conflitos" in status
    assert "2 sucesso" in status
    assert cache_key == ""
    assert refreshed_page == 1
    assert len(validation_service.calls) == 2


def test_batch_validate_conflicts_no_conflicts() -> None:
    """Test batch validation when no conflicts are present."""
    audio_service = FakeAudioService()
    validation_service = FakeValidationService()
    rows = [
        ["dkey_01", "audio_11", "sp", 0.9, 0.0, 1.0, "positive", 2, "", ""],
    ]

    status, cache_key, audio_path, refreshed_rows, refreshed_page = _batch_validate_conflicts(
        validation_service=validation_service,
        audio_service=audio_service,
        queue_service=FakeQueueService(),
        snapshot_reader=FakeSnapshotReader(),
        project_slug="demo-project",
        rows=rows,
        status_value="positive",
        validator="validator-demo",
        notes="batch approval",
        cache_key="",
        page=1,
        scientific_name="",
        min_confidence=0.0,
    )

    assert "Nenhuma deteccao com conflito" in status
    assert len(validation_service.calls) == 0
