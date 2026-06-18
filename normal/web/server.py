from __future__ import annotations

import json
import hashlib
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

from normal.movie_profile import OPERATOR_PREFERENCES_PATH
from . import state
from .activity import ActivityTracker
from .routes_audit import handle_audit_follow_up_update, handle_audit_read, handle_audit_stream, record_system_event
from .http import RequestContext
from .routes_cleanup import (
    handle_movies_delete,
    handle_movies_delete_preview,
    handle_movies_audio_packaging_fix,
    handle_movies_junk,
    handle_movies_junk_delete,
    handle_movies_repair_defaults_fix,
    handle_movies_subtitle_readiness_fix,
)
from .routes_core import handle_activity, handle_library_roots_get, handle_library_roots_post, handle_source_approve, handle_source_scan_warning
from normal.source_policy import ApprovedRootRequiredError, ApprovedRoots, MutableApprovedRoots
from .routes_normalize import handle_movies_apply, handle_movies_normalize, handle_tv_apply, handle_tv_normalize
from .routes_queue import handle_queue_drain, handle_queue_stage, handle_queue_status
from .routes_settings import (
    handle_settings_keys_update,
    handle_settings_preferences_update,
    handle_settings_read,
)
from . import security
from .security import PostRejected
from .routes_profile import (
    handle_movies_canonical_lists,
    handle_movies_canonical_refresh,
    handle_movies_canonical_status,
    handle_movies_dashboard_histogram,
    handle_movies_inspect,
    handle_movies_omdb_ratings,
    handle_movies_profile,
    handle_movies_register,
    handle_movies_standards_update,
    handle_policy_read,
    handle_policy_update,
)
from .state import RequestConflictError


WEB_ASSET_ROOT = "web_assets"
WEB_STATIC_ASSETS = {
    "/assets/workbench.css": ("normalize_lab.css", "text/css; charset=utf-8"),
    "/assets/workbench.js": ("normalize_lab.js", "application/javascript; charset=utf-8"),
}
WEB_BOOTSTRAP_SENTINEL = "__NORMAL_BOOTSTRAP__"
SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
    ),
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}


def read_web_asset_text(name: str) -> str:
    return resources.files("normal").joinpath(WEB_ASSET_ROOT, name).read_text(encoding="utf-8")


def read_web_asset_bytes(name: str) -> bytes:
    return read_web_asset_text(name).encode("utf-8")


def versioned_asset_route(route: str, asset_name: str) -> str:
    digest = hashlib.sha256(read_web_asset_bytes(asset_name)).hexdigest()[:12]
    return f"{route}?v={digest}"


def read_onboarding_bootstrap(omdb_key: str | None = None, tmdb_key: str | None = None) -> dict[str, object]:
    has_probe_cache = state.PROBE_CACHE.has_entries()
    has_profile = OPERATOR_PREFERENCES_PATH.exists()
    has_omdb_key = bool(omdb_key or state.CREDENTIAL_STORE.omdb_key())
    has_tmdb_key = bool(tmdb_key or state.CREDENTIAL_STORE.tmdb_key())
    temp = "warm" if has_probe_cache or has_profile else "cold"
    return {
        "temp": temp,
        "reasons": {
            "has_probe_cache": has_probe_cache,
            "has_profile": has_profile,
            "has_omdb_key": has_omdb_key,
            "has_tmdb_key": has_tmdb_key,
        },
    }


def render_web_bootstrap(default_source: Path | None = None, omdb_key: str | None = None, tmdb_key: str | None = None) -> str:
    boot = {
        "defaultSource": str(default_source) if default_source else "",
        "omdbAvailable": bool(omdb_key),
        "tmdbAvailable": bool(tmdb_key),
        "onboarding": read_onboarding_bootstrap(omdb_key=omdb_key, tmdb_key=tmdb_key),
        "token": security.MUTATION_TOKEN,
    }
    return json.dumps(boot).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def render_workbench_html(default_source: Path | None = None, omdb_key: str | None = None, tmdb_key: str | None = None) -> str:
    template = read_web_asset_text("normalize_lab.html")
    html = template.replace(
        WEB_BOOTSTRAP_SENTINEL,
        render_web_bootstrap(default_source=default_source, omdb_key=omdb_key, tmdb_key=tmdb_key),
        1,
    )
    for route, (asset_name, _) in WEB_STATIC_ASSETS.items():
        html = html.replace(route, versioned_asset_route(route, asset_name))
    return html


