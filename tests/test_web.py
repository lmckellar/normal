from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from normal.web import (
    INDEX_HTML,
    ActivityTracker,
    HEAVY_SCAN_REGISTRY,
    build_activity_payload,
    build_source_scan_warning,
    delete_movie_junk_files,
    find_external_activity,
    format_storage_size,
    guarded_heavy_scan,
    looks_like_drive_directory,
    RequestConflictError,
    resolve_source_path,
    SourceMountDetails,
)


class WebTests(unittest.TestCase):
    def test_resolve_source_path_uses_explicit_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = resolve_source_path(tmpdir)
            self.assertEqual(path, Path(tmpdir).resolve())

    def test_resolve_source_path_falls_back_to_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = resolve_source_path(None, default_source=Path(tmpdir))
            self.assertEqual(path, Path(tmpdir).resolve())

    def test_scan_warning_is_wired(self) -> None:
        self.assertIn("'/api/source/scan-warning'", INDEX_HTML)
        self.assertIn("payload.message || 'This source may be risky for a heavy recursive scan.'", INDEX_HTML)
        self.assertIn("Total size: ${payload.total_size_label}", INDEX_HTML)
        self.assertIn("Only run one heavy scan for this source at a time.", INDEX_HTML)

    def test_library_switcher_remembers_music_and_movie_roots(self) -> None:
        self.assertIn("Library Switcher", INDEX_HTML)
        self.assertIn("id=\"libraryRoots\"", INDEX_HTML)
        self.assertIn("n_library_roots", INDEX_HTML)
        self.assertIn("n_recent_libraries", INDEX_HTML)
        self.assertIn("Main Libraries", INDEX_HTML)
        self.assertIn("Recently Scanned Libraries", INDEX_HTML)
        self.assertIn("music: typeof roots.music === 'string' ? roots.music : ''", INDEX_HTML)
        self.assertIn("movies: typeof roots.movies === 'string' ? roots.movies : ''", INDEX_HTML)
        self.assertIn("data-library-lane=\"${lane}\"", INDEX_HTML)
        self.assertIn("data-recent-library-index=\"${item.index}\"", INDEX_HTML)
        self.assertIn("function useLibraryRoot(lane)", INDEX_HTML)
        self.assertIn("function useRecentLibrary(index)", INDEX_HTML)
        self.assertIn("function promoteRecentLibrary(index)", INDEX_HTML)
        self.assertIn("function removeRecentLibrary(index)", INDEX_HTML)
        self.assertIn("setLane(lane, { forceSource: source });", INDEX_HTML)
        self.assertIn("const isCurrent = state.lane === lane && source && source === currentSource;", INDEX_HTML)
        self.assertIn("data-promote-library-index=\"${item.index}\"", INDEX_HTML)
        self.assertIn("${isCurrent ? `<button class=\"secondary\" data-promote-library-index=\"${item.index}\">Make Main ${escapeHtml(CONFIG[item.lane].title)} Library</button>` : ''}", INDEX_HTML)
        self.assertIn("data-remove-recent-library-index=\"${item.index}\"", INDEX_HTML)
        self.assertIn("Make Main ${escapeHtml(CONFIG[item.lane].title)} Library", INDEX_HTML)
        self.assertIn(">Remove</button>", INDEX_HTML)
        self.assertIn("const uniqueRecentLibraries = _recentLibraries", INDEX_HTML)
        self.assertIn(".filter(item => _libraryRoots[item.lane] !== item.source);", INDEX_HTML)
        self.assertIn("${recentRows ? `<div class=\"library-subhead\">Recently Scanned Libraries</div>${recentRows}` : ''}", INDEX_HTML)
        self.assertNotIn("No recent scans yet.", INDEX_HTML)
        self.assertIn("library-current-chip", INDEX_HTML)
        self.assertIn("${isCurrent ? 'Using' : 'Use'}", INDEX_HTML)
        self.assertIn("rememberScannedLibrary(payload.source_root || source);", INDEX_HTML)
        self.assertIn("localStorage.setItem('n_library_roots', JSON.stringify(_libraryRoots))", INDEX_HTML)
        self.assertIn("persistRecentLibraries();", INDEX_HTML)
        self.assertIn("sourceInput.value = window.DEFAULT_SOURCE || _libraryRoots.movies || '';", INDEX_HTML)
        self.assertNotIn("class=\"lane-button", INDEX_HTML)
        self.assertNotIn("data-lane=\"movies\"", INDEX_HTML)
        self.assertNotIn("data-lane=\"music\"", INDEX_HTML)
        self.assertNotIn("document.querySelectorAll('.lane-button')", INDEX_HTML)
        self.assertNotIn("Save current", INDEX_HTML)
        self.assertNotIn("Set Current", INDEX_HTML)
        self.assertNotIn("Snapshot", INDEX_HTML)

    def test_run_button_becomes_stop_while_scan_runs(self) -> None:
        self.assertIn("let _activeRunController = null;", INDEX_HTML)
        self.assertIn("runButton.textContent = running ? 'Stop' : 'Run';", INDEX_HTML)
        self.assertIn("_activeRunController.abort();", INDEX_HTML)
        self.assertIn("signal: _activeRunController.signal", INDEX_HTML)
        self.assertIn("Scan stopped.", INDEX_HTML)

    def test_drive_activity_indicator_is_wired(self) -> None:
        self.assertIn("id=\"activityBar\"", INDEX_HTML)
        self.assertIn("Drive activity: idle", INDEX_HTML)
        self.assertIn("'/api/activity?source='", INDEX_HTML)
        self.assertIn("function refreshActivityState", INDEX_HTML)
        self.assertIn("let _activityRequest = null;", INDEX_HTML)
        self.assertIn("let _activityRequestSource = '';", INDEX_HTML)
        self.assertIn("async function _runActivityPollLoop(gen)", INDEX_HTML)
        self.assertIn("if (_activityRequestSource === source) return _activityRequest;", INDEX_HTML)
        self.assertIn("_activityTimer = setTimeout(() => _runActivityPollLoop(gen), payload?.active ? 2000 : 10000);", INDEX_HTML)
        self.assertIn("external ${process.command} detected", INDEX_HTML)
        self.assertIn("ffprobe active", INDEX_HTML)
        self.assertIn("Drive activity: ffmpeg remux active", INDEX_HTML)
        self.assertIn("formatEta(job.eta_seconds)", INDEX_HTML)
        self.assertIn("formatByteSize(job.output_size_bytes)", INDEX_HTML)

    def test_activity_tracker_snapshots_active_probe_for_source(self) -> None:
        tracker = ActivityTracker()
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            movie = source / "Movie.mkv"
            movie.write_text("movie", encoding="utf-8")
            with tracker.track(source, "ffprobe movie metadata", kind="probe", current_path=movie):
                items = tracker.snapshot(source)
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["kind"], "probe")
            self.assertEqual(items[0]["current_path"], str(movie.resolve()))
            self.assertEqual(tracker.snapshot(source), [])

    def test_activity_tracker_snapshot_includes_progress_metadata(self) -> None:
        tracker = ActivityTracker()
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            movie = source / "Movie.mkv"
            temp_output = source / "Movie.tmp.mkv"
            movie.write_text("movie", encoding="utf-8")
            with tracker.track(source, "Movie audio fix", kind="remux", current_path=movie) as item_id:
                tracker.update(
                    item_id,
                    status_text="ffmpeg remux active",
                    progress_fraction=0.5,
                    completed_seconds=60.0,
                    total_seconds=120.0,
                    eta_seconds=60.0,
                    output_size_bytes=1000,
                    output_path=temp_output,
                    speed="2.0x",
                )
                items = tracker.snapshot(source)
            self.assertEqual(items[0]["kind"], "remux")
            self.assertEqual(items[0]["status_text"], "ffmpeg remux active")
            self.assertEqual(items[0]["progress_fraction"], 0.5)
            self.assertEqual(items[0]["eta_seconds"], 60.0)
            self.assertEqual(items[0]["output_path"], str(temp_output.resolve()))

    def test_find_external_activity_matches_ffprobe_for_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir).resolve()
            ps_output = f"123 1 ffprobe ffprobe -v error {source}/Movie.mkv\n"
            completed = CompletedProcess(args=[], returncode=0, stdout=ps_output, stderr="")
            with patch("normal.web.subprocess.run", return_value=completed):
                matches, note = find_external_activity(source)
            self.assertIsNone(note)
            self.assertEqual(matches[0]["pid"], 123)
            self.assertEqual(matches[0]["command"], "ffprobe")

    def test_build_activity_payload_reports_idle_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            completed = CompletedProcess(args=[], returncode=0, stdout="", stderr="")
            with patch("normal.web.subprocess.run", return_value=completed):
                payload = build_activity_payload(Path(tmpdir))
            self.assertFalse(payload["active"])
            self.assertEqual(payload["app"], [])
            self.assertEqual(payload["external"], [])

    def test_build_activity_payload_skips_external_scan_when_app_activity_exists(self) -> None:
        tracker = ActivityTracker()
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            movie = source / "Movie.mkv"
            movie.write_text("movie", encoding="utf-8")
            with tracker.track(source, "Movie audio fix", kind="remux", current_path=movie):
                with patch("normal.web.ACTIVITY_TRACKER", tracker):
                    with patch("normal.web.find_external_activity") as find_external:
                        payload = build_activity_payload(source)
            find_external.assert_not_called()
            self.assertTrue(payload["active"])
            self.assertEqual(payload["external"], [])

    def test_build_activity_payload_uses_external_scan_when_no_app_activity_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            external_items = [{"pid": 123, "ppid": 1, "command": "ffprobe", "summary": "ffprobe Movie.mkv"}]
            with patch("normal.web.find_external_activity", return_value=(external_items, None)) as find_external:
                payload = build_activity_payload(source)
            find_external.assert_called_once_with(source)
            self.assertTrue(payload["active"])
            self.assertEqual(payload["external"], external_items)

    def test_drive_directory_detection_covers_common_mount_roots(self) -> None:
        self.assertTrue(looks_like_drive_directory(Path("/mnt/media_storage")))
        self.assertTrue(looks_like_drive_directory(Path("/media/lachlan/Drive")))
        self.assertTrue(looks_like_drive_directory(Path("/Volumes/Media")))
        self.assertFalse(looks_like_drive_directory(Path("/mnt/media_storage/Movies")))

    def test_build_source_scan_warning_marks_risky_ntfs_mount(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            usage = shutil.disk_usage(source)
            with patch("normal.web.source_mount_details", return_value=SourceMountDetails(fstype="fuseblk", target="/mnt/media_storage")):
                payload = build_source_scan_warning(source)
        self.assertTrue(payload["warn"])
        self.assertIn("mount:fuseblk", payload["reasons"])
        self.assertIn("higher risk", payload["message"])
        self.assertEqual(payload["mount_fstype"], "fuseblk")
        self.assertEqual(payload["total_size_bytes"], usage.total)

    def test_guarded_heavy_scan_rejects_same_source_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            with patch("normal.web.HEAVY_SCAN_REGISTRY", HEAVY_SCAN_REGISTRY.__class__()):
                with guarded_heavy_scan(source, "Movie profile scan"):
                    with self.assertRaises(RequestConflictError):
                        with guarded_heavy_scan(source, "Movie canonical lists"):
                            self.fail("overlapping heavy scan should not be allowed")

    def test_format_storage_size_uses_tb_for_large_drives(self) -> None:
        self.assertEqual(format_storage_size(4_500_000_000_000), "4.5 TB")

    def test_movie_junk_page_is_wired(self) -> None:
        self.assertIn("id: 'junk'", INDEX_HTML)
        self.assertIn("endpoint: '/api/movies/junk'", INDEX_HTML)
        self.assertIn("id: 'promo'", INDEX_HTML)
        self.assertIn("endpoint: '/api/movies/promo-docs'", INDEX_HTML)
        self.assertIn("'/api/movies/junk/delete'", INDEX_HTML)

    def test_movie_replacement_queue_is_wired_inside_weak_encodes(self) -> None:
        self.assertIn("Replacement Queue", INDEX_HTML)
        self.assertIn("Replacement Queue · Weak Encode", INDEX_HTML)
        self.assertIn("Replacement Queue · Audio Packaging", INDEX_HTML)
        self.assertIn("pending delete", INDEX_HTML)
        self.assertIn("deleted and waiting replacement", INDEX_HTML)
        self.assertIn("deleted, waiting replacement", INDEX_HTML)
        self.assertIn("successfully replaced", INDEX_HTML)
        self.assertIn("deleted from queue", INDEX_HTML)
        self.assertIn("Replacement History", INDEX_HTML)
        self.assertIn("Deleted, Awaiting Replacement", INDEX_HTML)
        self.assertIn("Replaced", INDEX_HTML)
        self.assertIn("Deleted From Queue", INDEX_HTML)
        self.assertIn("All Items", INDEX_HTML)
        self.assertIn("queue-list", INDEX_HTML)
        self.assertIn("queue-list-row", INDEX_HTML)
        self.assertIn("Select All", INDEX_HTML)
        self.assertIn("Deselect All", INDEX_HTML)
        self.assertIn("toggleAllReplacementButton", INDEX_HTML)
        self.assertNotIn("selectAllReplacementButton", INDEX_HTML)
        self.assertNotIn("deselectAllReplacementButton", INDEX_HTML)
        self.assertIn("Delete Selected Files", INDEX_HTML)
        self.assertNotIn("Queue selected folders", INDEX_HTML)
        self.assertNotIn("queueReplacementFoldersButton", INDEX_HTML)
        self.assertIn("renderReplacementQueueDetail", INDEX_HTML)
        self.assertIn("function buildPendingReplacementTable", INDEX_HTML)
        self.assertIn("function buildReplacementHistoryTable", INDEX_HTML)
        self.assertIn("function groupedReplacementHistoryItems", INDEX_HTML)
        self.assertIn("replacementHistoryFilter: 'deleted'", INDEX_HTML)
        self.assertIn("replacementHistorySort: { col: null, dir: 'asc' }", INDEX_HTML)
        self.assertIn("original_folder_path", INDEX_HTML)
        self.assertIn("['seq','#'],['title','Title'],['year','Year'],['count','Count']", INDEX_HTML)
        self.assertIn("<th>Movie Title</th><th>Issue</th><th>Resolution</th><th>Video Bitrate</th><th>Action</th>", INDEX_HTML)
        self.assertIn("attachReplacementQueueDetailHandlers();", INDEX_HTML)
        self.assertIn("function attachReplacementQueueDetailHandlers", INDEX_HTML)
        self.assertNotIn("buildReplacementQueueSection", INDEX_HTML)
        self.assertIn("current directory's Replacement Queue", INDEX_HTML)
        self.assertIn("'/api/movies/replacement-queue/list'", INDEX_HTML)
        self.assertIn("n_movie_replacement_queue_cache", INDEX_HTML)
        self.assertIn("function cacheMovieReplacementQueue(queue)", INDEX_HTML)
        self.assertIn("function restoreCachedMovieReplacementQueue(source)", INDEX_HTML)
        self.assertIn("restoreCachedMovieReplacementQueue(source);", INDEX_HTML)
        self.assertIn("'/api/movies/replacement-queue/add'", INDEX_HTML)
        self.assertIn("'/api/movies/replacement-queue/delete'", INDEX_HTML)
        self.assertIn("'/api/movies/replacement-queue/dismiss'", INDEX_HTML)
        self.assertIn("function buildMovieQualityTable", INDEX_HTML)
        self.assertIn("function buildMovieAudioPackagingTable", INDEX_HTML)
        self.assertIn("function strictWeakMovies", INDEX_HTML)
        self.assertIn("function audioPackagingMovies", INDEX_HTML)
        self.assertIn("function activeMovieTriageFamily", INDEX_HTML)
        self.assertIn("function replacementQueueItemForPath", INDEX_HTML)
        self.assertIn("function replacementQueueStatusChip", INDEX_HTML)
        self.assertIn("replacement-history-filter", INDEX_HTML)
        self.assertIn("replacement-history-sort-th", INDEX_HTML)
        self.assertIn("replacement-history-remove", INDEX_HTML)
        self.assertIn("queue-inline-remove", INDEX_HTML)
        self.assertIn("<th>Status</th>", INDEX_HTML)
        self.assertIn("queued</span>", INDEX_HTML)
        self.assertIn("Deleted, Waiting Replacement", INDEX_HTML)
        self.assertIn("!replacementQueueItemForPath(payload, item.path)", INDEX_HTML)
        self.assertIn("button:disabled { opacity: 0.45; cursor: not-allowed; transform: none; }", INDEX_HTML)
        self.assertIn("color: var(--ink);", INDEX_HTML.split("button {", 1)[1].split("}", 1)[0])
        self.assertIn("color: var(--ink);", INDEX_HTML.split(".page-button, .filter-button {", 1)[1].split("}", 1)[0])
        self.assertNotIn("cursor: progress", INDEX_HTML)
        self.assertIn("const source = sourceInput.value.trim() || queue?.source_root || ''", INDEX_HTML)
        self.assertIn("Choose a source directory before deleting replacement media.", INDEX_HTML)
        self.assertIn("No pending replacement media is selected for deletion.", INDEX_HTML)
        self.assertIn("Choose a source directory before removing items from the replacement queue.", INDEX_HTML)
        self.assertIn("Remove from queue", INDEX_HTML)
        self.assertIn("['file','profile','resolution','video_bitrate','audio_bitrate','audio_summary','file_size']", INDEX_HTML)
        self.assertNotIn("Select strict weak", INDEX_HTML)
        self.assertNotIn("['strict_weak', 'Strict Weak']", INDEX_HTML)
        self.assertNotIn("<th>Inspect</th>", INDEX_HTML)
        self.assertNotIn("inspect-movie", INDEX_HTML)

    def test_movie_audio_packaging_page_is_wired(self) -> None:
        self.assertIn("id: 'audio_packaging'", INDEX_HTML)
        self.assertIn("label: 'Fix Multi-Audio Packaging'", INDEX_HTML)
        self.assertIn("renderMovieAudioPackaging", INDEX_HTML)
        self.assertIn("movieAudioFixBusy: false", INDEX_HTML)
        self.assertIn("function movieAudioFixSelectionLocked()", INDEX_HTML)
        self.assertIn("wrong default + weak English", INDEX_HTML)
        self.assertIn("Wrong Default Language", INDEX_HTML)
        self.assertIn("Weak English Fallback", INDEX_HTML)
        self.assertIn("issue_family: issueFamily", INDEX_HTML)
        self.assertIn("'/api/movies/audio-packaging/fix'", INDEX_HTML)
        self.assertIn("Make English Default", INDEX_HTML)
        self.assertIn("Make English Default + Delete Foreign Audio", INDEX_HTML)
        self.assertIn("junk-actions audio-packaging-actions", INDEX_HTML)
        self.assertIn("triage-action-spacer", INDEX_HTML)
        self.assertIn("Selection locked while ffmpeg remux is running.", INDEX_HTML)
        self.assertIn("Wait for the active remux to finish before changing audio-packaging selections.", INDEX_HTML)
        self.assertIn("state.movieAudioFixBusy = true;", INDEX_HTML)
        self.assertIn("state.movieAudioFixBusy = false;", INDEX_HTML)
        self.assertIn("function fixSelectedAudioDefaults(options = {})", INDEX_HTML)
        self.assertIn("drop_foreign_audio: dropForeignAudio", INDEX_HTML)
        self.assertIn("function summarizeAudioFixResult(result, dropForeignAudio)", INDEX_HTML)
        self.assertIn("English already default", INDEX_HTML)
        self.assertIn("<th>Main Audio</th>", INDEX_HTML)
        self.assertIn("function describeAudioFormat(stream)", INDEX_HTML)

    def test_movie_subtitle_readiness_page_is_wired(self) -> None:
        self.assertIn("id: 'subtitle_readiness'", INDEX_HTML)
        self.assertIn("label: 'Repair Subtitle Readiness'", INDEX_HTML)
        self.assertIn("renderMovieSubtitleReadiness", INDEX_HTML)
        self.assertIn("movieSubtitleFixBusy: false", INDEX_HTML)
        self.assertIn("function movieSubtitleFixSelectionLocked()", INDEX_HTML)
        self.assertIn("function movieSubtitleReadinessIssueCode(item)", INDEX_HTML)
        self.assertIn("function movieSubtitleReadinessIsRepairable(item)", INDEX_HTML)
        self.assertIn("Repair Subtitle Defaults", INDEX_HTML)
        self.assertIn("'/api/movies/subtitle-readiness/fix'", INDEX_HTML)
        self.assertIn("This page is non-destructive", INDEX_HTML)
        self.assertIn("Selection locked while ffmpeg remux is running.", INDEX_HTML)
        self.assertIn("state.movieSubtitleFixBusy = true;", INDEX_HTML)
        self.assertIn("state.movieSubtitleFixBusy = false;", INDEX_HTML)
        self.assertIn("function summarizeSubtitleFixResult(result)", INDEX_HTML)
        self.assertNotIn("Replacement Queue · Subtitle Readiness", INDEX_HTML)

    def test_movie_dashboard_has_replacement_queue_summary_without_detail_pane(self) -> None:
        self.assertIn("Deleted, Awaiting Replacement", INDEX_HTML)
        self.assertIn("from Replacement Queue", INDEX_HTML)
        self.assertIn("id=\"exportCatalogueButton\"", INDEX_HTML)
        self.assertIn("Export Catalogue", INDEX_HTML)
        self.assertIn("attachMovieDashboardHandlers(payload);", INDEX_HTML)
        self.assertNotIn("Generate Catalogue", INDEX_HTML)
        self.assertNotIn("catalogue-btn", INDEX_HTML)
        self.assertIn("For movies, this pane stays attached to the current directory's Replacement Queue.", INDEX_HTML)
        self.assertIn("library: 'Dashboard'", INDEX_HTML)
        self.assertIn("n_movie_dashboard_cache", INDEX_HTML)
        self.assertIn("function cacheMovieDashboard(payload)", INDEX_HTML)
        self.assertIn("function restoreCachedMovieDashboard(source)", INDEX_HTML)
        self.assertIn("cacheMovieDashboard(payload);", INDEX_HTML)
        self.assertIn("renderMovieLibrary(profile || restoreCachedMovieDashboard(source));", INDEX_HTML)
        self.assertIn("const total = histogram.movie_count ?? (payload.movies || []).length;", INDEX_HTML)
        self.assertIn("if (label === 'replacement_candidate') return 'Replacement Candidate';", INDEX_HTML)
        self.assertIn("'replacement_candidate'", INDEX_HTML)
        self.assertIn("function movieProfileInlineSummary(item)", INDEX_HTML)
        self.assertIn("const definitions = Array.isArray(payload.profile_definitions) ? payload.profile_definitions : [];", INDEX_HTML)
        self.assertIn("const definitionSummary = options?.rule_summary || '';", INDEX_HTML)
        self.assertIn("profile-card-band", INDEX_HTML)
        self.assertLess(INDEX_HTML.index("function humanProfileLabel"), INDEX_HTML.index("function buildMovieQualityTable"))
        library_section = INDEX_HTML.split("function renderMovieLibrary(payload) {", 1)[1].split(
            "function renderMovieQuality(payload) {",
            1,
        )[0]
        self.assertNotIn("renderReplacementQueueDetail(payload)", library_section)
        self.assertNotIn("attachMovieReplacementHandlers(payload)", library_section)

    def test_movie_dashboard_exposes_inline_profile_definition_controls(self) -> None:
        self.assertIn("/api/movies/standards/update", INDEX_HTML)
        self.assertIn("movieStandardsEditorLabel", INDEX_HTML)
        self.assertIn("movie-profile-definition-toggle", INDEX_HTML)
        self.assertIn("function buildMovieProfileDefinitionEditor(definition)", INDEX_HTML)
        self.assertIn("function movieProfileEditorValues(label)", INDEX_HTML)
        self.assertIn("function saveMovieProfileDefinition(label)", INDEX_HTML)
        self.assertIn("Saves to repo-local <span class=\"mono\">movie_standards.json</span> and reruns the dashboard.", INDEX_HTML)

    def test_movie_canonical_lists_page_is_wired(self) -> None:
        self.assertIn("id: 'canonical_lists'", INDEX_HTML)
        self.assertIn("label: 'Canonical Lists'", INDEX_HTML)
        self.assertIn("endpoint: '/api/movies/canonical-lists'", INDEX_HTML)
        self.assertIn("n_movie_canonical_lists_cache", INDEX_HTML)
        self.assertIn("function cacheMovieCanonicalLists(payload)", INDEX_HTML)
        self.assertIn("function restoreCachedMovieCanonicalLists(source)", INDEX_HTML)
        self.assertIn("renderMovieCanonicalLists(canonical || restoreCachedMovieCanonicalLists(source));", INDEX_HTML)
        self.assertIn("Badge Collection", INDEX_HTML)
        self.assertIn("This page ignores bitrate, quality, and warning telemetry.", INDEX_HTML)
        self.assertIn("Provider: TMDb canonical lists", INDEX_HTML)
        self.assertIn("Run Movies / Canonical Lists to compare the library against curated movie lists.", INDEX_HTML)
        canonical_section = INDEX_HTML.split("function renderMovieCanonicalLists(payload) {", 1)[1].split(
            "function renderMovieQuality(payload) {",
            1,
        )[0]
        self.assertNotIn("buildBitrateBellCurve(payload)", canonical_section)
        self.assertNotIn("renderReplacementQueueDetail(payload)", canonical_section)

    def test_movie_normalize_has_review_and_apply_workflow(self) -> None:
        self.assertIn("endpoint: '/api/movies/normalize'", INDEX_HTML)
        self.assertIn("'/api/movies/apply'", INDEX_HTML)
        self.assertIn("function applySelectedMovieChanges", INDEX_HTML)
        self.assertIn("showMovieNormalizeTreeDetail", INDEX_HTML)
        self.assertIn("All Safe", INDEX_HTML)

    def test_music_artwork_page_is_album_artist_browser(self) -> None:
        self.assertIn("label: 'Repair Artwork for Jellyfin'", INDEX_HTML)
        self.assertIn("class=\"artist-grid\"", INDEX_HTML)
        self.assertIn("Missing artist image", INDEX_HTML)
        self.assertIn("album artist folders", INDEX_HTML)
        self.assertIn("Write Selected to Library", INDEX_HTML)
        self.assertIn("Approve & Save", INDEX_HTML)
        self.assertIn("applySingleArtworkCandidate", INDEX_HTML)
        self.assertNotIn("Upgrade to High Confidence", INDEX_HTML)
        self.assertIn("Backfill Jellyfin", INDEX_HTML)
        self.assertIn("'/api/music/artwork/backfill-jellyfin'", INDEX_HTML)
        self.assertIn("source === 'jellyfin'", INDEX_HTML)
        self.assertIn("Find Candidates", INDEX_HTML)
        self.assertIn("Bing image search", INDEX_HTML)
        self.assertIn("source === 'image-search'", INDEX_HTML)
        self.assertIn("nextImageSearchCandidates", INDEX_HTML)
        self.assertIn("previousImageSearchCandidates", INDEX_HTML)
        self.assertIn("'/api/music/artwork/image-search'", INDEX_HTML)
        self.assertIn("'/api/music/artwork/candidates'", INDEX_HTML)
        self.assertIn("function artworkImageUrl", INDEX_HTML)
        self.assertIn("mtime_ns", INDEX_HTML)
        self.assertIn("const previewSrc = approved ? candidatePreviewUrl(approved) : imgSrc", INDEX_HTML)
        self.assertNotIn("Approved Replacement", INDEX_HTML)
        self.assertIn("artworkDropZone", INDEX_HTML)
        self.assertIn("approveDroppedArtwork", INDEX_HTML)
        self.assertIn("source: 'drop'", INDEX_HTML)
        self.assertIn("low confidence dropped image", INDEX_HTML)
        self.assertIn("split(/\\r?\\n/)", INDEX_HTML)
        self.assertNotIn("split(/\r?\n/)", INDEX_HTML)

    def test_music_dashboard_is_wired(self) -> None:
        self.assertIn("id: 'library', label: 'Dashboard View', action: 'scan', endpoint: '/api/music/profile'", INDEX_HTML)
        self.assertIn("'/api/music/profile'", INDEX_HTML)
        self.assertIn("n_music_dashboard_cache", INDEX_HTML)
        self.assertIn("function cacheMusicDashboard(payload)", INDEX_HTML)
        self.assertIn("function restoreCachedMusicDashboard(source)", INDEX_HTML)
        self.assertIn("renderMusicLibrary(profile || restoreCachedMusicDashboard(source));", INDEX_HTML)
        self.assertIn("MP3 Trash", INDEX_HTML)
        self.assertIn("MP3 High Quality", INDEX_HTML)
        self.assertIn("FLAC 16-bit / 44.1 kHz", INDEX_HTML)
        self.assertIn("FLAC 24-bit / 48 kHz", INDEX_HTML)
        self.assertIn("FLAC 24-bit / 192 kHz", INDEX_HTML)
        self.assertLess(INDEX_HTML.index("'mp3_trash'"), INDEX_HTML.index("'flac_24_192'"))
        self.assertIn("Format / Fidelity Breakdown", INDEX_HTML)
        self.assertIn("Signals Under Development", INDEX_HTML)
        self.assertIn("feature confidence: low", INDEX_HTML)

    def test_music_weak_encodes_page_is_wired(self) -> None:
        self.assertIn("id: 'music_quality', label: 'Delete Weak Encodes', action: 'scan', endpoint: '/api/music/profile'", INDEX_HTML)
        self.assertIn("'/api/music/replacement-queue/list'", INDEX_HTML)
        self.assertIn("'/api/music/replacement-queue/add'", INDEX_HTML)
        self.assertIn("'/api/music/replacement-queue/delete'", INDEX_HTML)
        self.assertIn("function renderMusicQuality", INDEX_HTML)
        self.assertIn("function buildMusicQualityTable", INDEX_HTML)
        self.assertIn("function isStrictWeakTrack", INDEX_HTML)
        self.assertIn("function strictWeakTracks", INDEX_HTML)
        self.assertIn("function musicReplacementQueueItemForPath", INDEX_HTML)
        self.assertIn("function musicReplacementQueueStatusChip", INDEX_HTML)
        self.assertIn("function attachMusicReplacementHandlers", INDEX_HTML)
        self.assertIn("function renderMusicReplacementQueueDetail", INDEX_HTML)
        self.assertIn("function buildMusicPendingReplacementTable", INDEX_HTML)
        self.assertIn("function attachMusicReplacementQueueDetailHandlers", INDEX_HTML)
        self.assertIn("function loadMusicReplacementQueue", INDEX_HTML)
        self.assertIn("function deleteMusicSelectedFiles", INDEX_HTML)
        self.assertIn("toggleAllMusicReplacementButton", INDEX_HTML)
        self.assertIn("deleteMusicSelectedFilesButton", INDEX_HTML)
        self.assertIn("['file','profile','format','bitrate','sample_rate','file_size']", INDEX_HTML)
        self.assertIn("['mp3_trash', 'unknown_unreadable']", INDEX_HTML)
        self.assertNotIn("resolution_bucket", INDEX_HTML.split("function buildMusicQualityTable")[1].split("function currentMusicReplacementQueue")[0])
        self.assertNotIn("video_bitrate_kbps", INDEX_HTML.split("function buildMusicQualityTable")[1].split("function currentMusicReplacementQueue")[0])
        music_table = INDEX_HTML.split("function buildMusicQualityTable")[1].split("function currentMusicReplacementQueue")[0]
        self.assertIn("File", music_table)
        self.assertIn("Profile", music_table)
        self.assertIn("Format", music_table)
        self.assertIn("Bitrate", music_table)
        self.assertIn("Sample Rate", music_table)
        self.assertIn("File Size", music_table)
        self.assertIn("Status", music_table)

    def test_delete_movie_junk_files_only_deletes_current_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            sample = source / "Movie.2000" / "RARBG.com.mp4"
            second_sample = source / "Movie.2000" / "Movie.sample.mp4"
            promo_document = source / "Movie.2000" / "RARBG.txt"
            movie = source / "Movie.2000" / "Movie.2000.mkv"
            sample.parent.mkdir()
            sample.write_text("sample", encoding="utf-8")
            second_sample.write_text("sample", encoding="utf-8")
            promo_document.write_text("Downloaded from RARBG", encoding="utf-8")
            with movie.open("wb") as handle:
                handle.truncate(101 * 1024 * 1024)

            result = delete_movie_junk_files(source, [sample, second_sample, promo_document, movie])

            self.assertEqual(
                result["deleted"],
                [str(sample.resolve()), str(second_sample.resolve()), str(promo_document.resolve())],
            )
            self.assertFalse(sample.exists())
            self.assertFalse(second_sample.exists())
            self.assertFalse(promo_document.exists())
            self.assertTrue(movie.exists())
            self.assertEqual(result["skipped"], [{"path": str(movie.resolve()), "reason": "not_current_junk_candidate"}])


if __name__ == "__main__":
    unittest.main()
