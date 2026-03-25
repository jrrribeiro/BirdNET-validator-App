import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from src.domain.models import Validation


class AppendOnlyValidationRepository:
    def __init__(self, base_dir: str) -> None:
        self._base_dir = Path(base_dir)

    def save_validation(self, project_slug: str, item: Validation) -> None:
        project_dir = self._base_dir / project_slug / "validations"
        project_dir.mkdir(parents=True, exist_ok=True)

        event_date = datetime.now(UTC).strftime("%Y%m%d")
        events_file = project_dir / f"events-{event_date}.jsonl"
        event = {
            "event_id": str(uuid4()),
            "timestamp": datetime.now(UTC).isoformat(),
            "project_slug": project_slug,
            **item.model_dump(),
        }
        with events_file.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=True) + "\n")

        current_file = project_dir / "current.json"
        if current_file.exists():
            current_payload = json.loads(current_file.read_text(encoding="utf-8"))
        else:
            current_payload = {}

        current_payload[item.detection_key] = {
            "status": item.status,
            "corrected_species": item.corrected_species,
            "notes": item.notes,
            "validator": item.validator,
            "updated_at": event["timestamp"],
        }
        current_file.write_text(json.dumps(current_payload, indent=2), encoding="utf-8")

    def list_events(self, project_slug: str) -> list[dict[str, object]]:
        project_dir = self._base_dir / project_slug / "validations"
        if not project_dir.exists():
            return []

        events: list[dict[str, object]] = []
        for path in sorted(project_dir.glob("events-*.jsonl")):
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    payload = line.strip()
                    if payload:
                        events.append(json.loads(payload))
        return events

    def load_current_snapshot(self, project_slug: str) -> dict[str, dict[str, object]]:
        current_file = self._base_dir / project_slug / "validations" / "current.json"
        if not current_file.exists():
            return {}
        return json.loads(current_file.read_text(encoding="utf-8"))
