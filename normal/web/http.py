from __future__ import annotations

import json
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlsplit

from normal.movie_omdb import resolve_original_language
from .scan_guard import ApprovedRoots, client_disconnected, resolve_source_path
from .security import MAX_JSON_BODY


@dataclass(slots=True)
class RequestContext:
    handler: BaseHTTPRequestHandler
    default_source: Path | None = None
    omdb_key: str | None = None
    tmdb_key: str | None = None
    approved_roots: ApprovedRoots = ApprovedRoots()

    def language_resolver(self) -> Callable[[str, int | None], str | None] | None:
        omdb_key = self.omdb_key
        if not omdb_key:
            return None
        return lambda title, year: resolve_original_language(title, year, omdb_key)

    def read_json_body(self) -> dict[str, Any]:
        length = int(self.handler.headers.get("Content-Length", "0"))
        if length > MAX_JSON_BODY:
            raise ValueError("request body too large")
        body = self.handler.rfile.read(length) if length else b"{}"
        if not body:
            return {}
        return json.loads(body.decode("utf-8"))

    def respond_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.handler.send_response(status)
        self.handler.send_header("Content-Type", "application/json; charset=utf-8")
        self.handler.send_header("Content-Length", str(len(body)))
        self.handler.end_headers()
        self.handler.wfile.write(body)

    def respond_bytes(
        self,
        body: bytes,
        *,
        content_type: str,
        status: HTTPStatus = HTTPStatus.OK,
        content_disposition: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.handler.send_response(status)
        self.handler.send_header("Content-Type", content_type)
        if content_disposition is not None:
            self.handler.send_header("Content-Disposition", content_disposition)
        for key, value in (headers or {}).items():
            self.handler.send_header(key, value)
        self.handler.send_header("Content-Length", str(len(body)))
        self.handler.end_headers()
        self.handler.wfile.write(body)

    def resolve_source(self, raw_source: Any) -> Path:
        return self.approved_roots.resolve_approved(raw_source, default_source=self.default_source)

    def inspect_source(self, raw_source: Any) -> Path:
        return resolve_source_path(raw_source, default_source=self.default_source)

    def client_disconnected(self) -> bool:
        return client_disconnected(self.handler.connection)

    def query_param(self, name: str) -> str:
        values = parse_qs(urlsplit(self.handler.path).query).get(name, [])
        return str(values[0]) if values else ""
