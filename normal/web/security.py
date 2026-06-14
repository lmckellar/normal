from __future__ import annotations

import hmac
import ipaddress
import secrets
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlsplit

MUTATION_TOKEN = secrets.token_urlsafe(32)
MAX_JSON_BODY = 5 * 1024 * 1024
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


class PostRejected(Exception):
    def __init__(self, status: HTTPStatus, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass(frozen=True)
class RequestOrigin:
    scheme: str | None
    host: str
    port: int | None


def _normal_host(host: str) -> str:
    return host.lower().rstrip(".")


def _default_port(scheme: str) -> int:
    return 443 if scheme == "https" else 80


def parse_origin(value: str) -> RequestOrigin:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        raise PostRejected(HTTPStatus.FORBIDDEN, "origin not allowed")
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise PostRejected(HTTPStatus.FORBIDDEN, "origin not allowed")
    return RequestOrigin(parsed.scheme, _normal_host(parsed.hostname), port or _default_port(parsed.scheme))


def parse_host(value: str) -> RequestOrigin:
    if not value or any(char in value for char in "/?#@"):
        raise PostRejected(HTTPStatus.FORBIDDEN, "host not allowed")
    try:
        parsed = urlsplit("//" + value)
        port = parsed.port
    except ValueError:
        raise PostRejected(HTTPStatus.FORBIDDEN, "host not allowed")
    if not parsed.hostname or parsed.username is not None or parsed.password is not None:
        raise PostRejected(HTTPStatus.FORBIDDEN, "host not allowed")
    return RequestOrigin(None, _normal_host(parsed.hostname), port)


def is_loopback_bind(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return _normal_host(host) == "localhost"


def parse_allowed_hosts(values: list[str]) -> frozenset[str]:
    allowed: set[str] = set()
    for value in values:
        host = value.strip()
        if not host or any(char in host for char in "/?#@"):
            raise ValueError(f"invalid allowed host: {value}")
        if host.startswith("[") and host.endswith("]"):
            host = host[1:-1]
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            if ":" in host or any(char.isspace() for char in host):
                raise ValueError(f"invalid allowed host: {value}")
            if host == "0.0.0.0":
                raise ValueError(f"invalid allowed host: {value}")
        else:
            if address.is_unspecified:
                raise ValueError(f"invalid allowed host: {value}")
        allowed.add(_normal_host(host))
    return frozenset(allowed)


def check_token(handler: BaseHTTPRequestHandler, *, allow_query: bool = False) -> None:
    token = handler.headers.get("X-Normal-Token", "")
    if allow_query and not token:
        token = parse_qs(urlsplit(handler.path).query).get("token", [""])[0]
    if not hmac.compare_digest(token, MUTATION_TOKEN):
        raise PostRejected(HTTPStatus.FORBIDDEN, "invalid or missing token")


def check_post(
    handler: BaseHTTPRequestHandler,
    *,
    bound_port: int,
    allowed_hosts: frozenset[str],
) -> int:
    check_token(handler)

    content_type = handler.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        raise PostRejected(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "Content-Type must be application/json")

    host = parse_host(handler.headers.get("Host", ""))
    if host.port != bound_port or host.host not in LOCAL_HOSTS | allowed_hosts:
        raise PostRejected(HTTPStatus.FORBIDDEN, "host not allowed")

    origin_header = handler.headers.get("Origin")
    if origin_header is not None:
        origin = parse_origin(origin_header)
        expected_origin = RequestOrigin("http", host.host, bound_port)
        if origin != expected_origin:
            raise PostRejected(HTTPStatus.FORBIDDEN, "origin not allowed")

    if handler.headers.get("Transfer-Encoding") is not None:
        raise PostRejected(HTTPStatus.BAD_REQUEST, "Transfer-Encoding is not supported")
    raw_content_length = handler.headers.get("Content-Length")
    if raw_content_length is None:
        raise PostRejected(HTTPStatus.LENGTH_REQUIRED, "Content-Length is required")
    try:
        content_length = int(raw_content_length)
    except ValueError:
        raise PostRejected(HTTPStatus.BAD_REQUEST, "invalid Content-Length")
    if content_length < 0:
        raise PostRejected(HTTPStatus.BAD_REQUEST, "invalid Content-Length")
    if content_length > MAX_JSON_BODY:
        raise PostRejected(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "request body too large")
    return content_length
