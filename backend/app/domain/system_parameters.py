from __future__ import annotations

from dataclasses import dataclass
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.errors import AppError


@dataclass(frozen=True)
class SystemParameterValues:
    max_upload_size_mb: int = 100
    default_timezone: str = "Asia/Taipei"
    staging_index_ttl_days: int = 7
    session_expired_form_draft_ttl_minutes: int = 30

    def validate(self) -> "SystemParameterValues":
        details: dict[str, str] = {}
        if not 1 <= self.max_upload_size_mb <= 10240:
            details["max_upload_size_mb"] = "must be between 1 and 10240"
        if not 1 <= self.staging_index_ttl_days <= 3650:
            details["staging_index_ttl_days"] = "must be between 1 and 3650"
        if self.session_expired_form_draft_ttl_minutes != 0 and not 5 <= self.session_expired_form_draft_ttl_minutes <= 120:
            details["session_expired_form_draft_ttl_minutes"] = "must be 0 or between 5 and 120"
        try:
            ZoneInfo(self.default_timezone)
        except ZoneInfoNotFoundError:
            details["default_timezone"] = "must be a valid IANA timezone"
        if details:
            raise AppError("invalid_system_parameters", "System parameters are invalid", status_code=422, details=details)
        return self
