from __future__ import annotations

import tempfile
import threading
import types
import unittest
import urllib.error
import urllib.request
from contextlib import contextmanager
from http import HTTPStatus
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
from urllib.parse import quote
from unittest.mock import patch

from normal.web import (
    ApprovedRoots,
    build_handler,
    delete_movie_junk_files,
    read_web_asset_text,
    read_onboarding_bootstrap,
    render_workbench_html,
)
from normal.web.routes_cleanup import delete_mode_for_kind
from normal.web.security import (
    MAX_JSON_BODY,
    MUTATION_TOKEN,
    PostRejected,
    check_post,
    parse_allowed_hosts,
)


WORKBENCH_TEMPLATE = read_web_asset_text("normalize_lab.html")
WORKBENCH_CSS = read_web_asset_text("normalize_lab.css")
WORKBENCH_JS = read_web_asset_text("normalize_lab.js")
FRONTEND = "\n".join((WORKBENCH_TEMPLATE, WORKBENCH_CSS, WORKBENCH_JS))
APP_CSS = WORKBENCH_CSS
APP_JS = WORKBENCH_JS
NORMALIZE_LAB_TEMPLATE = WORKBENCH_TEMPLATE
NORMALIZE_LAB_CSS = WORKBENCH_CSS
NORMALIZE_LAB_JS = WORKBENCH_JS
NORMALIZE_LAB_FRONTEND = FRONTEND


