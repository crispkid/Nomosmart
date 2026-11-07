from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.core.errors import AppError


@dataclass(frozen=True)
class EmbeddingProfile:
    id: UUID
    model_id: UUID
    model_version: str
    vector_dimension: int
    distance_method: str
    mapping_version: int

    def compatible_with(self, other: "EmbeddingProfile") -> bool:
        return (
            self.id == other.id
            and self.vector_dimension == other.vector_dimension
            and self.distance_method == other.distance_method
            and self.mapping_version == other.mapping_version
        )


@dataclass(frozen=True)
class ActiveVersionEntry:
    project_id: UUID
    document_id: UUID
    document_version_id: UUID
    embedding_profile_id: UUID
    embedding_build_id: UUID
    publication_generation: int
    index_ready: bool


def active_version_ids(entries: list[ActiveVersionEntry]) -> list[str]:
    if not entries or any(not entry.index_ready for entry in entries):
        raise AppError("serving_manifest_unavailable", "Active serving manifest is unavailable", status_code=503)
    return [str(entry.document_version_id) for entry in entries]


def vector_document_id(profile_id: UUID, version_id: UUID, chunk_id: UUID) -> str:
    return f"{profile_id}:{version_id}:{chunk_id}"

