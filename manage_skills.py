#!/usr/bin/env python3
"""Publish explicitly selected agent skills into a local Claude marketplace.

The publisher deliberately owns only the outputs recorded in its receipt.  It
never fetches inputs, installs Claude plugins, or adopts pre-existing files.
Caught pre-commit failures are rolled back, but process death is not recoverable
without human inspection, and publication is not an atomic snapshot for readers.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import ntpath
import os
import re
import shutil
import stat
import sys
import tempfile
import tomllib
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO


MARKETPLACE_REL = ".config/claude-code-chezmoi"
GENERATED_REL = f"{MARKETPLACE_REL}/generated-skills"
SHARED_REL = ".agents/skills"
MARKETPLACE_FILE_REL = f"{MARKETPLACE_REL}/.claude-plugin/marketplace.json"
RECEIPT_REL = f"{MARKETPLACE_REL}/.skill-publisher.json"
LOCK_REL = f"{MARKETPLACE_REL}/.skill-publisher.lock"
WORK_REL = f"{MARKETPLACE_REL}/.skill-publisher-work"
LOCK_MARKER = b"chezmoi skill publisher lock\n"

NAME_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
DIGEST_RE = re.compile(r"[0-9a-f]{64}\Z")
PLUGIN_PATH_RE = re.compile(r"\$\{CLAUDE_PLUGIN_ROOT\}/([^\s\"';&|<>]+)")
_HEADER_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|$)", re.S)
_HEADER_NAMES_RE = re.compile(r"^name:[ \t]*(.*)$", re.M)
_HEADER_NAME_VALUE_RE = re.compile(
    r"([\"']?)([a-z0-9-]+)\1[ \t]*(?:#.*)?\r?\Z"
)
_HEADER_DESCRIPTION_RE = re.compile(r"^description:[ \t]*\S", re.M)

_WINDOWS_INVALID = frozenset('<>:"\\|?*')
_WINDOWS_DEVICES = frozenset(
    {"con", "prn", "aux", "nul", "conin$", "conout$"}
    | {f"com{number}" for number in range(1, 10)}
    | {f"lpt{number}" for number in range(1, 10)}
    | {f"com{number}" for number in "¹²³"}
    | {f"lpt{number}" for number in "¹²³"}
)
_FILE_ATTRIBUTE_DIRECTORY = 0x10
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400
_IO_REPARSE_TAG_SYMLINK = 0xA000000C

_MANIFEST_PATH = ".claude-plugin/plugin.json"
_DEFAULT_HOOKS_PATH = "hooks/hooks.json"
_ALLOWED_MANIFEST_FIELDS = frozenset(
    {
        "name",
        "version",
        "description",
        "author",
        "homepage",
        "repository",
        "license",
        "keywords",
        "skills",
        "hooks",
        "agents",
        "outputStyles",
    }
)
_MANIFEST_STRING_FIELDS = frozenset(
    {"name", "version", "description", "homepage", "repository", "license"}
)
_ROOT_LOCKFILES = frozenset(
    {
        "package-lock.json",
        "npm-shrinkwrap.json",
        "yarn.lock",
        "bun.lock",
        "bun.lockb",
        "pnpm-lock.yaml",
    }
)
_MATT_DEPENDENCIES: dict[str, tuple[str, ...]] = {
    "grill-me": ("grilling",),
    "grill-with-docs": ("grilling", "domain-modeling"),
    "tdd": ("codebase-design",),
    "implement": ("code-review", "tdd"),
    "improve-codebase-architecture": (
        "codebase-design",
        "grilling",
        "domain-modeling",
    ),
    "wayfinder": (
        "codebase-design",
        "grilling",
        "domain-modeling",
        "research",
        "prototype",
        "wizard",
    ),
    "code-review": ("setup-matt-pocock-skills",),
    "to-spec": ("setup-matt-pocock-skills",),
    "to-tickets": ("setup-matt-pocock-skills",),
    "triage": ("setup-matt-pocock-skills",),
}


class PublicationError(ValueError):
    """The requested publication was refused or could not be completed."""

    def __init__(
        self,
        message: str,
        *,
        committed: bool = False,
        report: Report | None = None,
    ) -> None:
        super().__init__(message)
        self.committed = committed
        self.report = report


@dataclass(frozen=True)
class PublishedFile:
    data: bytes
    executable: bool


@dataclass(frozen=True)
class Candidate:
    files: dict[str, PublishedFile]
    skills: dict[str, str]
    version: str
    digest: str


@dataclass(frozen=True)
class Report:
    actions: list[str]
    plugins: list[str]
    removed: list[str]
    marketplace_name: str


@dataclass(frozen=True)
class _ReceiptSource:
    digest: str
    skills: dict[str, str]


@dataclass(frozen=True)
class _Receipt:
    sources: dict[str, _ReceiptSource]
    marketplace: str


@dataclass
class _Plan:
    home: Path
    candidates: dict[str, Candidate]
    old_receipt: _Receipt | None
    old_receipt_bytes: bytes | None
    old_marketplace_bytes: bytes | None
    marketplace_bytes: bytes
    receipt_bytes: bytes
    old_links: dict[str, Path]
    new_links: dict[str, Path]
    view_changes: dict[str, str]
    link_changes: dict[str, str]
    marketplace_change: str | None
    receipt_change: bool
    actions: list[str]
    report: Report


@dataclass(frozen=True)
class _Transfer:
    source: Path
    destination: Path
    witness: os.stat_result
    hardlink: bool = False


@dataclass
class _FileWrite:
    path: Path
    new: bytes
    old: bytes | None
    prepared: _Transfer | None = None
    preparing: bool = False


@dataclass
class _DirectoryAcquisition:
    path: Path
    state: str = "unattempted"
    witness: os.stat_result | None = None


@dataclass
class _TransactionRecord:
    work: _DirectoryAcquisition
    backed_views: list[tuple[_Transfer, str]]
    backed_links: list[tuple[_Transfer, Path]]
    installed_views: list[tuple[_Transfer, str]]
    created_links: list[tuple[_Transfer, Path]]
    file_writes: list[_FileWrite]
    created_directories: list[_DirectoryAcquisition]

    @classmethod
    def empty(cls, work: Path) -> _TransactionRecord:
        return cls(_DirectoryAcquisition(work), [], [], [], [], [], [])


def json_bytes(value: Any) -> bytes:
    """Return the publisher's canonical UTF-8 JSON representation."""

    return (
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")


def tree_digest(files: Mapping[str, PublishedFile]) -> str:
    """Hash a canonical inventory of relative names, modes, and file bytes."""

    inventory = [
        [name, file.executable, hashlib.sha256(file.data).hexdigest()]
        for name, file in sorted(files.items())
    ]
    return hashlib.sha256(json_bytes(inventory)).hexdigest()


def _error(message: str) -> PublicationError:
    return PublicationError(message)


def _validate_name(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) > 64 or not NAME_RE.fullmatch(value):
        raise _error(
            f"{label} must match [a-z0-9]+(?:-[a-z0-9]+)* and be at most 64 characters"
        )
    return value


def _validate_literal_path(value: Any, label: str, *, allow_dot: bool) -> str:
    if not isinstance(value, str):
        raise _error(f"{label} must be a string")
    if value == ".":
        if allow_dot:
            return value
        raise _error(f"{label} may not be '.'")
    if not value:
        raise _error(f"{label} may not be empty")
    if value.startswith("/") or value.startswith("\\"):
        raise _error(f"{label} must be relative")
    if "\\" in value:
        raise _error(f"{label} must use forward slashes")

    components = value.split("/")
    for component in components:
        if component in {"", ".", ".."}:
            raise _error(f"{label} contains an empty, dot, or dot-dot component")
        if component.endswith((" ", ".")):
            raise _error(f"{label} contains a component ending in a space or dot")
        if any(char in _WINDOWS_INVALID for char in component):
            raise _error(f"{label} contains a Windows-invalid character")
        if any(unicodedata.category(char) == "Cc" for char in component):
            raise _error(f"{label} contains a control character")
        device_stem = component.split(".", 1)[0].casefold()
        if device_stem in _WINDOWS_DEVICES:
            raise _error(f"{label} contains reserved Windows device name {component!r}")
    return value


def _path_parts(value: str) -> tuple[str, ...]:
    return () if value == "." else tuple(value.split("/"))


def _is_prefix(left: Sequence[str], right: Sequence[str]) -> bool:
    return len(left) <= len(right) and tuple(left) == tuple(right[: len(left)])


def _is_reparse(st: os.stat_result) -> bool:
    return bool(getattr(st, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT)


def _reject_reparse(path: Path, st: os.stat_result, label: str) -> None:
    if stat.S_ISLNK(st.st_mode) or _is_reparse(st):
        raise _error(f"{label} is a symlink or reparse point: {path}")


def _absolute_path(value: os.PathLike[str] | str) -> Path:
    return Path(os.path.abspath(os.fspath(value)))


def _all_absolute_ancestors(path: Path) -> list[Path]:
    result: list[Path] = []
    current = path
    while True:
        result.append(current)
        if current.parent == current:
            break
        current = current.parent
    result.reverse()
    return result


def _assert_safe_existing_ancestors(
    path: Path, label: str, *, require_leaf: bool = False
) -> None:
    for ancestor in _all_absolute_ancestors(path):
        if not os.path.lexists(ancestor):
            if ancestor == path and require_leaf:
                raise _error(f"{label} does not exist: {path}")
            continue
        try:
            st = os.lstat(ancestor)
        except OSError as exc:
            raise _error(f"cannot inspect {label} ancestor {ancestor}: {exc}") from exc
        _reject_reparse(ancestor, st, label)
        if ancestor != path and not stat.S_ISDIR(st.st_mode):
            raise _error(f"{label} ancestor is not a directory: {ancestor}")
    if require_leaf and not os.path.lexists(path):
        raise _error(f"{label} does not exist: {path}")


def _scan_case_matches(parent: Path, name: str, label: str) -> list[str]:
    try:
        with os.scandir(parent) as entries:
            return [entry.name for entry in entries if entry.name.casefold() == name.casefold()]
    except OSError as exc:
        raise _error(f"cannot inspect {label} parent {parent}: {exc}") from exc


def _exact_existing_path(base: Path, relative: str, label: str) -> Path:
    current = base
    for component in _path_parts(relative):
        st = os.lstat(current)
        _reject_reparse(current, st, label)
        if not stat.S_ISDIR(st.st_mode):
            raise _error(f"{label} parent is not a directory: {current}")
        matches = _scan_case_matches(current, component, label)
        if component not in matches:
            if matches:
                raise _error(
                    f"{label} does not use exact source path spelling: "
                    f"expected {component!r}, found {matches!r}"
                )
            raise _error(f"{label} does not exist: {current / component}")
        current = current / component
    return current


def _strict_output_chain(home: Path, relative: str, label: str) -> bool:
    """Validate existing components and casing; return whether the leaf exists."""

    current = home
    components = _path_parts(relative)
    if not components:
        return True
    for index, component in enumerate(components):
        if not os.path.lexists(current):
            return False
        st = os.lstat(current)
        _reject_reparse(current, st, label)
        if not stat.S_ISDIR(st.st_mode):
            raise _error(f"{label} parent is not a directory: {current}")
        matches = _scan_case_matches(current, component, label)
        if not matches:
            return False
        if matches != [component]:
            raise _error(
                f"case-spelling collision at {current / component}: found {matches!r}"
            )
        current = current / component
        if index < len(components) - 1:
            child_st = os.lstat(current)
            _reject_reparse(current, child_st, label)
            if not stat.S_ISDIR(child_st.st_mode):
                raise _error(f"{label} parent is not a directory: {current}")
    return True


def _strict_slot(parent: Path, name: str, label: str) -> Path | None:
    if not os.path.lexists(parent):
        return None
    parent_st = os.lstat(parent)
    _reject_reparse(parent, parent_st, label)
    if not stat.S_ISDIR(parent_st.st_mode):
        raise _error(f"{label} parent is not a directory: {parent}")
    matches = _scan_case_matches(parent, name, label)
    if not matches:
        return None
    if matches != [name]:
        raise _error(f"case-spelling collision for {label}: found {matches!r}")
    return parent / name


def _read_regular_bytes(path: Path, label: str) -> bytes:
    _assert_safe_existing_ancestors(path, label, require_leaf=True)
    try:
        before = os.lstat(path)
    except OSError as exc:
        raise _error(f"cannot inspect {label} {path}: {exc}") from exc
    _reject_reparse(path, before, label)
    if not stat.S_ISREG(before.st_mode):
        raise _error(f"{label} is not a regular file: {path}")

    flags = os.O_RDONLY
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise _error(f"cannot open {label} {path}: {exc}") from exc
    try:
        opened = os.fstat(descriptor)
        after_open = os.lstat(path)
        _reject_reparse(path, after_open, label)
        if (
            not stat.S_ISREG(opened.st_mode)
            or not stat.S_ISREG(after_open.st_mode)
            or not os.path.samestat(opened, after_open)
        ):
            raise _error(f"{label} changed while being opened: {path}")
        with os.fdopen(descriptor, "rb") as input_file:
            descriptor = -1
            data = input_file.read()
        after_read = os.lstat(path)
    except OSError as exc:
        raise _error(f"cannot read {label} {path}: {exc}") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    _reject_reparse(path, after_read, label)
    if not stat.S_ISREG(after_read.st_mode) or not os.path.samestat(opened, after_read):
        raise _error(f"{label} changed while being read: {path}")
    return data


def _pairs_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _error(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _parse_json_bytes(data: bytes, label: str) -> Any:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise _error(f"{label} is not valid UTF-8: {exc}") from exc
    try:
        return json.loads(text, object_pairs_hook=_pairs_object)
    except PublicationError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise _error(f"{label} is not valid JSON: {exc}") from exc


def _check_selected_path_collisions(files: Mapping[str, PublishedFile], label: str) -> None:
    seen_components: dict[tuple[str, ...], tuple[str, ...]] = {}
    file_paths: set[tuple[str, ...]] = set()
    for name in sorted(files):
        parts = tuple(name.split("/"))
        folded: list[str] = []
        actual: list[str] = []
        for component in parts:
            folded.append(component.casefold())
            actual.append(component)
            folded_key = tuple(folded)
            actual_key = tuple(actual)
            previous = seen_components.get(folded_key)
            if previous is not None and previous != actual_key:
                raise _error(
                    f"{label} contains a case-spelling collision between "
                    f"{'/'.join(previous)!r} and {'/'.join(actual_key)!r}"
                )
            seen_components[folded_key] = actual_key
            if folded_key in file_paths and len(folded_key) < len(parts):
                raise _error(f"{label} contains a file/directory-prefix collision at {name!r}")
        folded_parts = tuple(component.casefold() for component in parts)
        if any(
            len(other) > len(folded_parts) and _is_prefix(folded_parts, other)
            for other in file_paths
        ):
            raise _error(f"{label} contains a file/directory-prefix collision at {name!r}")
        file_paths.add(folded_parts)


def _is_excluded(relative: str, excludes: Sequence[str]) -> bool:
    relative_parts = _path_parts(relative)
    for exclusion in excludes:
        exclusion_parts = _path_parts(exclusion)
        if not exclusion_parts or _is_prefix(exclusion_parts, relative_parts):
            return True
    return False


def _select_files(
    source_id: str,
    source_root: Path,
    includes: Sequence[str],
    excludes: Sequence[str],
) -> dict[str, PublishedFile]:
    label = f"source {source_id!r}"

    # Includes are declarations and must exist even if an exclusion later wins.
    include_paths: list[tuple[str, Path]] = []
    for include in includes:
        path = source_root if include == "." else _exact_existing_path(source_root, include, f"{label} include")
        if not os.path.lexists(path):
            raise _error(f"{label} include does not exist: {include}")
        include_paths.append((include, path))

    files: dict[str, PublishedFile] = {}

    def visit(relative: str, path: Path) -> None:
        if _is_excluded(relative, excludes):
            return
        _validate_literal_path(relative, f"selected path in {label}", allow_dot=True)
        try:
            entry_stat = os.lstat(path)
        except OSError as exc:
            raise _error(f"cannot inspect selected path {path}: {exc}") from exc
        _reject_reparse(path, entry_stat, f"selected path in {label}")
        if stat.S_ISREG(entry_stat.st_mode):
            if relative == ".":
                raise _error(f"{label} root must be a directory")
            try:
                data = path.read_bytes()
            except OSError as exc:
                raise _error(f"cannot read selected file {path}: {exc}") from exc
            selected = PublishedFile(data, bool(entry_stat.st_mode & 0o111))
            previous = files.get(relative)
            if previous is not None and previous != selected:
                raise _error(f"selected file changed during collection: {relative}")
            files[relative] = selected
            return
        if not stat.S_ISDIR(entry_stat.st_mode):
            raise _error(f"selected path is not a regular file or directory: {path}")
        try:
            with os.scandir(path) as iterator:
                entries = sorted(iterator, key=lambda item: item.name)
        except OSError as exc:
            raise _error(f"cannot traverse selected directory {path}: {exc}") from exc
        for entry in entries:
            child_relative = entry.name if relative == "." else f"{relative}/{entry.name}"
            if _is_excluded(child_relative, excludes):
                continue
            visit(child_relative, Path(entry.path))

    for include, path in include_paths:
        visit(include, path)

    _check_selected_path_collisions(files, label)
    return files


def _validate_selected_metadata_paths(files: Mapping[str, PublishedFile], source_id: str) -> None:
    canonical_paths = {
        _MANIFEST_PATH.casefold(): _MANIFEST_PATH,
        ".claude-plugin/marketplace.json".casefold(): ".claude-plugin/marketplace.json",
        _DEFAULT_HOOKS_PATH.casefold(): _DEFAULT_HOOKS_PATH,
        ".mcp.json".casefold(): ".mcp.json",
        ".lsp.json".casefold(): ".lsp.json",
        "package.json".casefold(): "package.json",
        **{name.casefold(): name for name in _ROOT_LOCKFILES},
    }
    for name in sorted(files):
        parts = name.split("/")
        first = parts[0].casefold()
        if first in {".git", "commands"}:
            raise _error(f"source {source_id!r} selects unsupported root content {name!r}")
        folded = name.casefold()
        expected = canonical_paths.get(folded)
        if expected is not None and name != expected:
            raise _error(f"supported metadata path must use canonical casing {expected!r}")
        if first == ".claude-plugin" and parts[0] != ".claude-plugin":
            raise _error("the .claude-plugin directory must use canonical casing")
        if folded == ".claude-plugin/marketplace.json":
            raise _error("a selected source may not provide .claude-plugin/marketplace.json")
        if len(parts) == 1 and folded in {".mcp.json", ".lsp.json"}:
            raise _error(f"a selected source may not provide {name}")
        if len(parts) == 1 and folded in _ROOT_LOCKFILES:
            raise _error(f"a selected source may not provide installer lockfile {name}")
        if parts[-1].casefold() == "skill.md" and parts[-1] != "SKILL.md":
            raise _error(f"skill marker must be named exactly SKILL.md: {name}")
        if parts[-1].casefold() == "package.json" and parts[-1] != "package.json":
            raise _error(f"package metadata must be named exactly package.json: {name}")


def _discover_skills(
    files: Mapping[str, PublishedFile], source_id: str
) -> dict[str, str]:
    markers = [name for name in sorted(files) if name.split("/")[-1] == "SKILL.md"]
    skills: dict[str, str] = {}
    roots: list[str] = []
    for marker in markers:
        relative_directory = marker.rsplit("/", 1)[0] if "/" in marker else "."
        try:
            text = files[marker].data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise _error(f"skill marker {marker!r} is not valid UTF-8: {exc}") from exc
        header = _HEADER_RE.match(text)
        if header is None:
            raise _error(f"skill marker {marker!r} is missing bounded frontmatter")
        names = _HEADER_NAMES_RE.findall(header[1])
        if len(names) != 1:
            raise _error(f"skill marker {marker!r} must declare exactly one top-level name")
        match = _HEADER_NAME_VALUE_RE.fullmatch(names[0])
        if match is None:
            raise _error(f"skill marker {marker!r} has an unsupported name declaration")
        skill_name = _validate_name(match[2], f"skill name in {marker!r}")
        if _HEADER_DESCRIPTION_RE.search(header[1]) is None:
            raise _error(f"skill marker {marker!r} must declare a nonempty description")
        if relative_directory != ".":
            basename = relative_directory.rsplit("/", 1)[-1]
            if skill_name != basename:
                raise _error(
                    f"skill {skill_name!r} does not match directory basename {basename!r}"
                )
        folded = skill_name.casefold()
        duplicate = next((name for name in skills if name.casefold() == folded), None)
        if duplicate is not None:
            raise _error(f"duplicate skill name {skill_name!r} in source {source_id!r}")
        skills[skill_name] = relative_directory
        roots.append(relative_directory)

    if not skills:
        raise _error(f"source {source_id!r} selection contains no skills")

    root_parts = [(root, _path_parts(root)) for root in roots]
    for index, (left_name, left) in enumerate(root_parts):
        for right_name, right in root_parts[index + 1 :]:
            if _is_prefix(left, right) or _is_prefix(right, left):
                raise _error(
                    f"source {source_id!r} contains nested skill roots "
                    f"{left_name!r} and {right_name!r}"
                )
    return dict(sorted(skills.items()))


def _normalize_plugin_path(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise _error(f"{label} must be a path string")
    normalized = value[2:] if value.startswith("./") else value
    return _validate_literal_path(normalized, label, allow_dot=True)


def _path_is_retained(path: str, files: Mapping[str, PublishedFile]) -> bool:
    if path == ".":
        return True
    if path in files:
        return True
    prefix = f"{path}/"
    return any(name.startswith(prefix) for name in files)


def _validate_retained_path(
    value: Any,
    label: str,
    files: Mapping[str, PublishedFile],
) -> str:
    path = _normalize_plugin_path(value, label)
    if not _path_is_retained(path, files):
        raise _error(f"{label} refers to content not retained by selection: {value!r}")
    return path


def _path_values(value: Any, label: str) -> list[str]:
    if isinstance(value, str):
        return [value]
    if not isinstance(value, list):
        raise _error(f"{label} must be a path string or a list of path strings")
    if any(not isinstance(item, str) for item in value):
        raise _error(f"{label} must contain only path strings")
    return value


def _validate_hook_document(
    document: Any,
    label: str,
    files: Mapping[str, PublishedFile],
) -> None:
    if not isinstance(document, dict) or set(document) != {"hooks"}:
        raise _error(f"{label} must be an object with exactly one key, 'hooks'")
    events = document["hooks"]
    if not isinstance(events, dict):
        raise _error(f"{label}.hooks must be an object")
    for event, groups in events.items():
        if not isinstance(event, str) or not isinstance(groups, list):
            raise _error(f"{label} hook events must map to lists")
        for group_index, group in enumerate(groups):
            if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
                raise _error(f"{label} group {event}[{group_index}] must contain a hooks list")
            for hook_index, hook in enumerate(group["hooks"]):
                if (
                    not isinstance(hook, dict)
                    or hook.get("type") != "command"
                    or not isinstance(hook.get("command"), str)
                ):
                    raise _error(
                        f"{label} hook {event}[{group_index}].hooks[{hook_index}] "
                        "must be a command hook with a string command"
                    )
                for reference in PLUGIN_PATH_RE.findall(hook["command"]):
                    _validate_retained_path(
                        reference,
                        f"plugin-root reference in {label}",
                        files,
                    )


def _validate_package_files(files: Mapping[str, PublishedFile], source_id: str) -> None:
    for name, selected in sorted(files.items()):
        if name.split("/")[-1] != "package.json":
            continue
        package = _parse_json_bytes(selected.data, f"package.json {name!r} in {source_id!r}")
        if not isinstance(package, dict):
            raise _error(f"package.json {name!r} in {source_id!r} must contain an object")
        for field in ("dependencies", "devDependencies", "optionalDependencies", "scripts"):
            if package.get(field):
                raise _error(
                    f"package.json {name!r} in {source_id!r} has nonempty {field}"
                )


def _normalize_manifest(
    source_id: str,
    files: Mapping[str, PublishedFile],
    skills: Mapping[str, str],
) -> dict[str, Any]:
    retained_files = dict(files)
    # The generated manifest itself is retained even when the input omitted it.
    retained_files.setdefault(_MANIFEST_PATH, PublishedFile(b"", False))

    manifest_file = files.get(_MANIFEST_PATH)
    if manifest_file is None:
        manifest: dict[str, Any] = {"name": source_id}
    else:
        parsed = _parse_json_bytes(
            manifest_file.data, f"plugin manifest for source {source_id!r}"
        )
        if not isinstance(parsed, dict):
            raise _error(f"plugin manifest for source {source_id!r} must contain an object")
        manifest = dict(parsed)
        if manifest.get("name") != source_id:
            raise _error(f"plugin manifest name must equal source ID {source_id!r}")

    unknown = set(manifest) - _ALLOWED_MANIFEST_FIELDS
    if unknown:
        raise _error(
            f"plugin manifest for {source_id!r} has unsupported fields: {sorted(unknown)!r}"
        )
    for field in _MANIFEST_STRING_FIELDS:
        if field in manifest and not isinstance(manifest[field], str):
            raise _error(f"plugin manifest field {field!r} must be a string")
    if manifest.get("name") != source_id:
        raise _error(f"plugin manifest name must equal source ID {source_id!r}")

    if "keywords" in manifest:
        keywords = manifest["keywords"]
        if not isinstance(keywords, list) or any(not isinstance(item, str) for item in keywords):
            raise _error("plugin manifest keywords must be a list of strings")
    if "author" in manifest:
        author = manifest["author"]
        if (
            not isinstance(author, dict)
            or not isinstance(author.get("name"), str)
            or not author["name"].strip()
            or any(not isinstance(value, str) for value in author.values())
        ):
            raise _error(
                "plugin manifest author must be an object with a nonblank string name "
                "and string values"
            )

    if "skills" in manifest:
        for index, value in enumerate(_path_values(manifest["skills"], "manifest skills")):
            _normalize_plugin_path(value, f"manifest skills[{index}]")

    for field in ("agents", "outputStyles"):
        if field in manifest:
            for index, value in enumerate(_path_values(manifest[field], f"manifest {field}")):
                _validate_retained_path(
                    value,
                    f"manifest {field}[{index}]",
                    retained_files,
                )

    if "hooks" in manifest:
        hooks = manifest["hooks"]
        if isinstance(hooks, str):
            hook_path = _validate_retained_path(hooks, "manifest hooks", retained_files)
            if hook_path == _DEFAULT_HOOKS_PATH:
                raise _error(
                    "manifest hooks may not name automatically loaded hooks/hooks.json"
                )
            if not hook_path.endswith(".json") or hook_path not in retained_files:
                raise _error("manifest hooks path must name a retained JSON file")
            hook_document = _parse_json_bytes(
                retained_files[hook_path].data, f"hook document {hook_path!r}"
            )
            _validate_hook_document(
                hook_document, f"hook document {hook_path!r}", retained_files
            )
        elif isinstance(hooks, dict):
            _validate_hook_document(hooks, "inline manifest hooks", retained_files)
        else:
            raise _error("plugin manifest hooks must be an inline object or path string")

    if _DEFAULT_HOOKS_PATH in files:
        default_hooks = _parse_json_bytes(
            files[_DEFAULT_HOOKS_PATH].data, "default hooks/hooks.json"
        )
        _validate_hook_document(default_hooks, "default hooks/hooks.json", retained_files)

    manifest.pop("version", None)
    manifest["skills"] = [
        "." if directory == "." else f"./{directory}"
        for directory in sorted(skills.values())
    ]
    if "description" not in manifest:
        manifest["description"] = f"Selected {source_id} skills managed by chezmoi."
    return manifest


def _check_matt_dependencies(source_id: str, skills: Mapping[str, str]) -> None:
    if source_id != "mattpocock-skills":
        return
    selected = set(skills)
    for skill, dependencies in _MATT_DEPENDENCIES.items():
        if skill not in selected:
            continue
        missing = [dependency for dependency in dependencies if dependency not in selected]
        if missing:
            raise _error(
                f"Matt skill {skill!r} requires selected skills {', '.join(missing)}"
            )


def _build_candidate(
    home: Path,
    source_id: str,
    declaration: Any,
    output_roots: Sequence[str],
) -> Candidate:
    _validate_name(source_id, "source ID")
    if not isinstance(declaration, Mapping):
        raise _error(f"source {source_id!r} declaration must be a mapping")
    unknown = set(declaration) - {"directory", "include", "exclude"}
    if unknown:
        raise _error(f"source {source_id!r} has unsupported fields: {sorted(unknown)!r}")
    if "directory" not in declaration or "include" not in declaration:
        raise _error(f"source {source_id!r} requires directory and include")

    directory = _validate_literal_path(
        declaration["directory"], f"source {source_id!r} directory", allow_dot=True
    )
    directory_folded = tuple(part.casefold() for part in _path_parts(directory))
    for output_root in output_roots:
        output_folded = tuple(part.casefold() for part in _path_parts(output_root))
        if _is_prefix(directory_folded, output_folded) or _is_prefix(
            output_folded, directory_folded
        ):
            raise _error(
                f"source {source_id!r} directory overlaps output root {output_root!r}"
            )

    includes_value = declaration["include"]
    excludes_value = declaration.get("exclude", [])
    if not isinstance(includes_value, list) or not includes_value:
        raise _error(f"source {source_id!r} include must be a nonempty list")
    if not isinstance(excludes_value, list):
        raise _error(f"source {source_id!r} exclude must be a list")
    includes = [
        _validate_literal_path(value, f"source {source_id!r} include", allow_dot=True)
        for value in includes_value
    ]
    excludes = [
        _validate_literal_path(value, f"source {source_id!r} exclude", allow_dot=True)
        for value in excludes_value
    ]

    source_root = home if directory == "." else _exact_existing_path(
        home, directory, f"source {source_id!r} directory"
    )
    _assert_safe_existing_ancestors(
        source_root, f"source {source_id!r} directory", require_leaf=True
    )
    source_stat = os.lstat(source_root)
    _reject_reparse(source_root, source_stat, f"source {source_id!r} directory")
    if not stat.S_ISDIR(source_stat.st_mode):
        raise _error(f"source {source_id!r} directory is not a directory")

    files = _select_files(source_id, source_root, includes, excludes)
    _validate_selected_metadata_paths(files, source_id)
    skills = _discover_skills(files, source_id)
    _validate_package_files(files, source_id)
    _check_matt_dependencies(source_id, skills)
    manifest = _normalize_manifest(source_id, files, skills)

    normalized_files = dict(files)
    normalized_files[_MANIFEST_PATH] = PublishedFile(json_bytes(manifest), False)
    _check_selected_path_collisions(
        normalized_files, f"normalized source {source_id!r}"
    )
    seed_digest = tree_digest(normalized_files)
    version = f"0.0.0-s{seed_digest}"
    manifest["version"] = version
    normalized_files[_MANIFEST_PATH] = PublishedFile(json_bytes(manifest), False)
    final_digest = tree_digest(normalized_files)
    return Candidate(
        files=dict(sorted(normalized_files.items())),
        skills=dict(sorted(skills.items())),
        version=version,
        digest=final_digest,
    )


def _build_candidates(
    home: Path,
    sources: Any,
    reserved_names: Iterable[str],
) -> dict[str, Candidate]:
    if not isinstance(sources, Mapping):
        raise _error("sources must be a mapping")
    source_ids: dict[str, str] = {}
    for source_id in sources:
        _validate_name(source_id, "source ID")
        folded = source_id.casefold()
        if folded in source_ids:
            raise _error(
                f"source IDs collide case-insensitively: {source_ids[folded]!r}, {source_id!r}"
            )
        source_ids[folded] = source_id

    candidates: dict[str, Candidate] = {}
    for source_id in sorted(sources):
        candidates[source_id] = _build_candidate(
            home,
            source_id,
            sources[source_id],
            (MARKETPLACE_REL, SHARED_REL),
        )

    reserved: dict[str, str] = {}
    for value in reserved_names:
        if not isinstance(value, str):
            raise _error("reserved skill names must be strings")
        reserved[value.casefold()] = value

    discovered: dict[str, tuple[str, str]] = {}
    for source_id, candidate in sorted(candidates.items()):
        for skill_name in sorted(candidate.skills):
            folded = skill_name.casefold()
            if folded in reserved:
                raise _error(
                    f"selected skill {skill_name!r} is reserved by {reserved[folded]!r}"
                )
            if folded in discovered:
                previous_source, previous_name = discovered[folded]
                raise _error(
                    f"duplicate skill name across sources: {previous_name!r} in "
                    f"{previous_source!r} and {skill_name!r} in {source_id!r}"
                )
            discovered[folded] = (source_id, skill_name)
    return candidates


def _validate_marketplace_base(value: Any, candidates: Mapping[str, Candidate]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _error("marketplace base must contain a JSON object")
    if "name" not in value:
        raise _error("marketplace base is missing name")
    _validate_name(value["name"], "marketplace name")
    owner = value.get("owner")
    if (
        not isinstance(owner, dict)
        or not isinstance(owner.get("name"), str)
        or not owner["name"].strip()
    ):
        raise _error("marketplace owner.name must be a nonblank string")
    fixed_plugins = value.get("plugins")
    if not isinstance(fixed_plugins, list):
        raise _error("marketplace plugins must be a list")

    names: dict[str, str] = {}
    for index, plugin in enumerate(fixed_plugins):
        if not isinstance(plugin, dict) or "name" not in plugin:
            raise _error(f"marketplace plugin {index} must be an object with a name")
        plugin_name = _validate_name(plugin["name"], f"marketplace plugin {index} name")
        folded = plugin_name.casefold()
        if folded in names:
            raise _error(
                f"duplicate marketplace plugin names {names[folded]!r} and {plugin_name!r}"
            )
        names[folded] = plugin_name
    for source_id in sorted(candidates):
        folded = source_id.casefold()
        if folded in names:
            raise _error(
                f"generated plugin {source_id!r} collides with fixed plugin {names[folded]!r}"
            )
        names[folded] = source_id

    marketplace = dict(value)
    marketplace["plugins"] = list(fixed_plugins) + [
        {"name": source_id, "source": f"./generated-skills/{source_id}"}
        for source_id in sorted(candidates)
    ]
    return marketplace


def _parse_receipt(data: bytes) -> _Receipt:
    value = _parse_json_bytes(data, "ownership receipt")
    if not isinstance(value, dict) or set(value) != {"schema", "sources", "marketplace"}:
        raise _error("ownership receipt must contain exactly schema, sources, and marketplace")
    if isinstance(value["schema"], bool) or not isinstance(value["schema"], int) or value["schema"] != 1:
        raise _error("ownership receipt schema must be integer 1")
    if not isinstance(value["sources"], dict):
        raise _error("ownership receipt sources must be an object")
    if not isinstance(value["marketplace"], str) or not DIGEST_RE.fullmatch(value["marketplace"]):
        raise _error("ownership receipt marketplace must be a lowercase SHA-256 digest")

    source_names: dict[str, str] = {}
    shared_names: dict[str, tuple[str, str]] = {}
    sources: dict[str, _ReceiptSource] = {}
    for source_id, source_value in value["sources"].items():
        _validate_name(source_id, "receipt source ID")
        folded_source = source_id.casefold()
        if folded_source in source_names:
            raise _error("receipt source IDs collide case-insensitively")
        source_names[folded_source] = source_id
        if not isinstance(source_value, dict) or set(source_value) != {"digest", "skills"}:
            raise _error(
                f"receipt source {source_id!r} must contain exactly digest and skills"
            )
        digest = source_value["digest"]
        if not isinstance(digest, str) or not DIGEST_RE.fullmatch(digest):
            raise _error(f"receipt source {source_id!r} has an invalid digest")
        skills_value = source_value["skills"]
        if not isinstance(skills_value, dict):
            raise _error(f"receipt source {source_id!r} skills must be an object")
        skills: dict[str, str] = {}
        local_names: set[str] = set()
        for skill_name, relative in skills_value.items():
            _validate_name(skill_name, "receipt skill name")
            folded_skill = skill_name.casefold()
            if folded_skill in local_names:
                raise _error(f"receipt source {source_id!r} has colliding skill names")
            local_names.add(folded_skill)
            relative_path = _validate_literal_path(
                relative, f"receipt path for skill {skill_name!r}", allow_dot=True
            )
            if folded_skill in shared_names:
                previous_source, previous_name = shared_names[folded_skill]
                raise _error(
                    f"receipt has duplicate shared skill {previous_name!r} in "
                    f"{previous_source!r} and {skill_name!r} in {source_id!r}"
                )
            shared_names[folded_skill] = (source_id, skill_name)
            skills[skill_name] = relative_path
        sources[source_id] = _ReceiptSource(digest, dict(sorted(skills.items())))
    return _Receipt(dict(sorted(sources.items())), value["marketplace"])


def _receipt_value(candidates: Mapping[str, Candidate], marketplace_bytes: bytes) -> dict[str, Any]:
    return {
        "schema": 1,
        "sources": {
            source_id: {
                "digest": candidate.digest,
                "skills": dict(sorted(candidate.skills.items())),
            }
            for source_id, candidate in sorted(candidates.items())
        },
        "marketplace": hashlib.sha256(marketplace_bytes).hexdigest(),
    }


def _scan_tree(path: Path, label: str) -> dict[str, PublishedFile]:
    try:
        root_stat = os.lstat(path)
    except OSError as exc:
        raise _error(f"cannot inspect {label} {path}: {exc}") from exc
    _reject_reparse(path, root_stat, label)
    if not stat.S_ISDIR(root_stat.st_mode):
        raise _error(f"{label} is not a real directory: {path}")
    files: dict[str, PublishedFile] = {}

    def walk(directory: Path, prefix: str) -> None:
        try:
            with os.scandir(directory) as iterator:
                entries = sorted(iterator, key=lambda item: item.name)
        except OSError as exc:
            raise _error(f"cannot scan {label} directory {directory}: {exc}") from exc
        for entry in entries:
            relative = entry.name if not prefix else f"{prefix}/{entry.name}"
            try:
                entry_stat = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise _error(f"cannot inspect {label} entry {entry.path}: {exc}") from exc
            _reject_reparse(Path(entry.path), entry_stat, label)
            if stat.S_ISDIR(entry_stat.st_mode):
                walk(Path(entry.path), relative)
            elif stat.S_ISREG(entry_stat.st_mode):
                try:
                    data = Path(entry.path).read_bytes()
                except OSError as exc:
                    raise _error(f"cannot read {label} file {entry.path}: {exc}") from exc
                files[relative] = PublishedFile(data, bool(entry_stat.st_mode & 0o111))
            else:
                raise _error(f"{label} contains a nonregular file: {entry.path}")

    walk(path, "")
    _check_selected_path_collisions(files, label)
    return files


def _current_tree_digest(path: Path, label: str) -> str:
    return tree_digest(_scan_tree(path, label))


def _link_compare_value(value: str) -> str:
    if os.name != "nt":
        return value
    normalized = value.replace("/", "\\")
    folded = normalized.casefold()
    if folded.startswith("\\\\?\\unc\\"):
        normalized = "\\\\" + normalized[8:]
    elif folded.startswith("\\??\\unc\\"):
        normalized = "\\\\" + normalized[8:]
    elif folded.startswith("\\\\?\\"):
        normalized = normalized[4:]
    elif folded.startswith("\\??\\"):
        normalized = normalized[4:]
    # Account for Windows case-insensitivity and slash spelling without
    # collapsing dot or dot-dot components.
    return ntpath.normcase(normalized)


def _link_is_absolute(value: str) -> bool:
    return ntpath.isabs(value) if os.name == "nt" else os.path.isabs(value)


def _require_expected_link(path: Path, expected_target: Path, label: str) -> None:
    try:
        st = os.lstat(path)
    except OSError as exc:
        raise _error(f"cannot inspect {label} {path}: {exc}") from exc
    if not stat.S_ISLNK(st.st_mode):
        raise _error(f"{label} is not a real directory symlink: {path}")
    if os.name == "nt":
        if getattr(st, "st_reparse_tag", _IO_REPARSE_TAG_SYMLINK) != _IO_REPARSE_TAG_SYMLINK:
            raise _error(f"{label} is a junction or unsupported reparse point: {path}")
        if not st.st_file_attributes & _FILE_ATTRIBUTE_DIRECTORY:
            raise _error(f"{label} is not a real directory symlink: {path}")
    try:
        stored = os.readlink(path)
    except OSError as exc:
        raise _error(f"cannot read {label} target {path}: {exc}") from exc
    if not _link_is_absolute(stored):
        raise _error(f"{label} target must be absolute: {path}")
    if _link_compare_value(stored) != _link_compare_value(str(expected_target)):
        raise _error(
            f"{label} target is not owned: expected {expected_target}, found {stored}"
        )
    if os.path.lexists(expected_target):
        target_stat = os.lstat(expected_target)
        _reject_reparse(expected_target, target_stat, f"{label} target")
        if not stat.S_ISDIR(target_stat.st_mode):
            raise _error(f"{label} does not target a real directory: {expected_target}")


def _link_matches(path: Path, expected_target: Path) -> bool:
    if not os.path.lexists(path):
        return False
    try:
        _require_expected_link(path, expected_target, "managed link")
    except PublicationError:
        return False
    return True


def _derive_links(home: Path, sources: Mapping[str, _ReceiptSource | Candidate]) -> dict[str, Path]:
    links: dict[str, Path] = {}
    generated_root = home.joinpath(*GENERATED_REL.split("/"))
    for source_id, source in sorted(sources.items()):
        for skill_name, relative in sorted(source.skills.items()):
            target = generated_root / source_id
            if relative != ".":
                target = target.joinpath(*relative.split("/"))
            links[skill_name] = target
    return links


def _validate_output_parents(home: Path) -> None:
    _assert_safe_existing_ancestors(home, "home", require_leaf=True)
    home_stat = os.lstat(home)
    _reject_reparse(home, home_stat, "home")
    if not stat.S_ISDIR(home_stat.st_mode):
        raise _error(f"home is not a directory: {home}")
    for relative, label in (
        (MARKETPLACE_REL, "marketplace root"),
        (GENERATED_REL, "generated-skills root"),
        (SHARED_REL, "shared-skills root"),
        (f"{MARKETPLACE_REL}/.claude-plugin", "marketplace metadata directory"),
    ):
        exists = _strict_output_chain(home, relative, label)
        if exists:
            path = home.joinpath(*relative.split("/"))
            st = os.lstat(path)
            _reject_reparse(path, st, label)
            if not stat.S_ISDIR(st.st_mode):
                raise _error(f"{label} is not a directory: {path}")


def _read_receipt(home: Path) -> tuple[_Receipt | None, bytes | None]:
    root = home.joinpath(*MARKETPLACE_REL.split("/"))
    path = home.joinpath(*RECEIPT_REL.split("/"))
    slot = _strict_slot(root, path.name, "ownership receipt") if os.path.lexists(root) else None
    if slot is None:
        return None, None
    data = _read_regular_bytes(slot, "ownership receipt")
    return _parse_receipt(data), data


def _preflight(
    home: Path,
    candidates: dict[str, Candidate],
    marketplace_bytes: bytes,
    receipt_bytes: bytes,
    marketplace_name: str,
) -> _Plan:
    _validate_output_parents(home)
    market_root = home.joinpath(*MARKETPLACE_REL.split("/"))
    generated_root = home.joinpath(*GENERATED_REL.split("/"))
    shared_root = home.joinpath(*SHARED_REL.split("/"))
    marketplace_path = home.joinpath(*MARKETPLACE_FILE_REL.split("/"))
    receipt_path = home.joinpath(*RECEIPT_REL.split("/"))
    work_path = home.joinpath(*WORK_REL.split("/"))

    if os.path.lexists(market_root):
        work_slot = _strict_slot(market_root, work_path.name, "publisher work directory")
        if work_slot is not None:
            raise _error(
                f"publisher work directory already exists; inspect it manually: {work_slot}"
            )

    old_receipt, old_receipt_bytes = _read_receipt(home)
    old_sources = old_receipt.sources if old_receipt is not None else {}

    all_sources = sorted(set(old_sources) | set(candidates))
    view_present: dict[str, bool] = {}
    for source_id in all_sources:
        slot = _strict_slot(generated_root, source_id, f"publication {source_id!r}")
        present = slot is not None
        view_present[source_id] = present
        old_source = old_sources.get(source_id)
        if old_source is None:
            if present:
                raise _error(
                    f"unowned publication destination already exists: {generated_root / source_id}"
                )
            continue
        if present:
            digest = _current_tree_digest(slot, f"owned publication {source_id!r}")
            if digest != old_source.digest:
                raise _error(f"owned publication {source_id!r} does not match its receipt")

    metadata_root = marketplace_path.parent
    marketplace_slot = (
        _strict_slot(metadata_root, marketplace_path.name, "generated marketplace")
        if os.path.lexists(metadata_root)
        else None
    )
    old_marketplace_bytes: bytes | None = None
    if marketplace_slot is not None:
        if old_receipt is None:
            raise _error(f"unowned generated marketplace already exists: {marketplace_slot}")
        old_marketplace_bytes = _read_regular_bytes(
            marketplace_slot, "generated marketplace"
        )
        if hashlib.sha256(old_marketplace_bytes).hexdigest() != old_receipt.marketplace:
            raise _error("generated marketplace does not match its receipt")

    old_links = _derive_links(home, old_sources)
    new_links = _derive_links(home, candidates)
    all_link_names = sorted(set(old_links) | set(new_links))
    link_present: dict[str, bool] = {}
    for skill_name in all_link_names:
        slot = _strict_slot(shared_root, skill_name, f"shared skill {skill_name!r}")
        present = slot is not None
        link_present[skill_name] = present
        old_link = old_links.get(skill_name)
        if present:
            if old_link is None:
                raise _error(f"unowned shared skill entry already exists: {slot}")
            _require_expected_link(slot, old_link, f"shared skill {skill_name!r}")

    view_changes: dict[str, str] = {}
    actions: list[str] = []
    for source_id in all_sources:
        old_source = old_sources.get(source_id)
        candidate = candidates.get(source_id)
        if old_source is None and candidate is not None:
            view_changes[source_id] = "publish"
            actions.append(f"publish source {source_id}")
        elif old_source is not None and candidate is None:
            view_changes[source_id] = "remove"
            actions.append(f"remove source {source_id}")
        elif old_source is not None and candidate is not None:
            if old_source.digest != candidate.digest:
                view_changes[source_id] = "update"
                actions.append(f"update source {source_id}")
            elif not view_present[source_id]:
                view_changes[source_id] = "repair"
                actions.append(f"repair source {source_id}")

    link_changes: dict[str, str] = {}
    for skill_name in all_link_names:
        old_link = old_links.get(skill_name)
        new_link = new_links.get(skill_name)
        if old_link is None and new_link is not None:
            link_changes[skill_name] = "create"
            actions.append(f"create shared skill {skill_name}")
        elif old_link is not None and new_link is None:
            link_changes[skill_name] = "remove"
            actions.append(f"remove shared skill {skill_name}")
        elif old_link is not None and new_link is not None:
            if _link_compare_value(str(old_link)) != _link_compare_value(str(new_link)):
                link_changes[skill_name] = "retarget"
                actions.append(f"retarget shared skill {skill_name}")
            elif not link_present[skill_name]:
                link_changes[skill_name] = "repair"
                actions.append(f"repair shared skill {skill_name}")

    marketplace_change: str | None = None
    if old_marketplace_bytes is None:
        marketplace_change = "write" if old_receipt is None else "repair"
        actions.append(f"{marketplace_change} marketplace")
    elif old_marketplace_bytes != marketplace_bytes:
        marketplace_change = "write"
        actions.append("write marketplace")

    receipt_change = old_receipt_bytes != receipt_bytes
    if receipt_change:
        actions.append("write ownership receipt")

    removed = sorted(set(old_sources) - set(candidates))
    report = Report(
        actions=list(actions), plugins=sorted(candidates), removed=removed,
        marketplace_name=marketplace_name,
    )
    return _Plan(
        home=home,
        candidates=candidates,
        old_receipt=old_receipt,
        old_receipt_bytes=old_receipt_bytes,
        old_marketplace_bytes=old_marketplace_bytes,
        marketplace_bytes=marketplace_bytes,
        receipt_bytes=receipt_bytes,
        old_links=old_links,
        new_links=new_links,
        view_changes=view_changes,
        link_changes=link_changes,
        marketplace_change=marketplace_change,
        receipt_change=receipt_change,
        actions=actions,
        report=report,
    )


def _same_entry(path: Path, witness: os.stat_result) -> bool:
    _assert_safe_existing_ancestors(path.parent, "transaction path parent", require_leaf=False)
    try:
        current = os.lstat(path)
    except FileNotFoundError:
        return False
    return os.path.samestat(current, witness) and stat.S_IFMT(current.st_mode) == stat.S_IFMT(witness.st_mode)


def _transfer_applied(transfer: _Transfer) -> bool:
    """Reconcile an intent using identity, never matching content as authorship."""

    at_source = _same_entry(transfer.source, transfer.witness)
    at_destination = _same_entry(transfer.destination, transfer.witness)
    if at_destination and (transfer.hardlink or not os.path.lexists(transfer.source)):
        return True
    if at_source and not at_destination:
        return False
    raise _error(f"transaction transfer has uncertain completion: {transfer.source} -> {transfer.destination}")


def _acquire_directory(acquisition: _DirectoryAcquisition) -> None:
    acquisition.state = "pending"
    try:
        os.mkdir(acquisition.path)
    except FileExistsError:
        acquisition.state = "refused"
        raise
    st = os.lstat(acquisition.path)
    _reject_reparse(acquisition.path, st, "transaction directory")
    if not stat.S_ISDIR(st.st_mode):
        raise _error(f"transaction directory is not a directory: {acquisition.path}")
    acquisition.witness = st
    acquisition.state = "owned"


def _owns_directory(acquisition: _DirectoryAcquisition) -> bool:
    if acquisition.state in {"unattempted", "refused"}:
        return False
    if acquisition.witness is None:
        if not os.path.lexists(acquisition.path):
            return False
        raise _error(f"directory acquisition is uncertain; preserve {acquisition.path}")
    if not _same_entry(acquisition.path, acquisition.witness):
        raise _error(f"transaction directory changed; preserve {acquisition.path}")
    return True


def _ensure_directory(path: Path, home: Path, created: list[_DirectoryAcquisition]) -> None:
    if path == home:
        return
    try:
        relative = path.relative_to(home)
    except ValueError as exc:
        raise _error(f"refusing to create directory outside home: {path}") from exc
    current = home
    for component in relative.parts:
        slot = _strict_slot(current, component, f"output directory {path}")
        if slot is None:
            candidate = current / component
            acquisition = _DirectoryAcquisition(candidate)
            created.append(acquisition)
            try:
                _acquire_directory(acquisition)
            except FileExistsError:
                # A racing creator must still have produced exactly the safe directory.
                slot = _strict_slot(current, component, f"output directory {path}")
                if slot is None:
                    raise _error(f"output directory appeared with unsafe spelling: {candidate}")
            except OSError as exc:
                raise _error(f"cannot create output directory {candidate}: {exc}") from exc
            else:
                slot = candidate
        st = os.lstat(slot)
        _reject_reparse(slot, st, f"output directory {path}")
        if not stat.S_ISDIR(st.st_mode):
            raise _error(f"output parent is not a directory: {slot}")
        current = slot


def _open_lock_descriptor(path: Path, *, create: bool) -> int:
    if not create:
        st = os.lstat(path)
        _reject_reparse(path, st, "publisher lock")
        if not stat.S_ISREG(st.st_mode):
            raise _error(f"publisher lock is not a regular file: {path}")

    if os.name == "nt":
        # The CRT's O_EXCL can follow a dangling symlink on Windows. Open the
        # leaf itself and disallow deletion/retargeting while the handle is held.
        import ctypes
        import msvcrt
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        create_file = kernel32.CreateFileW
        create_file.argtypes = (
            wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
            wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
        )
        create_file.restype = wintypes.HANDLE
        handle = create_file(
            str(path), 0x80000000 | 0x40000000, 0x1 | 0x2, None,
            1 if create else 3,  # CREATE_NEW / OPEN_EXISTING
            0x00200000 | 0x80, None,  # OPEN_REPARSE_POINT / NORMAL
        )
        if handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return msvcrt.open_osfhandle(handle, os.O_RDWR | os.O_BINARY)
        except BaseException:
            close_handle = kernel32.CloseHandle
            close_handle.argtypes = (wintypes.HANDLE,)
            close_handle.restype = wintypes.BOOL
            close_handle(handle)
            raise

    flags = os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    if create:
        flags |= os.O_CREAT | os.O_EXCL
    return os.open(path, flags, 0o644)


class _WriterLock:
    def __init__(self, home: Path) -> None:
        self.home = home
        self.path = home.joinpath(*LOCK_REL.split("/"))
        self.file: BinaryIO | None = None
        self._windows_locked = False
        self._posix_locked = False

    def __enter__(self) -> _WriterLock:
        # Parent creation is the sole publication-side effect allowed before lock.
        market_root = self.path.parent
        _ensure_directory(market_root, self.home, [])
        slot = _strict_slot(market_root, self.path.name, "publisher lock")
        created = slot is None
        try:
            descriptor = _open_lock_descriptor(self.path, create=created)
        except FileExistsError:
            # A race is handled as an existing lock file, never by replacing it.
            created = False
            slot = _strict_slot(market_root, self.path.name, "publisher lock")
            if slot is None:
                raise _error("publisher lock appeared with unsafe spelling")
            descriptor = _open_lock_descriptor(self.path, create=False)
        except OSError as exc:
            raise _error(f"cannot open publisher lock {self.path}: {exc}") from exc
        self.file = os.fdopen(descriptor, "r+b", buffering=0)
        try:
            st = os.fstat(descriptor)
            if not stat.S_ISREG(st.st_mode):
                raise _error(f"publisher lock is not a regular file: {self.path}")
            path_st = os.lstat(self.path)
            _reject_reparse(self.path, path_st, "publisher lock")
            if not os.path.samestat(st, path_st):
                raise _error("publisher lock changed while being opened")
            try:
                if os.name == "nt":
                    import msvcrt

                    self.file.seek(0)
                    msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
                    self._windows_locked = True
                else:
                    import fcntl

                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    self._posix_locked = True
            except (OSError, BlockingIOError) as exc:
                raise _error("another skill publisher holds the writer lock") from exc

            locked_path_stat = os.lstat(self.path)
            _reject_reparse(self.path, locked_path_stat, "publisher lock")
            if not os.path.samestat(st, locked_path_stat):
                raise _error("publisher lock changed after locking")
            self.file.seek(0)
            marker = self.file.read()
            if created:
                if marker:
                    raise _error("new publisher lock unexpectedly contains data")
                self.file.seek(0)
                self.file.write(LOCK_MARKER)
                self.file.truncate()
                self.file.flush()
                os.fsync(descriptor)
            elif marker != LOCK_MARKER:
                raise _error(
                    f"publisher lock has a foreign or incomplete marker: {self.path}"
                )
            return self
        except BaseException:
            self.__exit__(*sys.exc_info())
            raise

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if self.file is None:
            return
        descriptor = self.file.fileno()
        try:
            if self._windows_locked:
                import msvcrt

                self.file.seek(0)
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            elif self._posix_locked:
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            self.file.close()
            self.file = None


def _verify_pre_mutation(plan: _Plan) -> None:
    home = plan.home
    _validate_output_parents(home)
    receipt_path = home.joinpath(*RECEIPT_REL.split("/"))
    market_root = receipt_path.parent
    receipt_slot = _strict_slot(market_root, receipt_path.name, "ownership receipt")
    if plan.old_receipt_bytes is None:
        if receipt_slot is not None:
            raise _error("ownership receipt appeared during publication")
    else:
        if receipt_slot is None:
            raise _error("ownership receipt disappeared during publication")
        if _read_regular_bytes(receipt_slot, "ownership receipt") != plan.old_receipt_bytes:
            raise _error("ownership receipt changed during publication")

    old_sources = plan.old_receipt.sources if plan.old_receipt else {}
    generated_root = home.joinpath(*GENERATED_REL.split("/"))
    for source_id in sorted(set(old_sources) | set(plan.candidates)):
        slot = _strict_slot(generated_root, source_id, f"publication {source_id!r}")
        old_source = old_sources.get(source_id)
        if old_source is None:
            if slot is not None:
                raise _error(f"unowned publication {source_id!r} appeared during publication")
        elif slot is not None:
            if _current_tree_digest(slot, f"owned publication {source_id!r}") != old_source.digest:
                raise _error(f"owned publication {source_id!r} changed during publication")

    shared_root = home.joinpath(*SHARED_REL.split("/"))
    for skill_name in sorted(set(plan.old_links) | set(plan.new_links)):
        slot = _strict_slot(shared_root, skill_name, f"shared skill {skill_name!r}")
        old_link = plan.old_links.get(skill_name)
        if slot is not None:
            if old_link is None:
                raise _error(f"unowned shared skill {skill_name!r} appeared during publication")
            _require_expected_link(slot, old_link, f"shared skill {skill_name!r}")

    marketplace_path = home.joinpath(*MARKETPLACE_FILE_REL.split("/"))
    marketplace_slot = _strict_slot(
        marketplace_path.parent, marketplace_path.name, "generated marketplace"
    ) if os.path.lexists(marketplace_path.parent) else None
    if plan.old_marketplace_bytes is None:
        if marketplace_slot is not None:
            raise _error("generated marketplace appeared during publication")
    else:
        if marketplace_slot is None:
            raise _error("generated marketplace disappeared during publication")
        if _read_regular_bytes(marketplace_slot, "generated marketplace") != plan.old_marketplace_bytes:
            raise _error("generated marketplace changed during publication")


def _verify_new_outputs(plan: _Plan) -> None:
    """Verify the complete attested state immediately before receipt commit."""

    home = plan.home
    generated_root = home.joinpath(*GENERATED_REL.split("/"))
    old_sources = plan.old_receipt.sources if plan.old_receipt else {}
    for source_id in sorted(set(old_sources) | set(plan.candidates)):
        path = generated_root / source_id
        candidate = plan.candidates.get(source_id)
        if candidate is None:
            if os.path.lexists(path):
                raise _error(f"removed publication reappeared before commit: {path}")
            continue
        if not os.path.lexists(path):
            raise _error(f"new publication is missing before commit: {path}")
        if _current_tree_digest(path, f"new publication {source_id!r}") != candidate.digest:
            raise _error(f"new publication {source_id!r} changed before commit")

    shared_root = home.joinpath(*SHARED_REL.split("/"))
    for skill_name in sorted(set(plan.old_links) | set(plan.new_links)):
        path = shared_root / skill_name
        target = plan.new_links.get(skill_name)
        if target is None:
            if os.path.lexists(path):
                raise _error(f"removed shared skill reappeared before commit: {path}")
            continue
        if not os.path.lexists(path):
            raise _error(f"new shared skill is missing before commit: {path}")
        _require_expected_link(path, target, f"new shared skill {skill_name!r}")

    marketplace_path = home.joinpath(*MARKETPLACE_FILE_REL.split("/"))
    if not os.path.lexists(marketplace_path):
        raise _error("generated marketplace is missing before receipt commit")
    if _read_regular_bytes(marketplace_path, "generated marketplace") != plan.marketplace_bytes:
        raise _error("generated marketplace changed before receipt commit")


def _write_tree(path: Path, files: Mapping[str, PublishedFile]) -> None:
    for relative, selected in sorted(files.items()):
        destination = path.joinpath(*relative.split("/"))
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb") as output:
            output.write(selected.data)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(destination, 0o755 if selected.executable else 0o644)


def _create_directory_link(link: Path, target: Path) -> None:
    """Filesystem seam for failure-injection tests."""

    os.symlink(str(target), str(link), target_is_directory=True)


def _install_directory_link(transfer: _Transfer) -> None:
    """Install an already-owned symlink without overwriting an arriving entry."""

    if transfer.hardlink:
        os.link(transfer.source, transfer.destination, follow_symlinks=False)
    else:
        os.rename(transfer.source, transfer.destination)


def _atomic_replace_file(write: _FileWrite) -> None:
    path = write.path
    descriptor: int | None = None
    temporary_name: str | None = None
    output: BinaryIO | None = None
    write.preparing = True
    try:
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        output = os.fdopen(descriptor, "wb")
        temporary = Path(temporary_name)
        write.prepared = _Transfer(temporary, path, os.fstat(descriptor), write.old is None)
        write.preparing = False
        output.write(write.new)
        output.flush()
        os.fsync(output.fileno())
        output.close()
        os.chmod(temporary, 0o644)
        if write.old is None:
            if os.path.lexists(path):
                raise _error(f"destination appeared before atomic write: {path}")
            try:
                os.link(temporary, path)
            except FileExistsError as exc:
                raise _error(f"destination appeared before atomic write: {path}") from exc
        else:
            if not os.path.lexists(path):
                raise _error(f"destination disappeared before atomic write: {path}")
            if _read_regular_bytes(path, f"atomic destination {path.name}") != write.old:
                raise _error(f"destination changed before atomic write: {path}")
            os.replace(temporary, path)
        # Retain the prepared identity until recovery or committed cleanup.
    except BaseException:
        # A caught interruption can precede ordinary preparation enrollment.
        # Recover the acquisition witness while the descriptor is still owned.
        if write.prepared is None and descriptor is not None and temporary_name is not None:
            try:
                write.prepared = _Transfer(Path(temporary_name), path, os.fstat(descriptor), write.old is None)
                write.preparing = False
            except OSError:
                pass  # Unresolved acquisition blocks cleanup below; never guess.
        raise
    finally:
        if output is not None:
            output.close()
        elif descriptor is not None:
            os.close(descriptor)


def _cleanup_file_temporary(write: _FileWrite) -> None:
    prepared = write.prepared
    if prepared is None and write.preparing:
        raise _error(f"commit temporary acquisition is uncertain; inspect {write.path.parent}")
    if prepared is not None and os.path.lexists(prepared.source):
        if not _same_entry(prepared.source, prepared.witness):
            raise _error(f"prepared commit file changed; preserve {prepared.source}")
        prepared.source.unlink()


def _write_marketplace(write: _FileWrite) -> None:
    """Marketplace-write seam for failure-injection tests."""

    _atomic_replace_file(write)


def _write_receipt(write: _FileWrite) -> None:
    """Receipt-write seam for failure-injection tests."""

    _atomic_replace_file(write)


def _cleanup_work(path: Path) -> None:
    """Post-commit/recovery cleanup seam for failure-injection tests."""

    shutil.rmtree(path)


def _remove_verified_tree(path: Path, digest: str) -> None:
    if not os.path.lexists(path):
        return
    if _current_tree_digest(path, f"transaction-installed publication {path.name!r}") != digest:
        raise _error(f"transaction-installed publication changed before recovery: {path}")
    shutil.rmtree(path)


def _restore_file(path: Path, new: bytes, old: bytes | None) -> None:
    if not os.path.lexists(path):
        if old is None:
            return
        raise _error(f"transaction output disappeared before recovery: {path}")
    current = _read_regular_bytes(path, f"transaction output {path.name}")
    if current != new:
        raise _error(f"transaction output changed before recovery: {path}")
    if old is None:
        path.unlink()
    else:
        restoration = _FileWrite(path, old, new)
        _atomic_replace_file(restoration)
        _cleanup_file_temporary(restoration)


def _restore_backup(transfer: _Transfer, label: str) -> None:
    if os.path.lexists(transfer.source):
        raise _error(f"cannot restore {label} over existing path: {transfer.source}")
    os.rename(transfer.destination, transfer.source)


def _recover(work: Path, record: _TransactionRecord) -> list[str]:
    failures: list[str] = []

    def attempt(description: str, operation: Any) -> None:
        try:
            operation()
        except BaseException as exc:  # recovery must attempt every independent step
            failures.append(f"{description}: {exc}")

    for write in reversed(record.file_writes):
        def restore_write(w: _FileWrite = write) -> None:
            if w.prepared is not None and _transfer_applied(w.prepared):
                _restore_file(w.path, w.new, w.old)

        attempt(f"restore {write.path}", restore_write)

    for transfer, target in reversed(record.created_links):
        def remove_link(op: _Transfer = transfer, t: Path = target) -> None:
            if not _transfer_applied(op):
                return
            if not _link_matches(op.destination, t):
                raise _error(f"transaction-installed link changed before recovery: {op.destination}")
            op.destination.unlink()

        attempt(f"remove new link {transfer.destination}", remove_link)

    for transfer, digest in reversed(record.installed_views):
        def remove_view(op: _Transfer = transfer, d: str = digest) -> None:
            if _transfer_applied(op):
                _remove_verified_tree(op.destination, d)

        attempt(f"remove new publication {transfer.destination}", remove_view)

    for transfer, digest in reversed(record.backed_views):
        def restore_view(op: _Transfer = transfer, d: str = digest) -> None:
            if not _transfer_applied(op):
                if os.path.lexists(op.destination):
                    raise _error(f"unowned publication backup appeared: {op.destination}")
                return
            if _current_tree_digest(op.destination, "publication backup") != d:
                raise _error(f"publication backup changed: {op.destination}")
            _restore_backup(op, "publication")

        attempt(f"restore publication {transfer.source}", restore_view)

    for transfer, target in reversed(record.backed_links):
        def restore_link(op: _Transfer = transfer, t: Path = target) -> None:
            if not _transfer_applied(op):
                if os.path.lexists(op.destination):
                    raise _error(f"unowned link backup appeared: {op.destination}")
                return
            _require_expected_link(op.destination, t, "link backup")
            _restore_backup(op, "link")

        attempt(f"restore link {transfer.source}", restore_link)

    for write in record.file_writes:
        attempt(f"remove prepared commit file for {write.path}", lambda w=write: _cleanup_file_temporary(w))

    for acquisition in reversed(record.created_directories):
        def remove_empty(a: _DirectoryAcquisition = acquisition) -> None:
            if _owns_directory(a):
                os.rmdir(a.path)

        attempt(f"remove transaction-created directory {acquisition.path}", remove_empty)

    if not failures:
        def cleanup_owned_work() -> None:
            if _owns_directory(record.work):
                _cleanup_work(work)

        attempt(f"remove work directory {work}", cleanup_owned_work)
    return failures


def _execute_plan(plan: _Plan) -> Report:
    if not plan.actions:
        return plan.report

    home = plan.home
    work = home.joinpath(*WORK_REL.split("/"))
    generated_root = home.joinpath(*GENERATED_REL.split("/"))
    shared_root = home.joinpath(*SHARED_REL.split("/"))
    marketplace_path = home.joinpath(*MARKETPLACE_FILE_REL.split("/"))
    receipt_path = home.joinpath(*RECEIPT_REL.split("/"))
    record = _TransactionRecord.empty(work)

    try:
        if os.path.lexists(work):
            raise _error(f"publisher work directory appeared during publication: {work}")
        _acquire_directory(record.work)

        staged_views: dict[str, Path] = {}
        if any(change != "remove" for change in plan.view_changes.values()):
            new_root = work / "new"
            os.mkdir(new_root)
            for source_id, change in sorted(plan.view_changes.items()):
                if change == "remove":
                    continue
                candidate = plan.candidates[source_id]
                staged = new_root / source_id
                os.mkdir(staged)
                _write_tree(staged, candidate.files)
                if _current_tree_digest(staged, f"staged publication {source_id!r}") != candidate.digest:
                    raise _error(f"staged publication {source_id!r} failed digest verification")
                staged_views[source_id] = staged

        links_to_create = [
            name
            for name, change in plan.link_changes.items()
            if change in {"create", "retarget", "repair"}
        ]
        if links_to_create:
            probe_target = work / "link-probe-target"
            probe_link = work / "link-probe"
            os.mkdir(probe_target)
            _create_directory_link(probe_link, probe_target)
            probe_installed = work / "link-probe-installed"
            probe_transfer = _Transfer(probe_link, probe_installed, os.lstat(probe_link), os.name != "nt")
            _install_directory_link(probe_transfer)
            _require_expected_link(probe_installed, probe_target, "directory-symlink probe")
            if not _same_entry(probe_installed, probe_transfer.witness):
                raise _error("directory-symlink installation did not preserve identity")
            probe_installed.unlink()
            if os.path.lexists(probe_link):
                probe_link.unlink()
            probe_target.rmdir()

        _verify_pre_mutation(plan)

        old_views_root: Path | None = None
        for source_id, change in sorted(plan.view_changes.items()):
            if change not in {"update", "remove"}:
                continue
            current = generated_root / source_id
            if not os.path.lexists(current):
                continue
            old_source = plan.old_receipt.sources[source_id] if plan.old_receipt else None
            if old_source is None or _current_tree_digest(
                current, f"owned publication {source_id!r}"
            ) != old_source.digest:
                raise _error(f"publication {source_id!r} changed immediately before backup")
            if old_views_root is None:
                old_views_root = work / "old-views"
                os.mkdir(old_views_root)
            backup = old_views_root / source_id
            if os.path.lexists(backup):
                raise _error(f"publication backup destination exists: {backup}")
            transfer = _Transfer(current, backup, os.lstat(current))
            record.backed_views.append((transfer, old_source.digest))
            os.rename(current, backup)

        old_links_root: Path | None = None
        for skill_name, change in sorted(plan.link_changes.items()):
            if change not in {"remove", "retarget"}:
                continue
            current = shared_root / skill_name
            if not os.path.lexists(current):
                continue
            expected = plan.old_links[skill_name]
            _require_expected_link(
                current, expected, f"shared skill {skill_name!r} immediately before backup"
            )
            if old_links_root is None:
                old_links_root = work / "old-links"
                os.mkdir(old_links_root)
            backup = old_links_root / skill_name
            if os.path.lexists(backup):
                raise _error(f"link backup destination exists: {backup}")
            transfer = _Transfer(current, backup, os.lstat(current))
            record.backed_links.append((transfer, expected))
            os.rename(current, backup)

        if staged_views:
            _ensure_directory(generated_root, home, record.created_directories)
            for source_id, staged in sorted(staged_views.items()):
                destination = generated_root / source_id
                if os.path.lexists(destination):
                    raise _error(f"publication destination appeared during transaction: {destination}")
                transfer = _Transfer(staged, destination, os.lstat(staged))
                record.installed_views.append((transfer, plan.candidates[source_id].digest))
                os.rename(staged, destination)

        if links_to_create:
            _ensure_directory(shared_root, home, record.created_directories)
            new_links_root = work / "new-links"
            os.mkdir(new_links_root)
            for skill_name in sorted(links_to_create):
                destination = shared_root / skill_name
                target = plan.new_links[skill_name]
                if os.path.lexists(destination):
                    raise _error(f"shared skill destination appeared during transaction: {destination}")
                staged_link = new_links_root / skill_name
                _create_directory_link(staged_link, target)
                _require_expected_link(staged_link, target, f"staged shared skill {skill_name!r}")
                transfer = _Transfer(staged_link, destination, os.lstat(staged_link), os.name != "nt")
                record.created_links.append((transfer, target))
                _install_directory_link(transfer)
                _require_expected_link(destination, target, f"new shared skill {skill_name!r}")

        if plan.marketplace_change is not None:
            _ensure_directory(marketplace_path.parent, home, record.created_directories)
            write = _FileWrite(marketplace_path, plan.marketplace_bytes, plan.old_marketplace_bytes)
            record.file_writes.append(write)
            _write_marketplace(write)

        _verify_new_outputs(plan)

        if plan.receipt_change:
            write = _FileWrite(receipt_path, plan.receipt_bytes, plan.old_receipt_bytes)
            record.file_writes.append(write)
            _write_receipt(write)
    except BaseException as exc:
        failures = _recover(work, record)
        if failures:
            detail = "; ".join(failures)
            raise PublicationError(
                f"publication failed ({exc}); recovery was incomplete. "
                f"Preserve and inspect {work}: {detail}"
            ) from exc
        if record.work.state in {"unattempted", "refused"}:
            raise PublicationError(f"publication refused; unowned work was preserved: {exc}") from exc
        raise PublicationError(
            f"publication failed; previous outputs were restored: {exc}"
        ) from exc

    # Both commit files now describe the new output.  Cleanup failures are
    # deliberately reported without attempting rollback from partial backups.
    try:
        for write in record.file_writes:
            _cleanup_file_temporary(write)
        if not _owns_directory(record.work):
            raise _error(f"work directory ownership is uncertain; preserve {work}")
        _cleanup_work(work)
    except BaseException as exc:
        raise PublicationError(
            f"publication committed, but cleanup failed; preserve and inspect {work}: {exc}",
            committed=True,
            report=plan.report,
        ) from exc
    return plan.report


def _publish(
    home: os.PathLike[str] | str,
    sources: Mapping[str, Any],
    base: os.PathLike[str] | str,
    *,
    dry_run: bool,
    reserved_names: Iterable[str],
) -> Report:
    home_path = _absolute_path(home)
    _assert_safe_existing_ancestors(home_path, "home", require_leaf=True)
    home_stat = os.lstat(home_path)
    _reject_reparse(home_path, home_stat, "home")
    if not stat.S_ISDIR(home_stat.st_mode):
        raise _error(f"home is not a directory: {home_path}")

    base_path = _absolute_path(base)
    base_value = _parse_json_bytes(
        _read_regular_bytes(base_path, "marketplace base"), "marketplace base"
    )
    candidates = _build_candidates(home_path, sources, reserved_names)
    marketplace = _validate_marketplace_base(base_value, candidates)
    marketplace_bytes = json_bytes(marketplace)
    receipt_bytes = json_bytes(_receipt_value(candidates, marketplace_bytes))

    if dry_run:
        plan = _preflight(home_path, candidates, marketplace_bytes, receipt_bytes, marketplace["name"])
        return plan.report

    with _WriterLock(home_path):
        plan = _preflight(home_path, candidates, marketplace_bytes, receipt_bytes, marketplace["name"])
        return _execute_plan(plan)


def publish(
    home: os.PathLike[str] | str,
    sources: Mapping[str, Any],
    base: os.PathLike[str] | str,
    *,
    dry_run: bool = False,
    reserved_names: Iterable[str] = (),
) -> Report:
    """Publish selected sources beneath *home* and return a deterministic report.

    ``dry_run`` performs candidate construction, validation, ownership preflight,
    and planning, but creates no directories, lock, staging data, files, or links.
    """

    try:
        return _publish(
            home,
            sources,
            base,
            dry_run=bool(dry_run),
            reserved_names=reserved_names,
        )
    except PublicationError:
        raise
    except Exception as exc:
        raise PublicationError(str(exc)) from exc


def _repository_reserved_names(repository_root: Path) -> tuple[str, ...]:
    names = {"herdr"}
    skills_root = repository_root / "dot_agents" / "skills"
    if os.path.lexists(skills_root):
        st = os.lstat(skills_root)
        _reject_reparse(skills_root, st, "repository skills directory")
        if not stat.S_ISDIR(st.st_mode):
            raise _error(f"repository skills path is not a directory: {skills_root}")
        try:
            with os.scandir(skills_root) as entries:
                for entry in entries:
                    entry_stat = entry.stat(follow_symlinks=False)
                    if stat.S_ISDIR(entry_stat.st_mode) and not _is_reparse(entry_stat):
                        names.add(entry.name)
        except OSError as exc:
            raise _error(f"cannot discover repository skill names: {exc}") from exc
    return tuple(sorted(names))


def _print_report(report: Report, *, dry_run: bool, marketplace_root: Path) -> None:
    if report.actions:
        heading = "Publication preview:" if dry_run else "Publication actions:"
        print(heading)
        prefix = "would " if dry_run else ""
        for action in report.actions:
            print(f"  - {prefix}{action}")
    else:
        print("Skill publication is already up to date; no actions are required.")
    print("Claude activation was not performed.")
    print("Suggested native Claude commands (review before running):")
    print(f"  claude plugin marketplace update {report.marketplace_name}")
    print(f'  claude plugin marketplace add "{marketplace_root}"')
    for plugin in report.plugins:
        print(f"  claude plugin update {plugin}@{report.marketplace_name} --scope user")
        print(f"  claude plugin install {plugin}@{report.marketplace_name} --scope user")
    for plugin in report.removed:
        print(f"  claude plugin uninstall {plugin}@{report.marketplace_name} --scope user")


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise PublicationError(f"invalid command line: {message}")


def main(argv: Sequence[str] | None = None) -> int:
    repository_root = Path(__file__).resolve().parent
    parser = _ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="validate and preview without writes")
    parser.add_argument("--home", type=Path, default=Path.home(), help="publication home")
    parser.add_argument(
        "--config",
        type=Path,
        default=repository_root / ".chezmoidata.toml",
        help="TOML file containing agent_skills.sources",
    )
    parser.add_argument(
        "--base",
        type=Path,
        default=repository_root
        / "dot_config"
        / "claude-code-chezmoi"
        / "marketplace-base.json",
        help="declarative marketplace base JSON",
    )
    try:
        arguments = parser.parse_args(argv)
        config_bytes = _read_regular_bytes(_absolute_path(arguments.config), "publisher config")
        try:
            config = tomllib.loads(config_bytes.decode("utf-8-sig"))
        except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
            raise _error(f"publisher config is not valid TOML: {exc}") from exc
        try:
            sources = config["agent_skills"]["sources"]
        except (KeyError, TypeError) as exc:
            raise _error("publisher config is missing data['agent_skills']['sources']") from exc
        reserved = _repository_reserved_names(repository_root)
        report = publish(
            arguments.home,
            sources,
            arguments.base,
            dry_run=arguments.dry_run,
            reserved_names=reserved,
        )
    except (PublicationError, OSError, TypeError, ValueError) as exc:
        print(f"Skill publication failed: {exc}", file=sys.stderr)
        return 1

    marketplace_root = _absolute_path(arguments.home).joinpath(*MARKETPLACE_REL.split("/"))
    _print_report(
        report,
        dry_run=arguments.dry_run,
        marketplace_root=marketplace_root,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
