import hashlib
import io
import tomllib
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

import update_externals


REPO_ROOT = Path(__file__).resolve().parents[1]


DATA = """
[external_resources.github_releases.superpowers]
repository = "obra/superpowers"
tag = "6.1.0"
sha256 = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
""".lstrip()

EMPTY_DATA = """
[external_resources.github_releases.superpowers]
repository = "obra/superpowers"
tag = ""
sha256 = ""
""".lstrip()

TWO_PIN_DATA = DATA + """

[external_resources.github_releases.other]
repository = "example/other"
tag = "1.0.0"
sha256 = "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
"""

EXTERNAL_DATA = """
["resource.txt"]
type = "file"
url = "https://example.test/resource.txt"
checksum.sha256 = "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
""".lstrip()


class RepositoryGithubReleaseConfigurationTests(unittest.TestCase):
    def test_repository_declares_mattpocock_skills_release_pin(self):
        content = (REPO_ROOT / ".chezmoidata.toml").read_text(encoding="utf-8")
        pins = {
            pin.name: pin
            for pin in update_externals.extract_github_release_pins(content)
        }

        pin = pins["mattpocock_skills"]
        self.assertEqual(pin.repository, "mattpocock/skills")
        self.assertTrue(pin.tag)
        self.assertRegex(pin.sha256, r"^[0-9a-f]{64}$")


class GithubReleasePinParsingTests(unittest.TestCase):
    def test_extracts_github_release_pin(self):
        pins = update_externals.extract_github_release_pins(DATA)

        self.assertEqual(len(pins), 1)
        self.assertEqual(pins[0].name, "superpowers")
        self.assertEqual(pins[0].repository, "obra/superpowers")
        self.assertEqual(pins[0].tag, "6.1.0")

    def test_applies_tag_and_checksum_update_together(self):
        pin = update_externals.extract_github_release_pins(DATA)[0]

        updated = update_externals.apply_github_release_updates(
            DATA, [(pin, "6.1.1", "b" * 64)]
        )

        self.assertIn('tag = "6.1.1"', updated)
        self.assertIn(f'sha256 = "{"b" * 64}"', updated)
        self.assertNotIn("6.1.0", updated)

    def test_escapes_and_round_trips_quote_in_updated_tag(self):
        pin = update_externals.extract_github_release_pins(DATA)[0]

        updated = update_externals.apply_github_release_updates(
            DATA, [(pin, 'release"1', "b" * 64)]
        )

        parsed = tomllib.loads(updated)
        self.assertEqual(
            parsed["external_resources"]["github_releases"]["superpowers"]["tag"],
            'release"1',
        )
        self.assertEqual(
            update_externals.extract_github_release_pins(updated)[0].tag,
            'release"1',
        )

    def test_accepts_fully_empty_pin_for_first_refresh(self):
        pin = update_externals.extract_github_release_pins(EMPTY_DATA)[0]

        self.assertEqual(pin.tag, "")
        self.assertEqual(pin.sha256, "")

    def test_extracts_pin_from_crlf_metadata(self):
        pin = update_externals.extract_github_release_pins(
            DATA.replace("\n", "\r\n")
        )[0]

        self.assertEqual(pin.repository, "obra/superpowers")
        self.assertEqual(pin.tag, "6.1.0")

    def test_ignores_keys_outside_github_release_sections(self):
        content = """
[unrelated]
repository = "obra/superpowers"
tag = "6.1.0"
sha256 = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
""".lstrip()

        self.assertEqual(update_externals.extract_github_release_pins(content), [])

    def test_rejects_empty_repository(self):
        invalid = DATA.replace("obra/superpowers", "")

        with self.assertRaises(ValueError):
            update_externals.extract_github_release_pins(invalid)

    def test_rejects_invalid_checksum(self):
        invalid = DATA.replace("a" * 64, "not-a-checksum")

        with self.assertRaises(ValueError):
            update_externals.extract_github_release_pins(invalid)


