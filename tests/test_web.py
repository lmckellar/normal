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

from normal.web import (
    build_handler,
    delete_movie_junk_files,
    read_web_asset_text,
    render_index_html,
    render_normalize_lab_html,
    render_workbench_html,
)


APP_TEMPLATE = read_web_asset_text("index.html")
APP_CSS = read_web_asset_text("app.css")
APP_JS = read_web_asset_text("app.js")
FRONTEND = "\n".join((APP_TEMPLATE, APP_CSS, APP_JS))
WORKBENCH_TEMPLATE = read_web_asset_text("workbench.html")
WORKBENCH_CSS = read_web_asset_text("workbench.css")
WORKBENCH_JS = read_web_asset_text("workbench.js")
WORKBENCH_FRONTEND = "\n".join((WORKBENCH_TEMPLATE, WORKBENCH_CSS, WORKBENCH_JS))
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

    def test_web_runtime_keys_are_available_before_initial_render(self) -> None:
        html = render_index_html(Path("/library/movies"), omdb_key="omdb-test", tmdb_key="tmdb-test")
        self.assertIn('<link rel="stylesheet" href="/assets/app.css">', html)
        self.assertIn('<script src="/assets/app.js"></script>', html)
        self.assertLess(html.index("window.OMDB_AVAILABLE"), html.index('<script src="/assets/app.js"></script>'))
        self.assertIn('window.DEFAULT_SOURCE = "/library/movies";', html)
        self.assertIn("window.OMDB_AVAILABLE = true;", html)
        self.assertNotIn("omdb-test", html)
        self.assertIn('window.TMDB_KEY = "tmdb-test";', html)

    def test_handler_serves_static_assets(self) -> None:
        with self.run_test_server() as base_url:
            with urllib.request.urlopen(f"{base_url}/assets/app.css") as response:
                self.assertEqual(response.headers.get_content_type(), "text/css")
                self.assertIn(".activity-bar", response.read().decode("utf-8"))
            with urllib.request.urlopen(f"{base_url}/assets/app.js") as response:
                self.assertEqual(response.headers.get_content_type(), "application/javascript")
                self.assertIn("function refreshActivityState", response.read().decode("utf-8"))
            with urllib.request.urlopen(f"{base_url}/book-style-alt-design-ui-assets/workbench.css") as response:
                self.assertEqual(response.headers.get_content_type(), "text/css")
                self.assertIn(".wb-frame", response.read().decode("utf-8"))
            with urllib.request.urlopen(f"{base_url}/book-style-alt-design-ui-assets/workbench.js") as response:
                self.assertEqual(response.headers.get_content_type(), "application/javascript")
                self.assertIn("Preview Selected Changes", response.read().decode("utf-8"))
            with urllib.request.urlopen(f"{base_url}/parser-tester-ui-assets/normalize_lab.css") as response:
                self.assertEqual(response.headers.get_content_type(), "text/css")
                self.assertIn(".lab-layout", response.read().decode("utf-8"))
            with urllib.request.urlopen(f"{base_url}/parser-tester-ui-assets/normalize_lab.js") as response:
                self.assertEqual(response.headers.get_content_type(), "application/javascript")
                self.assertIn("/api/movies/apply", response.read().decode("utf-8"))

    def test_workbench_runtime_keys_are_available_before_initial_render(self) -> None:
        html = render_workbench_html(Path("/library/movies"), omdb_key="omdb-test", tmdb_key="tmdb-test")
        self.assertIn('<link rel="stylesheet" href="/book-style-alt-design-ui-assets/workbench.css">', html)
        self.assertIn('<script src="/book-style-alt-design-ui-assets/workbench.js"></script>', html)
        self.assertLess(html.index("window.OMDB_AVAILABLE"), html.index('<script src="/book-style-alt-design-ui-assets/workbench.js"></script>'))
        self.assertIn('window.DEFAULT_SOURCE = "/library/movies";', html)
        self.assertIn("window.OMDB_AVAILABLE = true;", html)
        self.assertNotIn("omdb-test", html)
        self.assertIn('window.TMDB_KEY = "tmdb-test";', html)

    def test_workbench_route_serves_parallel_ui(self) -> None:
        with self.run_test_server() as base_url:
            with urllib.request.urlopen(f"{base_url}/book-style-alt-design-ui") as response:
                html = response.read().decode("utf-8")
        self.assertIn("Book Style Alt Design UI", html)
        self.assertIn("/book-style-alt-design-ui-assets/workbench.js", html)

    def test_normalize_lab_route_serves_internal_ui(self) -> None:
        html = render_normalize_lab_html(Path("/library/movies"))
        self.assertIn('/parser-tester-ui-assets/normalize_lab.css', html)
        self.assertIn('/parser-tester-ui-assets/normalize_lab.js', html)
        self.assertIn('window.DEFAULT_SOURCE = "/library/movies";', html)
        with self.run_test_server() as base_url:
            with urllib.request.urlopen(f"{base_url}/parser-tester-ui") as response:
                served = response.read().decode("utf-8")
        self.assertIn("Parser Testing UI", served)
        self.assertIn("Weak Encodes Testing UI", served)
        self.assertIn("Confirm (0 Changes)", served)

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

    def test_workbench_frontend_is_wired_for_fixed_spread(self) -> None:
        self.assertIn("Primary Surface", WORKBENCH_FRONTEND)
        self.assertIn("Secondary Surface", WORKBENCH_FRONTEND)
        self.assertIn("Downstream Ledger", WORKBENCH_FRONTEND)
        self.assertIn("Preview Selected Changes", WORKBENCH_FRONTEND)
        self.assertIn("Diff View", WORKBENCH_FRONTEND)
        self.assertIn("Full Preview", WORKBENCH_FRONTEND)
        self.assertIn("Reveal File Tree", WORKBENCH_FRONTEND)
        self.assertIn("Collapse File Tree", WORKBENCH_FRONTEND)
        self.assertIn("state.auditExpanded = !state.auditExpanded;", WORKBENCH_FRONTEND)
        self.assertIn("buildAuditExpandedContent()", WORKBENCH_FRONTEND)
        self.assertIn("/api/movies/apply", WORKBENCH_FRONTEND)
        self.assertIn("/api/movies/junk/delete", WORKBENCH_FRONTEND)
        self.assertIn("/api/movies/audio-packaging/fix", WORKBENCH_FRONTEND)
        self.assertIn("/api/movies/subtitle-readiness/fix", WORKBENCH_FRONTEND)
        self.assertIn("window.confirm(`Permanently delete ${items.length} file", WORKBENCH_FRONTEND)
        self.assertIn("wb-frame", WORKBENCH_CSS)
        self.assertIn("grid-template-columns: 240px minmax(0, 1fr) minmax(0, 1fr) 82px;", WORKBENCH_CSS)

    def test_handler_returns_404_for_unknown_static_asset(self) -> None:
        with self.run_test_server() as base_url:
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f"{base_url}/assets/missing.css")
        self.assertEqual(ctx.exception.code, 404)

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
        self.assertIn("junk: null,", FRONTEND)
        self.assertIn("if (page === 'junk') {\n          state.results.movies.junk = payload;", FRONTEND)
        self.assertIn("renderMovieJunk(state.results.movies.junk);", FRONTEND)
        self.assertNotIn("id: 'promo'", FRONTEND)
        self.assertNotIn("endpoint: '/api/movies/promo-docs'", FRONTEND)

    def test_movie_replacement_queue_is_wired_inside_weak_encodes(self) -> None:
        self.assertIn("Replacement Queue", FRONTEND)
        self.assertIn("Replacement Queue · Weak Encode", FRONTEND)
        self.assertIn("Replacement Queue · Audio Packaging", FRONTEND)
        self.assertIn("pending delete", FRONTEND)
        self.assertIn("deleted and waiting replacement", FRONTEND)
        self.assertIn("deleted, waiting replacement", FRONTEND)
        self.assertIn("successfully replaced", FRONTEND)
        self.assertIn("deleted from queue", FRONTEND)
        self.assertIn("Replacement History", FRONTEND)
        self.assertIn("Deleted, Awaiting Replacement", FRONTEND)
        self.assertIn("Replaced", FRONTEND)
        self.assertIn("Deleted From Queue", FRONTEND)
        self.assertIn("All Items", FRONTEND)
        self.assertIn("queue-list", FRONTEND)
        self.assertIn("queue-list-row", FRONTEND)
        self.assertIn("Select All", FRONTEND)
        self.assertIn("Deselect All", FRONTEND)
        self.assertIn("toggleAllReplacementButton", FRONTEND)
        self.assertNotIn("selectAllReplacementButton", FRONTEND)
        self.assertNotIn("deselectAllReplacementButton", FRONTEND)
        self.assertIn("Delete Selected Files", FRONTEND)
        self.assertNotIn("Queue selected folders", FRONTEND)
        self.assertNotIn("queueReplacementFoldersButton", FRONTEND)
        self.assertIn("renderReplacementQueueDetail", FRONTEND)
        self.assertIn("function buildPendingReplacementTable", FRONTEND)
        self.assertIn("function buildReplacementHistoryTable", FRONTEND)
        self.assertIn("function groupedReplacementHistoryItems", FRONTEND)
        self.assertIn("replacementHistoryFilter: 'deleted'", FRONTEND)
        self.assertIn("replacementHistorySort: { col: null, dir: 'asc' }", FRONTEND)
        self.assertIn("original_folder_path", FRONTEND)
        self.assertIn("['seq','#'],['title','Title'],['year','Year'],['count','Count']", FRONTEND)
        self.assertIn("<th>Movie Title</th><th>Issue</th><th>Resolution</th><th>Video Bitrate</th><th>Action</th>", FRONTEND)
        self.assertIn("attachReplacementQueueDetailHandlers();", FRONTEND)
        self.assertIn("function attachReplacementQueueDetailHandlers", FRONTEND)
        self.assertNotIn("buildReplacementQueueSection", FRONTEND)
        self.assertIn("current directory's Replacement Queue", FRONTEND)
        self.assertIn("'/api/movies/replacement-queue/list'", FRONTEND)
        self.assertIn("n_movie_replacement_queue_cache", FRONTEND)
        self.assertIn("function cacheMovieReplacementQueue(queue)", FRONTEND)
        self.assertIn("function restoreCachedMovieReplacementQueue(source)", FRONTEND)
        self.assertIn("restoreCachedMovieReplacementQueue(source);", FRONTEND)
        self.assertIn("'/api/movies/replacement-queue/add'", FRONTEND)
        self.assertIn("'/api/movies/replacement-queue/delete'", FRONTEND)
        self.assertIn("'/api/movies/replacement-queue/dismiss'", FRONTEND)
        self.assertIn("'/api/movies/omdb/ratings'", FRONTEND)
        self.assertNotIn("www.omdbapi.com", FRONTEND)
        self.assertIn("function replacementHistoryRatingCell", FRONTEND)
        self.assertIn("IMDb limit reached. Cached ratings still show; new ratings retry later.", FRONTEND)
        self.assertIn("return '<span class=\"subtle\">limit</span>';", FRONTEND)
        self.assertIn("function buildMovieQualityTable", FRONTEND)
        self.assertIn("function buildMovieAudioPackagingTable", FRONTEND)
        self.assertIn("function strictWeakMovies", FRONTEND)
        self.assertIn("function audioPackagingMovies", FRONTEND)
        self.assertIn("function activeMovieTriageFamily", FRONTEND)
        self.assertIn("function replacementQueueItemForPath", FRONTEND)
        self.assertIn("function replacementQueueStatusChip", FRONTEND)
        self.assertIn("replacement-history-filter", FRONTEND)
        self.assertIn("replacement-history-sort-th", FRONTEND)
        self.assertIn("replacement-history-remove", FRONTEND)
        self.assertIn("queue-inline-remove", FRONTEND)
        self.assertIn("<th>Status</th>", FRONTEND)
        self.assertIn("queued</span>", FRONTEND)
        self.assertIn("Deleted, Waiting Replacement", FRONTEND)
        self.assertIn("!replacementQueueItemForPath(payload, item.path)", FRONTEND)
        self.assertIn("button:disabled { opacity: 0.45; cursor: not-allowed; }", APP_CSS)
        self.assertIn("color: var(--ink);", APP_CSS.split("button {", 1)[1].split("}", 1)[0])
        self.assertIn("color: var(--ink);", APP_CSS.split(".page-button, .filter-button {", 1)[1].split("}", 1)[0])
        self.assertNotIn("cursor: progress", FRONTEND)
        self.assertIn("const source = sourceInput.value.trim() || queue?.source_root || ''", FRONTEND)
        self.assertIn("Choose a source directory before deleting replacement media.", FRONTEND)
        self.assertIn("No pending replacement media is selected for deletion.", FRONTEND)
        self.assertIn("Choose a source directory before removing items from the replacement queue.", FRONTEND)
        self.assertIn("Remove from queue", FRONTEND)
        self.assertIn("['file','profile','resolution','video_bitrate','audio_bitrate','audio_summary','file_size']", FRONTEND)
        self.assertNotIn("Select strict weak", FRONTEND)
        self.assertNotIn("['strict_weak', 'Strict Weak']", FRONTEND)
        self.assertNotIn("<th>Inspect</th>", FRONTEND)
        self.assertNotIn("inspect-movie", FRONTEND)

    def test_movie_audio_packaging_page_is_wired(self) -> None:
        self.assertIn("id: 'fix_defaults'", FRONTEND)
        self.assertIn("label: 'Repair Defaults'", FRONTEND)
        self.assertIn("renderMovieFixDefaults", FRONTEND)
        self.assertIn("movieAudioFixBusy: false", FRONTEND)
        self.assertIn("function movieAudioFixSelectionLocked()", FRONTEND)
        self.assertIn("wrong language · weak English", FRONTEND)
        self.assertIn("Wrong Default Language", FRONTEND)
        self.assertIn("Weak English Fallback", FRONTEND)
        self.assertIn("issue_family: issueFamily", FRONTEND)
        self.assertIn("'/api/movies/audio-packaging/fix'", FRONTEND)
        self.assertIn("Set English Default", FRONTEND)
        self.assertIn("Set English Default + Drop Foreign", FRONTEND)
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
        self.assertIn("Repair Subtitle Defaults", FRONTEND)
        self.assertIn("'/api/movies/subtitle-readiness/fix'", FRONTEND)
        self.assertIn("This page is non-destructive", FRONTEND)
        self.assertIn("Selection locked while ffmpeg remux is running.", FRONTEND)
        self.assertIn("state.movieSubtitleFixBusy = true;", FRONTEND)
        self.assertIn("state.movieSubtitleFixBusy = false;", FRONTEND)
        self.assertIn("function summarizeSubtitleFixResult(result)", FRONTEND)
        self.assertNotIn("Replacement Queue · Subtitle Readiness", FRONTEND)

    def test_movie_dashboard_has_replacement_queue_summary_without_detail_pane(self) -> None:
        self.assertIn("Deleted, Awaiting Replacement", FRONTEND)
        self.assertIn("from Replacement Queue", FRONTEND)
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
        self.assertIn("/api/movies/replacement-queue/delete-preview", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Parser Testing UI", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Weak Encodes Testing UI", NORMALIZE_LAB_FRONTEND)
        self.assertIn("reason code", NORMALIZE_LAB_FRONTEND)
        self.assertIn("warning code", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Select all", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Deselect all", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Full library", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Confirm (0 Changes)", NORMALIZE_LAB_FRONTEND)
        self.assertIn("package cases", NORMALIZE_LAB_FRONTEND)
        self.assertIn("collision cases", NORMALIZE_LAB_FRONTEND)
        self.assertIn("artifact cleanup cases", NORMALIZE_LAB_FRONTEND)
        self.assertIn("subtitle-merge cases", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Why this is", NORMALIZE_LAB_FRONTEND)
        self.assertIn("state.activePane = 'preview';", NORMALIZE_LAB_FRONTEND)
        self.assertIn("state.previewMode = 'library';", NORMALIZE_LAB_FRONTEND)
        self.assertIn("function renderPreviewPane()", NORMALIZE_LAB_FRONTEND)
        self.assertIn("state.activeRowId = id;", NORMALIZE_LAB_FRONTEND)
        self.assertIn("row.linked_changes || []", NORMALIZE_LAB_FRONTEND)
        self.assertIn("row.warning_messages || []", NORMALIZE_LAB_FRONTEND)
        self.assertIn("function selectedProposedChanges()", NORMALIZE_LAB_FRONTEND)
        self.assertIn("function renderConfirmButton()", NORMALIZE_LAB_FRONTEND)
        self.assertIn("change.change_type !== 'folder_delete' || change.confidence !== 'safe' || !change.current_value", NORMALIZE_LAB_FRONTEND)
        self.assertIn("selectedRelatedCount !== relatedRows.length", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Delete Selected Files (", NORMALIZE_LAB_FRONTEND)
        self.assertIn("Weak mode keeps item inspection in the scan table", NORMALIZE_LAB_FRONTEND)
        self.assertNotIn("Replacement History", NORMALIZE_LAB_FRONTEND)
        self.assertNotIn("buildReplacementHistoryTable", NORMALIZE_LAB_FRONTEND)

    def test_replacement_queue_delete_preview_route(self) -> None:
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
                    f"{base_url}/api/movies/replacement-queue/delete-preview",
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
