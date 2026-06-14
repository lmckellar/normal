from __future__ import annotations

import hmac
import secrets
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


def _hostname(value: str) -> str | None:
    if not value:
        return None
    if "//" not in value:
        value = "//" + value
    return urlsplit(value).hostname


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

    allowed = LOCAL_HOSTS if not unsafe_remote else LOCAL_HOSTS | {bound_host}

    origin = handler.headers.get("Origin")
    if origin is not None and _hostname(origin) not in allowed:
        raise PostRejected(HTTPStatus.FORBIDDEN, "origin not allowed")

    if _hostname(handler.headers.get("Host", "")) not in allowed:
        raise PostRejected(HTTPStatus.FORBIDDEN, "host not allowed")

    if int(handler.headers.get("Content-Length", "0")) > MAX_JSON_BODY:
        raise PostRejected(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "request body too large")