def serve_web_ui(
    host: str,
    port: int,
    default_source: Path | None = None,
    omdb_key: str | None = None,
    tmdb_key: str | None = None,
    approved_roots: ApprovedRoots | None = None,
    allowed_hosts: frozenset[str] = frozenset(),
) -> None:
    state.CREDENTIAL_STORE.seed_from_boot(omdb_key=omdb_key, tmdb_key=tmdb_key)
    handler = build_handler(
        default_source=default_source,
        approved_roots=approved_roots,
        allowed_hosts=allowed_hosts,
    )
    server = ThreadingHTTPServer((host, port), handler)
    source_hint = f" default source {default_source}" if default_source else ""
    print(f"normal web UI listening on http://{host}:{port}/{source_hint}")
    record_system_event(
        action="start",
        summary="Started normal web UI.",
        metadata={
            "host": host,
            "port": port,
            "default_source": str(default_source.resolve()) if default_source else "",
            "omdb_enabled": bool(omdb_key),
            "tmdb_enabled": bool(tmdb_key),
        },
    )
    server.serve_forever()


def serve_static_asset(ctx: RequestContext, route: str) -> None:
    asset_name, content_type = WEB_STATIC_ASSETS[route]
    body = read_web_asset_bytes(asset_name)
    ctx.respond_bytes(body, content_type=content_type, headers={"Cache-Control": "no-store", **SECURITY_HEADERS})


def serve_workbench(ctx: RequestContext) -> None:
    body = render_workbench_html(
        default_source=ctx.default_source,
        omdb_key=ctx.omdb_key,
        tmdb_key=ctx.tmdb_key,
    ).encode("utf-8")
    ctx.respond_bytes(body, content_type="text/html; charset=utf-8", headers={"Cache-Control": "no-store", **SECURITY_HEADERS})


def build_get_routes() -> dict[str, Callable[[RequestContext], None]]:
    routes: dict[str, Callable[[RequestContext], None]] = {
        "/api/activity": handle_activity,
        "/api/audit/stream": handle_audit_stream,
        "/api/library-roots": handle_library_roots_get,
        "/": serve_workbench,
        "/index.html": serve_workbench,
    }
    for route in WEB_STATIC_ASSETS:
        routes[route] = lambda ctx, route=route: serve_static_asset(ctx, route)
    return routes


