from __future__ import annotations

import hashlib
import json
from uuid import uuid4

from sqlalchemy import event, select

from app.api.routes.serving import _hydrate_graph_chunk_content
from app.api.schemas import ProjectGraphNode, ProjectGraphResponse
from app.db.models import Chunk
from app.db.session import get_session_factory


def _chunk_graph(chunk: Chunk, *, metadata: dict | None = None) -> ProjectGraphResponse:
    return ProjectGraphResponse(
        project_id=chunk.project_id,
        nodes=[
            ProjectGraphNode(
                id=str(chunk.id),
                type="Chunk",
                label="legacy-title-must-not-be-content-authority",
                metadata=metadata
                or {
                    "technical_id": str(chunk.id),
                    "document_version_id": str(chunk.document_version_id),
                    "chunk_index": 999,
                    "content": "untrusted-preexisting-value",
                },
            )
        ],
        edges=[],
        node_limit=10,
    )


def main() -> None:
    session = get_session_factory()()
    try:
        chunk = session.scalar(select(Chunk).where(Chunk.status == "active").order_by(Chunk.created_at.desc(), Chunk.chunk_index))
        if chunk is None:
            raise RuntimeError("CHG-270 live acceptance requires one active Chunk")

        statement_count = 0

        def count_statement(*_args: object) -> None:
            nonlocal statement_count
            statement_count += 1

        bind = session.get_bind()
        event.listen(bind, "before_cursor_execute", count_statement)
        try:
            hydrated = _hydrate_graph_chunk_content(
                session,
                _chunk_graph(chunk),
                chunk.project_id,
                {chunk.document_version_id},
            )
        finally:
            event.remove(bind, "before_cursor_execute", count_statement)

        node = hydrated.nodes[0]
        assert statement_count == 1
        assert node.metadata["chunk_index"] == chunk.chunk_index
        assert node.metadata["content"] == chunk.content
        assert node.metadata["document_version_id"] == str(chunk.document_version_id)

        wrong_project = _hydrate_graph_chunk_content(
            session,
            _chunk_graph(chunk),
            uuid4(),
            {chunk.document_version_id},
        ).nodes[0]
        assert "chunk_index" not in wrong_project.metadata
        assert "content" not in wrong_project.metadata

        wrong_version = _hydrate_graph_chunk_content(
            session,
            _chunk_graph(chunk, metadata={"document_version_id": str(uuid4()), "chunk_index": 999, "content": "untrusted"}),
            chunk.project_id,
            {chunk.document_version_id},
        ).nodes[0]
        assert "chunk_index" not in wrong_version.metadata
        assert "content" not in wrong_version.metadata

        print(
            json.dumps(
                {
                    "authorized_batch_queries": statement_count,
                    "authorized_equal": True,
                    "chunk_id": str(chunk.id),
                    "chunk_index": chunk.chunk_index,
                    "content_length": len(chunk.content),
                    "content_sha256": hashlib.sha256(chunk.content.encode("utf-8")).hexdigest(),
                    "wrong_project_content_present": False,
                    "wrong_version_content_present": False,
                },
                sort_keys=True,
            )
        )
    finally:
        session.close()


if __name__ == "__main__":
    main()
