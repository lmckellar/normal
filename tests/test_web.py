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
    render_index_html,
    render_normalize_lab_html,
)
from normal.web.routes_cleanup import delete_mode_for_kind


APP_TEMPLATE = read_web_asset_text("index.html")
APP_CSS = read_web_asset_text("app.css")
APP_JS = read_web_asset_text("app.js")
FRONTEND = "\n".join((APP_TEMPLATE, APP_CSS, APP_JS))
NORMALIZE_LAB_TEMPLATE = read_web_asset_text("normalize_lab.html")
NORMALIZE_LAB_CSS = read_web_asset_text("normalize_lab.css")
NORMALIZE_LAB_JS = read_web_asset_text("normalize_lab.js")
NORMALIZE_LAB_FRONTEND = "\n".join((NORMALIZE_LAB_TEMPLATE, NORMALIZE_LAB_CSS, NORMALIZE_LAB_JS))


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
        self.assertIn("'/api/source/scan-warning'", FRONTEND)
        self.assertIn("payload.message || 'This source may be risky for a heavy recursive scan.'", FRONTEND)
        self.assertIn("Total size: ${payload.total_size_label}", FRONTEND)
        self.assertIn("Only run one heavy scan for this source at a time.", FRONTEND)

    def test_legacy_dashboard_runtime_keys_are_available_before_initial_render(self) -> None:
        html = render_index_html(Path("/library/movies"), omdb_key="omdb-test", tmdb_key="tmdb-test")
        self.assertIn('<link rel="stylesheet" href="/assets/app.css?v=', html)
        self.assertIn('<script src="/assets/app.js?v=', html)
        self.assertLess(html.index("window.OMDB_AVAILABLE"), html.index('<script src="/assets/app.js?v='))
        self.assertIn('window.DEFAULT_SOURCE = "/library/movies";', html)
        self.assertIn("window.OMDB_AVAILABLE = true;", html)
        self.assertNotIn("omdb-test", html)
        self.assertIn('window.TMDB_KEY = "tmdb-test";', html)

    def test_handler_serves_static_assets(self) -> None:
        with self.run_test_server() as base_url:
            with urllib.request.urlopen(f"{base_url}/assets/app.css") as response:
                self.assertEqual(response.headers.get_content_type(), "text/css")
                self.assertEqual(response.headers.get("Cache-Control"), "no-store")
                self.assertIn(".activity-bar", response.read().decode("utf-8"))
            with urllib.request.urlopen(f"{base_url}/assets/app.js") as response:
                self.assertEqual(response.headers.get_content_type(), "application/javascript")
                self.assertEqual(response.headers.get("Cache-Control"), "no-store")
                self.assertIn("function refreshActivityState", response.read().decode("utf-8"))
            with urllib.request.urlopen(f"{base_url}/parser-tester-ui-assets/normalize_lab.css") as response:
                self.assertEqual(response.headers.get_content_type(), "text/css")
                self.assertEqual(response.headers.get("Cache-Control"), "no-store")
                self.assertIn(".lab-layout", response.read().decode("utf-8"))
            with urllib.request.urlopen(f"{base_url}/parser-tester-ui-assets/normalize_lab.js") as response:
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
        self.assertIn("/parser-tester-ui-assets/normalize_lab.js?v=", served)
        self.assertIn("Movie Normalize", served)
        self.assertEqual(served, served_index)

    def test_normalize_lab_route_serves_default_ui_alias(self) -> None:
        html = render_normalize_lab_html(Path("/library/movies"))
        self.assertIn('/parser-tester-ui-assets/normalize_lab.css?v=', html)
        self.assertIn('/parser-tester-ui-assets/normalize_lab.js?v=', html)
        self.assertIn('window.DEFAULT_SOURCE = "/library/movies";', html)
        self.assertIn('id="policyToggle"', html)
        self.assertIn('id="policyRail"', html)
        self.assertIn('id="policyEditorPanel"', html)
        self.assertIn('id="inspectionPane"', html)
        self.assertNotIn('Repair Lane', html)
        self.assertIn('data-layout-mode="2-page-lopsided"', html)
        self.assertIn('data-page-role="scan"', html)
        self.assertIn('data-page-role="preview"', html)
        self.assertIn('data-collapse-mode="reflow"', html)
        self.assertIn('data-collapse-mode="anchored-slot"', html)
        with self.run_test_server() as base_url:
            with urllib.request.urlopen(f"{base_url}/parser-tester-ui") as response:
                served = response.read().decode("utf-8")
        self.assertIn("Movie Normalize", served)
        self.assertIn("Weak Encodes", served)
        self.assertIn("Repair Defaults", served)
        self.assertIn("Delete Junk &amp; Spam", served)
        self.assertIn("Confirm (0 Operations)", served)

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
        self.assertIn("Library Switcher", FRONTEND)
        self.assertIn("id=\"libraryRoots\"", FRONTEND)
        self.assertIn("n_library_roots", FRONTEND)
        self.assertIn("n_recent_libraries", FRONTEND)
        self.assertIn("Main Libraries", FRONTEND)
        self.assertIn("Recently Scanned Libraries", FRONTEND)
        self.assertIn("movies: typeof roots.movies === 'string' ? roots.movies : ''", FRONTEND)
        self.assertIn("data-library-lane=\"${lane}\"", FRONTEND)
        self.assertIn("data-recent-library-index=\"${item.index}\"", FRONTEND)
        self.assertIn("function useLibraryRoot(lane)", FRONTEND)
        self.assertIn("function useRecentLibrary(index)", FRONTEND)
        self.assertIn("function promoteRecentLibrary(index)", FRONTEND)
        self.assertIn("function removeRecentLibrary(index)", FRONTEND)
        self.assertIn("setLane(lane, { forceSource: source });", FRONTEND)
        self.assertIn("const isCurrent = state.lane === lane && source && source === currentSource;", FRONTEND)
        self.assertIn("data-promote-library-index=\"${item.index}\"", FRONTEND)
        self.assertIn("${isCurrent ? `<button class=\"secondary\" data-promote-library-index=\"${item.index}\">Make Main ${escapeHtml(CONFIG[item.lane].title)} Library</button>` : ''}", FRONTEND)
        self.assertIn("data-remove-recent-library-index=\"${item.index}\"", FRONTEND)
        self.assertIn("Make Main ${escapeHtml(CONFIG[item.lane].title)} Library", FRONTEND)
        self.assertIn(">Remove</button>", FRONTEND)
        self.assertIn("const uniqueRecentLibraries = _recentLibraries", FRONTEND)
        self.assertIn(".filter(item => _libraryRoots[item.lane] !== item.source);", FRONTEND)
        self.assertIn("${recentRows ? `<div class=\"library-subhead\">Recently Scanned Libraries</div>${recentRows}` : ''}", FRONTEND)
        self.assertNotIn("No recent scans yet.", FRONTEND)
        self.assertIn("library-current-chip", FRONTEND)
        self.assertIn("${isCurrent ? 'Using' : 'Use'}", FRONTEND)
        self.assertIn("rememberScannedLibrary(payload.source_root || source);", FRONTEND)
        self.assertIn("localStorage.setItem('n_library_roots', JSON.stringify(_libraryRoots))", FRONTEND)
        self.assertIn("persistRecentLibraries();", FRONTEND)
        self.assertIn("sourceInput.value = window.DEFAULT_SOURCE || _libraryRoots.movies || '';", FRONTEND)
        self.assertNotIn("class=\"lane-button", FRONTEND)
        self.assertNotIn("data-lane=\"movies\"", FRONTEND)
        self.assertNotIn("data-lane=\"music\"", FRONTEND)
        self.assertNotIn("document.querySelectorAll('.lane-button')", FRONTEND)
        self.assertNotIn("Save current", FRONTEND)
        self.assertNotIn("Set Current", FRONTEND)
        self.assertNotIn("Snapshot", FRONTEND)

    def test_run_button_becomes_stop_while_scan_runs(self) -> None:
        self.assertIn("let _activeRunController = null;", FRONTEND)
        self.assertIn("runButton.textContent = running ? 'Stop' : 'Run';", FRONTEND)
        self.assertIn("_activeRunController.abort();", FRONTEND)
        self.assertIn("signal: _activeRunController.signal", FRONTEND)
        self.assertIn("Scan stopped.", FRONTEND)

    def test_drive_activity_indicator_is_wired(self) -> None:
        self.assertIn("id=\"activityBar\"", FRONTEND)
        self.assertIn("Drive activity: idle", FRONTEND)
        self.assertIn("'/api/activity?source='", FRONTEND)
        self.assertIn("function refreshActivityState", FRONTEND)
        self.assertIn("let _activityRequest = null;", FRONTEND)
        self.assertIn("let _activityRequestSource = '';", FRONTEND)
        self.assertIn("async function _runActivityPollLoop(gen)", FRONTEND)
        self.assertIn("if (_activityRequestSource === source) return _activityRequest;", FRONTEND)
        self.assertIn("_activityTimer = setTimeout(() => _runActivityPollLoop(gen), payload?.active ? 2000 : 10000);", FRONTEND)
        self.assertIn("external ${process.command} detected", FRONTEND)
        self.assertIn("ffprobe active", FRONTEND)
        self.assertIn("Drive activity: ffmpeg remux active", FRONTEND)
        self.assertIn("formatEta(job.eta_seconds)", FRONTEND)
        self.assertIn("formatByteSize(job.output_size_bytes)", FRONTEND)
        self.assertIn("function activityProgressPieces(job)", FRONTEND)
        self.assertIn("files processed", FRONTEND)
        self.assertIn("app.find(item => item.kind !== 'probe')", FRONTEND)

    def test_movie_junk_page_is_wired(self) -> None:
        self.assertIn("id: 'junk'", FRONTEND)
        self.assertIn("endpoint: '/api/movies/junk'", FRONTEND)
        self.assertIn("'/api/movies/junk/delete'", FRONTEND)
        self.assertIn("state.results.movies.junk = payload;", FRONTEND)
        self.assertIn("renderMovieJunk(state.results.movies.junk);", FRONTEND)
        self.assertNotIn("id: 'promo'", FRONTEND)
        self.assertNotIn("endpoint: '/api/movies/promo-docs'", FRONTEND)

    def test_movie_delete_flows_are_direct_in_weak_encodes(self) -> None:
        self.assertIn("Delete Selected Files", FRONTEND)
        self.assertIn("renderReplacementQueueDetail", FRONTEND)
        self.assertIn("function buildMovieQualityTable", FRONTEND)
        self.assertIn("function buildMovieAudioPackagingTable", FRONTEND)
        self.assertIn("function strictWeakMovies", FRONTEND)
        self.assertIn("function audioPackagingMovies", FRONTEND)
        self.assertIn("function activeMovieTriageFamily", FRONTEND)
        self.assertIn("'/api/movies/delete'", FRONTEND)
        self.assertNotIn("'/api/movies/replacement-queue/list'", FRONTEND)
        self.assertNotIn("'/api/movies/replacement-queue/add'", FRONTEND)
        self.assertNotIn("'/api/movies/replacement-queue/delete'", FRONTEND)
        self.assertNotIn("'/api/movies/replacement-queue/dismiss'", FRONTEND)
        self.assertNotIn("n_movie_replacement_queue_cache", FRONTEND)
        self.assertIn("button:disabled { opacity: 0.45; cursor: not-allowed; }", APP_CSS)
        self.assertIn("color: var(--ink);", APP_CSS.split("button {", 1)[1].split("}", 1)[0])
        self.assertIn("color: var(--ink);", APP_CSS.split(".page-button, .filter-button {", 1)[1].split("}", 1)[0])
        self.assertNotIn("cursor: progress", FRONTEND)

    def test_movie_audio_packaging_page_is_wired(self) -> None:
        self.assertIn("id: 'fix_defaults'", FRONTEND)
        self.assertIn("label: 'Repair Defaults'", FRONTEND)
        self.assertIn("renderMovieFixDefaults", FRONTEND)
        self.assertIn("movieAudioFixBusy: false", FRONTEND)
        self.assertIn("function movieAudioFixSelectionLocked()", FRONTEND)
        self.assertIn("wrong language · weak English", FRONTEND)
        self.assertIn("Wrong Default Language", FRONTEND)
        self.assertIn("Weak English Fallback", FRONTEND)
        self.assertIn("'/api/movies/audio-packaging/fix'", FRONTEND)
        self.assertIn("'/api/movies/delete'", FRONTEND)
        self.assertIn("Make Best English Audio Default", FRONTEND)
        self.assertIn("Make Best English Audio Default + Remove Foreign Audio", FRONTEND)
        self.assertIn("junk-actions audio-packaging-actions", FRONTEND)
        self.assertIn("triage-action-spacer", FRONTEND)
        self.assertIn("Selection locked while ffmpeg remux is running.", FRONTEND)
        self.assertIn("Wait for the active remux to finish before changing audio-packaging selections.", FRONTEND)
        self.assertIn("state.movieAudioFixBusy = true;", FRONTEND)
        self.assertIn("state.movieAudioFixBusy = false;", FRONTEND)
        self.assertIn("function fixSelectedAudioDefaults(options = {})", FRONTEND)
        self.assertIn("drop_foreign_audio: dropForeignAudio", FRONTEND)
        self.assertIn("function summarizeAudioFixResult(result, dropForeignAudio)", FRONTEND)
        self.assertIn("English already default", FRONTEND)
        self.assertIn("<th>Audio</th>", FRONTEND)
        self.assertIn("function describeAudioFormat(stream)", FRONTEND)

    def test_movie_subtitle_readiness_page_is_wired(self) -> None:
        self.assertIn("id: 'fix_defaults'", FRONTEND)
        self.assertIn("label: 'Repair Defaults'", FRONTEND)
        self.assertIn("renderMovieFixDefaults", FRONTEND)
        self.assertIn("movieSubtitleFixBusy: false", FRONTEND)
        self.assertIn("function movieSubtitleFixSelectionLocked()", FRONTEND)
        self.assertIn("function movieSubtitleReadinessIssueCode(item)", FRONTEND)
        self.assertIn("function movieSubtitleReadinessIsRepairable(item)", FRONTEND)
        self.assertIn("Normalize Subtitle Defaults", FRONTEND)
        self.assertIn("'/api/movies/subtitle-readiness/fix'", FRONTEND)
        self.assertIn("This page is non-destructive", FRONTEND)
        self.assertIn("Selection locked while ffmpeg remux is running.", FRONTEND)
        self.assertIn("state.movieSubtitleFixBusy = true;", FRONTEND)
        self.assertIn("state.movieSubtitleFixBusy = false;", FRONTEND)
        self.assertIn("function summarizeSubtitleFixResult(result)", FRONTEND)
        self.assertNotIn("Replacement Queue · Subtitle Readiness", FRONTEND)

    def test_movie_dashboard_has_replacement_queue_summary_without_detail_pane(self) -> None:
        self.assertIn("Action Based", FRONTEND)
        self.assertIn("Quality Profile", FRONTEND)
        self.assertIn("Standard Definition", FRONTEND)
        self.assertIn("Library Grade", FRONTEND)
        self.assertIn("Collector Grade", FRONTEND)
        self.assertIn("data-catalogue-source", FRONTEND)
        self.assertIn("generateCatalogue", FRONTEND)
        self.assertIn("attachMovieDashboardHandlers(payload);", FRONTEND)
        self.assertNotIn("Generate Catalogue", FRONTEND)
        self.assertNotIn("catalogue-btn", FRONTEND)
        self.assertIn("For movies, this pane stays attached to the current directory's Replacement Queue.", FRONTEND)
        self.assertIn("library: 'Dashboard'", FRONTEND)
        self.assertIn("n_movie_dashboard_cache_v2", FRONTEND)
        self.assertIn("function cacheMovieDashboard(payload)", FRONTEND)
        self.assertIn("function restoreCachedMovieDashboard(source)", FRONTEND)
        self.assertIn("cacheMovieDashboard(payload);", FRONTEND)
        self.assertIn("renderMovieLibrary(profile || restoreCachedMovieDashboard(source));", FRONTEND)
        self.assertIn("const total = histogram.movie_count ?? (payload.movies || []).length;", FRONTEND)
        self.assertIn("'/api/movies/dashboard/histogram'", FRONTEND)
        self.assertIn("function refreshMovieDashboardHistogram(payload)", FRONTEND)
        self.assertIn("function removeDeletedMovieProfileItems(payload, deletedItems)", FRONTEND)
        self.assertIn("vline(mean, 'mean', 'var(--accent-2)')", FRONTEND)
        self.assertIn("function fmtVideoBitrate(kbps)", FRONTEND)
        self.assertIn("(kbps / 1000).toFixed(1) + ' Mbps'", FRONTEND)
        self.assertNotIn("vline(p50, 'med'", FRONTEND)
        self.assertNotIn("const p10 = dist.p10, p50 = dist.p50", FRONTEND)
        self.assertIn("if (label === 'replacement_candidate') return 'Replacement Candidate';", FRONTEND)
        self.assertIn("'replacement_candidate'", FRONTEND)
        self.assertIn("function movieProfileInlineSummary(item)", FRONTEND)
        self.assertIn("function humanMovieProfileIssueLabel(code, summary = '')", FRONTEND)
        self.assertIn("Below Min. Video Bitrate", FRONTEND)
        self.assertIn("Main Audio Below ${threshold} Channels", FRONTEND)
        self.assertNotIn("Deleted, Awaiting Replacement", FRONTEND)
        self.assertNotIn("from Replacement Queue", FRONTEND)
        self.assertNotIn("Low confidence:", FRONTEND)
        self.assertIn("const qualityProfileCounts = histogram.quality_profile_counts || {};", FRONTEND)
        self.assertIn("const definitions = Array.isArray(payload.quality_profile_definitions) ? payload.quality_profile_definitions : [];", FRONTEND)
        self.assertIn("const replacementCandidateDefinition = payload.replacement_candidate_definition || null;", FRONTEND)
        self.assertIn("const barWidth = total ? (count / total) * 100 : 0;", FRONTEND)
        self.assertNotIn("const barWidth = (count / actionMaxCount) * 100;", FRONTEND)
        self.assertNotIn("const barWidth = (count / qualityMaxCount) * 100;", FRONTEND)
        self.assertIn("const definitionSummary = options?.rule_summary || '';", FRONTEND)
        self.assertIn("profile-card-band", FRONTEND)
        self.assertLess(APP_JS.index("function humanProfileLabel"), APP_JS.index("function buildMovieQualityTable"))
        library_section = APP_JS.split("function renderMovieLibrary(payload) {", 1)[1].split(
            "function renderMovieQuality(payload) {",
            1,
        )[0]
        self.assertNotIn("renderReplacementQueueDetail(payload)", library_section)
        self.assertNotIn("attachMovieReplacementHandlers(payload)", library_section)

    def test_movie_dashboard_exposes_inline_profile_definition_controls(self) -> None:
        self.assertIn("/api/movies/standards/update", FRONTEND)
        self.assertIn("movieStandardsEditorLabel", FRONTEND)
        self.assertIn("movieStandardsPendingDraft", FRONTEND)
        self.assertIn("movie-profile-definition-toggle", FRONTEND)
        self.assertIn("label === 'replacement_candidate' && !!options?.fields", FRONTEND)
        self.assertIn("${isEditorOpen ? 'Close' : 'Edit'}</button>", FRONTEND)
        self.assertIn("function movieProfileDefinitionDraft(label)", FRONTEND)
        self.assertIn("function buildMovieProfileDefinitionEditor(definition)", FRONTEND)
        self.assertIn("function movieProfileEditorValues(label)", FRONTEND)
        self.assertIn("function saveMovieProfileDefinition(label)", FRONTEND)
        self.assertIn("quality_profile_definitions", FRONTEND)
        self.assertIn("replacement_candidate_definition", FRONTEND)
        self.assertIn("movie_standards_revision", FRONTEND)
        self.assertIn("const fieldValue = hasDraftValue ? draftValues[field.key] : field.value;", FRONTEND)
        self.assertIn("const disabledAttr = isBusy ? ' disabled' : '';", FRONTEND)
        self.assertIn("if (!Object.prototype.hasOwnProperty.call(values, key)) values[key] = [];", FRONTEND)
        self.assertIn("state.movieStandardsPendingDraft = { label, values: editorValues };", FRONTEND)
        self.assertIn("state.movieStandardsPendingDraft = null;", FRONTEND)
        self.assertIn("body: JSON.stringify({ label, revision, values: editorValues })", FRONTEND)
        self.assertIn("Saves to repo-local <span class=\"mono\">movie_standards.json</span> and reruns the dashboard.", FRONTEND)

    def test_movie_canonical_lists_page_is_wired(self) -> None:
        self.assertIn("id: 'canonical_lists'", FRONTEND)
        self.assertIn("label: 'Canonical Lists'", FRONTEND)
        self.assertIn("endpoint: '/api/movies/canonical-lists'", FRONTEND)
        self.assertIn("n_movie_canonical_lists_cache", FRONTEND)
        self.assertIn("function cacheMovieCanonicalLists(payload)", FRONTEND)
        self.assertIn("function restoreCachedMovieCanonicalLists(source)", FRONTEND)
        self.assertIn("renderMovieCanonicalLists(canonical || restoreCachedMovieCanonicalLists(source));", FRONTEND)
        self.assertIn("Badge Collection", FRONTEND)
        self.assertIn("This page ignores bitrate, quality, and warning telemetry.", FRONTEND)
        self.assertIn("Provider: TMDb canonical lists", FRONTEND)
        self.assertIn("Run Movies / Canonical Lists to compare the library against curated movie lists.", FRONTEND)
        canonical_section = APP_JS.split("function renderMovieCanonicalLists(payload) {", 1)[1].split(
            "function renderMovieQuality(payload) {",
            1,
        )[0]
        self.assertNotIn("buildBitrateBellCurve(payload)", canonical_section)
        self.assertNotIn("renderReplacementQueueDetail(payload)", canonical_section)

    def test_movie_normalize_has_review_and_apply_workflow(self) -> None:
        self.assertIn("endpoint: '/api/movies/normalize'", FRONTEND)
        self.assertIn("'/api/movies/apply'", FRONTEND)
        self.assertIn("function applySelectedMovieChanges", FRONTEND)
        self.assertIn("showMovieNormalizeTreeDetail", FRONTEND)
        self.assertIn("Flagged for review", FRONTEND)
        self.assertIn("movieNormalizeResultsForConfidence(payload, filter)", FRONTEND)
        movie_normalize_section = APP_JS.split("function renderMovieNormalize(payload) {", 1)[1].split(
            "async function applySelectedMovieChanges()",
            1,
        )[0]
        self.assertNotIn("id=\"selAllSafe\"", movie_normalize_section)
        self.assertNotIn("id=\"selFlaggedReview\"", movie_normalize_section)
        self.assertIn("function activeMovieNormalizePayload(payload) {", FRONTEND)
        self.assertNotIn("proposed_changes_by_naming_style", FRONTEND)
        self.assertNotIn("requestBody.naming_style", FRONTEND)
        self.assertIn("remaining_safe_count", FRONTEND)
        self.assertIn("Apply needs review", FRONTEND)
        self.assertIn("safe rename${remainingSafe === 1 ? '' : 's'} and ${remainingReview} review rename", FRONTEND)

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
        self.assertIn("Delete Junk & Spam", NORMALIZE_LAB_FRONTEND)
        self.assertIn("return workflow;", NORMALIZE_LAB_FRONTEND)
        self.assertIn("/api/policy/read", NORMALIZE_LAB_FRONTEND)
        self.assertIn("/api/policy/update", NORMALIZE_LAB_FRONTEND)
        self.assertIn("id=\"policyToggle\"", NORMALIZE_LAB_FRONTEND)
        self.assertIn("id=\"policyRail\"", NORMALIZE_LAB_FRONTEND)
        self.assertIn("id=\"policyEditorPanel\"", NORMALIZE_LAB_FRONTEND)
        self.assertIn("id=\"inspectionPane\"", NORMALIZE_LAB_FRONTEND)
        self.assertIn("state.policyEditing = false", NORMALIZE_LAB_FRONTEND)
        self.assertIn("function renderPolicyRail()", NORMALIZE_LAB_FRONTEND)
        self.assertIn("function renderPolicyEditor()", NORMALIZE_LAB_FRONTEND)
        self.assertIn("function renderInspectionPane()", NORMALIZE_LAB_FRONTEND)
        self.assertIn("function togglePolicyEditor()", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Preview and action controls are suppressed while policy editing is active.", NORMALIZE_LAB_FRONTEND)
        self.assertIn("applyPolicyPayload(payload);", NORMALIZE_LAB_FRONTEND)
        self.assertIn("repo-local <span class=\"lab-cell-mono\">movie_standards.json</span>", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Make Best English Audio Default", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Normalize Subtitle Defaults", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Make Best English Audio Default + Normalize Subtitle Defaults", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Make Best English Audio Default + Remove Foreign Audio", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Make Best English Audio Default + Remove Foreign Audio + Normalize Subtitle Defaults", NORMALIZE_LAB_FRONTEND)
        self.assertNotIn("Repair Lane", NORMALIZE_LAB_FRONTEND)
        self.assertIn("This page is non-destructive", NORMALIZE_LAB_FRONTEND)
        self.assertIn("wrong language · weak English", NORMALIZE_LAB_FRONTEND)
        self.assertIn("default_non_english_audio", NORMALIZE_LAB_FRONTEND)
        self.assertIn("issueFamilyLabel(issueFamilies)", NORMALIZE_LAB_FRONTEND)
        self.assertIn("selectable: Boolean(item.path) && issueFamilies.length > 0 && !repairDefaultsSelectionLocked()", NORMALIZE_LAB_FRONTEND)
        self.assertIn("File Name", NORMALIZE_LAB_FRONTEND)
        self.assertIn("label: 'Confidence'", NORMALIZE_LAB_FRONTEND)
        self.assertIn("function fileNameFromPath(path)", NORMALIZE_LAB_FRONTEND)
        self.assertIn("function middleTruncateJunkFileName(value, maxWidth, font)", NORMALIZE_LAB_FRONTEND)
        self.assertIn("new ResizeObserver", NORMALIZE_LAB_FRONTEND)
        self.assertIn("reason code", NORMALIZE_LAB_FRONTEND)
        self.assertIn("warning code", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Select all", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Deselect all", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Preview Scope", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Full library", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Action", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Run Repair", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Confirm (0 Operations)", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Run Delete Junk & Spam Files", NORMALIZE_LAB_FRONTEND)
        self.assertIn("package cases", NORMALIZE_LAB_FRONTEND)
        self.assertIn("collision cases", NORMALIZE_LAB_FRONTEND)
        self.assertIn("artifact cleanup cases", NORMALIZE_LAB_FRONTEND)
        self.assertIn("subtitle-merge cases", NORMALIZE_LAB_FRONTEND)
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
