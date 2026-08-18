#!/usr/bin/env python3
"""Update SHA-256 checksums for all chezmoi external resources."""

import argparse
import hashlib
import json
import re
import sys
import tempfile
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

PAIR_RE = re.compile(
    r'^[ \t]*url\s*=\s*"(?P<url>[^"]+)"'
    r'(?:\r?\n[ \t]+[^\r\n]*)*\r?\n'
    r'[ \t]*checksum\.sha256\s*=\s*"(?P<hash>[0-9a-fA-F]{64})"',
    re.MULTILINE,
)

SECTION_HEADER_RE = re.compile(
    r"^[ \t]*\[(?P<section>[^\]\r\n]+)\][ \t]*(?:#[^\r\n]*)?(?:\r?\n|$)",
    re.MULTILINE,
)

TOML_BASIC_STRING_RE = re.compile(
    r'^[ \t]*(?P<key>[A-Za-z0-9_-]+)[ \t]*=[ \t]*"'
    r'(?P<value>(?:[^"\\\r\n]|\\.)*)"[ \t]*(?:#[^\r\n]*)?\r?$',
    re.MULTILINE,
)

GITHUB_RELEASE_SECTION_PREFIX = "external_resources.github_releases."
GITHUB_RELEASE_ASSET_SECTION_PREFIX = "external_resources.github_release_assets."
DOWNLOAD_CHUNK_SIZE = 1024 * 1024
SHA256_RE = re.compile(r"[0-9a-fA-F]{64}")
GITHUB_SHA256_DIGEST_RE = re.compile(r"sha256:(?P<sha256>[0-9a-fA-F]{64})")


@dataclass(frozen=True)
class GithubReleasePin:
    name: str
    repository: str
    tag: str
    sha256: str
    tag_span: tuple[int, int]
    sha256_span: tuple[int, int]


@dataclass(frozen=True)
class GithubReleaseAsset:
    name: str
    filename: str
    sha256: str
    sha256_span: tuple[int, int]


@dataclass(frozen=True)
class GithubReleaseAssetPin:
    name: str
    repository: str
    tag: str
    tag_span: tuple[int, int]
    assets: tuple[GithubReleaseAsset, ...]


def find_external_files(repo_root):
    return sorted(repo_root.rglob(".chezmoiexternal.toml*"))


def extract_url_checksum_pairs(content):
    """Return (URL, checksum, checksum start, checksum end) tuples."""
    return [
        (match.group("url"), match.group("hash"), *match.span("hash"))
        for match in PAIR_RE.finditer(content)
    ]


def fetch_sha256(url, timeout=30):
    """Download url and return sha256 hex digest, or None on error."""
    try:
        digest = hashlib.sha256()
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            while chunk := resp.read(DOWNLOAD_CHUNK_SIZE):
                digest.update(chunk)
        return digest.hexdigest()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
        print(f"  [ERROR] {url}\n          {e}", file=sys.stderr)
        return None


def github_archive_url(repository, tag):
    """Return the GitHub source archive URL for a release tag."""
    quoted_tag = urllib.parse.quote(tag, safe="")
    return f"https://github.com/{repository}/archive/refs/tags/{quoted_tag}.tar.gz"


def fetch_latest_release(repository, timeout=30):
    """Return the repository's latest GitHub release payload, or None on error."""
    url = f"https://api.github.com/repos/{repository}/releases/latest"
    try:
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "chezmoi-update-externals",
            },
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read())
        return payload if isinstance(payload, dict) else None
    except (
        urllib.error.URLError,
        urllib.error.HTTPError,
        TimeoutError,
        OSError,
        ValueError,
    ) as error:
        print(f"  [ERROR] {url}\n          {error}", file=sys.stderr)
        return None


def _release_tag(release, repository):
    tag = release.get("tag_name")
    if isinstance(tag, str) and tag:
        return tag
    print(
        f"  [ERROR] Latest release metadata is incomplete for {repository}",
        file=sys.stderr,
    )
    return None


def build_github_release_update(repository):
    """Return the latest release tag and archive checksum, or None on error."""
    release = fetch_latest_release(repository)
    if release is None:
        return None
    tag = _release_tag(release, repository)
    if tag is None:
        return None
    digest = fetch_sha256(github_archive_url(repository, tag))
    if digest is None:
        return None
    return tag, digest


