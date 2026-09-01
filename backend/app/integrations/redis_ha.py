from __future__ import annotations

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
