from src.domain.models import Validation
from src.repositories.contracts import ValidationRepository


class ValidationService:
    def __init__(self, repository: ValidationRepository) -> None:
        self._repository = repository

    def validate_detection(
        self,
        project_slug: str,
        detection_key: str,
        status: str,
        validator: str,
        notes: str = "",
        corrected_species: str | None = None,
    ) -> Validation:
        item = Validation(
            detection_key=detection_key,
            status=status,
            corrected_species=corrected_species,
            notes=notes,
            validator=validator,
        )
        self._repository.save_validation(project_slug=project_slug, item=item)
        return item
