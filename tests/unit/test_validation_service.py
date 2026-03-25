from src.repositories.in_memory_validation_repository import InMemoryValidationRepository
from src.services.validation_service import ValidationService


def test_validate_detection_saves_item() -> None:
    repo = InMemoryValidationRepository()
    service = ValidationService(repo)

    item = service.validate_detection(
        project_slug="demo-project",
        detection_key="0000000000009999",
        status="positive",
        validator="validator-demo",
        notes="ok",
    )

    assert item.status == "positive"
    assert item.validator == "validator-demo"
    saved = repo.list_validations("demo-project")
    assert len(saved) == 1
    assert saved[0].detection_key == "0000000000009999"
