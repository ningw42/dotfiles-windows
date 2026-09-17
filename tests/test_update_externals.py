"""Behavioral tests for the updater's public operation, with HTTP mocked at transport."""

import http.client
import io
import json
import tomllib
import unittest
import urllib.error
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import update_externals


HASH_ABC = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
FIXED_DATA = f'''[external_resources.pins.theme]
url = "https://example.test/theme"
sha256 = "{'a' * 64}"
'''
SOURCE_DATA = f'''[external_resources.pins.skills]
url = "https://github.com/example/skills/archive/refs/tags/v1.tar.gz"
sha256 = "{'a' * 64}"
[external_resources.pins.skills.update]
type = "github_release"
repository = "example/skills"
tag = "v1"
'''

ASSET_DATA = f'''[external_resources.pins.bundle_x64]
url = "https://github.com/example/bundle/releases/download/v1/bundle-v1-x64.tgz"
sha256 = "{'a' * 64}"
[external_resources.pins.bundle_x64.update]
type = "github_release"
repository = "example/bundle"
tag = "v1"
asset = "bundle-{{tag}}-x64.tgz"

[external_resources.pins.bundle_arm64]
url = "https://github.com/example/bundle/releases/download/v1/bundle-v1-arm64.tgz"
sha256 = "{'b' * 64}"
[external_resources.pins.bundle_arm64.update]
type = "github_release"
repository = "example/bundle"
tag = "v1"
asset = "bundle-{{tag}}-arm64.tgz"
'''


class UpdateExternalsTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.path = self.root / ".chezmoidata.toml"
        self.path.write_text(FIXED_DATA, encoding="utf-8")

    def run_update(self, responses, *arguments):
        """Exercise CLI behavior; only the real HTTP transport is substituted."""
        def respond(request, **kwargs):
            url = getattr(request, "full_url", request)
            if url not in responses:
                raise AssertionError(f"Unexpected network request: {url}")
            response = responses[url]
            if callable(response):
                response = response()
            if isinstance(response, Exception):
                raise response
            if isinstance(response, dict):
                response = json.dumps(response).encode("utf-8")
            return response if hasattr(response, "read") else io.BytesIO(response)

        stdout, stderr = io.StringIO(), io.StringIO()
        with patch("urllib.request.urlopen", side_effect=respond), \
                redirect_stdout(stdout), redirect_stderr(stderr):
            status = update_externals.main(list(arguments), repo_root=self.root)
        return status, stdout.getvalue(), stderr.getvalue()

    def read_pins(self):
        return tomllib.loads(self.path.read_text(encoding="utf-8"))["external_resources"]["pins"]

    def test_configured_url_updates_only_structured_pin_data(self):
        manifest = self.root / "nested" / ".chezmoiexternal.toml.tmpl"
        manifest.parent.mkdir()
        original_manifest = b'url = "https://not-scanned.test/file"\nchecksum.sha256 = "' + b"f" * 64 + b'"\n'
        manifest.write_bytes(original_manifest)

        status, stdout, stderr = self.run_update({"https://example.test/theme": b"abc"})

        self.assertEqual(status, 1, stderr)
        self.assertEqual(self.read_pins()["theme"], {
            "url": "https://example.test/theme", "sha256": HASH_ABC,
        })
        self.assertEqual(manifest.read_bytes(), original_manifest)
        self.assertIn("Checked: 1", stdout)

    def test_source_release_updates_resolved_url_hash_and_tag_together(self):
        self.path.write_text(SOURCE_DATA, encoding="utf-8")
        archive_url = "https://github.com/example/skills/archive/refs/tags/release%2F2.tar.gz"
        status, stdout, stderr = self.run_update({
            "https://api.github.com/repos/example/skills/releases/latest": {"tag_name": "release/2"},
            archive_url: b"abc",
        })
        self.assertEqual(status, 1, stderr)
        pin = self.read_pins()["skills"]
        self.assertEqual(pin["url"], archive_url)
        self.assertEqual(pin["sha256"], HASH_ABC)
        self.assertEqual(pin["update"]["tag"], "release/2")

    def test_release_assets_share_one_release_and_use_api_digests_without_downloads(self):
        self.path.write_text(ASSET_DATA, encoding="utf-8")
        releases = iter([
            {"tag_name": "v2", "assets": [
                {"name": "bundle-v2-x64.tgz", "digest": "sha256:" + "C" * 64},
                {"name": "bundle-v2-arm64.tgz", "digest": "sha256:" + "d" * 64},
            ]},
            {"tag_name": "v3", "assets": []},
        ])
        status, stdout, stderr = self.run_update({
            "https://api.github.com/repos/example/bundle/releases/latest": lambda: next(releases),
        })
        self.assertEqual(status, 1, stderr)
        pins = self.read_pins()
        for arch, digest in [("x64", "c" * 64), ("arm64", "d" * 64)]:
            self.assertEqual(pins[f"bundle_{arch}"]["url"],
                             f"https://github.com/example/bundle/releases/download/v2/bundle-v2-{arch}.tgz")
            self.assertEqual(pins[f"bundle_{arch}"]["sha256"], digest)
            self.assertEqual(pins[f"bundle_{arch}"]["update"]["tag"], "v2")

    def test_missing_asset_prevents_every_pin_change(self):
        original = (FIXED_DATA + "\n" + ASSET_DATA).replace("\n", "\r\n").encode()
        self.path.write_bytes(original)
        status, stdout, stderr = self.run_update({
            "https://example.test/theme": b"abc",
            "https://api.github.com/repos/example/bundle/releases/latest": {
                "tag_name": "v2", "assets": [
                    {"name": "bundle-v2-x64.tgz", "digest": "sha256:" + "c" * 64},
                ],
            },
        })
        self.assertEqual(status, 2)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertIn("bundle_arm64", stderr)
        self.assertNotIn("[UPDATE]", stdout)
        self.assertIn("Updated: 0", stdout)
        self.assertEqual(list(self.root.iterdir()), [self.path])

    def test_invalid_release_metadata_never_writes_pins_or_downloads_assets(self):
        bad_releases = [b"not-json", b"[]", {}, {"tag_name": 2}, {"tag_name": ""},
                        {"tag_name": "v2"}, {"tag_name": "v2", "assets": {}}]
        for digest in [None, "", "c" * 64, "sha256:short", "sha512:" + "c" * 64, 42]:
            bad_releases.append({"tag_name": "v2", "assets": [
                {"name": "bundle-v2-x64.tgz", "digest": digest},
                {"name": "bundle-v2-arm64.tgz", "digest": "sha256:" + "d" * 64},
            ]})
        bad_releases.append({"tag_name": "v2", "assets": [
            {"name": "bundle-v2-x64.tgz", "digest": "sha256:" + "c" * 64},
            {"name": "bundle-v2-x64.tgz", "digest": "sha256:" + "d" * 64},
        ]})
        for release in bad_releases:
            with self.subTest(release=release):
                self.path.write_text(ASSET_DATA, encoding="utf-8")
                original = self.path.read_bytes()
                status, stdout, stderr = self.run_update({
                    "https://api.github.com/repos/example/bundle/releases/latest": release,
                })
                self.assertEqual(status, 2)
                self.assertEqual(self.path.read_bytes(), original)
                self.assertIn("[ERROR]", stderr)
                self.assertNotIn("[UPDATE]", stdout)

    def test_invalid_pin_data_fails_before_any_network_or_writes(self):
        invalid = [
            "[broken", "", "[external_resources.github_releases.legacy]\ntag = 'v1'\n",
            "[external_resources]\npins = []\n",
            FIXED_DATA.replace('url = "https://example.test/theme"', 'url = 42'),
            FIXED_DATA.replace("https://example.test/theme", "file:///tmp/local"),
            FIXED_DATA.replace("a" * 64, "invalid"),
            FIXED_DATA.replace('sha256 = "' + "a" * 64 + '"', 'checksum = "' + "a" * 64 + '"'),
            FIXED_DATA + '[external_resources.pins.theme.update]\n',
            SOURCE_DATA.replace('type = "github_release"', 'type = "unknown"'),
            SOURCE_DATA.replace('repository = "example/skills"', 'repository = "../skills"'),
            SOURCE_DATA.replace('tag = "v1"', 'tag = "v2"'),
            ASSET_DATA.replace('asset = "bundle-{tag}-x64.tgz"', 'asset = "bundle-{tag}-{tag}.tgz"'),
            ASSET_DATA.replace('asset = "bundle-{tag}-x64.tgz"', 'asset = ""'),
        ]
        for content in invalid:
            with self.subTest(content=content):
                self.path.write_text(content, encoding="utf-8")
                original = self.path.read_bytes()
                status, stdout, stderr = self.run_update({})
                self.assertEqual(status, 2)
                self.assertEqual(self.path.read_bytes(), original)
                self.assertIn("[ERROR]", stderr)

    def test_dry_run_reports_candidates_without_changing_even_formatting(self):
        original = b"# preserve me\r\n" + FIXED_DATA.replace("\n", "\r\n").encode()
        self.path.write_bytes(original)
        status, stdout, stderr = self.run_update({"https://example.test/theme": b"abc"}, "--dry-run")
        self.assertEqual(status, 1, stderr)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertIn("Updated: 1", stdout)
        self.assertIn("a" * 64, stdout)
        self.assertIn(HASH_ABC, stdout)
        self.assertIn("dry-run", stdout)

    def test_unchanged_pins_do_not_rewrite_the_document(self):
        original = ("# preserve me\n" + FIXED_DATA.replace("a" * 64, HASH_ABC)).encode()
        for arguments in [(), ("--dry-run",)]:
            with self.subTest(arguments=arguments):
                self.path.write_bytes(original)
                status, stdout, stderr = self.run_update({"https://example.test/theme": b"abc"}, *arguments)
                self.assertEqual(status, 0, stderr)
                self.assertEqual(self.path.read_bytes(), original)

    def test_network_failure_leaves_original_bytes(self):
        for error in [
            urllib.error.URLError("unreachable"), TimeoutError("timeout"),
            http.client.IncompleteRead(b"partial", 20), http.client.BadStatusLine("invalid HTTP"),
        ]:
            with self.subTest(error=error):
                original = self.path.read_bytes()
                status, stdout, stderr = self.run_update({"https://example.test/theme": error})
                self.assertEqual(status, 2)
                self.assertEqual(self.path.read_bytes(), original)
                self.assertIn(str(error), stderr)

    def test_atomic_replace_failure_keeps_data_and_cleans_temporary_file(self):
        original = self.path.read_bytes()
        with patch("os.replace", side_effect=PermissionError("replace denied")):
            status, stdout, stderr = self.run_update({"https://example.test/theme": b"abc"})
        self.assertEqual(status, 2)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(list(self.root.iterdir()), [self.path])
        self.assertIn("replace denied", stderr)
        self.assertNotIn("[UPDATE]", stdout)

    def test_concurrent_edit_is_not_overwritten(self):
        edited = self.path.read_bytes() + b"# edited while the download was in progress\n"
        def download():
            self.path.write_bytes(edited)
            return b"abc"
        status, stdout, stderr = self.run_update({"https://example.test/theme": download})
        self.assertEqual(status, 2)
        self.assertEqual(self.path.read_bytes(), edited)
        self.assertIn("changed", stderr)
        self.assertNotIn("[UPDATE]", stdout)

    def test_fully_empty_release_pin_can_be_initialized(self):
        self.path.write_text(SOURCE_DATA.replace(
            "https://github.com/example/skills/archive/refs/tags/v1.tar.gz", ""
        ).replace("a" * 64, "").replace('tag = "v1"', 'tag = ""'), encoding="utf-8")
        status, stdout, stderr = self.run_update({
            "https://api.github.com/repos/example/skills/releases/latest": {"tag_name": "v2"},
            "https://github.com/example/skills/archive/refs/tags/v2.tar.gz": b"abc",
        })
        self.assertEqual(status, 1, stderr)
        self.assertEqual(self.read_pins()["skills"]["sha256"], HASH_ABC)
        self.assertEqual(self.read_pins()["skills"]["update"]["tag"], "v2")

    def test_canonical_write_preserves_unrelated_toml_values(self):
        content = '''title = "unrelated \\"text\\""
extra = { "odd.key" = ["text", true, 2, 3.5], day = 2026-01-02, clock = 03:04:05, when = 2026-01-02T03:04:05Z, links = [{ name = "one" }] }
''' + FIXED_DATA
        original = tomllib.loads(content)
        self.path.write_text(content, encoding="utf-8")
        status, stdout, stderr = self.run_update({"https://example.test/theme": b"abc"})
        self.assertEqual(status, 1, stderr)
        result = tomllib.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(result["extra"], original["extra"])
        self.assertEqual(result["title"], original["title"])
        self.assertEqual(result["external_resources"]["pins"]["theme"]["sha256"], HASH_ABC)

    def test_canonical_write_round_trips_unicode_and_escaped_control_characters(self):
        content = '"标签😀" = "文字😀\\u007f"\n' + FIXED_DATA
        self.path.write_text(content, encoding="utf-8")
        status, stdout, stderr = self.run_update({"https://example.test/theme": b"abc"})
        self.assertEqual(status, 1, stderr)
        self.assertEqual(tomllib.loads(self.path.read_text(encoding="utf-8"))["标签😀"], "文字😀\x7f")

    def test_static_asset_name_and_tag_are_path_escaped(self):
        content = ASSET_DATA.split("[external_resources.pins.bundle_arm64]")[0]
        content = content.replace("bundle-v1-x64.tgz", "status%20bar.wasm")
        content = content.replace("bundle-{tag}-x64.tgz", "status bar.wasm")
        self.path.write_text(content, encoding="utf-8")
        status, stdout, stderr = self.run_update({
            "https://api.github.com/repos/example/bundle/releases/latest": {
                "tag_name": 'v"2', "assets": [
                    {"name": "status bar.wasm", "digest": "sha256:" + "c" * 64},
                ],
            },
        })
        self.assertEqual(status, 1, stderr)
        pin = self.read_pins()["bundle_x64"]
        self.assertEqual(pin["url"], "https://github.com/example/bundle/releases/download/v%222/status%20bar.wasm")
        self.assertEqual(pin["update"]["tag"], 'v"2')
        self.assertEqual(pin["update"]["asset"], "status bar.wasm")

    def test_same_release_tag_still_rehashes_its_source_archive(self):
        self.path.write_text(SOURCE_DATA, encoding="utf-8")
        status, stdout, stderr = self.run_update({
            "https://api.github.com/repos/example/skills/releases/latest": {"tag_name": "v1"},
            "https://github.com/example/skills/archive/refs/tags/v1.tar.gz": b"abc",
        })
        self.assertEqual(status, 1, stderr)
        self.assertEqual(self.read_pins()["skills"]["sha256"], HASH_ABC)
        self.assertEqual(self.read_pins()["skills"]["update"]["tag"], "v1")

    def test_artifact_download_is_hashed_in_bounded_chunks(self):
        class ChunkedResponse(io.BytesIO):
            def read(self, size=-1):
                if size <= 0:
                    raise AssertionError("Unbounded artifact read")
                return super().read(min(size, 1))
        status, stdout, stderr = self.run_update({"https://example.test/theme": ChunkedResponse(b"abc")})
        self.assertEqual(status, 1, stderr)
        self.assertEqual(self.read_pins()["theme"]["sha256"], HASH_ABC)

    def test_missing_or_unreadable_data_is_a_reported_error(self):
        self.path.unlink()
        status, stdout, stderr = self.run_update({})
        self.assertEqual(status, 2)
        self.assertIn("[ERROR]", stderr)
        self.path.write_bytes(FIXED_DATA.encode())
        with patch.object(Path, "read_bytes", side_effect=PermissionError("read denied")):
            status, stdout, stderr = self.run_update({})
        self.assertEqual(status, 2)
        self.assertIn("read denied", stderr)
        self.assertEqual(self.path.read_bytes(), FIXED_DATA.encode())

    def test_later_invalid_pin_is_rejected_before_fetching_any_earlier_pin(self):
        content = FIXED_DATA + "\n" + SOURCE_DATA.replace('tag = "v1"', 'tag = ""')
        self.path.write_text(content, encoding="utf-8")
        status, stdout, stderr = self.run_update({})
        self.assertEqual(status, 2)
        self.assertIn("skills", stderr)
        self.assertEqual(self.path.read_text(encoding="utf-8"), content)

    def test_truncated_content_length_never_becomes_an_accepted_pin(self):
        class Socket:
            def makefile(self, *args):
                return io.BytesIO(b"HTTP/1.1 200 OK\r\nContent-Length: 100\r\n\r\nabc")
        def response():
            result = http.client.HTTPResponse(Socket())
            result.begin()
            return result
        original = self.path.read_bytes()
        for arguments in [(), ("--dry-run",)]:
            with self.subTest(arguments=arguments):
                self.path.write_bytes(original)
                status, stdout, stderr = self.run_update({"https://example.test/theme": response}, *arguments)
                self.assertEqual(status, 2)
                self.assertEqual(self.path.read_bytes(), original)
                self.assertIn("Content-Length", stderr)
                self.assertNotIn("[UPDATE]", stdout)


if __name__ == "__main__":
    unittest.main()
