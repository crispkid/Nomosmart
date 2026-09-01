from __future__ import annotations

import hashlib
import hmac
import ssl
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import quote, urljoin, urlparse

import httpx

from app.core.config import Settings
from app.core.errors import AppError
from app.domain.document_imports import ObjectStorage, StoredObject


class RemoteObject:
    def __init__(self, *, body: bytes, etag: str | None = None, content_type: str | None = None, content_length: int | None = None) -> None:
        self.body = body
        self.etag = etag
        self.content_type = content_type
        self.content_length = content_length


@dataclass(frozen=True)
class S3ClientConfig:
    endpoint_url: str
    region: str
    access_key: str
    secret_key: str
    verify_tls: bool | ssl.SSLContext
    session_token: str | None = None

    @classmethod
    def from_settings(cls, settings: Settings) -> "S3ClientConfig":
        return cls(
            endpoint_url=settings.s3_endpoint_url,
            region=settings.s3_region,
            access_key=settings.s3_access_key_id.get_secret_value(),
            secret_key=settings.s3_secret_access_key.get_secret_value(),
            verify_tls=settings.s3_httpx_verify,
        )


class S3ObjectStorage(ObjectStorage):
    def __init__(self, settings: Settings | S3ClientConfig) -> None:
        self.config = settings if isinstance(settings, S3ClientConfig) else S3ClientConfig.from_settings(settings)

    def put_object(self, *, bucket: str, key: str, body: bytes, content_type: str | None) -> StoredObject:
        if not self.config.access_key or not self.config.secret_key:
            raise AppError("s3_credentials_missing", "S3 credentials are not configured", status_code=503)
        endpoint = self.config.endpoint_url.rstrip("/") + "/"
        encoded_key = "/".join(quote(part, safe="") for part in key.split("/"))
        url = urljoin(endpoint, f"{quote(bucket, safe='')}/{encoded_key}")
        now = datetime.now(UTC)
        headers = self._signed_headers("PUT", url, body, now, content_type)
        try:
            response = httpx.put(url, content=body, headers=headers, timeout=30, verify=self.config.verify_tls)
        except httpx.HTTPError as exc:
            raise AppError("s3_upload_failed", "S3 upload failed", status_code=503) from exc
        if response.status_code >= 400:
            raise AppError("s3_upload_failed", "S3 upload failed", status_code=503, details={"status_code": response.status_code})
        return StoredObject(bucket=bucket, key=key, etag=response.headers.get("etag"))

    def get_object(self, *, bucket: str, key: str, max_bytes: int | None = None) -> RemoteObject:
        if not self.config.access_key or not self.config.secret_key:
            raise AppError("s3_credentials_missing", "S3 credentials are not configured", status_code=503)
        endpoint = self.config.endpoint_url.rstrip("/") + "/"
        encoded_key = "/".join(quote(part, safe="") for part in key.split("/"))
        url = urljoin(endpoint, f"{quote(bucket, safe='')}/{encoded_key}")
        now = datetime.now(UTC)
        headers = self._signed_headers("GET", url, b"", now, None)
        try:
            response = httpx.get(url, headers=headers, timeout=30, verify=self.config.verify_tls)
        except httpx.HTTPError as exc:
            raise AppError("connection_failed", "Remote object fetch failed", status_code=503) from exc
        if response.status_code == 404:
            raise AppError("remote_file_not_found", "Remote file was not found", status_code=404)
        if response.status_code in {401, 403}:
            raise AppError("authentication_failed", "Remote authentication failed", status_code=503)
        if response.status_code >= 400:
            raise AppError("connection_failed", "Remote object fetch failed", status_code=503, details={"status_code": response.status_code})
        if max_bytes is not None and len(response.content) > max_bytes:
            raise AppError("sync_file_too_large", "Remote file exceeds the configured size limit", status_code=413)
        content_length = response.headers.get("content-length")
        return RemoteObject(body=response.content, etag=response.headers.get("etag"), content_type=response.headers.get("content-type"), content_length=int(content_length) if content_length and content_length.isdigit() else len(response.content))

    def delete_object(self, *, bucket: str, key: str) -> None:
        url = self._object_url(bucket, key)
        headers = self._signed_headers("DELETE", url, b"", datetime.now(UTC), None)
        try:
            response = httpx.delete(url, headers=headers, timeout=30, verify=self.config.verify_tls)
        except httpx.HTTPError as exc:
            raise AppError("s3_delete_failed", "S3 object deletion failed", status_code=503) from exc
        if response.status_code not in {200, 202, 204, 404}:
            raise AppError("s3_delete_failed", "S3 object deletion failed", status_code=503, details={"status_code": response.status_code})

    def object_status(self, *, bucket: str, key: str) -> tuple[str | None, int | None]:
        url = self._object_url(bucket, key)
        headers = self._signed_headers("HEAD", url, b"", datetime.now(UTC), None)
        try:
            response = httpx.head(url, headers=headers, timeout=15, verify=self.config.verify_tls)
        except httpx.HTTPError as exc:
            raise AppError("s3_object_check_failed", "S3 object readiness check failed", status_code=503) from exc
        if response.status_code == 404:
            raise AppError("s3_object_missing", "S3 object was not found after write", status_code=503)
        if response.status_code >= 400:
            raise AppError("s3_object_check_failed", "S3 object readiness check failed", status_code=503, details={"status_code": response.status_code})
        length = response.headers.get("content-length")
        return response.headers.get("etag"), int(length) if length and length.isdigit() else None

    def bucket_status(self, bucket: str) -> str:
        url = urljoin(self.config.endpoint_url.rstrip("/") + "/", f"{quote(bucket, safe='')}/")
        now = datetime.now(UTC)
        headers = self._signed_headers("HEAD", url, b"", now, None)
        try:
            response = httpx.head(url, headers=headers, timeout=15, verify=self.config.verify_tls)
        except httpx.HTTPError as exc:
            raise AppError("s3_bucket_check_failed", "S3 bucket readiness check failed", status_code=503) from exc
        if response.status_code in {200, 204}:
            return "existing"
        if response.status_code == 404:
            return "missing"
        if response.status_code != 404:
            raise AppError("s3_bucket_check_failed", "S3 bucket readiness check failed", status_code=503, details={"status_code": response.status_code})
        return "missing"

    def ensure_bucket(self, bucket: str) -> str:
        status = self.bucket_status(bucket)
        if status == "existing":
            return status
        url = urljoin(self.config.endpoint_url.rstrip("/") + "/", f"{quote(bucket, safe='')}/")
        headers = self._signed_headers("PUT", url, b"", datetime.now(UTC), None)
        try:
            response = httpx.put(url, headers=headers, content=b"", timeout=15, verify=self.config.verify_tls)
        except httpx.HTTPError as exc:
            raise AppError("s3_bucket_create_failed", "S3 bucket creation failed", status_code=503) from exc
        if response.status_code not in {200, 201, 204, 409}:
            raise AppError("s3_bucket_create_failed", "S3 bucket creation failed", status_code=503, details={"status_code": response.status_code})
        return "created" if response.status_code != 409 else "existing"

    def _object_url(self, bucket: str, key: str) -> str:
        endpoint = self.config.endpoint_url.rstrip("/") + "/"
        encoded_key = "/".join(quote(part, safe="") for part in key.split("/"))
        return urljoin(endpoint, f"{quote(bucket, safe='')}/{encoded_key}")

    def _signed_headers(self, method: str, url: str, body: bytes, now: datetime, content_type: str | None) -> dict[str, str]:
        parsed = urlparse(url)
        payload_hash = hashlib.sha256(body).hexdigest()
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        date_stamp = now.strftime("%Y%m%d")
        host = parsed.netloc
        canonical_uri = quote(parsed.path or "/", safe="/")
        headers = {
            "host": host,
            "x-amz-content-sha256": payload_hash,
            "x-amz-date": amz_date,
        }
        if content_type:
            headers["content-type"] = content_type
        if self.config.session_token:
            headers["x-amz-security-token"] = self.config.session_token
        signed_header_names = ";".join(sorted(headers))
        canonical_headers = "".join(f"{name}:{headers[name]}\n" for name in sorted(headers))
        canonical_request = "\n".join([method, canonical_uri, "", canonical_headers, signed_header_names, payload_hash])
        credential_scope = f"{date_stamp}/{self.config.region}/s3/aws4_request"
        string_to_sign = "\n".join(["AWS4-HMAC-SHA256", amz_date, credential_scope, hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()])
        signature = hmac.new(_signing_key(self.config.secret_key, date_stamp, self.config.region), string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
        headers["authorization"] = f"AWS4-HMAC-SHA256 Credential={self.config.access_key}/{credential_scope}, SignedHeaders={signed_header_names}, Signature={signature}"
        return headers


def _signing_key(secret_key: str, date_stamp: str, region: str) -> bytes:
    date_key = hmac.new(f"AWS4{secret_key}".encode("utf-8"), date_stamp.encode("utf-8"), hashlib.sha256).digest()
    region_key = hmac.new(date_key, region.encode("utf-8"), hashlib.sha256).digest()
    service_key = hmac.new(region_key, b"s3", hashlib.sha256).digest()
    return hmac.new(service_key, b"aws4_request", hashlib.sha256).digest()