def build_github_release_asset_update(repository, asset_filenames):
    """Return the latest release tag and requested asset digests."""
    release = fetch_latest_release(repository)
    if release is None:
        return None
    tag = _release_tag(release, repository)
    if tag is None:
        return None

    assets = release.get("assets")
    if not isinstance(assets, list):
        print(
            f"  [ERROR] Latest release metadata is incomplete for {repository}",
            file=sys.stderr,
        )
        return None

    digests = []
    for filename_template in asset_filenames:
        filename = filename_template.replace("{tag}", tag)
        matches = [
            asset
            for asset in assets
            if isinstance(asset, dict) and asset.get("name") == filename
        ]
        if len(matches) != 1:
            print(
                f"  [ERROR] Expected one release asset {filename!r} in {repository}@{tag}, "
                f"found {len(matches)}",
                file=sys.stderr,
            )
            return None

        digest = matches[0].get("digest")
        match = (
            GITHUB_SHA256_DIGEST_RE.fullmatch(digest)
            if isinstance(digest, str)
            else None
        )
        if match is None:
            print(
                f"  [ERROR] Release asset {filename!r} has no valid SHA-256 digest",
                file=sys.stderr,
            )
            return None
        digests.append(match.group("sha256").lower())

    return tag, tuple(digests)


def _encode_toml_basic_string(value):
    return json.dumps(value, ensure_ascii=False)[1:-1]


def _toml_sections(content):
    headers = list(SECTION_HEADER_RE.finditer(content))
    for index, header in enumerate(headers):
        end = headers[index + 1].start() if index + 1 < len(headers) else len(content)
        yield header.group("section"), (header.end(), end)


def _extract_toml_values(content, body_span, required, context):
    """Read required basic-string values and retain their source spans."""
    values = {}
    for match in TOML_BASIC_STRING_RE.finditer(content, *body_span):
        key = match.group("key")
        if key not in required:
            continue
        if key in values:
            raise ValueError(f"Duplicate {key!r} in {context}")
        try:
            value = tomllib.loads(f'value = "{match.group("value")}"')["value"]
        except tomllib.TOMLDecodeError as error:
            raise ValueError(f"Invalid {key!r} in {context}: {error}") from error
        values[key] = (value, match.span("value"))

    missing = required - values.keys()
    if missing:
        raise ValueError(f"{context} is missing: {', '.join(sorted(missing))}")
    return values


def extract_github_release_pins(content):
    """Extract and validate GitHub release pins while recording value spans."""
    pins = []
    for section, body_span in _toml_sections(content):
        if not section.startswith(GITHUB_RELEASE_SECTION_PREFIX):
            continue

        name = section.removeprefix(GITHUB_RELEASE_SECTION_PREFIX)
        if not name:
            raise ValueError("GitHub release pin name must not be empty")

        context = f"GitHub release pin {name!r}"
        values = _extract_toml_values(
            content, body_span, {"repository", "tag", "sha256"}, context
        )
        repository, tag, sha256 = (
            values[key][0] for key in ("repository", "tag", "sha256")
        )
        if not repository.strip():
            raise ValueError(f"{context} repository must not be empty")
        if bool(tag) != bool(sha256):
            raise ValueError(f"{context} tag and sha256 must both be empty or set")
        if sha256 and SHA256_RE.fullmatch(sha256) is None:
            raise ValueError(f"{context} sha256 must be 64 hexadecimal characters")

        pins.append(
            GithubReleasePin(
                name=name,
                repository=repository,
                tag=tag,
                sha256=sha256,
                tag_span=values["tag"][1],
                sha256_span=values["sha256"][1],
            )
        )
    return pins