class GithubReleaseLookupTests(unittest.TestCase):
    def test_fetch_sha256_hashes_response_in_fixed_size_chunks(self):
        class ChunkedResponse:
            def __init__(self):
                self.chunks = iter((b"abc", b"def", b""))
                self.read_sizes = []

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self, size=-1):
                if size < 0:
                    raise AssertionError("unbounded read attempted")
                self.read_sizes.append(size)
                return next(self.chunks)

        response = ChunkedResponse()
        with patch.object(
            update_externals.urllib.request, "urlopen", return_value=response
        ):
            try:
                digest = update_externals.fetch_sha256(
                    "https://example.test/archive"
                )
            except AssertionError as error:
                self.fail(str(error))

        self.assertEqual(digest, hashlib.sha256(b"abcdef").hexdigest())
        self.assertTrue(response.read_sizes)
        self.assertEqual(len(set(response.read_sizes)), 1)
        self.assertGreater(response.read_sizes[0], 0)

    def test_fetches_latest_release_tag_from_github_api(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{"tag_name":"6.1.1"}'

        with patch.object(update_externals.urllib.request, "urlopen", return_value=response) as urlopen:
            tag = update_externals.fetch_latest_release_tag(
                "obra/superpowers", timeout=12
            )

        self.assertEqual(tag, "6.1.1")
        request = urlopen.call_args.args[0]
        self.assertEqual(
            request.full_url,
            "https://api.github.com/repos/obra/superpowers/releases/latest",
        )
        self.assertEqual(request.get_header("Accept"), "application/vnd.github+json")
        self.assertEqual(
            request.get_header("User-agent"), "chezmoi-update-externals"
        )
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 12)

    def test_fetch_latest_release_tag_catches_invalid_url(self):
        with patch.object(
            update_externals.urllib.request,
            "Request",
            side_effect=ValueError("invalid URL"),
        ), redirect_stderr(io.StringIO()):
            tag = update_externals.fetch_latest_release_tag("invalid\nrepository")

        self.assertIsNone(tag)

    def test_build_update_returns_none_without_latest_release(self):
        with patch.object(update_externals, "fetch_latest_release_tag", return_value=None):
            self.assertIsNone(
                update_externals.build_github_release_update("obra/superpowers")
            )

    def test_archive_url_quotes_entire_tag(self):
        self.assertEqual(
            update_externals.github_archive_url(
                "obra/superpowers", "release/6.1.1"
            ),
            "https://github.com/obra/superpowers/archive/refs/tags/"
            "release%2F6.1.1.tar.gz",
        )

    def test_build_update_hashes_latest_release_archive(self):
        with patch.object(
            update_externals,
            "fetch_latest_release_tag",
            return_value="release/6.1.1",
        ), patch.object(
            update_externals, "fetch_sha256", return_value="b" * 64
        ) as fetch_sha256:
            result = update_externals.build_github_release_update(
                "obra/superpowers"
            )

        self.assertEqual(result, ("release/6.1.1", "b" * 64))
        fetch_sha256.assert_called_once_with(
            "https://github.com/obra/superpowers/archive/refs/tags/"
            "release%2F6.1.1.tar.gz"
        )


class GithubReleaseMetadataUpdateTests(unittest.TestCase):
    def write_metadata(self, directory, content=DATA):
        path = Path(directory) / ".chezmoidata.toml"
        path.write_bytes(content.encode("utf-8"))
        return path

    def test_updates_metadata_after_pin_resolves_and_verifies(self):
        with TemporaryDirectory() as directory:
            path = self.write_metadata(directory)
            with patch.object(
                update_externals,
                "build_github_release_update",
                return_value=("6.1.1", "b" * 64),
            ), redirect_stdout(io.StringIO()):
                result = update_externals.update_github_release_metadata(path)

            self.assertEqual(result, (1, 0))
            self.assertEqual(
                path.read_bytes(),
                DATA.replace("6.1.0", "6.1.1")
                .replace("a" * 64, "b" * 64)
                .encode("utf-8"),
            )

    def test_first_refresh_populates_empty_tag_and_checksum(self):
        with TemporaryDirectory() as directory:
            path = self.write_metadata(directory, EMPTY_DATA)
            with patch.object(
                update_externals,
                "build_github_release_update",
                return_value=("6.1.1", "b" * 64),
            ), redirect_stdout(io.StringIO()):
                result = update_externals.update_github_release_metadata(path)

            self.assertEqual(result, (1, 0))
            self.assertIn(b'tag = "6.1.1"', path.read_bytes())
            self.assertIn(f'sha256 = "{"b" * 64}"'.encode(), path.read_bytes())

    def test_archive_failure_leaves_original_bytes(self):
        with TemporaryDirectory() as directory:
            path = self.write_metadata(directory)
            original = path.read_bytes()
            with patch.object(
                update_externals,
                "fetch_latest_release_tag",
                return_value="6.1.1",
            ), patch.object(
                update_externals, "fetch_sha256", return_value=None
            ), redirect_stderr(io.StringIO()):
                result = update_externals.update_github_release_metadata(path)

            self.assertEqual(result, (0, 1))
            self.assertEqual(path.read_bytes(), original)

    def test_failure_on_second_pin_leaves_original_bytes(self):
        with TemporaryDirectory() as directory:
            path = self.write_metadata(directory, TWO_PIN_DATA)
            original = path.read_bytes()
            output = io.StringIO()
            with patch.object(
                update_externals,
                "build_github_release_update",
                side_effect=[("6.1.1", "b" * 64), None],
            ), redirect_stdout(output), redirect_stderr(io.StringIO()):
                result = update_externals.update_github_release_metadata(path)

            self.assertEqual(result, (0, 1))
            self.assertEqual(path.read_bytes(), original)
            self.assertNotIn("[UPDATE]", output.getvalue())

    def test_dry_run_reports_update_without_changing_bytes(self):
        with TemporaryDirectory() as directory:
            path = self.write_metadata(directory)
            original = path.read_bytes()
            output = io.StringIO()
            with patch.object(
                update_externals,
                "build_github_release_update",
                return_value=("6.1.1", "b" * 64),
            ), redirect_stdout(output):
                result = update_externals.update_github_release_metadata(
                    path, dry_run=True
                )

            self.assertEqual(result, (1, 0))
            self.assertEqual(path.read_bytes(), original)
            report = output.getvalue()
            self.assertIn("6.1.0", report)
            self.assertIn("6.1.1", report)
            self.assertIn("a" * 64, report)
            self.assertIn("b" * 64, report)

    def test_half_initialized_metadata_raises_without_changing_bytes(self):
        half_initialized = EMPTY_DATA.replace('tag = ""', 'tag = "6.1.0"')
        with TemporaryDirectory() as directory:
            path = self.write_metadata(directory, half_initialized)
            original = path.read_bytes()

            with self.assertRaises(ValueError):
                update_externals.update_github_release_metadata(path)

            self.assertEqual(path.read_bytes(), original)


