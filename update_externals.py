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
    r'(?P<url_prefix>\s*url\s*=\s*")'
    r'(?P<url>[^"]+)'
    r'(?P<url_suffix>")(?:\n\s+[^\n]*)*\n'
    r'(?P<hash_prefix>\s*checksum\.sha256\s*=\s*")'
    r'(?P<hash>[0-9a-fA-F]{64})'
    r'(?P<hash_suffix>")',
    re.MULTILINE,
)

SECTION_HEADER_RE = re.compile(
    r"^[ \t]*\[(?P<section>[^\]\r\n]+)\][ \t]*(?:#[^\r\n]*)?(?:\r?\n|$)",
    re.MULTILINE,
)

GITHUB_RELEASE_VALUE_RE = re.compile(
    r'^[ \t]*(?P<key>repository|tag|sha256)[ \t]*=[ \t]*"'
    r'(?P<value>(?:[^"\\\r\n]|\\.)*)"[ \t]*(?:#[^\r\n]*)?\r?$',
    re.MULTILINE,
)

GITHUB_RELEASE_SECTION_PREFIX = "external_resources.github_releases."
DOWNLOAD_CHUNK_SIZE = 1024 * 1024


@dataclass(frozen=True)
class GithubReleasePin:
    name: str
    repository: str
    tag: str
    sha256: str
    tag_span: tuple[int, int]
    sha256_span: tuple[int, int]


def find_external_files(repo_root):
    return sorted(repo_root.rglob(".chezmoiexternal.toml*"))


def extract_url_checksum_pairs(content):
    """Return list of (url, old_hash, hash_start_offset, hash_end_offset)."""
    pairs = []
    for m in PAIR_RE.finditer(content):
        pairs.append((m.group("url"), m.group("hash"), m.start("hash"), m.end("hash")))
    return pairs


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


def fetch_latest_release_tag(repository, timeout=30):
    """Return the repository's latest GitHub release tag, or None on error."""
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
        if not isinstance(payload, dict):
            return None
        tag = payload.get("tag_name")
        return tag if isinstance(tag, str) and tag else None
    except (
        urllib.error.URLError,
        urllib.error.HTTPError,
        TimeoutError,
        OSError,
        ValueError,
    ) as error:
        print(f"  [ERROR] {url}\n          {error}", file=sys.stderr)
        return None


def build_github_release_update(repository):
    """Return the latest release tag and archive checksum, or None on error."""
    tag = fetch_latest_release_tag(repository)
    if tag is None:
        return None
    digest = fetch_sha256(github_archive_url(repository, tag))
    if digest is None:
        return None
    return tag, digest


def _decode_toml_basic_string(value):
    return tomllib.loads(f'value = "{value}"')["value"]


def _encode_toml_basic_string(value):
    return json.dumps(value, ensure_ascii=False)[1:-1]


def extract_github_release_pins(content):
    """Extract and validate GitHub release pins while recording value spans."""
    pins = []
    headers = list(SECTION_HEADER_RE.finditer(content))

    for index, header in enumerate(headers):
        section = header.group("section")
        if not section.startswith(GITHUB_RELEASE_SECTION_PREFIX):
            continue

        name = section[len(GITHUB_RELEASE_SECTION_PREFIX) :]
        if not name:
            raise ValueError("GitHub release pin name must not be empty")

        section_end = (
            headers[index + 1].start() if index + 1 < len(headers) else len(content)
        )
        values = {}
        for match in GITHUB_RELEASE_VALUE_RE.finditer(
            content, header.end(), section_end
        ):
            key = match.group("key")
            if key in values:
                raise ValueError(f"Duplicate {key!r} in GitHub release pin {name!r}")
            raw_value = match.group("value")
            try:
                value = _decode_toml_basic_string(raw_value)
            except tomllib.TOMLDecodeError as error:
                raise ValueError(
                    f"Invalid {key!r} in GitHub release pin {name!r}: {error}"
                ) from error
            values[key] = (value, match.span("value"))

        missing = {"repository", "tag", "sha256"} - values.keys()
        if missing:
            missing_list = ", ".join(sorted(missing))
            raise ValueError(
                f"GitHub release pin {name!r} is missing: {missing_list}"
            )

        repository = values["repository"][0]
        tag = values["tag"][0]
        sha256 = values["sha256"][0]
        if not repository.strip():
            raise ValueError(
                f"GitHub release pin {name!r} repository must not be empty"
            )
        if bool(tag) != bool(sha256):
            raise ValueError(
                f"GitHub release pin {name!r} tag and sha256 must both be empty or set"
            )
        if sha256 and re.fullmatch(r"[0-9a-fA-F]{64}", sha256) is None:
            raise ValueError(
                f"GitHub release pin {name!r} sha256 must be 64 hexadecimal characters"
            )

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


