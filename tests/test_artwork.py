from __future__ import annotations

import base64
import io
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from normal.artwork import (
    ArtworkGapItem,
    apply_artwork,
    backfill_jellyfin_artist_artwork,
    extract_bing_image_search_candidates,
    find_album_artwork_candidates,
    extract_image_urls,
    has_reasonable_image_size_hint,
    is_candidate_page_url,
    resolve_cached_artwork,
    resolve_data_url_artwork,
    resolve_file_artwork,
    resolve_remote_artwork,
    scan_artist_artwork,
    sync_jellyfin_artist_metadata_artwork,
)


class ArtworkTests(unittest.TestCase):
    def test_scan_uses_jellyfin_artist_metadata_as_present_artwork(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            library = root / "music"
            jellyfin_artists = root / "jellyfin" / "metadata" / "artists"
            artist = library / "Between The Buried And Me"
            metadata_artist = jellyfin_artists / "Between the Buried and Me"
            artist.mkdir(parents=True)
            metadata_artist.mkdir(parents=True)
            Image.new("RGB", (80, 80), (20, 40, 80)).save(metadata_artist / "folder.jpg")

            report = scan_artist_artwork(library, jellyfin_artists_root=jellyfin_artists)

            self.assertEqual(report.missing, [])
            self.assertEqual(len(report.present), 1)
            self.assertEqual(report.present[0].artist_name, "Between The Buried And Me")
            self.assertEqual(report.present[0].source, "jellyfin")
            self.assertEqual(report.present[0].filename, "folder.jpg")

    def test_apply_copies_jellyfin_artist_artwork_to_artist_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            library = root / "music"
            jellyfin_artists = root / "jellyfin" / "metadata" / "artists"
            artist = library / "Burial"
            metadata_artist = jellyfin_artists / "Burial"
            artist.mkdir(parents=True)
            metadata_artist.mkdir(parents=True)
            Image.new("RGB", (80, 80), (20, 40, 80)).save(metadata_artist / "folder.jpg")
            report = scan_artist_artwork(library, jellyfin_artists_root=jellyfin_artists)

            results = apply_artwork([resolve_cached_artwork(report.present[0])])

            self.assertEqual(results[0].status, "written")
            self.assertTrue((artist / "artist.jpg").is_file())
            self.assertTrue((artist / "folder.jpg").is_file())
            with Image.open(artist / "artist.jpg") as image:
                self.assertEqual(image.size, (80, 80))
            with Image.open(artist / "folder.jpg") as image:
                self.assertEqual(image.size, (80, 80))

    def test_apply_does_not_overwrite_existing_artist_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            library = root / "music"
            jellyfin_artists = root / "jellyfin" / "metadata" / "artists"
            artist = library / "Periphery"
            metadata_artist = jellyfin_artists / "Periphery"
            artist.mkdir(parents=True)
            metadata_artist.mkdir(parents=True)
            Image.new("RGB", (80, 80), (20, 40, 80)).save(metadata_artist / "folder.jpg")
            Image.new("RGB", (20, 20), (200, 20, 40)).save(artist / "artist.jpg")
            report = scan_artist_artwork(library, jellyfin_artists_root=jellyfin_artists)

            results = apply_artwork([resolve_cached_artwork(report.present[0])])

            self.assertEqual(results[0].status, "skipped")
            self.assertEqual(results[0].message, "artist.jpg already exists")
            with Image.open(artist / "artist.jpg") as image:
                self.assertEqual(image.size, (20, 20))
            self.assertFalse((artist / "folder.jpg").is_file())

    def test_apply_can_explicitly_replace_existing_artist_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            artist = root / "Artist"
            album = artist / "2001 - Album"
            album.mkdir(parents=True)
            Image.new("RGB", (20, 20), (200, 20, 40)).save(artist / "artist.jpg")
            Image.new("RGB", (90, 90), (20, 120, 80)).save(album / "cover.jpg")
            gap = ArtworkGapItem(artist_name="Artist", folder_path=str(artist))

            results = apply_artwork([resolve_file_artwork(gap, str(album / "cover.jpg"), "album")], overwrite=True)

            self.assertEqual(results[0].status, "written")
            with Image.open(artist / "artist.jpg") as image:
                self.assertEqual(image.size, (90, 90))
            with Image.open(artist / "folder.jpg") as image:
                self.assertEqual(image.size, (90, 90))

    def test_remote_artwork_rejects_unapproved_hosts(self) -> None:
        gap = ArtworkGapItem(artist_name="Artist", folder_path="/tmp/Artist")

        resolution = resolve_remote_artwork(gap, "https://example.com/image.jpg", "wikimedia")

        self.assertEqual(resolution.source, "wikimedia")
        self.assertIsNone(resolution.image_bytes)

    def test_album_artwork_candidates_use_local_album_covers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            artist = Path(tmpdir) / "Artist"
            album = artist / "2001 - Album"
            album.mkdir(parents=True)
            Image.new("RGB", (90, 90), (20, 120, 80)).save(album / "cover.jpg")
            gap = ArtworkGapItem(artist_name="Artist", folder_path=str(artist))

            candidates = find_album_artwork_candidates(gap)

            self.assertEqual(len(candidates), 1)
            self.assertEqual(candidates[0].source, "album")
            self.assertEqual(candidates[0].title, "2001 - Album/cover.jpg")

    def test_apply_can_write_approved_local_album_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            artist = Path(tmpdir) / "Artist"
            album = artist / "2001 - Album"
            album.mkdir(parents=True)
            Image.new("RGB", (90, 90), (20, 120, 80)).save(album / "cover.jpg")
            gap = ArtworkGapItem(artist_name="Artist", folder_path=str(artist))

            results = apply_artwork([resolve_file_artwork(gap, str(album / "cover.jpg"), "album")])

            self.assertEqual(results[0].status, "written")
            self.assertEqual(results[0].source, "album")
            self.assertTrue((artist / "artist.jpg").is_file())
            self.assertTrue((artist / "folder.jpg").is_file())

            report = scan_artist_artwork(Path(tmpdir))

            self.assertEqual(report.present[0].source, "album")
            self.assertGreater(report.present[0].mtime_ns, 0)
            self.assertTrue((artist / "artist.normal-artwork.json").is_file())

    def test_data_url_artwork_can_write_dropped_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            artist = Path(tmpdir) / "Artist"
            artist.mkdir()
            buf = io.BytesIO()
            Image.new("RGB", (40, 40), (20, 80, 140)).save(buf, format="PNG")
            data_url = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
            gap = ArtworkGapItem(artist_name="Artist", folder_path=str(artist))

            results = apply_artwork([resolve_data_url_artwork(gap, data_url, "drop", title="drop.png")])

            self.assertEqual(results[0].status, "written")
            report = scan_artist_artwork(Path(tmpdir))
            self.assertEqual(report.present[0].source, "drop")

    def test_backfill_jellyfin_artist_artwork_mirrors_artist_jpg(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            artist = root / "Artist"
            missing = root / "Missing"
            artist.mkdir()
            missing.mkdir()
            Image.new("RGB", (50, 50), (90, 20, 140)).save(artist / "artist.jpg")

            result = backfill_jellyfin_artist_artwork(root)

            self.assertEqual(result["written"], [str(artist / "folder.jpg")])
            self.assertTrue((artist / "folder.jpg").is_file())
            self.assertFalse((missing / "folder.jpg").exists())

    def test_sync_jellyfin_artist_metadata_artwork_writes_and_backs_up_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            library = root / "music"
            jellyfin_artists = root / "jellyfin" / "metadata" / "artists"
            artist = library / "Burial"
            metadata_artist = jellyfin_artists / "Burial"
            artist.mkdir(parents=True)
            metadata_artist.mkdir(parents=True)
            Image.new("RGB", (60, 60), (20, 80, 140)).save(artist / "folder.jpg")
            Image.new("RGB", (30, 30), (200, 40, 40)).save(metadata_artist / "folder.jpg")

            result = sync_jellyfin_artist_metadata_artwork(library, jellyfin_artists_root=jellyfin_artists)

            self.assertEqual(result["written"], [str(metadata_artist / "folder.jpg")])
            self.assertEqual(len(result["backed_up"]), 1)
            self.assertTrue(Path(result["backed_up"][0]).is_file())
            with Image.open(metadata_artist / "folder.jpg") as image:
                self.assertEqual(image.size, (60, 60))

    def test_sync_jellyfin_artist_metadata_artwork_skips_missing_metadata_artist(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            library = root / "music"
            jellyfin_artists = root / "jellyfin" / "metadata" / "artists"
            artist = library / "New Artist"
            artist.mkdir(parents=True)
            jellyfin_artists.mkdir(parents=True)
            Image.new("RGB", (60, 60), (20, 80, 140)).save(artist / "folder.jpg")

            result = sync_jellyfin_artist_metadata_artwork(library, jellyfin_artists_root=jellyfin_artists)

            self.assertEqual(result["written"], [])
            self.assertEqual(result["skipped"], [{"path": str(artist), "reason": "missing_jellyfin_metadata_artist"}])

    def test_web_candidate_page_url_prefers_official_artist_sites(self) -> None:
        self.assertTrue(is_candidate_page_url("https://www.berriedaliveofficial.com/gallery", "Berried Alive"))
        self.assertFalse(is_candidate_page_url("https://www.facebook.com/berriedalivemn/photos", "Berried Alive"))
        self.assertFalse(is_candidate_page_url("https://musify.club/en/artist/berried-alive-362140/photos", "Berried Alive"))

    def test_extract_image_urls_reads_social_meta_and_images(self) -> None:
        payload = """
        <meta property="og:image" content="https://static.example.com/artist.jpg">
        <img src="/photo.png">
        """

        urls = extract_image_urls(payload, "https://example.com/about")

        self.assertEqual(urls, [
            "https://static.example.com/artist.jpg",
            "https://example.com/photo.png",
        ])

    def test_web_candidate_size_hint_filters_tiny_assets(self) -> None:
        self.assertFalse(has_reasonable_image_size_hint("https://example.com/image.png/v1/fill/w_86,h_65/image.png"))
        self.assertTrue(has_reasonable_image_size_hint("https://example.com/image.jpg/v1/fill/w_1920,h_1080/image.jpg"))
        self.assertTrue(has_reasonable_image_size_hint("https://example.com/image.jpg"))

    def test_image_search_candidates_read_bing_image_metadata(self) -> None:
        gap = ArtworkGapItem(artist_name="ASAVA", folder_path="/tmp/ASAVA")
        payload = """
        <a class="iusc" m="{&quot;purl&quot;:&quot;https://westsidebowl.com/event/asava&quot;,&quot;murl&quot;:&quot;https://westsidebowl.com/uploads/ASAVA-band.png&quot;,&quot;turl&quot;:&quot;https://ts1.mm.bing.net/th?id=OIP.test&amp;pid=15.1&quot;,&quot;t&quot;:&quot;ASAVA band photo&quot;}"></a>
        <a class="iusc" m="{&quot;purl&quot;:&quot;https://facebook.com/asava&quot;,&quot;murl&quot;:&quot;https://facebook.com/photo.jpg&quot;,&quot;t&quot;:&quot;ignored social result&quot;}"></a>
        """

        candidates = extract_bing_image_search_candidates(gap, payload)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].source, "image-search")
        self.assertEqual(candidates[0].image_url, "https://westsidebowl.com/uploads/ASAVA-band.png")
        self.assertEqual(candidates[0].page_url, "https://westsidebowl.com/event/asava")


if __name__ == "__main__":
    unittest.main()
