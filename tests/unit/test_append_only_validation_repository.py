from pathlib import Path

from src.domain.models import Validation
from src.repositories.append_only_validation_repository import AppendOnlyValidationRepository


def test_save_validation_appends_event_and_updates_snapshot(tmp_path: Path) -> None:
    repo = AppendOnlyValidationRepository(base_dir=str(tmp_path))

    first = Validation(
        detection_key="0000000000002001",
        status="positive",
        corrected_species=None,
        notes="first",
        validator="validator-a",
    )
    second = Validation(
        detection_key="0000000000002001",
        status="negative",
        corrected_species="Species B",
        notes="updated",
        validator="validator-b",
    )

    repo.save_validation(project_slug="demo-project", item=first)
    repo.save_validation(project_slug="demo-project", item=second)

    events = repo.list_events("demo-project")
    snapshot = repo.load_current_snapshot("demo-project")

    assert len(events) == 2
    assert events[0]["detection_key"] == "0000000000002001"
    assert snapshot["0000000000002001"]["status"] == "negative"
    assert snapshot["0000000000002001"]["validator"] == "validator-b"


def test_repository_returns_empty_for_missing_project(tmp_path: Path) -> None:
    repo = AppendOnlyValidationRepository(base_dir=str(tmp_path))

    assert repo.list_events("missing-project") == []
    assert repo.load_current_snapshot("missing-project") == {}
