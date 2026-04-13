#!/usr/bin/env python3
"""Update SHA-256 checksums for all chezmoi external resources."""

import argparse
import hashlib
import re
import sys
import time
import urllib.error
import urllib.request
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
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = resp.read()
        return hashlib.sha256(data).hexdigest()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
        print(f"  [ERROR] {url}\n          {e}", file=sys.stderr)
        return None


def apply_replacements(content, replacements):
    """Replace checksums at given offsets. Replacements: list of (start, end, new_hash)."""
    for start, end, new_hash in sorted(replacements, key=lambda r: r[0], reverse=True):
        content = content[:start] + new_hash + content[end:]
    return content


def main():
    parser = argparse.ArgumentParser(
        description="Update SHA-256 checksums for all chezmoi external resources."
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Show what would be updated without modifying files"
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent
    files = find_external_files(repo_root)

    if not files:
        print("No .chezmoiexternal files found.")
        return 0

    cache = {}  # url -> sha256
    total_checked = 0
    total_updated = 0
    total_errors = 0

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
