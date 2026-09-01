from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from uuid import UUID

BACKEND_ROOT = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_ROOT)
sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    AIModel,
    AIModelUsageEvent,
    ChatRecord,
    Chunk,
    ChunkTag,
    DocumentVersionTag,
    EmbeddingBuild,
    PublicApiRequestLog,
)
from app.db.session import get_engine
from app.domain.model_usage import record_model_usage


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill recoverable AI model usage events. Dry-run by default.")
    parser.add_argument("--apply", action="store_true", help="Commit backfilled rows.")
    parser.add_argument("--limit", type=int, default=10000, help="Maximum source rows per source type.")
    args = parser.parse_args()
    counts = {"chat_records": 0, "public_api_request_logs": 0, "embedding_builds": 0, "document_tags": 0, "chunk_tags": 0, "skipped": 0}
    with Session(get_engine(), expire_on_commit=False) as session:
        known = set(session.scalars(select(AIModelUsageEvent.correlation_id).where(AIModelUsageEvent.correlation_id.like("backfill:%"))))

        for record in session.scalars(select(ChatRecord).where(ChatRecord.llm_model_id.is_not(None), ChatRecord.token_usage.is_not(None)).limit(args.limit)):
            key = f"backfill:chat_records:{record.id}"
            model = session.get(AIModel, record.llm_model_id)
            if key in known or model is None:
                counts["skipped"] += 1
                continue
            record_model_usage(session, model=model, usage_purpose="chat_test", source_channel="backfill", status="success" if record.answer else "failed", token_usage=record.token_usage, latency_ms=record.latency_ms, project_id=record.project_id, document_version_id=record.document_version_id, chat_record_id=record.id, actor_user_id=record.created_by, correlation_id=key, metadata={"source": "backfill"}, created_at=record.created_at)
            known.add(key); counts["chat_records"] += 1

        for record in session.scalars(select(PublicApiRequestLog).where(PublicApiRequestLog.llm_model_id.is_not(None), PublicApiRequestLog.token_usage.is_not(None)).limit(args.limit)):
            key = f"backfill:public_api_request_logs:{record.id}"
            model = session.get(AIModel, record.llm_model_id)
            if key in known or model is None:
                counts["skipped"] += 1
                continue
            record_model_usage(session, model=model, usage_purpose="public_api_chat", source_channel="backfill", status="success" if record.result == "success" else record.result, token_usage=record.token_usage, latency_ms=record.latency_ms, project_id=record.project_id, document_version_id=record.document_version_id, public_api_request_log_id=record.id, integration_client_id=record.integration_client_id, correlation_id=key, metadata={"source": "backfill"}, created_at=record.created_at)
            known.add(key); counts["public_api_request_logs"] += 1

        for build in session.scalars(select(EmbeddingBuild).where(EmbeddingBuild.model_id.is_not(None)).limit(args.limit)):
            key = f"backfill:embedding_builds:{build.id}"
            model = session.get(AIModel, build.model_id)
            if key in known or model is None:
                counts["skipped"] += 1
                continue
            usage = dict(build.usage or {})
            usage.setdefault("embedding_tokens", build.token_count)
            record_model_usage(session, model=model, usage_purpose="embedding_build", source_channel="backfill", status="success" if build.status in {"completed", "staged", "published"} else build.status, token_usage=usage, project_id=build.project_id, document_id=build.document_id, document_version_id=build.document_version_id, vector_count=build.chunk_count, chunk_count=build.chunk_count, correlation_id=key, metadata={"source": "backfill", "embedding_build_id": str(build.id)}, created_at=build.created_at)
            known.add(key); counts["embedding_builds"] += 1

        for link in session.scalars(select(DocumentVersionTag).where(DocumentVersionTag.source == "llm").limit(args.limit)):
            metadata = link.metadata_ or {}
            key = f"backfill:document_tags:{link.document_version_id}:{metadata.get('request_id') or link.created_at.isoformat()}"
            model = _metadata_model(session, metadata)
            if key in known or model is None or not isinstance(metadata.get("token_usage"), dict):
                counts["skipped"] += 1
                continue
            record_model_usage(session, model=model, usage_purpose="document_auto_tag", source_channel="backfill", status="success", token_usage=metadata["token_usage"], document_version_id=link.document_version_id, actor_user_id=link.created_by, correlation_id=key, metadata={"source": "backfill"}, created_at=link.created_at)
            known.add(key); counts["document_tags"] += 1

        for link in session.scalars(select(ChunkTag).where(ChunkTag.source == "llm").limit(args.limit)):
            metadata = link.metadata_ or {}
            chunk = session.get(Chunk, link.chunk_id)
            key = f"backfill:chunk_tags:{link.chunk_id}:{metadata.get('request_id') or link.created_at.isoformat()}"
            model = _metadata_model(session, metadata)
            if key in known or model is None or chunk is None or not isinstance(metadata.get("token_usage"), dict):
                counts["skipped"] += 1
                continue
            record_model_usage(session, model=model, usage_purpose="chunk_auto_tag", source_channel="backfill", status="success", token_usage=metadata["token_usage"], project_id=chunk.project_id, document_id=chunk.document_id, document_version_id=chunk.document_version_id, actor_user_id=link.created_by, correlation_id=key, metadata={"source": "backfill", "chunk_id": str(chunk.id)}, created_at=link.created_at)
            known.add(key); counts["chunk_tags"] += 1

        print({"mode": "apply" if args.apply else "dry-run", "counts": counts})
        if args.apply:
            session.commit()
        else:
            session.rollback()
    return 0


def _metadata_model(session: Session, metadata: dict) -> AIModel | None:
    raw = metadata.get("llm_model_id")
    if not raw:
        return None
    try:
        return session.get(AIModel, UUID(str(raw)))
    except ValueError:
        return None


if __name__ == "__main__":
    raise SystemExit(main())