def extract_github_release_asset_pins(content):
    """Extract release pins whose checksums come from named GitHub assets."""
    roots = []
    assets_by_pin = {}
    for section, body_span in _toml_sections(content):
        if not section.startswith(GITHUB_RELEASE_ASSET_SECTION_PREFIX):
            continue
        suffix = section.removeprefix(GITHUB_RELEASE_ASSET_SECTION_PREFIX)
        if ".assets." in suffix:
            pin_name, asset_name = suffix.split(".assets.", 1)
            assets_by_pin.setdefault(pin_name, []).append((asset_name, body_span))
        elif suffix and "." not in suffix:
            roots.append((suffix, body_span))

    pins = []
    for name, body_span in roots:
        context = f"GitHub release asset pin {name!r}"
        values = _extract_toml_values(
            content, body_span, {"repository", "tag"}, context
        )
        repository, tag = (values[key][0] for key in ("repository", "tag"))
        if not repository.strip():
            raise ValueError(f"{context} repository must not be empty")

        assets = []
        for asset_name, asset_span in assets_by_pin.get(name, ()):
            if not asset_name or "." in asset_name:
                raise ValueError(f"Invalid asset name in {context}")
            asset_context = f"Asset {asset_name!r} in pin {name!r}"
            asset_values = _extract_toml_values(
                content, asset_span, {"name", "sha256"}, asset_context
            )
            filename, sha256 = (
                asset_values[key][0] for key in ("name", "sha256")
            )
            if filename.count("{tag}") != 1:
                raise ValueError(
                    f"{asset_context} must contain one '{{tag}}' placeholder"
                )
            if sha256 and SHA256_RE.fullmatch(sha256) is None:
                raise ValueError(
                    f"{asset_context} sha256 must be 64 hexadecimal characters"
                )
            assets.append(
                GithubReleaseAsset(
                    name=asset_name,
                    filename=filename,
                    sha256=sha256,
                    sha256_span=asset_values["sha256"][1],
                )
            )

        if not assets:
            raise ValueError(f"{context} must declare at least one asset")
        if any(bool(asset.sha256) != bool(tag) for asset in assets):
            raise ValueError(
                f"{context} tag and all sha256 values must be empty or set together"
            )
        pins.append(
            GithubReleaseAssetPin(
                name=name,
                repository=repository,
                tag=tag,
                tag_span=values["tag"][1],
                assets=tuple(assets),
            )
        )
    return pins


def _apply_replacements(content, replacements):
    """Apply (start, end, replacement) tuples from right to left."""
    ordered = sorted(replacements, key=lambda item: item[0], reverse=True)
    for start, end, value in ordered:
        content = content[:start] + value + content[end:]
    return content


