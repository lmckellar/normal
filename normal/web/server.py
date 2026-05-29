from __future__ import annotations

import json
from functools import lru_cache
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from typing import Callable

from . import state
from .activity import ActivityTracker
from .http import RequestContext
from .routes_cleanup import (
    handle_movies_audio_packaging_fix,
    handle_movies_junk,
    handle_movies_junk_delete,
    handle_movies_replacement_queue_add,
    handle_movies_replacement_queue_delete,
    handle_movies_replacement_queue_dismiss,
    handle_movies_replacement_queue_list,
    handle_movies_subtitle_readiness_fix,
    handle_movies_subtitle_readiness_history_dismiss,
    handle_movies_subtitle_readiness_history_list,
    handle_movies_subtitle_readiness_history_sync,
)
from .routes_core import handle_activity, handle_library_roots_get, handle_library_roots_post, handle_source_scan_warning
from .routes_normalize import handle_movies_apply, handle_movies_normalize, handle_movies_normalize_lab_export
from .routes_profile import (
    handle_movies_canonical_lists,
    handle_movies_dashboard_histogram,
    handle_movies_inspect,
    handle_movies_omdb_ratings,
    handle_movies_profile,
    handle_movies_register,
    handle_movies_standards_update,
)
from .state import RequestConflictError


WEB_ASSET_ROOT = "web_assets"
WEB_ASSET_TEMPLATE = "index.html"
WORKBENCH_ASSET_TEMPLATE = "workbench.html"
NORMALIZE_LAB_ASSET_TEMPLATE = "normalize_lab.html"
WEB_STATIC_ASSETS = {
    "/assets/app.css": ("app.css", "text/css; charset=utf-8"),
    "/assets/app.js": ("app.js", "application/javascript; charset=utf-8"),
}
WORKBENCH_STATIC_ASSETS = {
    "/workbench-assets/workbench.css": ("workbench.css", "text/css; charset=utf-8"),
    "/workbench-assets/workbench.js": ("workbench.js", "application/javascript; charset=utf-8"),
}
NORMALIZE_LAB_STATIC_ASSETS = {
    "/normalize-lab-assets/normalize_lab.css": ("normalize_lab.css", "text/css; charset=utf-8"),
    "/normalize-lab-assets/normalize_lab.js": ("normalize_lab.js", "application/javascript; charset=utf-8"),
}
WEB_BOOTSTRAP_SENTINEL = "__NORMAL_BOOTSTRAP__"


@lru_cache(maxsize=None)
def read_web_asset_text(name: str) -> str:
    return resources.files("normal").joinpath(WEB_ASSET_ROOT, name).read_text(encoding="utf-8")


@lru_cache(maxsize=None)
def read_web_asset_bytes(name: str) -> bytes:
    return read_web_asset_text(name).encode("utf-8")


def render_web_bootstrap(default_source: Path | None = None, omdb_key: str | None = None, tmdb_key: str | None = None) -> str:
    return "\n".join(
        (
            f"window.DEFAULT_SOURCE = {json.dumps(str(default_source) if default_source else '')};",
            f"window.OMDB_AVAILABLE = {json.dumps(bool(omdb_key))};",
            f"window.TMDB_KEY = {json.dumps(tmdb_key or '')};",
        )
    )


def render_asset_html(
    template_name: str,
    default_source: Path | None = None,
    omdb_key: str | None = None,
    tmdb_key: str | None = None,
) -> str:
    template = read_web_asset_text(template_name)
    return template.replace(
        WEB_BOOTSTRAP_SENTINEL,
        render_web_bootstrap(default_source=default_source, omdb_key=omdb_key, tmdb_key=tmdb_key),
        1,
    )


def render_index_html(default_source: Path | None = None, omdb_key: str | None = None, tmdb_key: str | None = None) -> str:
    return render_asset_html(WEB_ASSET_TEMPLATE, default_source=default_source, omdb_key=omdb_key, tmdb_key=tmdb_key)


def render_workbench_html(default_source: Path | None = None, omdb_key: str | None = None, tmdb_key: str | None = None) -> str:
    return render_asset_html(WORKBENCH_ASSET_TEMPLATE, default_source=default_source, omdb_key=omdb_key, tmdb_key=tmdb_key)


def render_normalize_lab_html(default_source: Path | None = None, omdb_key: str | None = None, tmdb_key: str | None = None) -> str:
    return render_asset_html(NORMALIZE_LAB_ASSET_TEMPLATE, default_source=default_source, omdb_key=omdb_key, tmdb_key=tmdb_key)


def serve_web_ui(
    host: str,
    port: int,
    default_source: Path | None = None,
    omdb_key: str | None = None,
    tmdb_key: str | None = None,
) -> None:
    handler = build_handler(default_source=default_source, omdb_key=omdb_key, tmdb_key=tmdb_key)
    server = ThreadingHTTPServer((host, port), handler)
    source_hint = f" default source {default_source}" if default_source else ""
    print(f"normal web UI listening on http://{host}:{port}/{source_hint}")
    server.serve_forever()


def serve_static_asset(ctx: RequestContext, route: str) -> None:
    asset_name, content_type = WEB_STATIC_ASSETS[route]
    body = read_web_asset_bytes(asset_name)
    ctx.respond_bytes(body, content_type=content_type)


def serve_workbench_static_asset(ctx: RequestContext, route: str) -> None:
    asset_name, content_type = WORKBENCH_STATIC_ASSETS[route]
    body = read_web_asset_bytes(asset_name)
    ctx.respond_bytes(body, content_type=content_type)


