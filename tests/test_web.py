from __future__ import annotations

import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
from unittest.mock import patch

from normal.web import (
    build_handler,
    delete_movie_junk_files,
    read_web_asset_text,
    render_workbench_html,
)
from normal.web.routes_cleanup import delete_mode_for_kind


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

    def test_scan_warning_is_wired(self) -> None:
        self.assertIn("const params = new URLSearchParams(window.location.search);", FRONTEND)
        self.assertIn("url.searchParams.set('workflow', state.workflow);", FRONTEND)
        self.assertIn("workflow === 'canonical-lists'", FRONTEND)

    def test_workbench_runtime_keys_are_available_before_initial_render(self) -> None:
        html = render_workbench_html(Path("/library/movies"), omdb_key="omdb-test", tmdb_key="tmdb-test")
        self.assertIn('<link rel="stylesheet" href="/assets/workbench.css?v=', html)
        self.assertIn('<script src="/assets/workbench.js?v=', html)
        self.assertLess(html.index("window.OMDB_AVAILABLE"), html.index('<script src="/assets/workbench.js?v='))
        self.assertIn('window.DEFAULT_SOURCE = "/library/movies";', html)
        self.assertIn("window.OMDB_AVAILABLE = true;", html)
        self.assertNotIn("omdb-test", html)
        self.assertIn('window.TMDB_KEY = "tmdb-test";', html)

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

    def test_root_route_serves_default_workbench(self) -> None:
        with self.run_test_server() as base_url:
            with urllib.request.urlopen(base_url) as response:
                served = response.read().decode("utf-8")
            with urllib.request.urlopen(f"{base_url}/index.html") as response:
                served_index = response.read().decode("utf-8")
        self.assertIn("normal workbench", served)
        self.assertIn("/assets/workbench.js?v=", served)
        self.assertIn("Movie Normalize", served)
        self.assertEqual(served, served_index)

    def test_rendered_workbench_includes_current_shell_contract(self) -> None:
        html = render_workbench_html(Path("/library/movies"))
        self.assertIn('/assets/workbench.css?v=', html)
        self.assertIn('/assets/workbench.js?v=', html)
        self.assertIn('window.DEFAULT_SOURCE = "/library/movies";', html)
        self.assertIn('id="policyToggle"', html)
        self.assertIn('id="placeholderToggle"', html)
        self.assertIn('id="placeholderDownloadToggle"', html)
        self.assertIn('id="policyRail"', html)
        self.assertIn('id="policyEditorPanel"', html)
        self.assertIn('id="inspectionPane"', html)
        self.assertNotIn('Repair Lane', html)
        self.assertIn('data-layout-mode="2-page-lopsided"', html)
        self.assertIn('data-page-role="scan"', html)
        self.assertIn('data-page-role="preview"', html)
        self.assertIn('data-collapse-mode="reflow"', html)
        self.assertIn('data-collapse-mode="anchored-slot"', html)

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

    def test_run_button_becomes_stop_while_scan_runs(self) -> None:
        self.assertIn("state.runInFlight ? 'Running' :", FRONTEND)
        self.assertIn("'Run Normalize'", FRONTEND)
        self.assertIn("'Run Repair Defaults'", FRONTEND)
        self.assertIn("'Run Canonical Lists'", FRONTEND)
        self.assertNotIn("runButton.textContent = running ? 'Stop' : 'Run';", FRONTEND)

    def test_drive_activity_indicator_is_wired(self) -> None:
        self.assertNotIn("id=\"activityBar\"", FRONTEND)
        self.assertNotIn("function refreshActivityState", FRONTEND)
        self.assertNotIn("Drive activity: idle", FRONTEND)

    def test_movie_junk_page_is_wired(self) -> None:
        self.assertIn("workflowJunk", FRONTEND)
        self.assertIn("postJson('/api/movies/junk'", FRONTEND)
        self.assertIn("'/api/movies/junk/delete'", FRONTEND)
        self.assertIn("state.junkPayload = payload;", FRONTEND)
        self.assertIn("clearDeletePreviewState();", FRONTEND)
        self.assertIn("Run Delete Junk & Spam Files", FRONTEND)
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
                    headers={"Content-Type": "application/json"},
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
        self.assertIn("selectedRepairAudioPaths()", FRONTEND)
        self.assertIn("'/api/movies/delete'", FRONTEND)
        self.assertIn("button:disabled {", APP_CSS)

    def test_movie_audio_packaging_page_is_wired(self) -> None:
        self.assertIn("'repair-defaults': 'Repair Defaults'", FRONTEND)
        self.assertIn("audioFixBusy: false", FRONTEND)
        self.assertIn("wrong language · weak English", FRONTEND)
        self.assertIn("'/api/movies/audio-packaging/fix'", FRONTEND)
        self.assertIn("'/api/movies/delete'", FRONTEND)
        self.assertIn("Make Best English Audio Default", FRONTEND)
        self.assertIn("Make Best English Audio Default + Remove Foreign Audio", FRONTEND)
        self.assertIn("state.audioFixBusy = true;", FRONTEND)
        self.assertIn("state.audioFixBusy = false;", FRONTEND)
        self.assertIn("drop_foreign_audio: dropForeignAudio", FRONTEND)
        self.assertIn("selectedRepairAudioPaths()", FRONTEND)
        self.assertIn("Running English-default remux", FRONTEND)
        self.assertIn("function actualResolutionLabel(item)", FRONTEND)
        self.assertIn("label: 'Audio', columnClass: 'lab-col-signal', cellClass: 'lab-cell-signal lab-cell-mono', priority: 'medium', width: '11ch' }", FRONTEND)
        self.assertIn("label: 'Default Subtitle', columnClass: 'lab-col-resolution', cellClass: 'lab-cell-supporting', priority: 'desktop', width: '13ch' }", FRONTEND)
        self.assertIn("label: 'Issue', columnClass: 'lab-col-issue', cellClass: 'lab-cell-decision', priority: 'essential', width: '13%' }", FRONTEND)
        self.assertIn("label: 'Current Default', columnClass: 'lab-col-resolution', cellClass: 'lab-cell-supporting', priority: 'medium', width: '15%' }", FRONTEND)
        self.assertIn("label: 'Repair Target', columnClass: 'lab-col-resolution', cellClass: 'lab-cell-supporting', priority: 'desktop', width: '17%' }", FRONTEND)
        self.assertIn("label: 'Resolution', columnClass: 'lab-col-signal', cellClass: 'lab-cell-signal lab-cell-mono', priority: 'medium', width: '16ch' }", FRONTEND)
        self.assertNotIn("audio: ${describeAudioStream(movieDefaultAudioStream(item))}", FRONTEND)
        self.assertNotIn("audio: ${describeAudioStream(movieBestEnglishAudioStream(item))}", FRONTEND)
        self.assertIn("function repairDefaultSubtitleLabel(item)", FRONTEND)

    def test_movie_subtitle_readiness_page_is_wired(self) -> None:
        self.assertIn("'repair-defaults': 'Repair Defaults'", FRONTEND)
        self.assertIn("subtitleFixBusy: false", FRONTEND)
        self.assertIn("function movieSubtitleReadinessIsRepairable(item)", FRONTEND)
        self.assertIn("Normalize Subtitle Defaults", FRONTEND)
        self.assertIn("'/api/movies/subtitle-readiness/fix'", FRONTEND)
        self.assertIn("This page is non-destructive", FRONTEND)
        self.assertIn("state.subtitleFixBusy = true;", FRONTEND)
        self.assertIn("state.subtitleFixBusy = false;", FRONTEND)
        self.assertIn("selectedSubtitleRowsFromPayload", FRONTEND)

    def test_movie_dashboard_has_replacement_queue_summary_without_detail_pane(self) -> None:
        self.assertIn("function renderDashboardPanel()", FRONTEND)
        self.assertIn("function currentDashboardPayload()", FRONTEND)
        self.assertIn("function updateDashboardPayload(payload, requestedSource = '')", FRONTEND)
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
        self.assertIn("policyDrafts: {}", FRONTEND)
        self.assertIn("payload.policy_definitions.filter(definition => definition?.label !== 'replacement_candidate')", FRONTEND)

    def test_normalize_policy_editor_filters_redundant_replacement_candidate_and_starts_collapsed(self) -> None:
        self.assertIn("payload.policy_definitions.filter(definition => definition?.label !== 'replacement_candidate')", NORMALIZE_LAB_FRONTEND)
        self.assertIn("const preferredOrder = ['default_source', 'delete_mode', 'library_defaults'];", NORMALIZE_LAB_FRONTEND)
        self.assertIn("return filtered.slice().sort((left, right) => {", NORMALIZE_LAB_FRONTEND)
        self.assertIn("const isOpen = state.policySectionLabel === definition.label;", NORMALIZE_LAB_FRONTEND)
        self.assertIn("state.policySectionLabel = label || '';", NORMALIZE_LAB_FRONTEND)
        self.assertIn("lab-policy-section-header", NORMALIZE_LAB_FRONTEND)
        self.assertIn("aria-expanded=\"${isOpen ? 'true' : 'false'}\"", NORMALIZE_LAB_FRONTEND)
        self.assertIn("section.addEventListener('keydown', event => {", NORMALIZE_LAB_FRONTEND)
        self.assertNotIn("${isOpen ? 'Collapse' : 'Edit'}", NORMALIZE_LAB_FRONTEND)
        self.assertNotIn("(!state.policySectionLabel && definition.label === 'library_defaults')", NORMALIZE_LAB_FRONTEND)
        self.assertNotIn("User-local", NORMALIZE_LAB_FRONTEND)
        self.assertNotIn("Repo-local", NORMALIZE_LAB_FRONTEND)
        self.assertNotIn("repo-local <span class=\"lab-cell-mono\">movie_standards.json</span>", NORMALIZE_LAB_FRONTEND)
        self.assertNotIn("user-local delete posture", NORMALIZE_LAB_FRONTEND)

    def test_movie_canonical_lists_page_is_wired(self) -> None:
        self.assertIn("Canonical Lists", FRONTEND)
        self.assertIn("'/api/movies/canonical-lists'", FRONTEND)
        self.assertIn("Run Canonical Lists", FRONTEND)
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
        self.assertIn("Movie Normalize", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Weak Encodes", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Repair Defaults", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Canonical Lists", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Delete Junk & Spam", NORMALIZE_LAB_FRONTEND)
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
        self.assertIn("dashboardRequestedSource", NORMALIZE_LAB_FRONTEND)
        self.assertIn("normalizeSourceKey(value)", NORMALIZE_LAB_FRONTEND)
        self.assertIn("state.dashboardProfileSource === source || state.dashboardRequestedSource === source", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Dashboard currently reuses the latest profile-bearing scan for this source.", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Library visibility snapshot", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Quality Profile Breakdown", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Library Improvement Metrics", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Resolution Breakdown", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Surround Sound Breakdown", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Current Top 500 above weak floor", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Canonical improvement", NORMALIZE_LAB_FRONTEND)
        self.assertIn("4K Scope Frame", NORMALIZE_LAB_FRONTEND)
        self.assertIn("7.1 Atmos Bed", NORMALIZE_LAB_FRONTEND)
        self.assertIn("function dashboardResolutionBreakdownKey(item)", NORMALIZE_LAB_FRONTEND)
        self.assertIn("function dashboardSurroundBreakdownKey(item)", NORMALIZE_LAB_FRONTEND)
        self.assertIn("function movieBreakdownCounts(items, keyFn)", NORMALIZE_LAB_FRONTEND)
        self.assertIn("histogram.resolution_breakdown_counts : movieResolutionCounts", NORMALIZE_LAB_FRONTEND)
        self.assertIn("histogram.surround_sound_breakdown_counts : movieSurroundCounts", NORMALIZE_LAB_FRONTEND)
        self.assertIn("histogram.resolution_breakdown_counts || {}", NORMALIZE_LAB_FRONTEND)
        self.assertIn("histogram.surround_sound_breakdown_counts || {}", NORMALIZE_LAB_FRONTEND)
        self.assertIn("id=\"canonicalListFilter\"", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Run Canonical Lists", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Quality Profile Inspector", NORMALIZE_LAB_FRONTEND)
        self.assertIn("function renderCanonicalPreviewPane()", NORMALIZE_LAB_FRONTEND)
        self.assertIn("function canonicalRows()", NORMALIZE_LAB_FRONTEND)
        self.assertIn("function imdbTitleUrl(imdbId)", NORMALIZE_LAB_FRONTEND)
        self.assertIn("function canonicalTitleMarkup(title, imdbId)", NORMALIZE_LAB_FRONTEND)
        self.assertIn("imdb_id: entry.imdb_id || ''", NORMALIZE_LAB_FRONTEND)
        self.assertIn("href=\"${escapeHtml(url)}\" target=\"_blank\" rel=\"noopener noreferrer\"", NORMALIZE_LAB_FRONTEND)
        self.assertIn("label: 'Quality Profile'", NORMALIZE_LAB_FRONTEND)
        self.assertIn("label: 'In Library'", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Top 100", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Top 250", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Top 500", NORMALIZE_LAB_FRONTEND)
        self.assertIn("const requestedListId = state.canonicalSelectedListId || el.canonicalListFilter?.value || 'top_100';", NORMALIZE_LAB_FRONTEND)
        self.assertIn("state.canonicalSelectedListId = lists.find(item => item.id === requestedListId)?.id", NORMALIZE_LAB_FRONTEND)
        self.assertNotIn("id=\"canonicalListsToggle\"", NORMALIZE_LAB_FRONTEND)
        self.assertIn("aria-label=\"Placeholder\"", NORMALIZE_LAB_FRONTEND)
        self.assertIn("disabled></button>", NORMALIZE_LAB_FRONTEND)
        self.assertIn("el.policyToggle.innerHTML = railIconSvg('scroll-text');", NORMALIZE_LAB_FRONTEND)
        self.assertIn("el.auditToggle.innerHTML = railIconSvg('clipboard-paste');", NORMALIZE_LAB_FRONTEND)
        self.assertIn("el.placeholderToggle.innerHTML = railIconSvg('trophy');", NORMALIZE_LAB_FRONTEND)
        self.assertIn("railIconSvg('download')", NORMALIZE_LAB_FRONTEND)
        self.assertIn("const exportLabel = exportBusy ? 'Exporting Catalogue' : 'Export Catalogue';", NORMALIZE_LAB_FRONTEND)
        self.assertIn("await fetch('/api/movies/register', {", NORMALIZE_LAB_FRONTEND)
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
        self.assertIn("id=\"policyRail\"", NORMALIZE_LAB_FRONTEND)
        self.assertIn("id=\"dashboardPanel\"", NORMALIZE_LAB_FRONTEND)
        self.assertIn("id=\"policyEditorPanel\"", NORMALIZE_LAB_FRONTEND)
        self.assertIn("id=\"inspectionPane\"", NORMALIZE_LAB_FRONTEND)
        self.assertIn("state.surfaceMode = 'default'", NORMALIZE_LAB_FRONTEND)
        self.assertIn("function renderPolicyRail()", NORMALIZE_LAB_FRONTEND)
        self.assertIn("function renderPolicyEditor()", NORMALIZE_LAB_FRONTEND)
        self.assertIn("function renderInspectionPane()", NORMALIZE_LAB_FRONTEND)
        self.assertIn("function togglePolicyEditor()", NORMALIZE_LAB_FRONTEND)
        self.assertIn("function syncSliverHeight()", NORMALIZE_LAB_FRONTEND)
        self.assertIn("function ensureSliverResizeObserver()", NORMALIZE_LAB_FRONTEND)
        self.assertIn("state.sliverResizeObserver = new ResizeObserver(() => {", NORMALIZE_LAB_FRONTEND)
        self.assertIn("if (!surfaceOpen()) {", NORMALIZE_LAB_FRONTEND)
        self.assertIn("el.sliverSlot.style.height = '';", NORMALIZE_LAB_FRONTEND)
        self.assertIn("el.sliver.style.height = `${nextHeight}px`;", NORMALIZE_LAB_FRONTEND)
        self.assertIn("id=\"auditToggle\"", NORMALIZE_LAB_FRONTEND)
        self.assertIn("id=\"auditPanel\"", NORMALIZE_LAB_FRONTEND)
        self.assertIn("/api/audit/read", NORMALIZE_LAB_FRONTEND)
        self.assertIn("await ensurePolicyPayload();", NORMALIZE_LAB_FRONTEND)
        self.assertIn("if (startupSource) el.sourcePath.value = startupSource;", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Preview and action controls are suppressed while policy editing is active.", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Preview and action controls are suppressed while dashboard view is open.", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Preview and action controls are suppressed while the audit ledger is open.", NORMALIZE_LAB_FRONTEND)
        self.assertIn("if (!state.runInFlight && state.workflow === 'normalize' && auditSurfaceOpen()) {", NORMALIZE_LAB_FRONTEND)
        self.assertIn("applyPolicyPayload(payload);", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Make Best English Audio Default", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Normalize Subtitle Defaults", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Make Best English Audio Default + Normalize Subtitle Defaults", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Make Best English Audio Default + Remove Foreign Audio", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Make Best English Audio Default + Remove Foreign Audio + Normalize Subtitle Defaults", NORMALIZE_LAB_FRONTEND)
        self.assertNotIn("Repair Lane", NORMALIZE_LAB_FRONTEND)
        self.assertIn("This page is non-destructive", NORMALIZE_LAB_FRONTEND)
        self.assertIn("wrong language · weak English", NORMALIZE_LAB_FRONTEND)
        self.assertIn("default_non_english_audio", NORMALIZE_LAB_FRONTEND)
        self.assertIn("function actualResolutionLabel(item)", NORMALIZE_LAB_FRONTEND)
        self.assertIn("return `${width} x ${height}`;", NORMALIZE_LAB_FRONTEND)
        self.assertIn("data-audio-popover=\"${escapeHtml(row.row_id)}\"", NORMALIZE_LAB_FRONTEND)
        self.assertIn("selectable: Boolean(item.path) && issueFamilies.length > 0 && !repairDefaultsSelectionLocked()", NORMALIZE_LAB_FRONTEND)
        self.assertIn("File Name", NORMALIZE_LAB_FRONTEND)
        self.assertIn("label: 'Confidence'", NORMALIZE_LAB_FRONTEND)
        self.assertIn("function fileNameFromPath(path)", NORMALIZE_LAB_FRONTEND)
        self.assertIn("function middleTruncateJunkFileName(value, maxWidth, font)", NORMALIZE_LAB_FRONTEND)
        self.assertIn("new ResizeObserver", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Select all", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Deselect all", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Preview Scope", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Full library", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Action", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Run Repair", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Confirm (0 Operations)", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Run Delete Junk & Spam Files", NORMALIZE_LAB_FRONTEND)
        self.assertNotIn("reason code", NORMALIZE_LAB_FRONTEND)
        self.assertNotIn("warning code", NORMALIZE_LAB_FRONTEND)
        self.assertNotIn("package cases", NORMALIZE_LAB_FRONTEND)
        self.assertNotIn("collision cases", NORMALIZE_LAB_FRONTEND)
        self.assertNotIn("artifact cleanup cases", NORMALIZE_LAB_FRONTEND)
        self.assertNotIn("subtitle-merge cases", NORMALIZE_LAB_FRONTEND)
        self.assertIn("state.previewMode = el.previewScopeSelect.value === 'library' ? 'library' : 'selected';", NORMALIZE_LAB_FRONTEND)
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
        self.assertIn("state.activeRowId = id;", NORMALIZE_LAB_FRONTEND)
        self.assertIn("function selectedProposedChanges()", NORMALIZE_LAB_FRONTEND)
        self.assertIn("function summarizeNormalizeRows(rows)", NORMALIZE_LAB_FRONTEND)
        self.assertIn("function renderNormalizeSummaryChips(operationCounts, visibleMutationCount)", NORMALIZE_LAB_FRONTEND)
        self.assertIn("function renderConfirmButton()", NORMALIZE_LAB_FRONTEND)
        self.assertIn("function renderShellLayout()", NORMALIZE_LAB_FRONTEND)
        self.assertIn("change.change_type !== 'folder_delete' || change.confidence !== 'safe' || !change.current_value", NORMALIZE_LAB_FRONTEND)
        self.assertIn("selectedRelatedCount !== relatedRows.length", NORMALIZE_LAB_FRONTEND)
        self.assertIn("mutated media file", NORMALIZE_LAB_FRONTEND)
        self.assertIn("visible path mutation", NORMALIZE_LAB_FRONTEND)
        self.assertIn("planned operation", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Delete Selected Files (", NORMALIZE_LAB_FRONTEND)
        self.assertIn("selected junk file", NORMALIZE_LAB_FRONTEND)
        self.assertIn("currently filtered junk candidate", NORMALIZE_LAB_FRONTEND)
        self.assertIn("summaryNoun: 'subtitle issue'", NORMALIZE_LAB_FRONTEND)
        self.assertIn("summaryNoun: 'audio-packaging title'", NORMALIZE_LAB_FRONTEND)
        self.assertIn("summaryNoun: 'repair title'", NORMALIZE_LAB_FRONTEND)
        self.assertIn("No remaining normalize changes.", NORMALIZE_LAB_FRONTEND)
        self.assertNotIn("detailPane", NORMALIZE_LAB_FRONTEND)
        self.assertNotIn("renderDetailPane", NORMALIZE_LAB_FRONTEND)
        self.assertNotIn("Why this is", NORMALIZE_LAB_FRONTEND)
        self.assertNotIn("detailTab", NORMALIZE_LAB_FRONTEND)
        self.assertNotIn("previewTab", NORMALIZE_LAB_FRONTEND)
        self.assertNotIn("label: 'Status'", NORMALIZE_LAB_FRONTEND)
        self.assertNotIn("Replacement History", NORMALIZE_LAB_FRONTEND)
        self.assertNotIn("buildReplacementHistoryTable", NORMALIZE_LAB_FRONTEND)
        self.assertNotIn('id="weakFloorSelect"', NORMALIZE_LAB_TEMPLATE)

    def test_normalize_lab_css_exposes_shell_layout_and_rhythm_contracts(self) -> None:
        self.assertIn('[hidden] { display: none !important; }', NORMALIZE_LAB_CSS)
        self.assertIn('--lab-track-rail', NORMALIZE_LAB_CSS)
        self.assertIn('--lab-track-scan', NORMALIZE_LAB_CSS)
        self.assertIn('--lab-track-inspection', NORMALIZE_LAB_CSS)
        self.assertIn('--lab-track-preview', NORMALIZE_LAB_CSS)
        self.assertIn('--lab-track-audit', NORMALIZE_LAB_CSS)
        self.assertIn('--lab-primary-surface-min-height', NORMALIZE_LAB_CSS)
        self.assertIn('--lab-rhythm-row-height', NORMALIZE_LAB_CSS)
        self.assertIn('--lab-rhythm-panel-body-offset', NORMALIZE_LAB_CSS)
        self.assertIn('--lab-table-select-column-width', NORMALIZE_LAB_CSS)
        self.assertIn('--lab-table-select-pad-inline-start', NORMALIZE_LAB_CSS)
        self.assertIn('.lab-scan-table col.lab-col-select', NORMALIZE_LAB_CSS)
        self.assertIn('.lab-shell[data-layout-mode="2-page-lopsided"]', NORMALIZE_LAB_CSS)
        self.assertIn('.lab-shell[data-layout-mode="3-page-book"] .lab-layout', NORMALIZE_LAB_CSS)
        self.assertIn('.lab-shell[data-layout-mode="4-page-ledger"] .lab-layout', NORMALIZE_LAB_CSS)
        self.assertIn('.lab-shell[data-policy-mode="editing"] .lab-layout', NORMALIZE_LAB_CSS)
        self.assertIn('.lab-sliver', NORMALIZE_LAB_CSS)
        self.assertIn('.lab-shell[data-policy-mode="default"] .lab-sliver {', NORMALIZE_LAB_CSS)
        self.assertIn('grid-template-rows: auto;', NORMALIZE_LAB_CSS)
        self.assertIn('min-height: 0;', NORMALIZE_LAB_CSS)
        self.assertIn('height: auto;', NORMALIZE_LAB_CSS)
        self.assertIn('.lab-shell[data-policy-mode="default"] .lab-sliver-slot {', NORMALIZE_LAB_CSS)
        self.assertIn('grid-template-columns: repeat(2, minmax(0, 1fr));', NORMALIZE_LAB_CSS)
        self.assertIn('.lab-dashboard-breakdowns {', NORMALIZE_LAB_CSS)
        self.assertIn('min-height: var(--lab-primary-surface-min-height);', NORMALIZE_LAB_CSS)
        self.assertIn('.lab-policy-panel', NORMALIZE_LAB_CSS)
        self.assertIn('.lab-inspection-pane', NORMALIZE_LAB_CSS)
        self.assertIn('.lab-page[data-panel-state="collapsed"][data-collapse-mode="anchored-slot"]', NORMALIZE_LAB_CSS)
        self.assertIn('.lab-page[data-panel-state="collapsed"][data-collapse-mode="reflow"]', NORMALIZE_LAB_CSS)
        self.assertIn('.lab-rhythm-surface[data-rhythm-surface="rows"]', NORMALIZE_LAB_CSS)

    def test_normalize_lab_table_declares_fixed_select_column_contract(self) -> None:
        self.assertIn('<colgroup id="tableColGroup"></colgroup>', NORMALIZE_LAB_TEMPLATE)
        self.assertIn("tableColGroup: document.getElementById('tableColGroup')", NORMALIZE_LAB_JS)
        self.assertIn('el.tableColGroup.innerHTML = headers.map(header => {', NORMALIZE_LAB_JS)
        self.assertIn("const styleAttr = header.width ? ` style=\"width:${escapeHtml(header.width)}\"` : '';", NORMALIZE_LAB_JS)
        self.assertIn('return `<col${classAttr}${styleAttr}>`;', NORMALIZE_LAB_JS)
        self.assertIn("width: 'var(--lab-table-select-column-width)'", NORMALIZE_LAB_JS)
        self.assertIn("width: 'auto'", NORMALIZE_LAB_JS)

    def test_normalize_lab_audio_repair_buttons_are_bound_to_mux_actions(self) -> None:
        self.assertIn("el.repairActionButton.addEventListener('click', () => {", NORMALIZE_LAB_JS)
        self.assertIn("const request = runSelectedRepairAction(action);", NORMALIZE_LAB_JS)
        self.assertIn("set_english_default_repair_subtitle_defaults", NORMALIZE_LAB_JS)
        self.assertIn("set_english_default_drop_foreign_repair_subtitle_defaults", NORMALIZE_LAB_JS)
        self.assertNotIn("repairDefaultsTab", NORMALIZE_LAB_JS)
        self.assertIn("Running English-default remux for ${paths.length} file", NORMALIZE_LAB_JS)
        self.assertIn("Running English-default remux and foreign-audio prune for ${paths.length} file", NORMALIZE_LAB_JS)
        self.assertIn("Running subtitle-default remux for ${paths.length} file", NORMALIZE_LAB_JS)
        self.assertIn("body: JSON.stringify({ source: el.sourcePath.value.trim(), paths, drop_foreign_audio: dropForeignAudio }),", NORMALIZE_LAB_JS)
        self.assertIn("if (actionTouchesSubtitle(action)) {", NORMALIZE_LAB_JS)
        self.assertIn("const applicableRows = selectedRepairRowsForAction(action);", NORMALIZE_LAB_JS)

    def test_repair_preview_calls_out_family_noops_for_combined_actions(self) -> None:
        self.assertIn("streams/audio [no audio-default change for this file]", NORMALIZE_LAB_JS)
        self.assertIn("streams/subtitles [no subtitle-default change for this file]", NORMALIZE_LAB_JS)

    def test_normalize_lab_selection_refreshes_all_selection_dependent_controls(self) -> None:
        self.assertIn("function refreshSelectionState() {", NORMALIZE_LAB_JS)
        refresh_section = NORMALIZE_LAB_JS.split("function refreshSelectionState() {", 1)[1].split("function attachRowHandlers()", 1)[0]
        self.assertIn("renderSelectionButtons();", refresh_section)
        self.assertIn("renderConfirmButton();", refresh_section)
        self.assertIn("renderWorkflowActionControls();", refresh_section)
        self.assertIn("renderSidePanel();", refresh_section)

    def test_normalize_lab_row_checkbox_changes_use_shared_selection_refresh(self) -> None:
        checkbox_section = NORMALIZE_LAB_JS.split("el.rowsBody.querySelectorAll('input[data-row-check]').forEach(input => {", 1)[1].split("el.rowsBody.querySelectorAll('button[data-audio-popover]')", 1)[0]
        self.assertIn("clearDeletePreviewState();", checkbox_section)
        self.assertIn("refreshSelectionState();", checkbox_section)
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
                            headers={"Content-Type": "application/json"},
                            method="POST",
                        )
                        with urllib.request.urlopen(req) as response:
                            payload = json.loads(response.read().decode("utf-8"))
        self.assertEqual(payload["fixed"], [])
        self.assertTrue(fix_audio.call_args.kwargs["drop_foreign_audio"])
        self.assertNotIn("replacement_queue", payload)

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
                    headers={"Content-Type": "application/json"},
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


if __name__ == "__main__":
    unittest.main()
