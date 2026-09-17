#!/usr/bin/env python3
"""Refresh resolved external pins in .chezmoidata.toml; never edit manifests."""

import argparse
import copy
import hashlib
import http.client
import json
import re
import sys
import tempfile
import tomllib
import urllib.parse
import urllib.request
from datetime import date, datetime, time
from pathlib import Path


DOWNLOAD_CHUNK_SIZE = 1024 * 1024
HEADER = (
    "# Resolved external pins and their update recipes.\n"
    "# update_externals.py refreshes this data and writes canonical TOML.\n"
)


def _toml_string(value):
    # TOML forbids surrogate escapes and literal DEL, unlike JSON.
    return json.dumps(value, ensure_ascii=False).replace("\x7f", "\\u007f")


def _toml_key(key):
    return key if re.fullmatch(r"[A-Za-z0-9_-]+", key) else _toml_string(key)


def _toml_value(value):
    if isinstance(value, str):
        return _toml_string(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, (date, datetime, time)):
        return value.isoformat()
    if isinstance(value, list):
        return "[" + ", ".join(map(_toml_value, value)) + "]"
    if isinstance(value, dict):
        fields = (f"{_toml_key(k)} = {_toml_value(v)}" for k, v in sorted(value.items()))
        return "{ " + ", ".join(fields) + " }"
    raise ValueError(f"Unsupported TOML value: {type(value).__name__}")


def _serialize(data):
    """Canonical TOML: preserve values, not comments, ordering or line endings."""
    sections = []
    field_order = {
        key: i for i, key in enumerate(("url", "sha256", "type", "repository", "tag", "asset"))
    }

    def table(values, path):
        scalar_keys = [key for key in values if not isinstance(values[key], dict)]
        scalar_keys.sort(key=lambda key: (field_order.get(key, len(field_order)), key))
        if scalar_keys or not values:
            lines = ["[" + ".".join(map(_toml_key, path)) + "]"] if path else []
            lines.extend(f"{_toml_key(key)} = {_toml_value(values[key])}" for key in scalar_keys)
            sections.append("\n".join(lines))
        for key, value in sorted(values.items()):
            if isinstance(value, dict):
                table(value, (*path, key))

    table(data, ())
    rendered = HEADER + "\n" + "\n\n".join(sections) + "\n"
    tomllib.loads(rendered)  # Never replace valid data with malformed output.
    return rendered.encode("utf-8")


def _write_atomically(path, data):
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as stream:
            temporary_path = Path(stream.name)
            stream.write(data)
        temporary_path.replace(path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _hash_url(url):
    digest = hashlib.sha256()
    with urllib.request.urlopen(url, timeout=30) as response:
        length_header = getattr(response, "headers", {}).get("Content-Length")
        expected = None if length_header is None else int(length_header)
        if expected is not None and expected < 0:
            raise ValueError("Invalid Content-Length")
        received = 0
        while chunk := response.read(DOWNLOAD_CHUNK_SIZE):
            digest.update(chunk)
            received += len(chunk)
        if expected is not None and received != expected:
            raise ValueError(f"Content-Length expected {expected} bytes, received {received}")
    return digest.hexdigest()


def _release_url(recipe, tag):
    base = f"https://github.com/{recipe['repository']}"
    quoted_tag = urllib.parse.quote(tag, safe="")
    if "asset" in recipe:
        filename = urllib.parse.quote(recipe["asset"].replace("{tag}", tag), safe="")
        return f"{base}/releases/download/{quoted_tag}/{filename}"
    return f"{base}/archive/refs/tags/{quoted_tag}.tar.gz"


def _validate(data):
    """Validate the entire pin catalog before performing any network operation."""
    resources = data.get("external_resources")
    if not isinstance(resources, dict) or set(resources) != {"pins"}:
        raise ValueError("external_resources must contain only the normalized pins table")
    pins = resources["pins"]
    if not isinstance(pins, dict) or not pins:
        raise ValueError("external_resources.pins must be a nonempty table")
    for name, pin in pins.items():
        label = f"Pin {name!r}"
        if (
            not isinstance(pin, dict)
            or not {"url", "sha256"} <= pin.keys()
            or pin.keys() - {"url", "sha256", "update"}
        ):
            raise ValueError(f"{label} requires url, sha256 and an optional update table")
        if not isinstance(pin["url"], str) or not isinstance(pin["sha256"], str):
            raise ValueError(f"{label} url and sha256 must be strings")
        if "update" in pin:
            recipe = pin["update"]
            required = {"type", "repository", "tag"}
            if (
                not isinstance(recipe, dict)
                or not required <= recipe.keys()
                or recipe.keys() - (required | {"asset"})
            ):
                raise ValueError(f"{label} update requires type, repository, tag and optional asset")
            if recipe["type"] != "github_release":
                raise ValueError(f"{label} has an unsupported update type")
            repository = recipe["repository"]
            if (
                not isinstance(repository, str)
                or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository)
                or any(part in {".", ".."} for part in repository.split("/"))
            ):
                raise ValueError(f"{label} repository must be owner/repo")
            if not isinstance(recipe["tag"], str):
                raise ValueError(f"{label} tag must be a string")
            if "asset" in recipe:
                asset = recipe["asset"]
                if (
                    not isinstance(asset, str)
                    or not asset.strip()
                    or asset.count("{tag}") > 1
                    or any(c in asset.replace("{tag}", "") for c in "{}\\/")
                ):
                    raise ValueError(f"{label} asset must be a filename with at most one {{tag}}")
            if recipe["tag"] == pin["url"] == pin["sha256"] == "":
                continue  # Explicit first refresh; partially initialized pins remain invalid.
            if not recipe["tag"].strip():
                raise ValueError(f"{label} tag, URL and sha256 must be all empty or all initialized")
            if pin["url"] != _release_url(recipe, recipe["tag"]):
                raise ValueError(f"{label} URL disagrees with its release recipe/tag")
        parsed = urllib.parse.urlsplit(pin["url"])
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or any(c.isspace() for c in pin["url"])
        ):
            raise ValueError(f"{label} URL must be an absolute HTTP(S) URL without whitespace")
        if not re.fullmatch(r"[0-9a-fA-F]{64}", pin["sha256"]):
            raise ValueError(f"{label} sha256 must be 64 hexadecimal characters")