def build_post_routes() -> dict[str, Callable[[RequestContext, dict], None]]:
    return {
        "/api/library-roots": handle_library_roots_post,
        "/api/audit/read": handle_audit_read,
        "/api/audit/follow-up/update": handle_audit_follow_up_update,
        "/api/movies/profile": handle_movies_profile,
        "/api/movies/dashboard/histogram": handle_movies_dashboard_histogram,
        "/api/movies/standards/update": handle_movies_standards_update,
        "/api/policy/read": handle_policy_read,
        "/api/policy/update": handle_policy_update,
        "/api/movies/canonical-lists": handle_movies_canonical_lists,
        "/api/movies/canonical-status": handle_movies_canonical_status,
        "/api/movies/canonical-refresh": handle_movies_canonical_refresh,
        "/api/movies/omdb/ratings": handle_movies_omdb_ratings,
        "/api/settings/read": handle_settings_read,
        "/api/settings/keys": handle_settings_keys_update,
        "/api/settings/preferences": handle_settings_preferences_update,
        "/api/source/approve": handle_source_approve,
        "/api/source/scan-warning": handle_source_scan_warning,
        "/api/movies/register": handle_movies_register,
        "/api/movies/inspect": handle_movies_inspect,
        "/api/movies/normalize": handle_movies_normalize,
        "/api/movies/apply": handle_movies_apply,
        "/api/tv/normalize": handle_tv_normalize,
        "/api/tv/apply": handle_tv_apply,
        "/api/normalize/queue/stage": handle_queue_stage,
        "/api/normalize/queue/drain": handle_queue_drain,
        "/api/normalize/queue/status": handle_queue_status,
        "/api/movies/junk": handle_movies_junk,
        "/api/movies/junk/delete": handle_movies_junk_delete,
        "/api/movies/delete-preview": handle_movies_delete_preview,
        "/api/movies/delete": handle_movies_delete,
        "/api/movies/audio-packaging/fix": handle_movies_audio_packaging_fix,
        "/api/movies/repair-defaults/fix": handle_movies_repair_defaults_fix,
        "/api/movies/subtitle-readiness/fix": handle_movies_subtitle_readiness_fix,
    }


def build_handler(
    default_source: Path | None = None,
    approved_roots: ApprovedRoots | None = None,
    allowed_hosts: frozenset[str] = frozenset(),
):
    get_routes = build_get_routes()
    post_routes = build_post_routes()
    roots = MutableApprovedRoots(approved_roots if approved_roots is not None else ApprovedRoots())

    def approval_error_payload(exc: ApprovedRootRequiredError) -> dict[str, object]:
        return {
            "error": str(exc),
            "approval_required": True,
            "source": str(exc.source),
            "suggested_root": str(exc.suggested_root),
            "approved_roots": [str(root) for root in exc.approved_roots],
        }

    class Handler(BaseHTTPRequestHandler):
        activity_tracker = state.ACTIVITY_TRACKER

        def _request_context(self) -> RequestContext:
            return RequestContext(
                handler=self,
                default_source=default_source,
                omdb_key=state.CREDENTIAL_STORE.omdb_key(),
                tmdb_key=state.CREDENTIAL_STORE.tmdb_key(),
                approved_roots=roots,
            )

        def do_GET(self) -> None:
            ctx = self._request_context()
            route = urlsplit(self.path).path
            handler = get_routes.get(route)
            if handler is None:
                ctx.respond_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)
                return
            try:
                if route.startswith("/api/"):
                    security.check_token(self, allow_query=route == "/api/audit/stream")
                handler(ctx)
            except PostRejected as exc:
                ctx.respond_json({"error": exc.message}, status=exc.status)
            except ApprovedRootRequiredError as exc:
                ctx.respond_json(approval_error_payload(exc), status=HTTPStatus.BAD_REQUEST)
            except RequestConflictError as exc:
                ctx.respond_json({"error": str(exc)}, status=HTTPStatus.CONFLICT)
            except Exception as exc:
                ctx.respond_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)

        def do_POST(self) -> None:
            ctx = self._request_context()
            try:
                route = urlsplit(self.path).path
                handler = post_routes.get(route)
                if handler is None:
                    ctx.respond_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)
                    return
                content_length = security.check_post(
                    self,
                    bound_port=self.server.server_address[1],
                    allowed_hosts=allowed_hosts,
                )
                payload = ctx.read_json_body(content_length)
                handler(ctx, payload)
            except PostRejected as exc:
                ctx.respond_json({"error": exc.message}, status=exc.status)
            except ApprovedRootRequiredError as exc:
                ctx.respond_json(approval_error_payload(exc), status=HTTPStatus.BAD_REQUEST)
            except RequestConflictError as exc:
                ctx.respond_json({"error": str(exc)}, status=HTTPStatus.CONFLICT)
            except Exception as exc:
                ctx.respond_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)

        def log_message(self, format: str, *args) -> None:
            return

    return Handler


state.ACTIVITY_TRACKER = ActivityTracker()
