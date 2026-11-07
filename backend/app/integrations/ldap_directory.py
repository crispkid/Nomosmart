"""Read-only LDAP protocol client with complete, bounded directory snapshots."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
import re
import ssl
import time
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

from ldap3 import BASE, NONE, SIMPLE, SUBTREE, Connection, Server, Tls
from ldap3.protocol.formatters.formatters import format_sid, format_uuid_le
from ldap3.core.exceptions import LDAPException
from ldap3.utils.conv import escape_filter_chars

from app.core.config import Settings
from app.core.errors import AppError
from app.security.auth_configuration import DirectoryConfiguration
from app.security.auth_network import trusted_ca, resolve_endpoint


PAGED = "1.2.840.113556.1.4.319"


@dataclass(frozen=True)
class DirectoryPerson:
    object_id: str
    dn: str
    username: str
    employee_id: str | None
    email: str | None
    given_name: str | None
    family_name: str | None
    display_name: str
    department: str | None
    title: str | None
    manager_dn: str | None
    enabled: bool
    primary_group_id: str | None = None
    primary_group_sid: str | None = None


@dataclass(frozen=True)
class DirectoryGroup:
    object_id: str
    dn: str
    name: str
    members: frozenset[str]


@dataclass(frozen=True)
class DirectorySnapshot:
    source_id: UUID
    schema_type: str
    people: tuple[DirectoryPerson, ...]
    groups: tuple[DirectoryGroup, ...]
    user_group_ids: dict[str, frozenset[str]]


def _values(attributes: dict[str, Any], name: str) -> list[Any]:
    value = next((v for k, v in attributes.items() if k.lower() == name.lower()), [])
    return value if isinstance(value, list) else [value] if value is not None else []


def _one(attributes: dict[str, Any], name: str) -> str | None:
    values = _values(attributes, name)
    return str(values[0]).strip() or None if values else None


def _object_id(attributes: dict[str, Any], name: str) -> str:
    values = _values(attributes, name)
    if len(values) != 1:
        raise AppError("directory_snapshot_invalid", "Directory object has no unique stable identifier", status_code=422)
    value = values[0]
    try:
        if isinstance(value, bytes):
            if name.casefold() == "objectguid":
                return str(UUID(bytes_le=value))
            value = value.decode("ascii")
        return str(UUID(str(value).strip("{}")))
    except (ValueError, TypeError, UnicodeDecodeError) as exc:
        raise AppError("directory_snapshot_invalid", "Directory object identifier is invalid", status_code=422) from exc


class LdapDirectory:
    def __init__(self, settings: Settings, config: DirectoryConfiguration, bind_password: str):
        if not bind_password:
            raise AppError("directory_credential_required", "Directory service credential is required", status_code=503)
        self.settings, self.config, self.bind_password = settings, config, bind_password
        self.deadline = time.monotonic() + settings.identity_sync_run_timeout_seconds

    @contextmanager
    def connection(self, *, user_dn: str | None = None, password: str | None = None):
        credential = self.bind_password if password is None else password
        if not credential or not credential.strip():
            raise AppError("invalid_credentials", "Sign-in could not be verified", status_code=401)
        connected = None
        for endpoint in self.config.endpoints:
            hostname, addresses = resolve_endpoint(self.settings, endpoint, schemes=("ldaps", "ldap"))
            parsed = urlparse(endpoint)
            tls = Tls(validate=ssl.CERT_REQUIRED, ca_certs_file=trusted_ca(self.settings, self.config.ca_reference), valid_names=[parsed.hostname], sni=parsed.hostname)
            server = Server(addresses[0], port=parsed.port or (636 if parsed.scheme == "ldaps" else 389), use_ssl=parsed.scheme == "ldaps", tls=tls, get_info=NONE, formatter={"objectGUID": format_uuid_le, "objectSid": format_sid}, connect_timeout=self.settings.auth_network_timeout_seconds)
            # Preserve AD's explicit range attributes; ldap3 2.9.1's synthetic
            # empty-attribute cleanup otherwise deletes a missing base attribute.
            conn = Connection(server, user=user_dn or self.config.bind_dn, password=credential, authentication=SIMPLE, read_only=True, auto_referrals=False, auto_range=False, return_empty_attributes=False, raise_exceptions=True, receive_timeout=self.settings.auth_network_timeout_seconds)
            try:
                conn.open()
                if parsed.scheme == "ldap" and (not self.config.start_tls or not conn.start_tls()):
                    raise AppError("directory_tls_failed", "Directory TLS negotiation failed", status_code=503)
                if not conn.bind():
                    raise AppError("invalid_credentials" if user_dn else "directory_bind_failed", "Directory authentication was rejected", status_code=401 if user_dn else 503)
                connected = conn
                break
            except LDAPException as exc:
                conn.unbind()
                if getattr(exc, "result", None) == 49:
                    raise AppError("invalid_credentials" if user_dn else "directory_bind_failed", "Directory authentication was rejected", status_code=401 if user_dn else 503) from exc
            except AppError:
                conn.unbind()
                raise
        if connected is None:
            raise AppError("directory_unavailable", "Directory service is unavailable", status_code=503)
        try:
            yield connected
        except LDAPException as exc:
            raise AppError("directory_read_failed", "Directory data could not be read completely", status_code=503) from exc
        finally:
            connected.unbind()

    def _search(self, conn: Connection, base: str, query: str, attributes: list[str], *, scope=SUBTREE) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        cookie = None
        seen: set[bytes] = set()
        while True:
            if time.monotonic() >= self.deadline:
                raise AppError("identity_sync_timeout", "Directory synchronization exceeded its time limit", status_code=504)
            conn.search(base, query, search_scope=scope, attributes=attributes, paged_size=self.config.page_size if scope == SUBTREE else None, paged_cookie=cookie)
            if conn.result.get("result") != 0 or any(row.get("type") == "searchResRef" for row in conn.response):
                raise AppError("directory_read_incomplete", "Directory read was incomplete", status_code=503)
            rows.extend(row for row in conn.response if row.get("type") == "searchResEntry")
            if len(rows) > self.config.maximum_entries:
                raise AppError("directory_limit_exceeded", "Directory snapshot exceeds its configured limit", status_code=422)
            cookie = conn.result.get("controls", {}).get(PAGED, {}).get("value", {}).get("cookie")
            if not cookie:
                break
            if cookie in seen:
                raise AppError("directory_read_incomplete", "Directory paging did not advance", status_code=503)
            seen.add(cookie)
        return rows

    def _person(self, row: dict[str, Any]) -> DirectoryPerson:
        attrs = row["attributes"]
        cfg = self.config
        object_id = _object_id(attrs, cfg.object_id_attribute)
        employee = _one(attrs, cfg.employee_attribute)
        if employee and not re.fullmatch(r"Z.{0,9}", employee):
            raise AppError("directory_employee_id_invalid", "A directory employee identifier is incompatible", status_code=422)
        username = _one(attrs, cfg.login_attribute)
        if not username:
            raise AppError("directory_snapshot_invalid", "Directory account has no login identifier", status_code=422)
        try:
            enabled = not (int(_one(attrs, "userAccountControl") or "0") & 2) if cfg.schema_type == "ad" else True
            expires = int(_one(attrs, "accountExpires") or "0") if cfg.schema_type == "ad" else 0
        except (TypeError, ValueError) as exc:
            raise AppError("directory_snapshot_invalid", "Directory account status is invalid", status_code=422) from exc
        if cfg.enabled_attribute:
            enabled = enabled and (_one(attrs, cfg.enabled_attribute) or "").casefold() != cfg.disabled_value.casefold()
        if expires not in {0, 9223372036854775807}:
            enabled = enabled and expires / 10000000 - 11644473600 > datetime.now(UTC).timestamp()
        sid, primary_id = _one(attrs, "objectSid"), _one(attrs, "primaryGroupID")
        primary_sid = sid.rsplit("-", 1)[0] + "-" + primary_id if sid and primary_id and sid.startswith("S-") else None
        given, family = _one(attrs, "givenName"), _one(attrs, "sn")
        return DirectoryPerson(object_id=object_id, dn=row["dn"], username=username, employee_id=employee, email=_one(attrs, "mail"), given_name=given, family_name=family, display_name=_one(attrs, "displayName") or " ".join(v for v in (given, family) if v) or username, department=_one(attrs, "department") or _one(attrs, "departmentNumber"), title=_one(attrs, "title"), manager_dn=_one(attrs, "manager"), enabled=bool(enabled), primary_group_id=primary_id, primary_group_sid=primary_sid)

    def people(self, conn: Connection, *, extra_filter: str = "") -> tuple[DirectoryPerson, ...]:
        cfg = self.config
        attrs = list({cfg.object_id_attribute, cfg.login_attribute, cfg.employee_attribute, "givenName", "sn", "displayName", "mail", "department", "departmentNumber", "title", "manager", *([cfg.enabled_attribute] if cfg.enabled_attribute else []), *(["userAccountControl", "accountExpires", "primaryGroupID", "objectSid"] if cfg.schema_type == "ad" else [])})
        query = f"(&{cfg.user_filter}{extra_filter})" if extra_filter else cfg.user_filter
        people = tuple(self._person(row) for row in self._search(conn, cfg.users_dn, query, attrs))
        if len({p.username.casefold() for p in people}) != len(people):
            raise AppError("directory_login_ambiguous", "Directory contains ambiguous login identifiers", status_code=422)
        employees = [p.employee_id for p in people if p.employee_id]
        if len(set(employees)) != len(employees):
            raise AppError("directory_employee_id_conflict", "Directory contains duplicate employee identifiers", status_code=422)
        if len({p.object_id for p in people}) != len(people):
            raise AppError("directory_snapshot_invalid", "Directory contains duplicate stable identities", status_code=422)
        return people

    def authenticate(self, username: str, password: str) -> DirectoryPerson:
        if not username.strip() or not password or not password.strip():
            raise AppError("invalid_credentials", "Sign-in could not be verified", status_code=401)
        with self.connection() as conn:
            people = self.people(conn, extra_filter=f"({self.config.login_attribute}={escape_filter_chars(username.strip())})")
        if len(people) != 1 or not people[0].enabled:
            raise AppError("invalid_credentials", "Sign-in could not be verified", status_code=401)
        with self.connection(user_dn=people[0].dn, password=password):
            return people[0]

    def snapshot(self, scope: str) -> DirectorySnapshot:
        cfg = self.config
        with self.connection() as conn:
            people = self.people(conn)
            if scope == "people":
                return DirectorySnapshot(cfg.source_id, cfg.schema_type, people, (), {})
            rows = self._search(conn, cfg.groups_dn, cfg.group_filter, [cfg.group_id_attribute, "cn", cfg.group_member_attribute, *(["objectSid"] if cfg.schema_type == "ad" else [])])
            groups: list[DirectoryGroup] = []
            primary: dict[str, str] = {}
            for row in rows:
                attrs = row["attributes"]
                members = [str(v) for v in _values(attrs, cfg.group_member_attribute)]
                ranged = [key for key in attrs if key.lower().startswith(cfg.group_member_attribute.lower() + ";range=")]
                expected_range = 0
                if ranged and members:
                    raise AppError("directory_read_incomplete", "Directory membership range is ambiguous", status_code=503)
                while ranged:
                    if len(ranged) != 1 or not ranged[0].lower().startswith(cfg.group_member_attribute.lower() + f";range={expected_range}-"):
                        raise AppError("directory_read_incomplete", "Directory membership range did not advance", status_code=503)
                    key = ranged[0]
                    members.extend(str(v) for v in _values(attrs, key))
                    end = key.rsplit("-", 1)[-1]
                    if end == "*":
                        break
                    if not end.isdecimal() or int(end) < expected_range or len(members) > cfg.maximum_entries:
                        raise AppError("directory_read_incomplete", "Directory membership range is incomplete", status_code=503)
                    expected_range = int(end) + 1
                    next_attribute = f"{cfg.group_member_attribute};range={expected_range}-*"
                    chunk = self._search(conn, row["dn"], "(objectClass=*)", [next_attribute], scope=BASE)
                    if len(chunk) != 1:
                        raise AppError("directory_read_incomplete", "Directory membership range is incomplete", status_code=503)
                    attrs = chunk[0]["attributes"]
                    ranged = [key for key in attrs if key.lower().startswith(cfg.group_member_attribute.lower() + f";range={int(end)+1}-")]
                    if not ranged:
                        raise AppError("directory_read_incomplete", "Directory membership range is incomplete", status_code=503)
                if len(members) > cfg.maximum_entries:
                    raise AppError("directory_limit_exceeded", "Directory membership exceeds its configured limit", status_code=422)
                group_id = _object_id(row["attributes"], cfg.group_id_attribute)
                groups.append(DirectoryGroup(group_id, row["dn"], _one(row["attributes"], "cn") or group_id, frozenset(members)))
                sid = _one(row["attributes"], "objectSid")
                if sid:
                    primary[sid] = group_id
            if len({g.object_id for g in groups}) != len(groups):
                raise AppError("directory_snapshot_invalid", "Directory contains duplicate group identifiers", status_code=422)
            by_dn = {g.dn.casefold(): g for g in groups}
            person_dn = {p.dn.casefold(): p.object_id for p in people}
            person_uid = {p.username.casefold(): p.object_id for p in people}
            memberships: dict[str, set[str]] = {p.object_id: set() for p in people}
            for root in groups:
                pending, visited = [root], set()
                while pending:
                    group = pending.pop()
                    if group.object_id in visited:
                        continue
                    visited.add(group.object_id)
                    for member in group.members:
                        key = member.casefold()
                        user_id = (person_uid if cfg.group_member_attribute == "memberUid" else person_dn).get(key)
                        if user_id:
                            memberships[user_id].add(root.object_id)
                        elif key in by_dn:
                            pending.append(by_dn[key])
                        elif cfg.group_member_attribute != "memberUid" and key.endswith(cfg.groups_dn.casefold()):
                            raise AppError("directory_nested_group_missing", "A nested group is outside the complete snapshot", status_code=422)
                for person in people:
                    if person.primary_group_sid and primary.get(person.primary_group_sid) in visited:
                        memberships[person.object_id].add(root.object_id)
            return DirectorySnapshot(cfg.source_id, cfg.schema_type, people, tuple(groups), {key: frozenset(value) for key, value in memberships.items()})