def _write_bytes_atomically(path, data):
    with tempfile.NamedTemporaryFile(
        dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as temporary_file:
        temporary_path = Path(temporary_file.name)

    try:
        temporary_path.write_bytes(data)
        temporary_path.replace(path)
    finally:
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass


def update_github_release_metadata(path, dry_run=False):
    """Refresh every GitHub release source and asset pin atomically.

    Return ``(updated_count, error_count)``. No bytes are written unless every
    pin resolves and all of its checksums are available.
    """
    path = Path(path)
    if not path.exists():
        return 0, 0

    try:
        content = path.read_bytes().decode("utf-8")
    except OSError as error:
        print(f"  [ERROR] {path}\n          {error}", file=sys.stderr)
        return 0, 1
    pins = extract_github_release_pins(content)
    asset_pins = extract_github_release_asset_pins(content)
    updates = []
    asset_updates = []
    errors = 0

    for pin in pins:
        candidate = build_github_release_update(pin.repository)
        if candidate is None:
            print(
                f"  [ERROR] GitHub release pin {pin.name} ({pin.repository})",
                file=sys.stderr,
            )
            errors += 1
            continue

        tag, sha256 = candidate
        if tag == pin.tag and sha256 == pin.sha256:
            print(f"  [OK]      GitHub release pin {pin.name}")
            continue

        updates.append((pin, tag, sha256))

    for pin in asset_pins:
        candidate = build_github_release_asset_update(
            pin.repository, tuple(asset.filename for asset in pin.assets)
        )
        if candidate is None:
            print(
                f"  [ERROR] GitHub release asset pin {pin.name} ({pin.repository})",
                file=sys.stderr,
            )
            errors += 1
            continue

        tag, sha256_values = candidate
        if len(sha256_values) != len(pin.assets):
            print(
                f"  [ERROR] GitHub release asset pin {pin.name} returned "
                f"{len(sha256_values)} checksums for {len(pin.assets)} assets",
                file=sys.stderr,
            )
            errors += 1
            continue
        if tag == pin.tag and all(
            sha256 == asset.sha256
            for asset, sha256 in zip(pin.assets, sha256_values)
        ):
            print(f"  [OK]      GitHub release asset pin {pin.name}")
            continue

        asset_updates.append((pin, tag, sha256_values))

    if errors:
        return 0, errors

    if (updates or asset_updates) and not dry_run:
        replacements = []
        for pin, tag, sha256 in updates:
            replacements.append((*pin.tag_span, _encode_toml_basic_string(tag)))
            replacements.append(
                (*pin.sha256_span, _encode_toml_basic_string(sha256))
            )
        for pin, tag, sha256_values in asset_updates:
            replacements.append((*pin.tag_span, _encode_toml_basic_string(tag)))
            for asset, sha256 in zip(pin.assets, sha256_values):
                replacements.append(
                    (*asset.sha256_span, _encode_toml_basic_string(sha256))
                )
        updated_content = _apply_replacements(content, replacements)
        try:
            _write_bytes_atomically(path, updated_content.encode("utf-8"))
        except OSError as error:
            print(f"  [ERROR] {path}\n          {error}", file=sys.stderr)
            return 0, 1

    for pin, tag, sha256 in updates:
        print(f"  [UPDATE]  GitHub release pin {pin.name}")
        print(f"            tag: {pin.tag} -> {tag}")
        print(f"         sha256: {pin.sha256} -> {sha256}")
    for pin, tag, sha256_values in asset_updates:
        print(f"  [UPDATE]  GitHub release asset pin {pin.name}")
        print(f"            tag: {pin.tag} -> {tag}")
        for asset, sha256 in zip(pin.assets, sha256_values):
            print(f"  {asset.name}.sha256: {asset.sha256} -> {sha256}")

    return len(updates) + len(asset_updates), 0


def update_external_files(repo_root, dry_run=False):
    """Refresh literal URL/checksum pairs in chezmoi external files."""
    files = find_external_files(repo_root)
    if not files:
        print("No .chezmoiexternal files found.")

    cache = {}
    checked = updated = errors = 0
    for file_path in files:
        content = file_path.read_bytes().decode("utf-8")
        pairs = extract_url_checksum_pairs(content)
        if not pairs:
            continue

        print(f"\n{file_path.relative_to(repo_root)} ({len(pairs)} entries)")
        replacements = []
        for url, old_hash, start, end in pairs:
            checked += 1
            short_url = url.partition("githubusercontent.com/")[2] or url

            if url not in cache:
                new_hash = fetch_sha256(url)
                if new_hash is None:
                    errors += 1
                    continue
                cache[url] = new_hash
                time.sleep(0.1)
            else:
                new_hash = cache[url]

            if new_hash == old_hash:
                print(f"  [OK]      {short_url}")
                continue
            print(f"  [UPDATE]  {short_url}")
            print(f"            {old_hash}")
            print(f"         -> {new_hash}")
            replacements.append((start, end, new_hash))
            updated += 1

        if replacements and not dry_run:
            new_content = _apply_replacements(content, replacements)
            file_path.write_bytes(new_content.encode("utf-8"))

    return checked, updated, errors


def main(argv=None, repo_root=None):
    parser = argparse.ArgumentParser(
        description="Update SHA-256 checksums for all chezmoi external resources."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be updated without modifying files",
    )
    args = parser.parse_args(argv)

    repo_root = (
        Path(repo_root) if repo_root is not None else Path(__file__).resolve().parent
    )
    try:
        metadata_updated, metadata_errors = update_github_release_metadata(
            repo_root / ".chezmoidata.toml", dry_run=args.dry_run
        )
    except ValueError as error:
        print(f"[ERROR] .chezmoidata.toml\n        {error}", file=sys.stderr)
        metadata_updated, metadata_errors = 0, 1

    checked, external_updated, external_errors = update_external_files(
        repo_root, dry_run=args.dry_run
    )
    updated = metadata_updated + external_updated
    errors = metadata_errors + external_errors

    print("\n--- Summary ---")
    print(f"Checked: {checked}  Updated: {updated}  Errors: {errors}")
    if args.dry_run and updated:
        print("(dry-run: no files were modified)")

    if errors:
        return 2
    return 1 if updated else 0


if __name__ == "__main__":
    sys.exit(main())