def serve_normalize_lab_static_asset(ctx: RequestContext, route: str) -> None:
    asset_name, content_type = NORMALIZE_LAB_STATIC_ASSETS[route]
    body = read_web_asset_bytes(asset_name)
    ctx.respond_bytes(body, content_type=content_type)


def serve_index(ctx: RequestContext) -> None:
    body = render_index_html(
        default_source=ctx.default_source,
        omdb_key=ctx.omdb_key,
        tmdb_key=ctx.tmdb_key,
    ).encode("utf-8")
    ctx.respond_bytes(body, content_type="text/html; charset=utf-8")


def serve_workbench(ctx: RequestContext) -> None:
    body = render_workbench_html(
        default_source=ctx.default_source,
        omdb_key=ctx.omdb_key,
        tmdb_key=ctx.tmdb_key,
    ).encode("utf-8")
    ctx.respond_bytes(body, content_type="text/html; charset=utf-8")


def serve_normalize_lab(ctx: RequestContext) -> None:
    body = render_normalize_lab_html(
        default_source=ctx.default_source,
        omdb_key=ctx.omdb_key,
        tmdb_key=ctx.tmdb_key,
    ).encode("utf-8")
    ctx.respond_bytes(body, content_type="text/html; charset=utf-8")


def build_get_routes() -> dict[str, Callable[[RequestContext], None]]:
    routes: dict[str, Callable[[RequestContext], None]] = {
        "/api/activity": handle_activity,
        "/api/library-roots": handle_library_roots_get,
        "/": serve_index,
        "/index.html": serve_index,
        "/workbench": serve_workbench,
        "/workbench.html": serve_workbench,
        "/normalize-lab": serve_normalize_lab,
        "/normalize-lab.html": serve_normalize_lab,
    }
    for route in WEB_STATIC_ASSETS:
        routes[route] = lambda ctx, route=route: serve_static_asset(ctx, route)
    for route in WORKBENCH_STATIC_ASSETS:
        routes[route] = lambda ctx, route=route: serve_workbench_static_asset(ctx, route)
    for route in NORMALIZE_LAB_STATIC_ASSETS:
        routes[route] = lambda ctx, route=route: serve_normalize_lab_static_asset(ctx, route)
    return routes


def build_post_routes() -> dict[str, Callable[[RequestContext, dict], None]]:
    return {
        "/api/library-roots": handle_library_roots_post,
        "/api/movies/profile": handle_movies_profile,
        "/api/movies/dashboard/histogram": handle_movies_dashboard_histogram,
        "/api/movies/standards/update": handle_movies_standards_update,
        "/api/movies/canonical-lists": handle_movies_canonical_lists,
        "/api/movies/omdb/ratings": handle_movies_omdb_ratings,
        "/api/source/scan-warning": handle_source_scan_warning,
        "/api/movies/register": handle_movies_register,
        "/api/movies/inspect": handle_movies_inspect,
        "/api/movies/normalize": handle_movies_normalize,
        "/api/movies/apply": handle_movies_apply,
        "/api/movies/normalize-lab/export": handle_movies_normalize_lab_export,
        "/api/movies/junk": handle_movies_junk,
        "/api/movies/junk/delete": handle_movies_junk_delete,
        "/api/movies/replacement-queue/list": handle_movies_replacement_queue_list,
        "/api/movies/replacement-queue/add": handle_movies_replacement_queue_add,
        "/api/movies/replacement-queue/delete": handle_movies_replacement_queue_delete,
        "/api/movies/replacement-queue/dismiss": handle_movies_replacement_queue_dismiss,
        "/api/movies/audio-packaging/fix": handle_movies_audio_packaging_fix,
        "/api/movies/subtitle-readiness/fix": handle_movies_subtitle_readiness_fix,
        "/api/movies/subtitle-readiness/history": handle_movies_subtitle_readiness_history_list,
        "/api/movies/subtitle-readiness/history/sync": handle_movies_subtitle_readiness_history_sync,
        "/api/movies/subtitle-readiness/history/dismiss": handle_movies_subtitle_readiness_history_dismiss,
    }


def build_handler(
    default_source: Path | None = None,
    omdb_key: str | None = None,
    tmdb_key: str | None = None,
):
    get_routes = build_get_routes()
    post_routes = build_post_routes()

    class Handler(BaseHTTPRequestHandler):
        activity_tracker = state.ACTIVITY_TRACKER

        def _request_context(self) -> RequestContext:
            return RequestContext(
                handler=self,
                default_source=default_source,
                omdb_key=omdb_key,
                tmdb_key=tmdb_key,
            )

        def do_GET(self) -> None:
            ctx = self._request_context()
            route = self.path.split("?", 1)[0]
            handler = get_routes.get(route)
            if handler is None:
                ctx.respond_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)
                return
            try:
                handler(ctx)
            except RequestConflictError as exc:
                ctx.respond_json({"error": str(exc)}, status=HTTPStatus.CONFLICT)
            except Exception as exc:
                ctx.respond_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)

        def do_POST(self) -> None:
            ctx = self._request_context()
            route = self.path
            handler = post_routes.get(route)
            if handler is None:
                ctx.respond_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)
                return
            try:
                payload = ctx.read_json_body()
                handler(ctx, payload)
            except RequestConflictError as exc:
                ctx.respond_json({"error": str(exc)}, status=HTTPStatus.CONFLICT)
            except Exception as exc:
                ctx.respond_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)

        def log_message(self, format: str, *args) -> None:
            return

    return Handler


state.ACTIVITY_TRACKER = ActivityTracker()