def apply_github_release_updates(content, updates):
    """Apply tag and checksum updates without disturbing surrounding formatting."""
    replacements = []
    for pin, tag, sha256 in updates:
        replacements.append((*pin.tag_span, _encode_toml_basic_string(tag)))
        replacements.append((*pin.sha256_span, _encode_toml_basic_string(sha256)))
    return apply_replacements(content, replacements)


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
    """Refresh every GitHub release pin atomically.

    Return ``(updated_count, error_count)``. No bytes are written unless every
    pin resolves and its archive checksum can be calculated.
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
    updates = []
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

    if errors:
        return 0, errors

    if updates and not dry_run:
        updated_content = apply_github_release_updates(content, updates)
        try:
            _write_bytes_atomically(path, updated_content.encode("utf-8"))
        except OSError as error:
            print(f"  [ERROR] {path}\n          {error}", file=sys.stderr)
            return 0, 1

    for pin, tag, sha256 in updates:
        print(f"  [UPDATE]  GitHub release pin {pin.name}")
        print(f"            tag: {pin.tag} -> {tag}")
        print(f"         sha256: {pin.sha256} -> {sha256}")

    return len(updates), 0


def apply_replacements(content, replacements):
    """Replace checksums at given offsets. Replacements: list of (start, end, new_hash)."""
    for start, end, new_hash in sorted(replacements, key=lambda r: r[0], reverse=True):
        content = content[:start] + new_hash + content[end:]
    return content


def main(argv=None, repo_root=None):
    parser = argparse.ArgumentParser(
        description="Update SHA-256 checksums for all chezmoi external resources."
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Show what would be updated without modifying files"
    )
    args = parser.parse_args(argv)

    repo_root = Path(repo_root) if repo_root is not None else Path(__file__).resolve().parent
    metadata_updated = 0
    metadata_errors = 0
    try:
        metadata_updated, metadata_errors = update_github_release_metadata(
            repo_root / ".chezmoidata.toml", dry_run=args.dry_run
        )
    except ValueError as error:
        print(f"[ERROR] .chezmoidata.toml\n        {error}", file=sys.stderr)
        metadata_errors = 1

    files = find_external_files(repo_root)

    if not files:
        print("No .chezmoiexternal files found.")
        if metadata_errors:
            return 2
        if metadata_updated:
            return 1
        return 0

    cache = {}  # url -> sha256
    total_checked = 0
    total_updated = metadata_updated
    total_errors = metadata_errors

    for file_path in files:
        rel = file_path.relative_to(repo_root)
        content = file_path.read_bytes().decode("utf-8")
        pairs = extract_url_checksum_pairs(content)

        if not pairs:
            continue

        print(f"\n{rel} ({len(pairs)} entries)")
        replacements = []

        for url, old_hash, start, end in pairs:
            total_checked += 1
            short_url = url.split("githubusercontent.com/")[-1] if "githubusercontent.com/" in url else url

            if url in cache:
                new_hash = cache[url]
            else:
                new_hash = fetch_sha256(url)
                if new_hash is None:
                    total_errors += 1
                    continue
                cache[url] = new_hash
                time.sleep(0.1)

            if new_hash == old_hash:
                print(f"  [OK]      {short_url}")
            else:
                print(f"  [UPDATE]  {short_url}")
                print(f"            {old_hash}")
                print(f"         -> {new_hash}")
                replacements.append((start, end, new_hash))
                total_updated += 1

        if replacements and not args.dry_run:
            new_content = apply_replacements(content, replacements)
            file_path.write_bytes(new_content.encode("utf-8"))

    print(f"\n--- Summary ---")
    print(f"Checked: {total_checked}  Updated: {total_updated}  Errors: {total_errors}")
    if args.dry_run and total_updated:
        print("(dry-run: no files were modified)")

    if total_errors:
        return 2
    if total_updated:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