def _latest_release(repository):
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repository}/releases/latest",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "chezmoi-update-externals"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        release = json.load(response)
    if (
        not isinstance(release, dict)
        or not isinstance(release.get("tag_name"), str)
        or not release["tag_name"].strip()
    ):
        raise ValueError("Latest release must have a nonempty tag_name")
    return release


def _asset_digest(release, filename):
    assets = release.get("assets")
    if not isinstance(assets, list):
        raise ValueError("Latest release must contain an assets array")
    matches = [
        asset for asset in assets if isinstance(asset, dict) and asset.get("name") == filename
    ]
    if len(matches) != 1:
        raise ValueError(f"Expected one release asset {filename!r}, found {len(matches)}")
    digest = matches[0].get("digest")
    if not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", digest):
        raise ValueError(f"Release asset {filename!r} has no valid SHA-256 digest")
    return digest.removeprefix("sha256:").lower()


def main(argv=None, repo_root=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="Resolve updates without writing pin data"
    )
    args = parser.parse_args(argv)
    root = Path(repo_root) if repo_root is not None else Path(__file__).resolve().parent
    path = root / ".chezmoidata.toml"
    checked = 0
    context = str(path)
    try:
        original = path.read_bytes()
        data = tomllib.loads(original.decode("utf-8"))
        _validate(data)
        updated = copy.deepcopy(data)
        pins = updated["external_resources"]["pins"]
        changes = []
        releases = {}
        for name, pin in pins.items():
            context = name
            checked += 1
            if recipe := pin.get("update"):
                repository = recipe["repository"]
                if repository not in releases:
                    releases[repository] = _latest_release(repository)
                release = releases[repository]
                recipe["tag"] = release["tag_name"]
                pin["url"] = _release_url(recipe, recipe["tag"])
                if "asset" in recipe:
                    filename = recipe["asset"].replace("{tag}", recipe["tag"])
                    pin["sha256"] = _asset_digest(release, filename)
                else:
                    pin["sha256"] = _hash_url(pin["url"])
            else:
                pin["sha256"] = _hash_url(pin["url"])
            if pin != data["external_resources"]["pins"][name]:
                changes.append(name)
        context = str(path)
        if changes and not args.dry_run:
            if path.read_bytes() != original:
                raise ValueError("Pin data changed during refresh; refusing to overwrite it")
            _write_atomically(path, _serialize(updated))
    except (OSError, ValueError, http.client.HTTPException) as error:
        print(f"[ERROR] {context}: {error}", file=sys.stderr)
        print(f"Checked: {checked}  Updated: 0  Errors: 1")
        return 2
    for name in changes:
        print(f"[UPDATE] {name}")
        before, after = data["external_resources"]["pins"][name], pins[name]
        for field in ("url", "sha256"):
            if before[field] != after[field]:
                print(f"  {field}: {json.dumps(before[field])} -> {json.dumps(after[field])}")
        old_tag = before.get("update", {}).get("tag")
        new_tag = after.get("update", {}).get("tag")
        if old_tag != new_tag:
            print(f"  tag: {json.dumps(old_tag)} -> {json.dumps(new_tag)}")
    print(f"Checked: {checked}  Updated: {len(changes)}  Errors: 0")
    if args.dry_run:
        print("(dry-run: pin data was not modified)")
    return 1 if changes else 0


if __name__ == "__main__":
    raise SystemExit(main())
