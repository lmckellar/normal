from __future__ import annotations

import hmac
import secrets
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlsplit

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
    host: str
    port: int | None


def _normal_host(host: str) -> str:
    return host.lower().rstrip(".")


def _default_port(scheme: str) -> int:
    return 443 if scheme == "https" else 80


def parse_origin(value: str) -> RequestOrigin:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise PostRejected(HTTPStatus.FORBIDDEN, "origin not allowed")
    return RequestOrigin(_normal_host(parsed.hostname), parsed.port or _default_port(parsed.scheme))


def parse_host(value: str) -> RequestOrigin:
    parsed = urlsplit("//" + value)
    if not parsed.hostname:
        raise PostRejected(HTTPStatus.FORBIDDEN, "host not allowed")
    return RequestOrigin(_normal_host(parsed.hostname), parsed.port)


def check_post(
    handler: BaseHTTPRequestHandler,
    *,
    bound_host: str,
    bound_port: int,
    unsafe_remote: bool,
) -> None:
    token = handler.headers.get("X-Normal-Token", "")
    if not hmac.compare_digest(token, MUTATION_TOKEN):
        raise PostRejected(HTTPStatus.FORBIDDEN, "invalid or missing token")

    content_type = handler.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        raise PostRejected(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "Content-Type must be application/json")

    allowed = LOCAL_HOSTS if not unsafe_remote else LOCAL_HOSTS | {_normal_host(bound_host)}

    origin_header = handler.headers.get("Origin")
    if origin_header is not None:
        origin = parse_origin(origin_header)
        if origin.host not in allowed or origin.port != bound_port:
            raise PostRejected(HTTPStatus.FORBIDDEN, "origin not allowed")

    host = parse_host(handler.headers.get("Host", ""))
    if host.host not in allowed or (host.port is not None and host.port != bound_port):
        raise PostRejected(HTTPStatus.FORBIDDEN, "host not allowed")

    try:
        content_length = int(handler.headers.get("Content-Length", "0"))
    except ValueError:
        raise PostRejected(HTTPStatus.BAD_REQUEST, "invalid Content-Length")
    if content_length > MAX_JSON_BODY:
        raise PostRejected(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "request body too large")
