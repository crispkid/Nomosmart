from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from app.core.config import Settings
from app.core.errors import AppError
from app.db.models import DocumentVersion
from app.domain.docx_security import inspect_docx_package
from app.domain.office_child import run_office_child


MAX_MEDIA_FILES = 512
PARSER_PROFILE = "pandoc-worker-local-sandbox-docx-gfm-title-v3"


@dataclass(frozen=True)
class ParsedOfficeDocument:
    markdown: str
    media: tuple[dict[str, object], ...]
    metadata: dict[str, object]
    reliable_text_layer: bool


@dataclass(frozen=True)
class _MediaData:
    original_path: str
    body: bytes


def parse_office_document(settings: Settings, version: DocumentVersion) -> ParsedOfficeDocument:
    from app.integrations.s3_storage import S3ObjectStorage

    if (version.canonical_extension or "").lower() != ".docx":
        code = "legacy_doc_reextraction_unsupported" if (version.canonical_extension or "").lower() == ".doc" else "office_format_unsupported"
        message = "Legacy DOC files cannot be re-extracted; upload a DOCX replacement" if code.startswith("legacy") else "DOCX is the only supported Word format"
        raise AppError(code, message, status_code=422)
    if not version.storage_bucket or not version.storage_key:
        raise AppError("office_source_missing", "DOCX source file is unavailable", status_code=409)

    storage = S3ObjectStorage(settings)
    source = storage.get_object(
        bucket=version.storage_bucket,
        key=version.storage_key,
        max_bytes=settings.max_upload_size_mb * 1024 * 1024,
    ).body
    inspection = inspect_docx_package(source, max_source_bytes=settings.max_upload_size_mb * 1024 * 1024)
    command = shlex.split(settings.pandoc_command)
    _require_runtime(command)
    parser_version = _pandoc_version(tuple(command), settings=settings)

    cache_key = _cache_key(settings, source, command, parser_version)
    cached = _read_cache(Path(settings.pandoc_cache_dir), cache_key, settings=settings)
    if cached is None:
        raw_markdown, media_data = _convert_with_pandoc(settings, source, command)
        cache_hit = False
    else:
        raw_markdown, media_data = cached
        cache_hit = True

    force_ocr = bool((version.chunk_strategy or {}).get("force_ocr"))
    if not _has_usable_text(raw_markdown) and not (force_ocr and media_data):
        raise AppError("pandoc_conversion_empty", "Pandoc produced no usable document text", status_code=422)
    if not cache_hit:
        _write_cache(Path(settings.pandoc_cache_dir), cache_key, raw_markdown, media_data)
    media_manifest, replacements = _persist_media(settings, storage, version, media_data)
    markdown = _rewrite_media_references(raw_markdown, replacements).strip()
    reliable_text = _has_usable_text(markdown)
    if not reliable_text and not (force_ocr and media_manifest):
        raise AppError("pandoc_conversion_empty", "Pandoc produced no usable document text", status_code=422)

    return ParsedOfficeDocument(
        markdown=markdown,
        media=tuple(media_manifest),
        reliable_text_layer=reliable_text,
        metadata={
            "adapter_source": PARSER_PROFILE,
            "parser_profile": PARSER_PROFILE,
            "cache_key": cache_key,
            "parser_version": parser_version,
            "track_changes": "accept",
            "comments_in_body": False,
            "has_comments": inspection.has_comments,
            "revision_count": inspection.revision_count,
            "source_visible_text_nodes": inspection.visible_text_nodes,
            "docx_entry_count": inspection.entry_count,
            "docx_expanded_bytes": inspection.expanded_bytes,
            "media_count": len(media_manifest),
            "cache_hit": cache_hit,
        },
    )


def _require_runtime(command: list[str]) -> None:
    if not command:
        raise AppError("pandoc_unavailable", "Pandoc is not configured", status_code=503)
    if len(command) != 1:
        raise AppError("pandoc_sandbox_unavailable", "Pandoc command must name one executable without extra arguments", status_code=503)
    executable = shutil.which(command[0])
    if executable is None:
        raise AppError("pandoc_unavailable", "Pandoc is unavailable", status_code=503)
    command[0] = str(Path(executable).resolve())


