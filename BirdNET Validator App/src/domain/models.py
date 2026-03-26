from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Role(str, Enum):
    admin = "admin"
    validator = "validator"


class User(BaseModel):
    username: str = Field(min_length=1)
    role: Role
    active: bool = True


class Project(BaseModel):
    project_slug: str = Field(min_length=3)
    name: str = Field(min_length=1)
    dataset_repo_id: str = Field(min_length=3)
    active: bool = True


class Detection(BaseModel):
    detection_key: str = Field(min_length=16)
    audio_id: str = Field(min_length=1)
    scientific_name: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    start_time: float = Field(ge=0.0)
    end_time: float = Field(gt=0.0)


class Validation(BaseModel):
    detection_key: str = Field(min_length=16)
    status: str = Field(min_length=1)
    corrected_species: Optional[str] = None
    notes: str = ""
    validator: str = Field(min_length=1)


class IndexManifest(BaseModel):
    schema_version: str = "1.0.0"
    project_slug: str
    total_detections: int = Field(ge=0)
    total_audio_files: int = Field(ge=0)