class WebTests(unittest.TestCase):
    def workbench_js_source(self) -> str:
        return (Path(__file__).resolve().parent.parent / "normal" / "web_assets" / "normalize_lab.js").read_text(encoding="utf-8")

    def workbench_css_source(self) -> str:
        return (Path(__file__).resolve().parent.parent / "normal" / "web_assets" / "normalize_lab.css").read_text(encoding="utf-8")

    @contextmanager
    def run_test_server(self, **handler_kwargs):
        handler_kwargs.setdefault("approved_roots", ApprovedRoots.from_paths([Path(tempfile.gettempdir())]))
        server = ThreadingHTTPServer(("127.0.0.1", 0), build_handler(**handler_kwargs))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_address[1]}"
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_scan_warning_is_wired(self) -> None:
        self.assertIn("const params = new URLSearchParams(window.location.search);", FRONTEND)
        self.assertIn("url.searchParams.set('workflow', state.workflow);", FRONTEND)
        self.assertIn("workflow === 'canonical-lists'", FRONTEND)

    def test_workbench_runtime_keys_are_available_before_initial_render(self) -> None:
        html = render_workbench_html(Path("/library/movies"), omdb_key="omdb-test", tmdb_key="tmdb-test")
        self.assertIn('<link rel="stylesheet" href="/assets/workbench.css?v=', html)
        self.assertIn('<script src="/assets/workbench.js?v=', html)
        self.assertLess(html.index('id="normal-boot"'), html.index('<script src="/assets/workbench.js?v='))
        self.assertIn('<script type="application/json" id="normal-boot">{"defaultSource": "/library/movies"', html)
        self.assertNotIn("omdb-test", html)
        self.assertNotIn("tmdb-test", html)
        self.assertIn('"tmdbAvailable": true', html)
        self.assertNotIn("fonts.googleapis.com", html)
        self.assertNotIn("fonts.gstatic.com", html)

    def test_workbench_template_avoids_remote_font_dependencies(self) -> None:
        self.assertNotIn("fonts.googleapis.com", WORKBENCH_TEMPLATE)
        self.assertNotIn("fonts.gstatic.com", WORKBENCH_TEMPLATE)
        self.assertNotIn("@font-face", WORKBENCH_CSS)

    def test_handler_serves_static_assets(self) -> None:
        with self.run_test_server() as base_url:
            with urllib.request.urlopen(f"{base_url}/assets/workbench.css") as response:
                self.assertEqual(response.headers.get_content_type(), "text/css")
                self.assertEqual(response.headers.get("Cache-Control"), "no-store")
                self.assertIn(".lab-layout", response.read().decode("utf-8"))
            with urllib.request.urlopen(f"{base_url}/assets/workbench.js") as response:
                self.assertEqual(response.headers.get_content_type(), "application/javascript")
                self.assertEqual(response.headers.get("Cache-Control"), "no-store")
                self.assertIn("/api/movies/apply", response.read().decode("utf-8"))

    def test_workbench_response_sets_security_headers(self) -> None:
        with self.run_test_server() as base_url:
            with urllib.request.urlopen(base_url) as response:
                csp = response.headers.get("Content-Security-Policy")
                self.assertIn("script-src 'self'", csp)
                self.assertIn("frame-ancestors 'none'", csp)
                self.assertIn("style-src 'self' 'unsafe-inline'", csp)
                self.assertEqual(response.headers.get("X-Frame-Options"), "DENY")
                self.assertEqual(response.headers.get("Referrer-Policy"), "no-referrer")
            with urllib.request.urlopen(f"{base_url}/assets/workbench.js") as response:
                self.assertIn("script-src 'self'", response.headers.get("Content-Security-Policy"))

    def test_audit_stream_route_serves_sse_revision_notice(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "movies"
            source.mkdir()
            with self.run_test_server() as base_url:
                url = f"{base_url}/api/audit/stream?source={quote(str(source))}&token={quote(MUTATION_TOKEN)}"
                with urllib.request.urlopen(url, timeout=2) as response:
                    self.assertEqual(response.headers.get("Content-Type"), "text/event-stream; charset=utf-8")
                    self.assertEqual(response.headers.get("Cache-Control"), "no-store")
                    data_line = response.readline().decode("utf-8").strip()
        self.assertTrue(data_line.startswith("data: "))
        payload = json.loads(data_line[6:])
        self.assertIn("revision", payload)
        self.assertEqual(payload["source_roots"], [str(source.resolve())])

    def test_root_route_serves_default_workbench(self) -> None:
        with self.run_test_server() as base_url:
            with urllib.request.urlopen(base_url) as response:
                served = response.read().decode("utf-8")
            with urllib.request.urlopen(f"{base_url}/index.html") as response:
                served_index = response.read().decode("utf-8")
        self.assertIn("normal workbench", served)
        self.assertIn("/assets/workbench.js?v=", served)
        self.assertIn("Normalize Movie Library Naming", served)
        self.assertEqual(served, served_index)

    def test_rendered_workbench_includes_current_shell_contract(self) -> None:
        html = render_workbench_html(Path("/library/movies"))
        self.assertIn('/assets/workbench.css?v=', html)
        self.assertIn('/assets/workbench.js?v=', html)
        self.assertIn('<script type="application/json" id="normal-boot">{"defaultSource": "/library/movies"', html)
        self.assertIn('id="policyToggle"', html)
        self.assertIn('id="placeholderToggle"', html)
        self.assertIn('id="placeholderDownloadToggle"', html)
        self.assertIn('id="settingsToggle"', html)
        self.assertIn('id="onboardingGate"', html)
        self.assertIn('id="onboardingGateClose"', html)
        self.assertIn('class="lab-sliver"', html)
        self.assertIn('id="policyEditorPanel"', html)
        self.assertIn('id="settingsPanel"', html)
        self.assertIn('id="inspectionPane"', html)
        self.assertNotIn('Repair Lane', html)
        self.assertIn('data-layout-mode="2-page-lopsided"', html)
        self.assertIn('data-page-role="scan"', html)
        self.assertIn('data-page-role="preview"', html)
        self.assertIn('data-collapse-mode="reflow"', html)
        self.assertIn('data-collapse-mode="anchored-slot"', html)

    def test_onboarding_bootstrap_reads_cold_state_from_existing_persistence_signals(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            profile_path = Path(tmpdir) / "operator-preferences.json"
            with patch("normal.web.server.OPERATOR_PREFERENCES_PATH", profile_path):
                with patch("normal.web.server.state.PROBE_CACHE.has_entries", return_value=False):
                    payload = read_onboarding_bootstrap()
                    self.assertEqual(payload["temp"], "cold")
                    self.assertEqual(payload["reasons"]["has_profile"], False)
                    self.assertEqual(payload["reasons"]["has_probe_cache"], False)

                    profile_path.write_text('{"default_source":"/library"}', encoding="utf-8")
                    payload = read_onboarding_bootstrap()
                    self.assertEqual(payload["temp"], "warm")
                    self.assertEqual(payload["reasons"]["has_profile"], True)

    def test_onboarding_bootstrap_marks_probe_cache_as_warm_even_without_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            profile_path = Path(tmpdir) / "operator-preferences.json"
            with patch("normal.web.server.OPERATOR_PREFERENCES_PATH", profile_path):
                with patch("normal.web.server.state.PROBE_CACHE.has_entries", return_value=True):
                    payload = read_onboarding_bootstrap(omdb_key="omdb-test")
        self.assertEqual(payload["temp"], "warm")
        self.assertEqual(payload["reasons"]["has_probe_cache"], True)
        self.assertEqual(payload["reasons"]["has_omdb_key"], True)

    def test_settings_keys_read_save_clear_cycle(self) -> None:
        from normal.web import credentials as credentials_module
        from normal.web import routes_settings

        class StubContext:
            def __init__(self) -> None:
                self.responses: list[dict] = []

            def respond_json(self, payload, status=None) -> None:
                self.responses.append(payload)

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict("os.environ", {"XDG_DATA_HOME": tmp}):
                store = credentials_module.CredentialStore()
                with patch.object(routes_settings, "CREDENTIAL_STORE", store):
                    secrets = credentials_module.secrets_file_path()
                    self.assertEqual(secrets, Path(tmp) / "normal" / "secrets.env")

                    ctx = StubContext()
                    routes_settings.handle_settings_read(ctx, {})
                    self.assertEqual(ctx.responses[-1]["keys"]["omdb"]["present"], False)
                    self.assertIsNone(ctx.responses[-1]["keys"]["omdb"]["last4"])

                    ctx = StubContext()
                    routes_settings.handle_settings_keys_update(ctx, {"omdb": "abcd1234SECRET"})
                    omdb = ctx.responses[-1]["keys"]["omdb"]
                    self.assertTrue(omdb["present"])
                    self.assertEqual(omdb["last4"], "CRET")
                    self.assertEqual(omdb["source"], "saved")
                    self.assertNotIn("abcd1234SECRET", json.dumps(ctx.responses[-1]))

                    self.assertEqual(oct(secrets.stat().st_mode & 0o777), "0o600")
                    self.assertIn("OMDB_KEY=abcd1234SECRET", secrets.read_text())

                    ctx = StubContext()
                    routes_settings.handle_settings_read(ctx, {})
                    self.assertTrue(ctx.responses[-1]["keys"]["omdb"]["present"])

                    ctx = StubContext()
                    routes_settings.handle_settings_keys_update(ctx, {"omdb": ""})
                    self.assertFalse(ctx.responses[-1]["keys"]["omdb"]["present"])
                    self.assertEqual(secrets.read_text(), "")

    def test_set_keys_rejects_newline_and_nul_values(self) -> None:
        from normal.web import credentials as credentials_module

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict("os.environ", {"XDG_DATA_HOME": tmp}):
                store = credentials_module.CredentialStore()
                store.set_keys({"OMDB_KEY": "good-key"})
                secrets = credentials_module.secrets_file_path()
                self.assertEqual(secrets.read_text(), "OMDB_KEY=good-key\n")

                for bad in ("inject\nMORE=1", "with\x00nul", "carriage\rreturn"):
                    with self.assertRaises(ValueError):
                        store.set_keys({"TMDB_KEY": bad})

                self.assertIsNone(store.tmdb_key())
                self.assertEqual(secrets.read_text(), "OMDB_KEY=good-key\n")

    def test_settings_preferences_persist_fun_mode_globally(self) -> None:
        from normal.web import routes_settings

        class StubContext:
            def __init__(self) -> None:
                self.responses: list[dict] = []

            def respond_json(self, payload, status=None) -> None:
                self.responses.append(payload)

        with tempfile.TemporaryDirectory() as tmpdir:
            preferences_path = Path(tmpdir) / "operator-preferences.json"
            with patch("normal.movie_profile.OPERATOR_PREFERENCES_PATH", preferences_path):
                ctx = StubContext()
                routes_settings.handle_settings_read(ctx, {})
                self.assertFalse(ctx.responses[-1]["fun_mode"])

                ctx = StubContext()
                routes_settings.handle_settings_preferences_update(ctx, {"fun_mode": True})
                self.assertTrue(ctx.responses[-1]["fun_mode"])
                self.assertTrue(ctx.responses[-1]["operator_preferences"]["fun_mode"])
                self.assertTrue(json.loads(preferences_path.read_text(encoding="utf-8"))["fun_mode"])

    def test_manual_immersive_confirm_route_is_removed(self) -> None:
        from normal.web import routes_profile, server

        self.assertNotIn("/api/movies/immersive/confirm", server.build_post_routes())
        self.assertFalse(hasattr(routes_profile, "handle_movies_immersive_confirm"))

    def test_local_probe_harvest_records_available_and_audits(self) -> None:
        from types import SimpleNamespace
        from normal.web import routes_profile
        from normal import movie_immersive_confirmations as confirmations

        report = SimpleNamespace(movies=[
            SimpleNamespace(path="Sneakers (1992)/Sneakers (1992).mkv", facts=SimpleNamespace(audio_immersive_extension="atmos")),
            SimpleNamespace(path="Heat (1995)/Heat (1995).mkv", facts=SimpleNamespace(audio_immersive_extension=None)),
        ])
        events: list = []
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "immersive-confirmations.json"
            with patch.object(confirmations, "default_store_path", lambda: store), \
                 patch.object(routes_profile, "load_operator_preferences", lambda: {"immersive_local_probe_telemetry": True}), \
                 patch.object(routes_profile.AUDIT_STORE, "append", events.append):
                routes_profile._harvest_local_immersive_votes(Path(tmp), report)
                self.assertEqual(
                    confirmations.confirmation_index(store).get(confirmations.confirmation_key("Sneakers", 1992)),
                    "available",
                )

        self.assertEqual([event.workflow for event in events], ["immersive"])
        self.assertEqual(events[0].action, "telemetry_vote")

    def test_deprecated_alt_ui_route_and_assets_are_removed(self) -> None:
        with self.run_test_server() as base_url:
            for path in (
                "/book-style-alt-design-ui",
                "/book-style-alt-design-ui.html",
                "/book-style-alt-design-ui-assets/workbench.css",
                "/book-style-alt-design-ui-assets/workbench.js",
            ):
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(f"{base_url}{path}")
                self.assertEqual(ctx.exception.code, 404)

    def test_legacy_dashboard_and_tester_routes_are_removed(self) -> None:
        with self.run_test_server() as base_url:
            for path in (
                "/parser-tester-ui",
                "/parser-tester-ui.html",
                "/parser-tester-ui-assets/normalize_lab.css",
                "/parser-tester-ui-assets/normalize_lab.js",
                "/assets/app.css",
                "/assets/app.js",
            ):
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(f"{base_url}{path}")
                self.assertEqual(ctx.exception.code, 404)

    def test_normalize_lab_export_endpoint_is_removed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "library"
            source.mkdir()
            with self.run_test_server() as base_url:
                body = json.dumps({"source": str(source), "rows": [{"current_value": "Movie.mkv"}]}).encode("utf-8")
                req = urllib.request.Request(
                    f"{base_url}/api/movies/parser-tester-ui/export",
                    data=body,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 404)

    def test_handler_returns_404_for_unknown_static_asset(self) -> None:
        with self.run_test_server() as base_url:
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f"{base_url}/assets/missing.css")
        self.assertEqual(ctx.exception.code, 404)

    def test_delete_mode_for_kind_supports_all_four_modes(self) -> None:
        self.assertEqual(delete_mode_for_kind("media", {"delete_mode": "recycle_all"}), "recycle")
        self.assertEqual(delete_mode_for_kind("junk", {"delete_mode": "hard_delete_all"}), "hard_delete")
        self.assertEqual(delete_mode_for_kind("media", {"delete_mode": "hybrid_media_to_bin_junk_hard_delete"}), "recycle")
        self.assertEqual(delete_mode_for_kind("junk", {"delete_mode": "hybrid_media_to_bin_junk_hard_delete"}), "hard_delete")
        self.assertEqual(delete_mode_for_kind("media", {"delete_mode": "hybrid_junk_to_bin_media_hard_delete"}), "hard_delete")
        self.assertEqual(delete_mode_for_kind("junk", {"delete_mode": "hybrid_junk_to_bin_media_hard_delete"}), "recycle")

    def test_library_switcher_remembers_music_and_movie_roots(self) -> None:
        self.assertIn("el.sourcePath.value = window.DEFAULT_SOURCE || '';", FRONTEND)
        self.assertIn("function preferredDefaultSource()", FRONTEND)
        self.assertIn("state.policyPayload?.operator_preferences?.default_source", FRONTEND)
        self.assertNotIn("Library Switcher", FRONTEND)
        self.assertNotIn("n_library_roots", FRONTEND)

    def test_onboarding_gate_is_client_owned_and_dismissible(self) -> None:
        self.assertIn("const ONBOARDING_DISMISS_KEY = 'normal.onboarding.dismissed.cold';", FRONTEND)
        self.assertIn("function onboardingShouldShow()", FRONTEND)
        self.assertIn("function showOnboardingGate()", FRONTEND)
        self.assertIn("function hideOnboardingGate({ remember = false } = {})", FRONTEND)
        self.assertIn("showOnboardingGate();", FRONTEND)
        self.assertIn("hideOnboardingGate({ remember: true });", FRONTEND)
        self.assertIn("window.localStorage.removeItem(ONBOARDING_DISMISS_KEY);", FRONTEND)
        self.assertIn("window.localStorage.setItem(ONBOARDING_DISMISS_KEY, '1');", FRONTEND)

    def test_run_button_becomes_stop_while_scan_runs(self) -> None:
        self.assertIn("state.runInFlight ? 'Running' :", FRONTEND)
        self.assertIn("'Run Normalize Movie Library Naming'", FRONTEND)
        self.assertIn("'Run Fix Audio and Subtitle Defaults'", FRONTEND)
        self.assertIn("'Run Compare Against Canonical Lists'", FRONTEND)
        self.assertNotIn("runButton.textContent = running ? 'Stop' : 'Run';", FRONTEND)

    def test_drive_activity_indicator_is_wired(self) -> None:
        self.assertNotIn("id=\"activityBar\"", FRONTEND)
        self.assertNotIn("function refreshActivityState", FRONTEND)
        self.assertNotIn("Drive activity: idle", FRONTEND)
        self.assertIn("const ACTIVITY_POLL_MS = 2000;", FRONTEND)
        self.assertIn("function activityPayloadHasRemux(payload = state.activityPayload)", FRONTEND)
        self.assertIn("await tokenFetch(`/api/activity?source=${encodeURIComponent(source)}`);", FRONTEND)
        self.assertIn("scheduleActivityPoll();", FRONTEND)

    def test_movie_junk_page_is_wired(self) -> None:
        self.assertIn("workflowJunk", FRONTEND)
        self.assertIn("postJson('/api/movies/junk'", FRONTEND)
        self.assertIn("'/api/movies/junk/delete'", FRONTEND)
        self.assertIn("state.junkPayload = payload;", FRONTEND)
        self.assertIn("clearDeletePreviewState();", FRONTEND)
        self.assertIn("Run Remove Junk Files", FRONTEND)
        self.assertIn("markAncestorsSelected: false", FRONTEND)
        self.assertIn("folder: true", FRONTEND)
        self.assertIn(".lab-tree-line.is-cleanup {\n  color: #8d5d1d;\n  font-weight: 600;", FRONTEND)

    def test_movie_junk_endpoint_returns_detected_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "library"
            movie_dir = source / "Movie"
            movie_dir.mkdir(parents=True)
            (movie_dir / "Movie-sample.mkv").write_bytes(b"x")
            body = json.dumps({"source": str(source)}).encode("utf-8")
            with self.run_test_server() as base_url:
                req = urllib.request.Request(
                    f"{base_url}/api/movies/junk",
                    data=body,
                    headers={"Content-Type": "application/json", "X-Normal-Token": MUTATION_TOKEN},
                    method="POST",
                )
                with urllib.request.urlopen(req) as response:
                    payload = json.loads(response.read().decode("utf-8"))
        self.assertEqual(payload["source_root"], str(source.resolve()))
        self.assertEqual(len(payload["junk"]), 1)
        self.assertEqual(payload["junk"][0]["relative_path"], "Movie/Movie-sample.mkv")

    def test_movie_delete_flows_are_direct_in_weak_encodes(self) -> None:
        self.assertIn("Delete Selected Files (", FRONTEND)
        self.assertIn("selectedWeakItems()", FRONTEND)
        self.assertIn("'/api/movies/delete'", FRONTEND)
        self.assertIn("button:disabled {", APP_CSS)
        self.assertIn("cursor: not-allowed;", APP_CSS)

    def test_movie_audio_packaging_page_is_wired(self) -> None:
        widths_js = self.workbench_js_source()
        self.assertIn("'repair-defaults': 'Fix Audio and Subtitle Defaults'", FRONTEND)
        self.assertIn("audioFixBusy: false", FRONTEND)
        self.assertIn("function repairWorkflowBusy()", FRONTEND)
        self.assertIn("non-English audio is default · English backup is weaker", FRONTEND)
        self.assertIn("'/api/movies/audio-packaging/fix'", FRONTEND)
        self.assertIn("Make Best English Audio Default", FRONTEND)
        self.assertIn("Make Best English Audio Default + Remove Foreign Audio", FRONTEND)
        self.assertIn("state.audioFixBusy = true;", FRONTEND)
        self.assertIn("state.audioFixBusy = false;", FRONTEND)
        self.assertIn("el.runButton.disabled = state.runInFlight || repairWorkflowBusy();", FRONTEND)
        self.assertIn("el.workflowButton.disabled = repairWorkflowBusy();", FRONTEND)
        self.assertIn("el.workflowButton.dataset.active = surfaceOpen() ? 'false' : 'true';", FRONTEND)
        self.assertIn("button.disabled = repairWorkflowBusy();", FRONTEND)
        self.assertIn("if (repairWorkflowBusy()) return;", FRONTEND)
        self.assertIn("drop_foreign_audio: dropForeignAudio", FRONTEND)
        self.assertIn("selectedRepairAudioPaths()", FRONTEND)
        self.assertIn("Running English-default remux", FRONTEND)
        self.assertIn("function actualResolutionLabel(item)", FRONTEND)
        self.assertIn("label: 'Default Audio'", widths_js)
        self.assertIn("width: TABLE_WIDTHS.defaultAudio", widths_js)
        self.assertIn("width: 'auto'", widths_js)
        self.assertIn("width: TABLE_WIDTHS.defaultSubtitle", widths_js)
        self.assertIn("width: TABLE_WIDTHS.issue", widths_js)
        self.assertIn("width: TABLE_WIDTHS.currentDefault", widths_js)
        self.assertIn("width: TABLE_WIDTHS.repairTarget", widths_js)
        self.assertIn("width: TABLE_WIDTHS.resolution", widths_js)
        self.assertIn("function currentWarningGateSafetyLevel()", FRONTEND)
        self.assertIn("function confirmSafeRepairWarningGates(action, applicableRows)", FRONTEND)
        self.assertIn("warning_gate_safety_level", FRONTEND)
        self.assertIn("Continue with this multi-file remux queue?", FRONTEND)
        self.assertNotIn("audio: ${describeAudioStream(movieDefaultAudioStream(item))}", FRONTEND)
        self.assertNotIn("audio: ${describeAudioStream(movieBestEnglishAudioStream(item))}", FRONTEND)
        self.assertIn("function repairDefaultSubtitleLabel(item)", FRONTEND)
        self.assertIn("function repairDefaultAudioLabel(item, row = null)", FRONTEND)
        self.assertIn("function effectiveAudioStreamBitrateKbps(track, row = null)", FRONTEND)
        self.assertIn("function describeAudioPopoverFacts(track, row = null)", FRONTEND)
        self.assertIn("const defaultAudioLabel = repairDefaultAudioLabel(row.item, row);", FRONTEND)
        self.assertIn("await refreshActivityPayload();", FRONTEND)
        self.assertIn("return state.filteredRows.filter(row => state.selected.has(row.row_id));", FRONTEND)
        self.assertNotIn("return state.filteredRows.filter(row => state.selected.has(row.row_id) && row.selectable);", FRONTEND)
        self.assertNotIn("if (!usesDeletePreviewShell() || !tracks.length) {", FRONTEND)

    def test_movie_subtitle_readiness_page_is_wired(self) -> None:
        self.assertIn("'repair-defaults': 'Fix Audio and Subtitle Defaults'", FRONTEND)
        self.assertIn("subtitleFixBusy: false", FRONTEND)
        self.assertIn("function movieSubtitleReadinessIsRepairable(item)", FRONTEND)
        self.assertIn("['off', 'forced_english', 'english', 'primary_language'].includes", FRONTEND)
        self.assertIn("subtitlePolicy.englishAudioSubtitles === 'forced_english'", FRONTEND)
        self.assertIn("Normalize Subtitle Defaults", FRONTEND)
        self.assertIn("'/api/movies/subtitle-readiness/fix'", FRONTEND)
        self.assertIn("This page is non-destructive", FRONTEND)
        self.assertIn("state.subtitleFixBusy = true;", FRONTEND)
        self.assertIn("state.subtitleFixBusy = false;", FRONTEND)
        self.assertIn("selectedSubtitleRowsFromPayload", FRONTEND)
        self.assertIn("function safeRepairLockOverlayEnabled()", FRONTEND)
        self.assertIn("currentWarningGateSafetyLevel() === 'safe'", FRONTEND)
        self.assertIn("Scanning, fixes, and settings are paused, not cancelled", FRONTEND)

    def test_policy_editor_render_is_guarded_against_unrelated_side_panel_refreshes(self) -> None:
        self.assertIn("policyEditorRenderKey: ''", NORMALIZE_LAB_JS)
        self.assertIn("function currentPolicyEditorRenderKey(definitions) {", NORMALIZE_LAB_JS)
        self.assertIn("if (state.policyEditorRenderKey === renderKey) return;", NORMALIZE_LAB_JS)

    def test_movie_dashboard_has_replacement_queue_summary_without_detail_pane(self) -> None:
        self.assertIn("function renderDashboardPanel()", FRONTEND)
        self.assertIn("function currentDashboardPayload()", FRONTEND)
        self.assertIn("function updateDashboardPayload(payload, requestedSource = '')", FRONTEND)
        self.assertIn("function qualityProfileDisplayLabel(label)", FRONTEND)
        self.assertIn("resolveLabel: entry => qualityProfileDisplayLabel(entry)", FRONTEND)
        self.assertIn("Dashboard currently reuses the latest profile-bearing scan for this source.", FRONTEND)
        self.assertIn("Library visibility snapshot", FRONTEND)
        self.assertIn("Quality Profile Breakdown", FRONTEND)
        self.assertIn("Resolution Breakdown", FRONTEND)
        self.assertIn("Surround Sound Breakdown", FRONTEND)

    def test_movie_dashboard_exposes_inline_profile_definition_controls(self) -> None:
        self.assertIn("/api/policy/read", FRONTEND)
        self.assertIn("/api/policy/update", FRONTEND)
        self.assertIn("function renderPolicyEditor()", FRONTEND)
        self.assertIn("function togglePolicyEditor()", FRONTEND)
        self.assertIn("function currentQualityProfileDefinitions()", FRONTEND)
        self.assertIn("function policyDefinitionDisplayLabel(label)", FRONTEND)
        self.assertIn("policyDrafts: {}", FRONTEND)
        self.assertIn("payload.policy_definitions.filter(definition => definition?.label !== 'replacement_candidate')", FRONTEND)

    def test_normalize_policy_editor_filters_redundant_replacement_candidate_and_starts_collapsed(self) -> None:
        self.assertIn("payload.policy_definitions.filter(definition => definition?.label !== 'replacement_candidate')", NORMALIZE_LAB_FRONTEND)
        self.assertIn("const preferredOrder = ['default_source', 'delete_mode', 'library_defaults', 'language_subtitle_defaults'];", NORMALIZE_LAB_FRONTEND)
        self.assertIn("return filtered.slice().sort((left, right) => {", NORMALIZE_LAB_FRONTEND)
        self.assertIn("const isOpen = state.policySectionLabel === definition.label;", NORMALIZE_LAB_FRONTEND)
        self.assertIn("state.policySectionLabel = label || '';", NORMALIZE_LAB_FRONTEND)
        self.assertIn("lab-policy-section-header", NORMALIZE_LAB_FRONTEND)
        self.assertIn("aria-expanded=\"${isOpen ? 'true' : 'false'}\"", NORMALIZE_LAB_FRONTEND)
        self.assertIn("section.addEventListener('keydown', event => {", NORMALIZE_LAB_FRONTEND)
        self.assertIn("if (label === 'language_subtitle_defaults') return 'Language & Subtitles';", NORMALIZE_LAB_FRONTEND)
        self.assertNotIn("${isOpen ? 'Collapse' : 'Edit'}", NORMALIZE_LAB_FRONTEND)
        self.assertNotIn("(!state.policySectionLabel && definition.label === 'library_defaults')", NORMALIZE_LAB_FRONTEND)
        self.assertNotIn("User-local", NORMALIZE_LAB_FRONTEND)
        self.assertNotIn("Repo-local", NORMALIZE_LAB_FRONTEND)
        self.assertNotIn("repo-local <span class=\"lab-cell-mono\">movie_standards.json</span>", NORMALIZE_LAB_FRONTEND)
        self.assertNotIn("user-local delete posture", NORMALIZE_LAB_FRONTEND)

    def test_lopsided_threshold_tuner_card_is_wired(self) -> None:
        self.assertIn("function lopsidedPolicySection()", NORMALIZE_LAB_FRONTEND)
        self.assertIn('data-policy-section="lopsided_encode"', NORMALIZE_LAB_FRONTEND)
        self.assertIn("${sections}${lopsidedPolicySection()}", NORMALIZE_LAB_FRONTEND)
        self.assertIn("function lopsidedVerdict(f, cfg)", NORMALIZE_LAB_FRONTEND)
        self.assertIn("function saveLopsidedDraft()", NORMALIZE_LAB_FRONTEND)
        self.assertIn("label: 'lopsided_encode'", NORMALIZE_LAB_FRONTEND)
        self.assertIn("'/api/movies/standards/update'", NORMALIZE_LAB_FRONTEND)
        self.assertIn("lopsided hits:", NORMALIZE_LAB_FRONTEND)
        self.assertIn("lab-lopsided-register", NORMALIZE_LAB_FRONTEND)
        self.assertIn("<h3>Lopsided encode thresholds</h3>", NORMALIZE_LAB_FRONTEND)

    def test_dashboard_payload_refresh_invalidates_lopsided_cache(self) -> None:
        section = NORMALIZE_LAB_JS.split("function updateDashboardPayload(payload, requestedSource = '') {", 1)[1].split("async function refreshDashboardPayload", 1)[0]
        self.assertIn("state._lopsidedFactsCache = null;", section)
    def test_movie_canonical_lists_page_is_wired(self) -> None:
        self.assertIn("Compare Against Canonical Lists", FRONTEND)
        self.assertIn("'/api/movies/canonical-lists'", FRONTEND)
        self.assertIn("Run Compare Against Canonical Lists", FRONTEND)
        self.assertIn("function renderCanonicalPreviewPane()", FRONTEND)
        self.assertIn("function canonicalRows()", FRONTEND)
        self.assertIn("Canonical improvement", FRONTEND)
        self.assertIn("['Video resolution', width > 0 && height > 0 ? `${width} x ${height}` : '—']", NORMALIZE_LAB_FRONTEND)

    def test_canonical_status_and_refresh_routes_are_wired(self) -> None:
        server_source = (Path(__file__).resolve().parent.parent / "normal" / "web" / "server.py").read_text(encoding="utf-8")
        self.assertIn('"/api/movies/canonical-status": handle_movies_canonical_status', server_source)
        self.assertIn('"/api/movies/canonical-refresh": handle_movies_canonical_refresh', server_source)

    def test_movie_normalize_has_review_and_apply_workflow(self) -> None:
        self.assertIn("'/api/movies/normalize'", FRONTEND)
        self.assertIn("'/api/movies/apply'", FRONTEND)
        self.assertIn("Run normalize to inspect projected output.", FRONTEND)
        self.assertIn("Select rows in the table to stage a preview", FRONTEND)
        self.assertIn("function selectedProposedChanges()", FRONTEND)
        self.assertIn("function summarizeNormalizeRows(rows)", FRONTEND)
        self.assertNotIn("proposed_changes_by_naming_style", FRONTEND)
        self.assertIn("No remaining normalize changes.", FRONTEND)
        self.assertIn("buildPreviewTree(rows)", FRONTEND)

    def test_normalize_lab_frontend_is_confirm_wired_and_reason_aware(self) -> None:
        self.assertIn("/api/movies/normalize", NORMALIZE_LAB_FRONTEND)
        self.assertIn("/api/movies/apply", NORMALIZE_LAB_FRONTEND)
        self.assertIn("/api/movies/profile", NORMALIZE_LAB_FRONTEND)
        self.assertIn("/api/movies/junk", NORMALIZE_LAB_FRONTEND)
        self.assertIn("/api/movies/junk/delete", NORMALIZE_LAB_FRONTEND)
        self.assertIn("/api/movies/audio-packaging/fix", NORMALIZE_LAB_FRONTEND)
        self.assertIn("/api/movies/subtitle-readiness/fix", NORMALIZE_LAB_FRONTEND)
        self.assertIn("weak_floor: state.weakFloor", NORMALIZE_LAB_FRONTEND)
        self.assertIn("/api/movies/delete-preview", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Normalize Movie Library Naming", NORMALIZE_LAB_FRONTEND)
        self.assertIn("workflowNormalize\" class=\"lab-workflow-option\" type=\"button\" data-workflow=\"normalize\" role=\"option\">Normalize Movie Library Naming</button>\n            <button id=\"workflowJunk\" class=\"lab-workflow-option\" type=\"button\" data-workflow=\"junk\" role=\"option\">Remove Junk Files</button>\n            <button id=\"workflowWeakEncodes\" class=\"lab-workflow-option\" type=\"button\" data-workflow=\"weak-encodes\" role=\"option\">Review Low-Quality Encodes</button>\n            <button id=\"workflowRepairDefaults\" class=\"lab-workflow-option\" type=\"button\" data-workflow=\"repair-defaults\" role=\"option\">Fix Audio and Subtitle Defaults</button>\n            <button id=\"workflowImmersive\" class=\"lab-workflow-option\" type=\"button\" data-workflow=\"format-upgrades\" role=\"option\">Review Format Upgrade Candidates</button>\n            <button id=\"workflowCanonicalLists\" class=\"lab-workflow-option\" type=\"button\" data-workflow=\"canonical-lists\" role=\"option\">Compare Against Canonical Lists</button>", NORMALIZE_LAB_FRONTEND)
        self.assertIn("state.immersivePayload?.trait_assessments", FRONTEND)
        self.assertNotIn("immersiveInferredVerdict", FRONTEND)
        self.assertIn("Review Low-Quality Encodes", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Fix Audio and Subtitle Defaults", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Compare Against Canonical Lists", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Remove Junk Files", NORMALIZE_LAB_FRONTEND)
        self.assertIn("/api/movies/canonical-lists", NORMALIZE_LAB_FRONTEND)
        self.assertIn("workflow === 'canonical-lists'", NORMALIZE_LAB_FRONTEND)
        self.assertIn("id=\"dashboardToggle\"", NORMALIZE_LAB_FRONTEND)
        self.assertIn("id=\"placeholderToggle\"", NORMALIZE_LAB_FRONTEND)
        self.assertIn("id=\"placeholderDownloadToggle\"", NORMALIZE_LAB_FRONTEND)
        self.assertIn("class=\"lab-sliver-separator\"", NORMALIZE_LAB_FRONTEND)
        self.assertIn("placeholderToggle\" class=\"lab-sliver-toggle\" type=\"button\" aria-label=\"Placeholder\" title=\"Placeholder\" disabled></button>\n            <div class=\"lab-sliver-separator\" aria-hidden=\"true\"></div>\n            <button id=\"placeholderDownloadToggle\"", NORMALIZE_LAB_FRONTEND)
        self.assertIn("state.surfaceMode = dashboardSurfaceOpen() ? 'default' : 'dashboard';", NORMALIZE_LAB_FRONTEND)
        self.assertIn("function renderDashboardPanel()", NORMALIZE_LAB_FRONTEND)
        self.assertIn("function currentDashboardPayload()", NORMALIZE_LAB_FRONTEND)
        self.assertIn("function updateDashboardPayload(payload, requestedSource = '')", NORMALIZE_LAB_FRONTEND)
        self.assertIn("function replacementFloorDisplayLabel(label)", NORMALIZE_LAB_FRONTEND)
        self.assertIn("dashboardRequestedSource", NORMALIZE_LAB_FRONTEND)
        self.assertIn("normalizeSourceKey(value)", NORMALIZE_LAB_FRONTEND)
        self.assertIn("state.dashboardProfileSource === source || state.dashboardRequestedSource === source", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Dashboard currently reuses the latest profile-bearing scan for this source.", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Library visibility snapshot", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Quality Profile Breakdown", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Library Improvement Metrics", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Non-audio files removed", NORMALIZE_LAB_JS)
        self.assertIn("Resolution Breakdown", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Surround Sound Breakdown", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Current Top 500 above weak floor", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Canonical improvement", NORMALIZE_LAB_FRONTEND)
        self.assertIn("4K Anamorphic", NORMALIZE_LAB_FRONTEND)
        self.assertIn("7.1 Atmos Bed", NORMALIZE_LAB_FRONTEND)
        self.assertIn("function dashboardResolutionBreakdownKey(item)", NORMALIZE_LAB_FRONTEND)
        self.assertIn("function dashboardSurroundBreakdownKey(item)", NORMALIZE_LAB_FRONTEND)
        self.assertIn("function movieBreakdownCounts(items, keyFn)", NORMALIZE_LAB_FRONTEND)
        self.assertIn("histogram.resolution_breakdown_counts : movieResolutionCounts", NORMALIZE_LAB_FRONTEND)
        self.assertIn("histogram.surround_sound_breakdown_counts : movieSurroundCounts", NORMALIZE_LAB_FRONTEND)
        self.assertIn("escapeHtml(replacementFloorDisplayLabel(cutoff))", NORMALIZE_LAB_FRONTEND)
        self.assertIn("histogram.resolution_breakdown_counts || {}", NORMALIZE_LAB_FRONTEND)
        self.assertIn("histogram.surround_sound_breakdown_counts || {}", NORMALIZE_LAB_FRONTEND)
        self.assertIn("id=\"canonicalListFilter\"", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Run Compare Against Canonical Lists", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Quality Profile Inspector", NORMALIZE_LAB_FRONTEND)
        self.assertIn("function renderCanonicalPreviewPane()", NORMALIZE_LAB_FRONTEND)
        self.assertIn("function canonicalRows()", NORMALIZE_LAB_FRONTEND)
        self.assertIn("function imdbTitleUrl(imdbId)", NORMALIZE_LAB_FRONTEND)
        self.assertIn("function imdbTitleSearchUrl(title)", NORMALIZE_LAB_FRONTEND)
        self.assertIn("function canonicalTitleMarkup(title, imdbId)", NORMALIZE_LAB_FRONTEND)
        self.assertIn("imdb_id: entry.imdb_id || ''", NORMALIZE_LAB_FRONTEND)
        self.assertIn("href=\"${escapeHtml(url)}\" target=\"_blank\" rel=\"noopener noreferrer\"", NORMALIZE_LAB_FRONTEND)
        self.assertIn("label: 'Quality Profile'", NORMALIZE_LAB_FRONTEND)
        self.assertIn("label: 'In Library'", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Top 100", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Top 250", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Top 500", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Animation", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Anime", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Sci-Fi", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Fantasy", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Action", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Thriller / Mystery", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Drama / Romance", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Documentary", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Comedy", NORMALIZE_LAB_FRONTEND)
        self.assertIn("TV Shows", NORMALIZE_LAB_FRONTEND)
        self.assertIn("disabled>Anime</option><option value=\"tv_shows\" disabled>TV Shows</option>", NORMALIZE_LAB_FRONTEND)
        self.assertIn("const CANONICAL_FALLBACK_LISTS = [", NORMALIZE_LAB_FRONTEND)
        self.assertIn("function canonicalFallbackOptionsMarkup()", NORMALIZE_LAB_FRONTEND)
        self.assertIn("const requestedListId = state.canonicalSelectedListId || el.canonicalListFilter?.value || 'top_100';", NORMALIZE_LAB_FRONTEND)
        self.assertIn("state.canonicalSelectedListId = lists.find(item => item.id === requestedListId)?.id", NORMALIZE_LAB_FRONTEND)
        self.assertIn("renderFilterVisibility();", NORMALIZE_LAB_FRONTEND)
        self.assertNotIn("id=\"canonicalListsToggle\"", NORMALIZE_LAB_FRONTEND)
        self.assertIn("aria-label=\"Placeholder\"", NORMALIZE_LAB_FRONTEND)
        self.assertIn("disabled></button>", NORMALIZE_LAB_FRONTEND)
        self.assertIn("el.policyToggle.innerHTML = railIconSvg('scroll-text');", NORMALIZE_LAB_FRONTEND)
        self.assertIn("el.auditToggle.innerHTML = railIconSvg('clipboard-paste');", NORMALIZE_LAB_FRONTEND)
        self.assertIn("el.placeholderToggle.innerHTML = railIconSvg('trophy');", NORMALIZE_LAB_FRONTEND)
        self.assertIn("railIconSvg('download')", NORMALIZE_LAB_FRONTEND)
        self.assertIn("const exportLabel = exportBusy ? 'Exporting Catalogue' : 'Export Catalogue';", NORMALIZE_LAB_FRONTEND)
        self.assertIn("await postFetch('/api/movies/register', {", NORMALIZE_LAB_FRONTEND)
        self.assertIn("el.placeholderDownloadToggle.addEventListener('click', () => {", NORMALIZE_LAB_FRONTEND)
        self.assertNotIn("class=\"lab-sliver-middle\"", NORMALIZE_LAB_FRONTEND)
        self.assertNotIn("class=\"lab-sliver-foot\"", NORMALIZE_LAB_FRONTEND)
        self.assertIn("return workflow;", NORMALIZE_LAB_FRONTEND)
        self.assertIn("/api/policy/read", NORMALIZE_LAB_FRONTEND)
        self.assertIn("/api/policy/update", NORMALIZE_LAB_FRONTEND)
        self.assertIn("if (label === 'default_source') return 'Default Library Directory';", NORMALIZE_LAB_FRONTEND)
        self.assertIn("function preferredDefaultSource()", NORMALIZE_LAB_FRONTEND)
        self.assertIn("state.policyPayload?.operator_preferences?.default_source", NORMALIZE_LAB_FRONTEND)
        self.assertIn("source: normalizeSourceKey(el.sourcePath.value),", NORMALIZE_LAB_FRONTEND)
        self.assertIn("id=\"policyToggle\"", NORMALIZE_LAB_FRONTEND)
        self.assertIn("class=\"lab-sliver\"", NORMALIZE_LAB_FRONTEND)
        self.assertIn("id=\"settingsToggle\"", NORMALIZE_LAB_FRONTEND)
        self.assertIn("id=\"settingsPanel\"", NORMALIZE_LAB_FRONTEND)
        self.assertIn("function renderSettingsPanel()", NORMALIZE_LAB_FRONTEND)
        self.assertIn("function settingsSurfaceOpen()", NORMALIZE_LAB_FRONTEND)
        self.assertIn("'/api/settings/read'", NORMALIZE_LAB_FRONTEND)
        self.assertIn("'/api/settings/keys'", NORMALIZE_LAB_FRONTEND)
        self.assertNotIn("<h3>Fun Mode</h3>", NORMALIZE_LAB_FRONTEND)
        self.assertNotIn('data-settings-preference="fun_mode"', NORMALIZE_LAB_FRONTEND)
        self.assertIn("state.funMode = Boolean(preferences.fun_mode);", NORMALIZE_LAB_FRONTEND)
        self.assertNotIn('id="funModeToggle"', NORMALIZE_LAB_FRONTEND)
        self.assertIn("id=\"dashboardPanel\"", NORMALIZE_LAB_FRONTEND)
        self.assertIn("id=\"policyEditorPanel\"", NORMALIZE_LAB_FRONTEND)
        self.assertIn("id=\"inspectionPane\"", NORMALIZE_LAB_FRONTEND)
        self.assertIn("state.surfaceMode = 'default'", NORMALIZE_LAB_FRONTEND)
        self.assertIn("function renderPolicyRail()", NORMALIZE_LAB_FRONTEND)
        self.assertIn("function renderPolicyEditor()", NORMALIZE_LAB_FRONTEND)
        self.assertIn("function renderInspectionPane()", NORMALIZE_LAB_FRONTEND)
        self.assertIn("function togglePolicyEditor()", NORMALIZE_LAB_FRONTEND)
        self.assertIn("if (!surfaceOpen()) {", NORMALIZE_LAB_FRONTEND)
        self.assertIn("id=\"auditToggle\"", NORMALIZE_LAB_FRONTEND)
        self.assertIn("id=\"auditPanel\"", NORMALIZE_LAB_FRONTEND)
        self.assertIn("/api/audit/read", NORMALIZE_LAB_FRONTEND)
        self.assertIn("new EventSource(`/api/audit/stream?${params.toString()}`)", NORMALIZE_LAB_FRONTEND)
        self.assertIn("function refreshAuditPayload(", NORMALIZE_LAB_FRONTEND)
        self.assertIn("function markAuditLedgerDirty()", NORMALIZE_LAB_FRONTEND)
        self.assertIn("function ensureAuditEventSource()", NORMALIZE_LAB_FRONTEND)
        self.assertIn("const AUDIT_STREAM_RETRY_MS = 2000;", NORMALIZE_LAB_FRONTEND)
        self.assertIn("function auditSessionContextLabel(payload)", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Session started ${formatAuditRecordedAt(event.recorded_at)}", NORMALIZE_LAB_FRONTEND)
        self.assertIn("class=\"lab-audit-context\"", NORMALIZE_LAB_FRONTEND)
        self.assertIn("auditOpenBreakdowns: new Set()", NORMALIZE_LAB_FRONTEND)
        self.assertIn("function bindAuditBreakdownToggleState()", NORMALIZE_LAB_FRONTEND)
        self.assertIn("data-audit-breakdown-toggle", NORMALIZE_LAB_FRONTEND)
        self.assertIn("lab-audit-summary-toggle", NORMALIZE_LAB_FRONTEND)
        self.assertIn("lab-audit-child-row", NORMALIZE_LAB_FRONTEND)
        self.assertIn("<th>Outcome</th>", NORMALIZE_LAB_FRONTEND)
        self.assertNotIn("<th>Effect</th>", NORMALIZE_LAB_FRONTEND)
        self.assertNotIn("lab-audit-sync-chip", NORMALIZE_LAB_FRONTEND)
        self.assertIn("await ensurePolicyPayload();", NORMALIZE_LAB_FRONTEND)
        self.assertIn("if (startupSource) el.sourcePath.value = startupSource;", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Preview and action controls are suppressed while policy editing is active.", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Preview and action controls are suppressed while dashboard view is open.", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Preview and action controls are suppressed while the audit ledger is open.", NORMALIZE_LAB_FRONTEND)
        self.assertIn("function dismissActiveSurface()", NORMALIZE_LAB_FRONTEND)
        self.assertIn("const surfaceDismissed = dismissActiveSurface();", NORMALIZE_LAB_FRONTEND)
        self.assertIn("if (auditSurfaceOpen()) closeAuditEventSource();", NORMALIZE_LAB_FRONTEND)
        self.assertIn("const surfaceDismissed = dismissActiveSurface();", NORMALIZE_LAB_FRONTEND)
        self.assertIn("if (label !== 'default_source' && el.sourcePath.value.trim()) {", NORMALIZE_LAB_FRONTEND)
        self.assertIn("applyPolicyPayload(payload);", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Make Best English Audio Default", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Normalize Subtitle Defaults", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Make Best English Audio Default + Normalize Subtitle Defaults", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Make Best English Audio Default + Remove Foreign Audio", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Make Best English Audio Default + Remove Foreign Audio + Normalize Subtitle Defaults", NORMALIZE_LAB_FRONTEND)
        self.assertNotIn("Repair Lane", NORMALIZE_LAB_FRONTEND)
        self.assertIn("This page is non-destructive", NORMALIZE_LAB_FRONTEND)
        self.assertIn("non-English audio is default · English backup is weaker", NORMALIZE_LAB_FRONTEND)
        self.assertIn("default_non_english_audio", NORMALIZE_LAB_FRONTEND)
        self.assertIn("function actualResolutionLabel(item)", NORMALIZE_LAB_FRONTEND)
        self.assertIn("return `${width} x ${height}`;", NORMALIZE_LAB_FRONTEND)
        self.assertIn("data-track-popover=\"${escapeHtml(row.row_id)}\"", NORMALIZE_LAB_FRONTEND)
        self.assertIn("data-track-popover-kind=\"subtitle\"", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Subtitle Tracks", NORMALIZE_LAB_FRONTEND)
        self.assertIn("after audio default flips:", NORMALIZE_LAB_FRONTEND)
        self.assertIn("audio/default:", NORMALIZE_LAB_FRONTEND)
        self.assertIn("subtitle/default: no subtitle default", NORMALIZE_LAB_FRONTEND)
        self.assertIn("sequence: sequence++", NORMALIZE_LAB_FRONTEND)
        self.assertIn("is-staged", NORMALIZE_LAB_FRONTEND)
        self.assertIn("is-landing", NORMALIZE_LAB_FRONTEND)
        self.assertIn("content: \"->\";", NORMALIZE_LAB_FRONTEND)
        self.assertIn("selectable: Boolean(item.path) && issueFamilies.length > 0 && !repairDefaultsSelectionLocked()", NORMALIZE_LAB_FRONTEND)
        self.assertIn("File Name", NORMALIZE_LAB_FRONTEND)
        self.assertIn("label: 'Confidence'", NORMALIZE_LAB_FRONTEND)
        self.assertIn("function fileNameFromPath(path)", NORMALIZE_LAB_FRONTEND)
        self.assertIn("function middleTruncateJunkFileName(value, maxWidth, font)", NORMALIZE_LAB_FRONTEND)
        self.assertIn("new ResizeObserver", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Select all", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Deselect all", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Action", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Run Repair", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Confirm (0 Operations)", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Run Remove Junk Files", NORMALIZE_LAB_FRONTEND)
        self.assertNotIn("reason code", NORMALIZE_LAB_FRONTEND)
        self.assertNotIn("warning code", NORMALIZE_LAB_FRONTEND)
        self.assertNotIn("package cases", NORMALIZE_LAB_FRONTEND)
        self.assertNotIn("collision cases", NORMALIZE_LAB_FRONTEND)
        self.assertNotIn("artifact cleanup cases", NORMALIZE_LAB_FRONTEND)
        self.assertNotIn("subtitle-merge cases", NORMALIZE_LAB_FRONTEND)
        self.assertNotIn("previewScopeSelect", NORMALIZE_LAB_FRONTEND)
        self.assertIn("function renderPreviewPane()", NORMALIZE_LAB_FRONTEND)
        self.assertIn("function renderPanelVisibility()", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Below Min. Video Bitrate", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Main Audio Below ${threshold} Channels", NORMALIZE_LAB_FRONTEND)
        self.assertIn("LAYOUT_MODES", NORMALIZE_LAB_FRONTEND)
        self.assertIn("2-page-lopsided", NORMALIZE_LAB_FRONTEND)
        self.assertIn("3-page-book", NORMALIZE_LAB_FRONTEND)
        self.assertIn("4-page-ledger", NORMALIZE_LAB_FRONTEND)
        self.assertIn("data-layout-mode", NORMALIZE_LAB_FRONTEND)
        self.assertIn("data-policy-mode", NORMALIZE_LAB_FRONTEND)
        self.assertIn("data-page-role", NORMALIZE_LAB_FRONTEND)
        self.assertIn("data-collapse-mode", NORMALIZE_LAB_FRONTEND)
        self.assertIn("data-panel-state", NORMALIZE_LAB_FRONTEND)
        self.assertIn("data-rhythm-surface", NORMALIZE_LAB_FRONTEND)
        self.assertIn("state.activeRowId = rowEl.dataset.rowId || '';", NORMALIZE_LAB_FRONTEND)
        self.assertNotIn("state.activeRowId = id;", NORMALIZE_LAB_FRONTEND)
        self.assertIn("function selectedProposedChanges()", NORMALIZE_LAB_FRONTEND)
        self.assertIn("function summarizeNormalizeRows(rows)", NORMALIZE_LAB_FRONTEND)
        self.assertIn("function renderNormalizeSummaryChips(operationCounts, visibleMutationCount)", NORMALIZE_LAB_FRONTEND)
        self.assertIn("function renderConfirmButton()", NORMALIZE_LAB_FRONTEND)
        self.assertIn("function renderShellLayout()", NORMALIZE_LAB_FRONTEND)
        self.assertIn("el.previewControls.classList.remove('is-repair-delete-leading');", NORMALIZE_LAB_FRONTEND)
        self.assertIn("el.confirmButton.hidden = true;", NORMALIZE_LAB_FRONTEND)
        self.assertIn("This page is non-destructive", NORMALIZE_LAB_FRONTEND)
        self.assertIn("change.change_type !== 'folder_delete' || change.confidence !== 'safe' || !change.current_value", NORMALIZE_LAB_FRONTEND)
        self.assertIn("selectedRelatedCount !== relatedRows.length", NORMALIZE_LAB_FRONTEND)
        self.assertIn("mutated media file", NORMALIZE_LAB_FRONTEND)
        self.assertIn("visible path mutation", NORMALIZE_LAB_FRONTEND)
        self.assertIn("planned operation", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Delete Selected Files (", NORMALIZE_LAB_FRONTEND)
        self.assertIn("selected junk file", NORMALIZE_LAB_FRONTEND)
        self.assertIn("selected junk file", NORMALIZE_LAB_FRONTEND)
        self.assertIn("summaryNoun: 'subtitle issue'", NORMALIZE_LAB_FRONTEND)
        self.assertIn("summaryNoun: 'audio-packaging title'", NORMALIZE_LAB_FRONTEND)
        self.assertIn("summaryNoun: 'repair title'", NORMALIZE_LAB_FRONTEND)
        self.assertIn("No remaining normalize changes.", NORMALIZE_LAB_FRONTEND)
        self.assertNotIn("detailPane", NORMALIZE_LAB_FRONTEND)
        self.assertNotIn("renderDetailPane", NORMALIZE_LAB_FRONTEND)
        self.assertNotIn("Why this is", NORMALIZE_LAB_FRONTEND)
        self.assertNotIn("detailTab", NORMALIZE_LAB_FRONTEND)
        self.assertNotIn("previewTab", NORMALIZE_LAB_FRONTEND)
        self.assertNotIn("Replacement History", NORMALIZE_LAB_FRONTEND)
        self.assertNotIn("buildReplacementHistoryTable", NORMALIZE_LAB_FRONTEND)
        self.assertNotIn('id="weakFloorSelect"', NORMALIZE_LAB_TEMPLATE)

    def test_normalize_lab_css_exposes_shell_layout_and_rhythm_contracts(self) -> None:
        css_source = self.workbench_css_source()
        self.assertIn('[hidden] { display: none !important; }', css_source)
        self.assertIn('--lab-track-rail', css_source)
        self.assertIn('--lab-track-scan', css_source)
        self.assertIn('--lab-track-inspection', css_source)
        self.assertIn('--lab-track-preview', css_source)
        self.assertIn('--lab-track-audit', css_source)
        self.assertIn('--lab-primary-surface-min-height', css_source)
        self.assertIn('--lab-rhythm-row-height', css_source)
        self.assertIn('--lab-rhythm-panel-body-offset', css_source)
        self.assertIn('--lab-table-foundation-column-width', css_source)
        self.assertIn('--lab-table-select-column-width', css_source)
        self.assertIn('--lab-table-select-pad-inline-start', css_source)
        self.assertIn('--lab-table-foundation-column-width: 8ch;', css_source)
        self.assertIn('--lab-table-select-column-width: var(--lab-table-foundation-column-width);', css_source)
        self.assertIn('--lab-table-select-pad-inline-start: 0px;', css_source)
        self.assertIn('--lab-table-select-pad-inline-end: 0px;', css_source)
        self.assertIn('.lab-scan-table col.lab-col-foundation', css_source)
        self.assertIn('text-align: center;', css_source)
        self.assertIn('.lab-shell[data-layout-mode="2-page-lopsided"]', css_source)
        self.assertIn('.lab-shell[data-layout-mode="3-page-book"] .lab-layout', css_source)
        self.assertIn('.lab-shell[data-layout-mode="4-page-ledger"] .lab-layout', css_source)
        self.assertIn('.lab-shell[data-policy-mode="editing"] .lab-layout', css_source)
        self.assertIn('.lab-sliver', css_source)
        self.assertIn('.lab-shell[data-policy-mode="default"] .lab-sliver {', css_source)
        self.assertIn('grid-template-rows: auto;', css_source)
        self.assertIn('min-height: 0;', css_source)
        self.assertIn('height: auto;', css_source)
        self.assertIn('.lab-shell[data-policy-mode="default"] .lab-sliver-slot {', css_source)
        self.assertIn('grid-template-columns: repeat(2, minmax(0, 1fr));', css_source)
        self.assertIn('.lab-workflow-button[data-active="true"] {', css_source)
        self.assertIn('box-shadow: inset 0 0 0 1px', css_source)
        self.assertIn('.lab-dashboard-breakdowns {', css_source)
        self.assertIn('.lab-audit-context {', css_source)
        self.assertIn('.lab-audit-summary-toggle {', css_source)
        self.assertIn('.lab-audit-summary-toggle-copy::before {', css_source)
        self.assertIn('.lab-audit-child-row td {', css_source)
        self.assertIn('.lab-cell-pill.is-audit-media-repair {', css_source)
        self.assertNotIn('.lab-audit-sync-chip {', css_source)
        self.assertIn('min-height: var(--lab-primary-surface-min-height);', css_source)
        self.assertIn('.lab-policy-panel', css_source)
        self.assertIn('.lab-inspection-pane', css_source)
        self.assertIn('.lab-preview-controls.is-repair-delete-leading .lab-confirm-button {', css_source)
        self.assertIn('.lab-preview-controls.is-repair-delete-leading .lab-preview-group {', css_source)
        self.assertIn('.lab-page[data-panel-state="collapsed"][data-collapse-mode="anchored-slot"]', css_source)
        self.assertIn('.lab-page[data-panel-state="collapsed"][data-collapse-mode="reflow"]', css_source)
        self.assertIn('.lab-rhythm-surface[data-rhythm-surface="rows"]', css_source)

    def test_audit_ledger_colgroup_favors_recorded_action_and_workflow_width(self) -> None:
        self.assertIn('<col style="width: 22ch">', NORMALIZE_LAB_JS)
        self.assertIn('<col style="width: 14ch">', NORMALIZE_LAB_JS)
        self.assertIn('<col style="width: 19ch">', NORMALIZE_LAB_JS)
        self.assertIn('<col style="width: 12%">', NORMALIZE_LAB_JS)
        self.assertIn('<col style="width: 20ch">', NORMALIZE_LAB_JS)
        self.assertIn('<col style="width: 24%">', NORMALIZE_LAB_JS)

    def test_normalize_lab_table_declares_fixed_select_column_contract(self) -> None:
        self.assertIn('<colgroup id="tableColGroup"></colgroup>', NORMALIZE_LAB_TEMPLATE)
        widths_js = self.workbench_js_source()
        self.assertIn("tableColGroup: document.getElementById('tableColGroup')", widths_js)
        self.assertIn("const TABLE_WIDTHS = {", widths_js)
        self.assertIn("foundation: 'var(--lab-table-foundation-column-width)'", widths_js)
        self.assertIn("projectedPath: '28%'", widths_js)
        self.assertIn("issue: '13%'", widths_js)
        self.assertIn("resolution: '16ch'", widths_js)
        self.assertIn('el.tableColGroup.innerHTML = headers.map(header => {', widths_js)
        self.assertIn("const styleAttr = header.width ? ` style=\"width:${escapeHtml(header.width)}\"` : '';", widths_js)
        self.assertIn('return `<col${classAttr}${styleAttr}>`;', widths_js)
        self.assertIn("width: TABLE_WIDTHS.foundation", widths_js)
        self.assertIn("columnClass: 'lab-col-foundation lab-col-select'", widths_js)
        self.assertIn("columnClass: 'lab-col-foundation lab-col-signal'", widths_js)
        self.assertIn("width: 'auto'", widths_js)

    def test_format_upgrade_columns_use_semantic_content_widths(self) -> None:
        widths_js = self.workbench_js_source()
        self.assertIn("category: '17ch'", widths_js)
        self.assertIn("verdict: '20ch'", widths_js)
        self.assertIn("key: 'year', label: 'Year'", widths_js)
        self.assertIn("width: TABLE_WIDTHS.year", widths_js)
        self.assertIn("key: 'trait', label: 'Upgrade Feature'", widths_js)
        self.assertIn("width: TABLE_WIDTHS.category", widths_js)
        self.assertIn("key: 'release_status', label: 'Known Release'", widths_js)
        self.assertIn("width: TABLE_WIDTHS.verdict", widths_js)
        self.assertIn("key: 'opportunity', label: 'Corpus Verdict'", widths_js)
        self.assertIn("key: 'coverage', label: 'Your Copies'", widths_js)
        self.assertIn("if (key === 'coverage') return localCopySummary(row).toLowerCase();", widths_js)
        self.assertIn("function localCopySummary(row)", widths_js)
        self.assertIn("function formatOpportunityDisplayLabel(opportunity)", widths_js)
        self.assertNotIn("immersiveAudio:", widths_js)
        self.assertNotIn("immersiveQuality:", widths_js)

    def test_normalize_lab_audio_repair_buttons_are_bound_to_mux_actions(self) -> None:
        self.assertIn("el.repairActionButton.addEventListener('click', () => {", NORMALIZE_LAB_JS)
        self.assertIn("const request = runSelectedRepairAction(action);", NORMALIZE_LAB_JS)
        self.assertIn("set_english_default_repair_subtitle_defaults", NORMALIZE_LAB_JS)
        self.assertIn("set_english_default_drop_foreign_repair_subtitle_defaults", NORMALIZE_LAB_JS)
        self.assertNotIn("repairDefaultsTab", NORMALIZE_LAB_JS)
        self.assertIn("Running English-default remux for ${paths.length} file", NORMALIZE_LAB_JS)
        self.assertIn("Running English-default remux and foreign-audio prune for ${paths.length} file", NORMALIZE_LAB_JS)
        self.assertIn("Running subtitle-default remux for ${paths.length} file", NORMALIZE_LAB_JS)
        self.assertIn("Running single-pass audio and subtitle remux for ${paths.length} file", NORMALIZE_LAB_JS)
        self.assertIn("Running single-pass audio, subtitle, and foreign-audio remux for ${paths.length} file", NORMALIZE_LAB_JS)
        self.assertIn("body: JSON.stringify({ source: el.sourcePath.value.trim(), paths, drop_foreign_audio: dropForeignAudio }),", NORMALIZE_LAB_JS)
        self.assertIn("await postFetch('/api/movies/repair-defaults/fix', {", NORMALIZE_LAB_JS)
        self.assertIn("if (actionTouchesSubtitle(action)) {", NORMALIZE_LAB_JS)
        self.assertIn("const applicableRows = selectedRepairRowsForAction(action);", NORMALIZE_LAB_JS)

    def test_immersive_rows_keep_normalization_tooltips_on_visible_text(self) -> None:
        widths_js = self.workbench_js_source()
        self.assertIn('const titleTooltip = needsNormalization ? \'File name needs normalization!\'', widths_js)
        self.assertIn('const yearTooltip = needsNormalization ? \'Year requires file normalization to display!\'', widths_js)
        self.assertIn('<span class="lab-cell-text" title="${escapeHtml(yearTooltip)}">', widths_js)
        self.assertIn('<span class="lab-cell-text" title="${escapeHtml(titleTooltip)}">', widths_js)
        self.assertIn('class="lab-format-parent-row"', widths_js)
        self.assertIn('class="lab-format-feature-row is-child-row"', widths_js)
        self.assertIn('class="lab-cell-foundation lab-cell-signal lab-cell-mono lab-format-child-spacer"', widths_js)
        self.assertNotIn('rowspan="${rowspan}"', widths_js)

    def test_combined_repair_action_uses_single_backend_remux_request(self) -> None:
        action_section = NORMALIZE_LAB_JS.split("async function runSelectedRepairAction(action) {", 1)[1].split("async function confirmSelected()", 1)[0]
        self.assertIn("if (actionTouchesAudio(action) && actionTouchesSubtitle(action)) {", action_section)
        self.assertIn("await runCombinedRepair(selectedPaths, action);", action_section)
        combined_branch = action_section.split("if (actionTouchesAudio(action) && actionTouchesSubtitle(action)) {", 1)[1].split("} else if (actionTouchesAudio(action)) {", 1)[0]
        self.assertNotIn("selectedSubtitleRowsFromPayload", combined_branch)

    def test_audit_labels_expand_multi_file_repair_rows(self) -> None:
        self.assertIn("if (subjects.length > 1) {", NORMALIZE_LAB_JS)
        self.assertIn("return `Movies · ${subjects.length} titles`;", NORMALIZE_LAB_JS)
        self.assertIn("const unit = lead.kind === 'remux_repair' ? 'file' : 'item';", NORMALIZE_LAB_JS)
        self.assertIn("return `${kind} · ${status} to ${effects.length} ${unit}${effects.length === 1 ? '' : 's'}`;", NORMALIZE_LAB_JS)
        self.assertIn("function auditRepairBreakdownRows(event) {", NORMALIZE_LAB_JS)
        self.assertIn("if (subjects.length <= 1 && familyLabels.length <= 1) return [];", NORMALIZE_LAB_JS)
        self.assertIn("function auditRepairBreakdownMarkup(event) {", NORMALIZE_LAB_JS)
        self.assertIn("function renderAuditRepairChildRows(event) {", NORMALIZE_LAB_JS)

    def test_audit_action_chips_and_outcomes_use_taxonomy_labels(self) -> None:
        self.assertIn("function auditActionChipMeta(event) {", NORMALIZE_LAB_JS)
        self.assertIn("return { label: 'System Boot', tone: 'is-audit-system-user' };", NORMALIZE_LAB_JS)
        self.assertIn("return { label: 'Remux Repair', tone: 'is-audit-media-repair' };", NORMALIZE_LAB_JS)
        self.assertIn("function auditOutcomeLabel(event) {", NORMALIZE_LAB_JS)
        self.assertIn("if (workflow === 'system' && action === 'start') return 'System booted';", NORMALIZE_LAB_JS)
        self.assertIn("if (action === 'scan') return 'Scan performed';", NORMALIZE_LAB_JS)

    def test_repair_preview_projects_planner_stages_with_explicit_states(self) -> None:
        # The preview is a projection of buildRepairPreviewModel; combined actions
        # resolve their subtitle stage through effectiveSubtitleStage, annotate the
        # second-order case, and surface unresolved stream lookups instead of
        # silently collapsing to a no-op.
        self.assertIn("audio/no change", NORMALIZE_LAB_JS)
        self.assertIn("subtitle/no change", NORMALIZE_LAB_JS)
        self.assertIn("function buildRepairPreviewModel(item, action)", NORMALIZE_LAB_JS)
        self.assertIn("function effectiveSubtitleStage(item, action)", NORMALIZE_LAB_JS)
        self.assertIn("function strictDefaultSubtitleStream(item)", NORMALIZE_LAB_JS)
        self.assertIn("const causal = stage.secondOrder ? ' — after audio flips to English' : '';", NORMALIZE_LAB_JS)
        self.assertIn("track could not be resolved", NORMALIZE_LAB_JS)
        self.assertIn("flags: { unresolved: true }", NORMALIZE_LAB_JS)
        self.assertIn("is-unresolved", NORMALIZE_LAB_JS)

    def test_normalize_lab_selection_refreshes_all_selection_dependent_controls(self) -> None:
        self.assertIn("function refreshSelectionState() {", NORMALIZE_LAB_JS)
        refresh_section = NORMALIZE_LAB_JS.split("function refreshSelectionState() {", 1)[1].split("function attachRowHandlers()", 1)[0]
        self.assertIn("renderSelectionButtons();", refresh_section)
        self.assertIn("renderConfirmButton();", refresh_section)
        self.assertIn("renderWorkflowActionControls();", refresh_section)
        self.assertIn("renderSidePanel();", refresh_section)

    def test_normalize_lab_row_checkbox_changes_use_shared_selection_refresh(self) -> None:
        checkbox_section = NORMALIZE_LAB_JS.split("el.rowsBody.querySelectorAll('input[data-row-check]').forEach(input => {", 1)[1].split("el.rowsBody.querySelectorAll('button[data-track-popover]')", 1)[0]
        self.assertIn("clearDeletePreviewState();", checkbox_section)
        self.assertIn("refreshSelectionState();", checkbox_section)
        self.assertNotIn("state.activeRowId = id;", checkbox_section)
        self.assertNotIn("clearDeletePreviewState();\n        renderSidePanel();", checkbox_section)

    def test_repair_defaults_rows_are_not_filtered_by_selected_action(self) -> None:
        active_rows_section = NORMALIZE_LAB_JS.split("function activeRows() {", 1)[1].split("function canonicalRows()", 1)[0]
        self.assertIn(".filter(item => !!movieAudioPackagingIssueCode(item) || movieSubtitleReadinessIsRepairable(item))", active_rows_section)
        self.assertNotIn(".filter(item => repairItemMatchesAction(item))", active_rows_section)

    def test_repair_action_change_preserves_selection_and_active_row(self) -> None:
        change_section = NORMALIZE_LAB_JS.split("el.repairActionSelect.addEventListener('change', () => {", 1)[1].split("el.repairActionButton.addEventListener('click', () => {", 1)[0]
        self.assertNotIn("state.selected = new Set();", change_section)
        self.assertNotIn("state.activeRowId = '';", change_section)
        self.assertIn("state.previewMode = 'selected';", change_section)

    def test_repair_defaults_exposes_partial_applicability_ui(self) -> None:
        self.assertIn("function selectedRepairApplicability(action = state.repairAction) {", NORMALIZE_LAB_JS)
        self.assertIn("function repairActionOptionLabel(action, selectedCount, applicableCount) {", NORMALIZE_LAB_JS)
        self.assertIn("No applicable rows.", NORMALIZE_LAB_JS)
        self.assertIn("selected, ${selection.applicableRows.length} applicable, ${selection.skippedRows.length} skipped", NORMALIZE_LAB_JS)
        self.assertIn("selection.selectedRows.length && !option.applicableCount ? 'disabled' : ''", NORMALIZE_LAB_JS)

    def test_default_subtitle_label_derives_from_actual_default_stream_flags(self) -> None:
        self.assertIn("function defaultSubtitleStreamsForItem(item)", NORMALIZE_LAB_JS)
        self.assertIn("const defaultStreams = defaultSubtitleStreamsForItem(item);", NORMALIZE_LAB_JS)
        self.assertIn("const defaultCount = defaultStreams.length;", NORMALIZE_LAB_JS)
        self.assertIn("const stream = defaultStreams[0] || null;", NORMALIZE_LAB_JS)

    def test_audio_popover_truncates_verbose_facts_within_bubble(self) -> None:
        self.assertIn("inline-size: min(480px, calc(100vw - 24px));", NORMALIZE_LAB_CSS)
        self.assertIn("grid-template-columns: minmax(7ch, 12ch) minmax(0, 1fr);", NORMALIZE_LAB_CSS)
        self.assertIn("text-overflow: ellipsis;", NORMALIZE_LAB_CSS)

    def test_track_popover_highlights_default_language_cell(self) -> None:
        self.assertIn("function popoverTrackLanguageMarkup(label, isDefault = false) {", NORMALIZE_LAB_JS)
        self.assertIn('lab-audio-popover-lang${isDefault ? \' is-default\' : \'\'}', NORMALIZE_LAB_JS)
        self.assertIn("${popoverTrackLanguageMarkup(describeSubtitleStream(track), !!track.is_default)}", NORMALIZE_LAB_JS)
        self.assertIn("${popoverTrackLanguageMarkup(displayAudioLanguage(track.language), isEffectiveDefaultAudioTrack(track, row))}", NORMALIZE_LAB_JS)
        self.assertIn(".lab-audio-popover-lang.is-default {", NORMALIZE_LAB_CSS)

    def test_audio_popover_marks_only_effective_default_track(self) -> None:
        self.assertIn("function isEffectiveDefaultAudioTrack(track, row) {", NORMALIZE_LAB_JS)
        self.assertIn("return sameTrack(track, movieDefaultAudioStream(row?.item));", NORMALIZE_LAB_JS)
        self.assertNotIn("track.is_default ? '<span class=\"lab-audio-popover-default\">default</span>' : ''", NORMALIZE_LAB_JS)

    def test_simple_selection_rows_render_selected_state_separately_from_active_cursor(self) -> None:
        self.assertIn("function simpleSelectionRowClass(rowId) {", NORMALIZE_LAB_JS)
        self.assertIn("if (state.selected.has(rowId)) classes.push('is-selected');", NORMALIZE_LAB_JS)
        self.assertIn("tbody tr.is-selected td { background: rgba(68, 97, 140, 0.12); }", NORMALIZE_LAB_CSS)
        self.assertIn('class="${escapeHtml(simpleSelectionRowClass(row.row_id))}"', NORMALIZE_LAB_JS)
        self.assertIn('class="lab-cell-foundation lab-cell-select"', NORMALIZE_LAB_JS)

    def test_safe_repair_lock_overlay_leaves_preview_page_open_while_blocking_rest_of_shell(self) -> None:
        self.assertIn('id="repairLockOverlay"', NORMALIZE_LAB_TEMPLATE)
        self.assertIn("previewPage: document.querySelector('.lab-page-preview')", NORMALIZE_LAB_JS)
        self.assertIn("repairLockOverlay: document.getElementById('repairLockOverlay')", NORMALIZE_LAB_JS)
        self.assertIn("function updateRepairLockOverlay() {", NORMALIZE_LAB_JS)
        self.assertIn("closeTrackPopover();", NORMALIZE_LAB_JS)
        self.assertIn("el.repairLockOverlay.style.setProperty('--lock-top',", NORMALIZE_LAB_JS)
        self.assertIn(".lab-repair-lock-overlay {", NORMALIZE_LAB_CSS)
        self.assertIn(".lab-repair-lock-block-top {", NORMALIZE_LAB_CSS)
        self.assertIn(".lab-repair-lock-port-frame {", NORMALIZE_LAB_CSS)

    def test_combined_repair_action_requires_audio_anchor_not_any_family_overlap(self) -> None:
        self.assertIn("function rowSupportsCombinedRepairAction(row) {", NORMALIZE_LAB_JS)
        self.assertIn("return rowSupportsAudioAction(row) && (rowSupportsSubtitleAction(row) || combinedSubtitleWillRun(row?.item));", NORMALIZE_LAB_JS)
        repair_match_section = NORMALIZE_LAB_JS.split("function repairRowMatchesAction(row, action = state.repairAction) {", 1)[1].split("function issueFamilyLabel(families) {", 1)[0]
        self.assertIn("if (actionTouchesAudio(action) && actionTouchesSubtitle(action)) {", repair_match_section)
        self.assertIn("return rowSupportsCombinedRepairAction(row);", repair_match_section)
        self.assertNotIn("repairActionConfig(action).families.some", repair_match_section)

    def test_audio_packaging_fix_route_forwards_drop_foreign_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "movies"
            source.mkdir()
            fixed_result = {"fixed": [], "skipped": []}
            with patch("normal.web.routes_cleanup.fix_english_audio_defaults", return_value=fixed_result) as fix_audio:
                with patch("normal.web.routes_cleanup.build_updated_profile_items", return_value=[]):
                    with self.run_test_server() as base_url:
                        body = json.dumps(
                            {
                                "source": str(source),
                                "paths": [str(source / "Movie.mkv")],
                                "drop_foreign_audio": True,
                            }
                        ).encode("utf-8")
                        req = urllib.request.Request(
                            f"{base_url}/api/movies/audio-packaging/fix",
                            data=body,
                            headers={"Content-Type": "application/json", "X-Normal-Token": MUTATION_TOKEN},
                            method="POST",
                        )
                        with urllib.request.urlopen(req) as response:
                            payload = json.loads(response.read().decode("utf-8"))
        self.assertEqual(payload["fixed"], [])
        self.assertTrue(fix_audio.call_args.kwargs["drop_foreign_audio"])
        self.assertNotIn("replacement_queue", payload)

    def test_repair_defaults_fix_route_forwards_combined_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "movies"
            source.mkdir()
            fixed_result = {"fixed": [], "skipped": []}
            with patch("normal.web.routes_cleanup.fix_movie_repair_defaults", return_value=fixed_result) as fix_repair:
                with patch("normal.web.routes_cleanup.build_updated_profile_items", return_value=[]):
                    with self.run_test_server() as base_url:
                        body = json.dumps(
                            {
                                "source": str(source),
                                "paths": [str(source / "Movie.mkv")],
                                "include_audio": True,
                                "include_subtitle": True,
                                "drop_foreign_audio": True,
                            }
                        ).encode("utf-8")
                        req = urllib.request.Request(
                            f"{base_url}/api/movies/repair-defaults/fix",
                            data=body,
                            headers={"Content-Type": "application/json", "X-Normal-Token": MUTATION_TOKEN},
                            method="POST",
                        )
                        with urllib.request.urlopen(req) as response:
                            payload = json.loads(response.read().decode("utf-8"))
        self.assertEqual(payload["fixed"], [])
        self.assertTrue(fix_repair.call_args.kwargs["include_audio"])
        self.assertTrue(fix_repair.call_args.kwargs["include_subtitle"])
        self.assertTrue(fix_repair.call_args.kwargs["drop_foreign_audio"])

    def test_movies_delete_preview_route(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "movies"
            movie = source / "Bad Movie (2001)" / "Bad Movie (2001).mkv"
            poster = movie.parent / "poster.jpg"
            movie.parent.mkdir(parents=True)
            movie.write_text("video", encoding="utf-8")
            poster.write_text("poster", encoding="utf-8")
            with self.run_test_server() as base_url:
                body = json.dumps({"source": str(source), "paths": [str(movie)]}).encode("utf-8")
                req = urllib.request.Request(
                    f"{base_url}/api/movies/delete-preview",
                    data=body,
                    headers={"Content-Type": "application/json", "X-Normal-Token": MUTATION_TOKEN},
                    method="POST",
                )
                with urllib.request.urlopen(req) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                self.assertEqual(payload["deleted"], [str(movie.resolve())])
                self.assertEqual(payload["cleaned_sidecars"], [str(poster.resolve())])
                self.assertEqual(payload["removed_folders"], [str(movie.parent.resolve())])
                self.assertTrue(movie.exists())

    def test_removed_queue_and_history_routes_return_404(self) -> None:
        with self.run_test_server() as base_url:
            for route in (
                "/api/movies/replacement-queue/list",
                "/api/movies/replacement-queue/add",
                "/api/movies/replacement-queue/delete",
                "/api/movies/replacement-queue/delete-preview",
                "/api/movies/replacement-queue/dismiss",
                "/api/movies/subtitle-readiness/history",
                "/api/movies/subtitle-readiness/history/sync",
                "/api/movies/subtitle-readiness/history/dismiss",
            ):
                req = urllib.request.Request(
                    f"{base_url}{route}",
                    data=b"{}",
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(req)
                self.assertEqual(ctx.exception.code, 404)

    def test_delete_movie_junk_files_only_deletes_current_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            sample = source / "Movie.2000" / "Extras" / "Behind.The.Scenes.mp4"
            second_sample = source / "Movie.2000" / "Movie.sample.mp4"
            promo_document = source / "Movie.2000" / "RARBG.txt"
            movie = source / "Movie.2000" / "Movie.2000.mkv"
            large_false_positive = source / "Movie.2000" / "Featurettes" / "Feature.mkv"
            sample.parent.mkdir(parents=True)
            large_false_positive.parent.mkdir(parents=True, exist_ok=True)
            sample.write_text("sample", encoding="utf-8")
            second_sample.write_text("sample", encoding="utf-8")
            promo_document.write_text("Downloaded from RARBG", encoding="utf-8")
            with movie.open("wb") as handle:
                handle.truncate(101 * 1024 * 1024)
            with large_false_positive.open("wb") as handle:
                handle.truncate(4 * 1024 * 1024 * 1024)

            result = delete_movie_junk_files(source, [sample, second_sample, promo_document, movie, large_false_positive])

            self.assertEqual(
                result["deleted"],
                [str(sample.resolve()), str(second_sample.resolve()), str(promo_document.resolve())],
            )
            self.assertFalse(sample.exists())
            self.assertFalse(second_sample.exists())
            self.assertFalse(promo_document.exists())
            self.assertTrue(movie.exists())
            self.assertTrue(large_false_positive.exists())
            self.assertEqual(
                result["skipped"],
                [
                    {"path": str(movie.resolve()), "reason": "not_current_junk_candidate"},
                    {"path": str(large_false_positive.resolve()), "reason": "not_current_junk_candidate"},
                ],
            )

    def test_delete_movie_junk_files_rejects_symlink_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            target = source / "Movie.sample.mp4"
            target.write_text("sample", encoding="utf-8")
            link = source / "Linked.sample.mp4"
            link.symlink_to(target)

            with self.assertRaisesRegex(RuntimeError, "symlink or reparse point"):
                delete_movie_junk_files(source, [link])

            self.assertTrue(link.is_symlink())
            self.assertTrue(target.exists())


class WebPostSecurityTests(unittest.TestCase):
    @contextmanager
    def run_test_server(self, **handler_kwargs):
        handler_kwargs.setdefault("approved_roots", ApprovedRoots.from_paths([Path(tempfile.gettempdir())]))
        server = ThreadingHTTPServer(("127.0.0.1", 0), build_handler(**handler_kwargs))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_address[1]}"
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def post(self, base_url, path, *, headers=None, data=b"{}"):
        req = urllib.request.Request(f"{base_url}{path}", data=data, headers=headers or {}, method="POST")
        return urllib.request.urlopen(req)

    def valid_headers(self):
        from normal.web.security import MUTATION_TOKEN

        return {"Content-Type": "application/json", "X-Normal-Token": MUTATION_TOKEN}

    def scan_warning_body(self, tmpdir):
        return json.dumps({"source": tmpdir}).encode("utf-8")

    def test_workbench_exposes_mutation_token(self) -> None:
        from normal.web.security import MUTATION_TOKEN

        html = render_workbench_html(Path("/library/movies"))
        self.assertIn(f'"token": "{MUTATION_TOKEN}"', html)
        self.assertIn('<script type="application/json" id="normal-boot">', html)

    def test_valid_token_and_json_passes_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.run_test_server() as base_url:
                with self.post(
                    base_url,
                    "/api/source/scan-warning",
                    headers=self.valid_headers(),
                    data=self.scan_warning_body(tmpdir),
                ) as response:
                    self.assertEqual(response.status, 200)

    def test_post_route_ignores_query_string(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.run_test_server() as base_url:
                with self.post(
                    base_url,
                    "/api/source/scan-warning?probe=1",
                    headers=self.valid_headers(),
                    data=self.scan_warning_body(tmpdir),
                ) as response:
                    self.assertEqual(response.status, 200)

    def test_missing_token_is_rejected_before_handler_runs(self) -> None:
        with patch("normal.web.server.handle_source_scan_warning") as spy:
            with self.run_test_server() as base_url:
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    self.post(
                        base_url,
                        "/api/source/scan-warning",
                        headers={"Content-Type": "application/json"},
                    )
        self.assertEqual(ctx.exception.code, 403)
        spy.assert_not_called()

    def test_bad_token_is_rejected(self) -> None:
        headers = self.valid_headers()
        headers["X-Normal-Token"] = "wrong"
        with self.run_test_server() as base_url:
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                self.post(base_url, "/api/source/scan-warning", headers=headers)
        self.assertEqual(ctx.exception.code, 403)

    def test_json_content_type_with_charset_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            headers = self.valid_headers()
            headers["Content-Type"] = "application/json; charset=utf-8"
            with self.run_test_server() as base_url:
                with self.post(
                    base_url,
                    "/api/source/scan-warning",
                    headers=headers,
                    data=self.scan_warning_body(tmpdir),
                ) as response:
                    self.assertEqual(response.status, 200)

    def test_non_json_content_type_is_rejected(self) -> None:
        headers = self.valid_headers()
        headers["Content-Type"] = "text/plain"
        with self.run_test_server() as base_url:
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                self.post(base_url, "/api/source/scan-warning", headers=headers)
        self.assertEqual(ctx.exception.code, 415)

    def test_cross_origin_is_rejected(self) -> None:
        headers = self.valid_headers()
        headers["Origin"] = "http://evil.example.com"
        with self.run_test_server() as base_url:
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                self.post(base_url, "/api/source/scan-warning", headers=headers)
        self.assertEqual(ctx.exception.code, 403)

    def test_foreign_host_requires_explicit_remote_host_allowlist(self) -> None:
        headers = self.valid_headers()
        headers["Host"] = "evil.example.com"
        with self.run_test_server() as base_url:
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                self.post(base_url, "/api/source/scan-warning", headers=headers)
        self.assertEqual(ctx.exception.code, 403)
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.run_test_server(
                allowed_hosts=parse_allowed_hosts(["evil.example.com"]),
            ) as base_url:
                port = urllib.parse.urlsplit(base_url).port
                with self.post(
                    base_url,
                    "/api/source/scan-warning",
                    headers={
                        **headers,
                        "Host": f"evil.example.com:{port}",
                        "Origin": f"http://evil.example.com:{port}",
                    },
                    data=self.scan_warning_body(tmpdir),
                ) as response:
                    self.assertEqual(response.status, 200)

    def test_origin_with_wrong_port_is_rejected(self) -> None:
        headers = self.valid_headers()
        headers["Origin"] = "http://127.0.0.1:9999"
        with self.run_test_server() as base_url:
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                self.post(base_url, "/api/source/scan-warning", headers=headers)
        self.assertEqual(ctx.exception.code, 403)

    def test_origin_with_wrong_scheme_is_rejected(self) -> None:
        headers = self.valid_headers()
        headers["Origin"] = "https://127.0.0.1:8765"
        with self.run_test_server() as base_url:
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                self.post(base_url, "/api/source/scan-warning", headers=headers)
        self.assertEqual(ctx.exception.code, 403)

    def test_host_with_wrong_port_is_rejected(self) -> None:
        headers = self.valid_headers()
        headers["Host"] = "127.0.0.1:9999"
        with self.run_test_server() as base_url:
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                self.post(base_url, "/api/source/scan-warning", headers=headers)
        self.assertEqual(ctx.exception.code, 403)

    def test_malformed_content_length_is_rejected_without_traceback(self) -> None:
        headers = self.valid_headers()
        headers["Content-Length"] = "not-a-number"
        with self.run_test_server() as base_url:
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                self.post(base_url, "/api/source/scan-warning", headers=headers)
        self.assertEqual(ctx.exception.code, 400)

    def test_oversized_body_is_rejected(self) -> None:
        from normal.web.security import MAX_JSON_BODY

        headers = self.valid_headers()
        headers["Content-Length"] = str(MAX_JSON_BODY + 1)
        with self.run_test_server() as base_url:
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                self.post(base_url, "/api/source/scan-warning", headers=headers)
        self.assertEqual(ctx.exception.code, 413)

    def test_token_is_checked_before_size(self) -> None:
        from normal.web.security import MAX_JSON_BODY

        with self.run_test_server() as base_url:
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                self.post(
                    base_url,
                    "/api/source/scan-warning",
                    headers={"Content-Type": "application/json", "Content-Length": str(MAX_JSON_BODY + 1)},
                )
        self.assertEqual(ctx.exception.code, 403)


class WebGetSecurityTests(unittest.TestCase):
    @contextmanager
    def run_test_server(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), build_handler())
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_address[1]}"
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_sensitive_get_routes_require_token(self) -> None:
        for path in ("/api/activity", "/api/library-roots", "/api/audit/stream"):
            with self.subTest(path=path), self.run_test_server() as base_url:
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(f"{base_url}{path}")
                self.assertEqual(ctx.exception.code, HTTPStatus.FORBIDDEN)

    def test_json_get_accepts_header_token(self) -> None:
        with self.run_test_server() as base_url:
            request = urllib.request.Request(
                f"{base_url}/api/library-roots",
                headers={"X-Normal-Token": MUTATION_TOKEN},
            )
            with urllib.request.urlopen(request) as response:
                self.assertEqual(response.status, HTTPStatus.OK)

    def test_static_and_index_remain_unauthenticated(self) -> None:
        with self.run_test_server() as base_url:
            for path in ("/", "/assets/workbench.js"):
                with self.subTest(path=path), urllib.request.urlopen(f"{base_url}{path}") as response:
                    self.assertEqual(response.status, HTTPStatus.OK)


class WebPostGateTests(unittest.TestCase):
    def handler(self, **headers):
        defaults = {
            "X-Normal-Token": MUTATION_TOKEN,
            "Content-Type": "application/json",
            "Host": "127.0.0.1:8765",
            "Content-Length": "0",
        }
        defaults.update(headers)
        return types.SimpleNamespace(headers=defaults)

    def test_ipv6_loopback_host_with_exact_port_is_allowed(self) -> None:
        check_post(
            self.handler(Host="[::1]:8765"),
            bound_port=8765,
            allowed_hosts=frozenset(),
        )

    def test_ipv6_loopback_origin_with_exact_port_is_allowed(self) -> None:
        check_post(
            self.handler(Host="[::1]:8765", Origin="http://[::1]:8765"),
            bound_port=8765,
            allowed_hosts=frozenset(),
        )

    def test_origin_scheme_must_match_http_server(self) -> None:
        with self.assertRaises(PostRejected):
            check_post(
                self.handler(Origin="https://127.0.0.1:8765"),
                bound_port=8765,
                allowed_hosts=frozenset(),
            )

    def test_remote_host_and_matching_origin_are_allowed(self) -> None:
        check_post(
            self.handler(
                Host="normal.local:8765",
                Origin="http://normal.local:8765",
            ),
            bound_port=8765,
            allowed_hosts=parse_allowed_hosts(["normal.local"]),
        )

    def test_origin_must_match_request_host(self) -> None:
        with self.assertRaises(PostRejected):
            check_post(
                self.handler(
                    Host="normal.local:8765",
                    Origin="http://192.168.1.50:8765",
                ),
                bound_port=8765,
                allowed_hosts=parse_allowed_hosts(["normal.local", "192.168.1.50"]),
            )

    def test_localhost_with_wrong_port_is_rejected(self) -> None:
        with self.assertRaises(PostRejected):
            check_post(
                self.handler(Host="localhost:9999"),
                bound_port=8765,
                allowed_hosts=frozenset(),
            )

    def test_malformed_host_and_origin_authorities_are_rejected(self) -> None:
        for host in ("localhost:not-a-port", "user@localhost:8765", "localhost:8765/path"):
            with self.assertRaises(PostRejected):
                check_post(
                    self.handler(Host=host),
                    bound_port=8765,
                    allowed_hosts=frozenset(),
                )
        for origin in (
            "http://localhost:not-a-port",
            "http://user@localhost:8765",
            "http://localhost:8765/path",
        ):
            with self.assertRaises(PostRejected):
                check_post(
                    self.handler(Origin=origin),
                    bound_port=8765,
                    allowed_hosts=frozenset(),
                )

    def test_negative_content_length_is_rejected(self) -> None:
        with self.assertRaises(PostRejected) as ctx:
            check_post(
                self.handler(**{"Content-Length": "-1"}),
                bound_port=8765,
                allowed_hosts=frozenset(),
            )
        self.assertEqual(ctx.exception.status, HTTPStatus.BAD_REQUEST)

    def test_malformed_content_length_is_rejected(self) -> None:
        with self.assertRaises(PostRejected) as ctx:
            check_post(
                self.handler(**{"Content-Length": "not-a-number"}),
                bound_port=8765,
                allowed_hosts=frozenset(),
            )
        self.assertEqual(ctx.exception.status, HTTPStatus.BAD_REQUEST)

    def test_validated_content_length_is_returned_for_the_body_read(self) -> None:
        self.assertEqual(
            check_post(
                self.handler(**{"Content-Length": "123"}),
                bound_port=8765,
                allowed_hosts=frozenset(),
            ),
            123,
        )

    def test_missing_content_length_is_rejected(self) -> None:
        handler = self.handler()
        del handler.headers["Content-Length"]
        with self.assertRaises(PostRejected) as ctx:
            check_post(handler, bound_port=8765, allowed_hosts=frozenset())
        self.assertEqual(ctx.exception.status, HTTPStatus.LENGTH_REQUIRED)

    def test_chunked_body_is_rejected(self) -> None:
        with self.assertRaises(PostRejected) as ctx:
            check_post(
                self.handler(**{"Transfer-Encoding": "chunked"}),
                bound_port=8765,
                allowed_hosts=frozenset(),
            )
        self.assertEqual(ctx.exception.status, HTTPStatus.BAD_REQUEST)

    def test_too_large_content_length_is_rejected(self) -> None:
        with self.assertRaises(PostRejected) as ctx:
            check_post(
                self.handler(**{"Content-Length": str(MAX_JSON_BODY + 1)}),
                bound_port=8765,
                allowed_hosts=frozenset(),
            )
        self.assertEqual(ctx.exception.status, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)

    def test_unspecified_bind_address_is_not_an_allowed_host(self) -> None:
        with self.assertRaises(ValueError):
            parse_allowed_hosts(["0.0.0.0"])


class WebApprovedRootTests(unittest.TestCase):
    @contextmanager
    def run_test_server(self, **handler_kwargs):
        server = ThreadingHTTPServer(("127.0.0.1", 0), build_handler(**handler_kwargs))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_address[1]}"
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def post(self, base_url, path, body):
        headers = {"Content-Type": "application/json", "X-Normal-Token": MUTATION_TOKEN}
        req = urllib.request.Request(f"{base_url}{path}", data=body, headers=headers, method="POST")
        return urllib.request.urlopen(req)

    def test_mutating_route_with_unapproved_source_is_rejected_and_deletes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "Movies"
            source.mkdir()
            movie = source / "Movie (2020).mkv"
            movie.write_text("data", encoding="utf-8")
            approved = Path(tmpdir) / "Approved"
            approved.mkdir()
            body = json.dumps({"source": str(source), "paths": [str(movie)]}).encode("utf-8")
            with self.run_test_server(approved_roots=ApprovedRoots.from_paths([approved])) as base_url:
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    self.post(base_url, "/api/movies/delete", body)
            self.assertEqual(ctx.exception.code, 400)
            self.assertIn("not under an approved root", ctx.exception.read().decode("utf-8"))
            self.assertTrue(movie.exists())

    def test_source_operating_routes_reject_unapproved_source_before_work(self) -> None:
        routes = {
            "/api/source/scan-warning": {},
            "/api/movies/apply": {"change_ids": []},
            "/api/tv/apply": {"change_ids": []},
            "/api/movies/delete": {"paths": []},
            "/api/movies/junk/delete": {"paths": []},
            "/api/movies/audio-packaging/fix": {"paths": []},
            "/api/movies/subtitle-readiness/fix": {"paths": []},
            "/api/movies/repair-defaults/fix": {
                "paths": [],
                "include_audio": True,
                "include_subtitle": False,
            },
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "Movies"
            source.mkdir()
            approved = Path(tmpdir) / "Approved"
            approved.mkdir()
            with self.run_test_server(approved_roots=ApprovedRoots.from_paths([approved])) as base_url:
                for route, extra_payload in routes.items():
                    with self.subTest(route=route):
                        body = json.dumps({"source": str(source), **extra_payload}).encode("utf-8")
                        with self.assertRaises(urllib.error.HTTPError) as ctx:
                            self.post(base_url, route, body)
                        self.assertEqual(ctx.exception.code, 400)
                        error = ctx.exception.read().decode("utf-8")
                        self.assertIn("not under an approved root", error)
                        self.assertIn("normal web --allow-root", error)

    def test_recursive_routes_reject_drive_root_sources(self) -> None:
        routes = (
            "/api/movies/normalize",
            "/api/tv/normalize",
            "/api/movies/junk",
            "/api/movies/profile",
            "/api/movies/canonical-lists",
            "/api/movies/register",
        )
        body = json.dumps({"source": "/"}).encode("utf-8")
        with self.run_test_server(approved_roots=ApprovedRoots.from_paths([Path("/")])) as base_url:
            for route in routes:
                with self.subTest(route=route):
                    with self.assertRaises(urllib.error.HTTPError) as ctx:
                        self.post(base_url, route, body)
                    self.assertEqual(ctx.exception.code, 400)
                    self.assertIn("drive_directory", ctx.exception.read().decode("utf-8"))

    def test_scan_warning_rejects_unapproved_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "Movies"
            source.mkdir()
            warn_body = json.dumps({"source": str(source)}).encode("utf-8")
            with self.run_test_server(approved_roots=ApprovedRoots.from_paths([])) as base_url:
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    self.post(base_url, "/api/source/scan-warning", warn_body)
            self.assertEqual(ctx.exception.code, 400)
            self.assertIn("not under an approved root", ctx.exception.read().decode("utf-8"))

    def test_library_roots_only_persist_approved_operation_safe_paths(self) -> None:
        from normal.web import routes_core

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            approved = root / "Movies"
            approved.mkdir()
            storage = root / "library-roots.json"
            body = json.dumps(
                {
                    "movies": str(approved),
                    "recent": [{"lane": "movies", "source": str(approved)}],
                }
            ).encode("utf-8")
            with patch("normal.web.routes_core.library_roots_path", return_value=storage):
                with self.run_test_server(approved_roots=ApprovedRoots.from_paths([approved])) as base_url:
                    with self.post(base_url, "/api/library-roots", body) as response:
                        payload = json.loads(response.read().decode("utf-8"))
                reloaded = routes_core.load_library_roots(ApprovedRoots.from_paths([approved]))

            self.assertEqual(payload["movies"], str(approved.resolve()))
            self.assertEqual(payload["recent"][0]["source"], str(approved.resolve()))
            self.assertEqual(reloaded, payload)

    def test_library_roots_reject_unapproved_path_without_overwriting_saved_roots(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            approved = root / "Approved"
            unapproved = root / "Other"
            approved.mkdir()
            unapproved.mkdir()
            storage = root / "library-roots.json"
            saved = {"movies": str(approved), "recent": []}
            storage.write_text(json.dumps(saved), encoding="utf-8")
            body = json.dumps({"movies": str(unapproved), "recent": []}).encode("utf-8")

            with patch("normal.web.routes_core.library_roots_path", return_value=storage):
                with self.run_test_server(approved_roots=ApprovedRoots.from_paths([approved])) as base_url:
                    with self.assertRaises(urllib.error.HTTPError) as ctx:
                        self.post(base_url, "/api/library-roots", body)

            self.assertEqual(ctx.exception.code, 400)
            self.assertIn("not under an approved root", ctx.exception.read().decode("utf-8"))
            self.assertEqual(json.loads(storage.read_text(encoding="utf-8")), saved)

    def test_library_roots_get_hides_legacy_unapproved_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            approved = root / "Approved"
            unapproved = root / "Other"
            approved.mkdir()
            unapproved.mkdir()
            storage = root / "library-roots.json"
            storage.write_text(
                json.dumps(
                    {
                        "movies": str(unapproved),
                        "recent": [
                            {"lane": "movies", "source": str(unapproved)},
                            {"lane": "movies", "source": str(approved)},
                        ],
                    }
                ),
                encoding="utf-8",
            )

            with patch("normal.web.routes_core.library_roots_path", return_value=storage):
                with self.run_test_server(approved_roots=ApprovedRoots.from_paths([approved])) as base_url:
                    request = urllib.request.Request(
                        f"{base_url}/api/library-roots",
                        headers={"X-Normal-Token": MUTATION_TOKEN},
                    )
                    with urllib.request.urlopen(request) as response:
                        payload = json.loads(response.read().decode("utf-8"))

            self.assertEqual(payload["movies"], "")
            self.assertEqual(payload["recent"], [{"lane": "movies", "source": str(approved.resolve())}])

    def test_source_under_approved_root_passes_at_route_level(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "Library"
            child = root / "Movies"
            child.mkdir(parents=True)
            with self.run_test_server(approved_roots=ApprovedRoots.from_paths([root])) as base_url:
                url = f"{base_url}/api/audit/stream?source={quote(str(child))}&token={quote(MUTATION_TOKEN)}"
                with urllib.request.urlopen(url, timeout=2) as response:
                    self.assertEqual(response.headers.get("Content-Type"), "text/event-stream; charset=utf-8")

    def test_run_web_seeds_approved_roots_from_source_and_allow_root(self) -> None:
        from normal import commands

        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "Movies"
            source.mkdir()
            extra = Path(tmpdir) / "Archive"
            extra.mkdir()
            captured: dict = {}
            with patch("normal.commands.serve_web_ui", lambda **kwargs: captured.update(kwargs)):
                commands.run_web(host="127.0.0.1", port=0, source=source, allow_roots=[extra])
            roots = captured["approved_roots"].roots
            self.assertIn(source.resolve(), roots)
            self.assertIn(extra.resolve(), roots)

    def test_run_web_requires_allowed_host_for_unspecified_bind(self) -> None:
        from normal import commands

        with self.assertRaisesRegex(ValueError, "requires at least one --allowed-host"):
            commands.run_web(
                host="0.0.0.0",
                port=0,
            )
        with patch("normal.commands.serve_web_ui") as serve:
            commands.run_web(
                host="0.0.0.0",
                port=0,
                allowed_hosts=["192.168.1.50", "normal.local"],
            )
        self.assertEqual(
            serve.call_args.kwargs["allowed_hosts"],
            frozenset({"192.168.1.50", "normal.local"}),
        )


if __name__ == "__main__":
    unittest.main()