def _cache_key(settings: Settings, source: bytes, command: list[str], parser_version: str) -> str:
    return hashlib.sha256(
        source + json.dumps({"command": command, "version": parser_version, "profile": PARSER_PROFILE,
            "sandbox": True, "from": "docx", "to": "gfm", "wrap": "none", "track_changes": "accept",
            "max_upload_mb": settings.max_upload_size_mb}, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _convert_with_pandoc(
    settings: Settings,
    source: bytes,
    command: list[str],
) -> tuple[str, list[_MediaData]]:
    deadline = time.monotonic() + settings.pandoc_timeout_seconds
    inspect_docx_package(source, max_source_bytes=settings.max_upload_size_mb * 1024 * 1024)
    maximum = settings.max_upload_size_mb * 1024**2 * 4

    def remaining() -> float:
        seconds = deadline - time.monotonic()
        if seconds <= 0:
            raise AppError("pandoc_timeout", "Pandoc conversion exceeded its time limit", status_code=503)
        return seconds

    with tempfile.TemporaryDirectory(prefix="nomosmart-pandoc-") as temp_root:
        root = Path(temp_root)
        input_path = root / "source.docx"
        ast_path = root / "document.json"
        output_path = root / "document.md"
        media_root = root / "media"
        input_path.write_bytes(source)
        input_path.chmod(0o600)
        media_root.mkdir(mode=0o700)

        def convert(arguments: list[str]) -> None:
            completed = run_office_child([*command, *arguments], cwd=root, timeout=remaining(),
                memory_bytes=settings.pandoc_max_memory_mb * 1024**2, file_bytes=maximum)
            remaining()
            if completed.returncode != 0:
                raise AppError("pandoc_conversion_failed", "Pandoc could not convert the DOCX file", status_code=422,
                    details={"return_code": completed.returncode})

        # The DOCX reader moves leading visible Title paragraphs to metadata.
        # Preserve that structured content before the body-only GFM writer.
        convert([str(input_path), "--sandbox", "--from=docx", "--to=json", "--track-changes=accept",
                 "--extract-media=media", "--output", str(ast_path)])
        try:
            document = json.loads(_read_conversion_output(ast_path, maximum))
            _preserve_title(document)
            encoded = json.dumps(document, ensure_ascii=False, allow_nan=False).encode("utf-8")
        except (ValueError, TypeError, RecursionError) as exc:
            raise AppError("pandoc_output_invalid", "Pandoc document structure is invalid", status_code=422) from exc
        if len(encoded) > maximum:
            raise AppError("pandoc_output_invalid", "Pandoc document structure exceeds the safe limit", status_code=422)
        remaining()
        ast_path.write_bytes(encoded)
        ast_path.chmod(0o600)
        convert([str(ast_path), "--sandbox", "--from=json", "--to=gfm", "--wrap=none", "--output", str(output_path)])
        markdown = _read_conversion_output(output_path, maximum)
        media = _collect_media(root, media_root, settings=settings)
        remaining()
        return markdown, media


def _read_conversion_output(path: Path, maximum: int) -> str:
    if not path.is_file() or path.is_symlink() or path.stat().st_size > maximum:
        raise AppError("pandoc_output_invalid", "Pandoc artifact is missing, unsafe or oversized", status_code=422)
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise AppError("pandoc_output_invalid", "Pandoc artifact is not UTF-8", status_code=422) from exc


def _preserve_title(document: dict) -> None:
    """Promote only Title content removed by the fixed DOCX reader, not properties.

    Middle-of-body titles remain body paragraphs with no metadata entry. Do not
    text-deduplicate: the source may legitimately repeat its title in the body.
    """
    if not isinstance(document, dict) or not isinstance(document.get("meta"), dict) or not isinstance(document.get("blocks"), list):
        raise ValueError("Invalid document structure")
    title = document["meta"].pop("title", None)
    if title is None:
        return
    if not isinstance(title, dict) or not isinstance(title.get("c"), list):
        raise ValueError("Invalid title structure")
    if title.get("t") == "MetaInlines":
        paragraphs = [title["c"]]
    elif title.get("t") == "MetaBlocks":
        if any(not isinstance(b, dict) or b.get("t") not in {"Para", "Plain"} or not isinstance(b.get("c"), list) for b in title["c"]):
            raise ValueError("Invalid title blocks")
        paragraphs = [b["c"] for b in title["c"]]
    else:
        raise ValueError("Unsupported title structure")
    headers = [{"t": "Header", "c": [1, ["", [], []], inlines]} for inlines in paragraphs if inlines]
    document["blocks"] = headers + document["blocks"]


def _collect_media(root: Path, media_root: Path, *, settings: Settings) -> list[_MediaData]:
    files = sorted(path for path in media_root.rglob("*") if path.is_file())
    if len(files) > MAX_MEDIA_FILES:
        raise AppError("pandoc_media_limit_exceeded", "DOCX contains too many media files", status_code=422)
    total = 0
    maximum_total = settings.max_upload_size_mb * 1024 * 1024 * 2
    result: list[_MediaData] = []
    resolved_root = root.resolve()
    for path in files:
        if path.is_symlink() or not path.resolve().is_relative_to(resolved_root):
            raise AppError("pandoc_media_path_invalid", "Pandoc media path is unsafe", status_code=422)
        total += path.stat().st_size
        if total > maximum_total:
            raise AppError("pandoc_media_limit_exceeded", "DOCX media exceeds the configured limit", status_code=422)
        body = path.read_bytes()
        _media_kind(body)
        result.append(_MediaData(original_path=path.relative_to(root).as_posix(), body=body))
    return result


def _persist_media(settings: Settings, storage, version: DocumentVersion, media: list[_MediaData]) -> tuple[list[dict[str, object]], dict[str, str]]:
    manifest_by_hash: dict[str, dict[str, object]] = {}
    replacements: dict[str, str] = {}
    for item in media:
        extension, content_type = _media_kind(item.body)
        digest = hashlib.sha256(item.body).hexdigest()
        artifact_uri = f"artifact://document_versions/{version.id}/media/{digest}{extension}"
        key = (
            f"projects/{version.project_id}/documents/{version.document_id}/versions/{version.id}"
            f"/artifacts/media/{digest}{extension}"
        )
        if digest not in manifest_by_hash:
            stored = storage.put_object(bucket=settings.s3_bucket, key=key, body=item.body, content_type=content_type)
            _, content_length = storage.object_status(bucket=settings.s3_bucket, key=key)
            if content_length is not None and content_length != len(item.body):
                raise AppError("pandoc_media_verification_failed", "DOCX media artifact could not be verified", status_code=503)
            manifest_by_hash[digest] = {
                "id": digest,
                "artifact_uri": artifact_uri,
                "storage_bucket": stored.bucket,
                "storage_key": stored.key,
                "content_type": content_type,
                "size": len(item.body),
                "sha256": digest,
            }
        replacements[item.original_path] = artifact_uri
        replacements[quote(item.original_path)] = artifact_uri
    return list(manifest_by_hash.values()), replacements


def _rewrite_media_references(markdown: str, replacements: dict[str, str]) -> str:
    rewritten = markdown
    for source_path in sorted(replacements, key=len, reverse=True):
        rewritten = rewritten.replace(source_path, replacements[source_path])
    return rewritten


def _media_kind(body: bytes) -> tuple[str, str]:
    if body.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png", "image/png"
    if body.startswith(b"\xff\xd8\xff"):
        return ".jpg", "image/jpeg"
    if body.startswith((b"GIF87a", b"GIF89a")):
        return ".gif", "image/gif"
    if len(body) >= 12 and body.startswith(b"RIFF") and body[8:12] == b"WEBP":
        return ".webp", "image/webp"
    if body.startswith(b"BM"):
        return ".bmp", "image/bmp"
    if body.startswith((b"II*\x00", b"MM\x00*")):
        return ".tiff", "image/tiff"
    raise AppError("pandoc_media_type_unsupported", "DOCX contains an unsupported media type", status_code=422)


def _has_usable_text(markdown: str) -> bool:
    without_images = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", markdown)
    without_images = re.sub(r"<img\b[^>]*>", "", without_images, flags=re.IGNORECASE)
    return bool(re.search(r"[\w\u3400-\u9fff]", without_images, flags=re.UNICODE))


def _read_cache(cache_root: Path, cache_key: str, *, settings: Settings) -> tuple[str, list[_MediaData]] | None:
    bundle = cache_root / cache_key
    if not bundle.exists():
        return None
    if not bundle.is_dir() or bundle.is_symlink():
        raise AppError("pandoc_cache_invalid", "Pandoc cache is unsafe", status_code=503)
    markdown_path = bundle / "document.md"
    manifest_path = bundle / "manifest.json"
    if not markdown_path.is_file() or markdown_path.is_symlink() or not manifest_path.is_file() or manifest_path.is_symlink():
        raise AppError("pandoc_cache_invalid", "Pandoc cache is incomplete", status_code=503)
    if markdown_path.stat().st_size > settings.max_upload_size_mb * 1024**2 * 4 or manifest_path.stat().st_size > 1024**2:
        raise AppError("pandoc_cache_invalid", "Pandoc cache exceeds the safe limit", status_code=503)
    try:
        markdown = markdown_path.read_text(encoding="utf-8")
        raw_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AppError("pandoc_cache_invalid", "Pandoc cache is invalid", status_code=503) from exc
    if not isinstance(raw_manifest, list) or len(raw_manifest) > MAX_MEDIA_FILES:
        raise AppError("pandoc_cache_invalid", "Pandoc cache media manifest is invalid", status_code=503)
    media: list[_MediaData] = []
    total = 0
    for item in raw_manifest:
        if not isinstance(item, dict) or not isinstance(item.get("original_path"), str) or not isinstance(item.get("cache_file"), str):
            raise AppError("pandoc_cache_invalid", "Pandoc cache media entry is invalid", status_code=503)
        path = bundle / item["cache_file"]
        if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(bundle.resolve()):
            raise AppError("pandoc_cache_invalid", "Pandoc cache media path is unsafe", status_code=503)
        total += path.stat().st_size
        if total > settings.max_upload_size_mb * 1024 * 1024 * 2:
            raise AppError("pandoc_cache_invalid", "Pandoc cache media exceeds the safe limit", status_code=503)
        body = path.read_bytes()
        _media_kind(body)
        media.append(_MediaData(original_path=item["original_path"], body=body))
    return markdown, media


def _write_cache(cache_root: Path, cache_key: str, markdown: str, media: list[_MediaData]) -> None:
    temporary = None
    try:
        cache_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        cache_root.chmod(0o700)
        destination = cache_root / cache_key
        if destination.exists():
            return
        temporary = Path(tempfile.mkdtemp(prefix=f".{cache_key}.", dir=cache_root))
        temporary.chmod(0o700)
        assets = temporary / "assets"
        assets.mkdir(mode=0o700)
        manifest: list[dict[str, str]] = []
        for item in media:
            extension, _ = _media_kind(item.body)
            digest = hashlib.sha256(item.body).hexdigest()
            cache_file = f"assets/{digest}{extension}"
            target = temporary / cache_file
            if not target.exists():
                target.write_bytes(item.body)
                target.chmod(0o600)
            manifest.append({"original_path": item.original_path, "cache_file": cache_file})
        (temporary / "document.md").write_text(markdown, encoding="utf-8")
        (temporary / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=True), encoding="utf-8")
        for path in (temporary / "document.md", temporary / "manifest.json"):
            path.chmod(0o600)
        os.replace(temporary, destination)
        temporary = None
    except OSError:
        return
    finally:
        if temporary is not None:
            # Exact directory made by this call, never an existing cache bundle.
            shutil.rmtree(temporary)


def _pandoc_version(command: tuple[str, ...], *, settings: Settings) -> str:
    with tempfile.TemporaryDirectory(prefix="nomosmart-pandoc-version-") as work:
        completed = run_office_child([*command, "--version"], cwd=Path(work), timeout=5,
            memory_bytes=settings.pandoc_max_memory_mb * 1024**2, file_bytes=65536)
    lines = completed.stdout.decode("utf-8", errors="replace").splitlines()
    if completed.returncode != 0 or not lines or not re.fullmatch(r"pandoc [0-9][\w.+-]*", lines[0]):
        raise AppError("pandoc_unavailable", "Pandoc version could not be verified", status_code=503)
    return lines[0][:100]