class MainExitStatusTests(unittest.TestCase):
    def run_main(self, metadata_result, argv=None):
        with TemporaryDirectory() as directory, patch.object(
            update_externals,
            "find_external_files",
            return_value=[],
        ), patch.object(
            update_externals,
            "update_github_release_metadata",
            return_value=metadata_result,
        ), patch("builtins.print"):
            return update_externals.main(argv or [], Path(directory))

    def test_returns_zero_when_metadata_is_unchanged(self):
        self.assertEqual(self.run_main((0, 0)), 0)

    def test_returns_one_when_metadata_changes(self):
        self.assertEqual(self.run_main((1, 0)), 1)

    def test_returns_one_for_dry_run_metadata_changes(self):
        self.assertEqual(self.run_main((1, 0), ["--dry-run"]), 1)

    def test_returns_two_when_metadata_has_errors(self):
        self.assertEqual(self.run_main((0, 1)), 2)

    def test_metadata_read_failure_is_reported_as_exit_two(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / ".chezmoidata.toml"
            path.write_bytes(DATA.encode("utf-8"))
            original = path.read_bytes()
            output = io.StringIO()
            with patch.object(
                Path, "read_bytes", side_effect=PermissionError("read denied")
            ), patch.object(
                update_externals, "find_external_files", return_value=[]
            ), redirect_stdout(io.StringIO()), redirect_stderr(output):
                try:
                    result = update_externals.main([], root)
                except OSError as error:
                    self.fail(f"metadata read error escaped main: {error}")

            self.assertEqual(result, 2)
            self.assertIn("read denied", output.getvalue())
            self.assertEqual(path.read_bytes(), original)

    def test_metadata_write_failure_is_reported_without_changing_bytes(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / ".chezmoidata.toml"
            path.write_bytes(DATA.encode("utf-8"))
            original = path.read_bytes()
            output = io.StringIO()
            with patch.object(
                update_externals,
                "build_github_release_update",
                return_value=("6.1.1", "b" * 64),
            ), patch.object(
                Path, "write_bytes", side_effect=PermissionError("write denied")
            ), patch.object(
                update_externals, "find_external_files", return_value=[]
            ), redirect_stdout(io.StringIO()), redirect_stderr(output):
                try:
                    result = update_externals.main([], root)
                except OSError as error:
                    self.fail(f"metadata write error escaped main: {error}")

            self.assertEqual(result, 2)
            self.assertIn("write denied", output.getvalue())
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(list(root.iterdir()), [path])

    def test_combines_metadata_and_external_checksum_updates(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            metadata_path = root / ".chezmoidata.toml"
            metadata_path.write_bytes(DATA.encode("utf-8"))
            external_path = root / "nested" / ".chezmoiexternal.toml"
            external_path.parent.mkdir()
            external_path.write_bytes(EXTERNAL_DATA.encode("utf-8"))
            output = io.StringIO()

            with patch.object(
                update_externals,
                "build_github_release_update",
                return_value=("6.1.1", "b" * 64),
            ), patch.object(
                update_externals, "fetch_sha256", return_value="d" * 64
            ), patch.object(update_externals.time, "sleep"), redirect_stdout(
                output
            ):
                result = update_externals.main([], root)

            self.assertEqual(result, 1)
            self.assertIn(b'tag = "6.1.1"', metadata_path.read_bytes())
            self.assertIn(
                f'sha256 = "{"b" * 64}"'.encode(), metadata_path.read_bytes()
            )
            external_bytes = external_path.read_bytes()
            self.assertIn(
                b'url = "https://example.test/resource.txt"', external_bytes
            )
            self.assertIn(
                f'checksum.sha256 = "{"d" * 64}"'.encode(), external_bytes
            )
            self.assertIn("Checked: 1  Updated: 2  Errors: 0", output.getvalue())


if __name__ == "__main__":
    unittest.main()
