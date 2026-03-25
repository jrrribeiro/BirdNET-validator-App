from collections import defaultdict
from typing import DefaultDict

from src.domain.models import Validation


class InMemoryValidationRepository:
    def __init__(self) -> None:
        self._by_project: DefaultDict[str, list[Validation]] = defaultdict(list)

    def save_validation(self, project_slug: str, item: Validation) -> None:
        self._by_project[project_slug].append(item)

    def list_validations(self, project_slug: str) -> list[Validation]:
        return list(self._by_project.get(project_slug, []))
