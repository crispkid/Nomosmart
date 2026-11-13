from __future__ import annotations

import hashlib
import os
import threading
from urllib.parse import unquote, urlsplit

from redis import Redis
from redis.sentinel import Sentinel

from app.core.config import Settings


def sentinel_endpoints(value: str) -> tuple[tuple[str, int], ...]:
    nodes: list[tuple[str, int]] = []
    for raw in value.split(","):
        item = raw.strip()
        if not item:
            continue
        host, separator, port = item.rpartition(":")
        if not separator or not host or not port.isdigit():
            raise ValueError("REDIS_SENTINEL_NODES must contain host:port entries")
        nodes.append((host, int(port)))
    if not nodes:
        raise ValueError("REDIS_SENTINEL_NODES must contain at least one endpoint")
    return tuple(nodes)


def _database_from_url(url: str) -> int:
    path = urlsplit(url).path.lstrip("/")
    return int(path or "0")


def redis_client(
    settings: Settings,
    *,
    url: str | None = None,
    database: int | None = None,
    decode_responses: bool = False,
    socket_timeout: float = 2,
) -> Redis:
    connection_url = url or settings.redis_url.get_secret_value()
    if settings.redis_ha_mode != "sentinel":
        return Redis.from_url(
            connection_url,
            socket_connect_timeout=socket_timeout,
            socket_timeout=socket_timeout,
            decode_responses=decode_responses,
        )

    parsed = urlsplit(connection_url)
    username = unquote(parsed.username or "") or None
    password = unquote(parsed.password or "") or None
    selected_database = _database_from_url(connection_url) if database is None else database
    tls = {
        "ssl": True,
        "ssl_ca_certs": settings.redis_tls_ca_cert_path,
        "ssl_cert_reqs": "required",
        "ssl_check_hostname": True,
    }
    sentinel = Sentinel(
        sentinel_endpoints(settings.redis_sentinel_nodes),
        sentinel_kwargs={
            "username": settings.redis_sentinel_username,
            "password": settings.redis_sentinel_password.get_secret_value(),
            "socket_connect_timeout": socket_timeout,
            "socket_timeout": socket_timeout,
            **tls,
        },
        username=username,
        password=password,
        socket_connect_timeout=socket_timeout,
        socket_timeout=socket_timeout,
        decode_responses=decode_responses,
        **tls,
    )
    return sentinel.master_for(
        settings.redis_sentinel_master_name,
        db=selected_database,
    )


_SHARED_REDIS_LOCK = threading.Lock()
_SHARED_REDIS_CLIENTS: dict[tuple[object, ...], Redis] = {}


def shared_redis_client(
    settings: Settings,
    *,
    url: str | None = None,
    database: int | None = None,
    decode_responses: bool = False,
    socket_timeout: float = 2,
) -> Redis:
    """Process-wide Redis client for hot paths; its connection pool is reused across calls (OPT424-019).

    Keyed by process id so forked workers never reuse a parent's sockets, and by a digest of the
    connection settings so a changed URL, credential or Sentinel topology gets a new client.
    Callers must not close the returned client.
    """
    connection_url = url or settings.redis_url.get_secret_value()
    digest = hashlib.sha256("\0".join((
        connection_url,
        settings.redis_ha_mode,
        settings.redis_sentinel_nodes,
        settings.redis_sentinel_master_name,
        settings.redis_sentinel_username,
        settings.redis_sentinel_password.get_secret_value(),
        settings.redis_tls_ca_cert_path,
    )).encode("utf-8")).hexdigest()
    key = (os.getpid(), digest, database, decode_responses, socket_timeout)
    with _SHARED_REDIS_LOCK:
        client = _SHARED_REDIS_CLIENTS.get(key)
        if client is None:
            client = redis_client(settings, url=url, database=database, decode_responses=decode_responses, socket_timeout=socket_timeout)
            _SHARED_REDIS_CLIENTS[key] = client
        return client
