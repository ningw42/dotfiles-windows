"""Behavioral and repository-integration tests for unified skill publication.

All publisher mutations use temporary homes.  Repository templates are rendered
with isolated chezmoi configuration/state, and the native Claude acceptance test
uses an isolated Claude profile.
"""

from __future__ import annotations

import ast
import copy
import contextlib
import hashlib
import inspect
import io
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import tomllib
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
import manage_skills as publisher  # noqa: E402


CHEZMOI = shutil.which("chezmoi")
POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")
CLAUDE = shutil.which("claude")

BASE_MARKETPLACE = {
    "name": "chezmoi",
    "description": "fixture marketplace",
    "owner": {"name": "test"},
    "plugins": [
        {
            "name": "fixed-plugin",
            "description": "fixture fixed entry",
            "source": "./plugins/fixed-plugin",
        }
    ],
}

MATT_SKILL_ROOTS = [
    "skills/engineering/ask-matt",
    "skills/engineering/diagnosing-bugs",
    "skills/engineering/grill-with-docs",
    "skills/engineering/triage",
    "skills/engineering/improve-codebase-architecture",
    "skills/engineering/setup-matt-pocock-skills",
    "skills/engineering/tdd",
    "skills/engineering/to-spec",
    "skills/engineering/to-tickets",
    "skills/engineering/wayfinder",
    "skills/engineering/implement",
    "skills/engineering/prototype",
    "skills/engineering/research",
    "skills/engineering/domain-modeling",
    "skills/engineering/codebase-design",
    "skills/engineering/code-review",
    "skills/engineering/resolving-merge-conflicts",
    "skills/engineering/wizard",
    "skills/productivity/grill-me",
    "skills/productivity/grilling",
    "skills/productivity/handoff",
    "skills/productivity/teach",
    "skills/productivity/to-questionnaire",
    "skills/productivity/wait-what",
    "skills/productivity/writing-for-agents",
]

# Independent contract table, not imported from the production checker.
EXPECTED_MATT_DEPENDENCIES = {
    "grill-me": ("grilling",),
    "grill-with-docs": ("grilling", "domain-modeling"),
    "tdd": ("codebase-design",),
    "implement": ("code-review", "tdd"),
    "improve-codebase-architecture": ("codebase-design", "grilling", "domain-modeling"),
    "wayfinder": (
        "codebase-design", "grilling", "domain-modeling", "research", "prototype", "wizard"
    ),
    "code-review": ("setup-matt-pocock-skills",),
    "to-spec": ("setup-matt-pocock-skills",),
    "to-tickets": ("setup-matt-pocock-skills",),
    "triage": ("setup-matt-pocock-skills",),
}

REPO_SKILL_NAMES = {
    "close-code-review",
    "develop-and-squash",
    "develop-and-submit-pr",
    "simplification-review",
    "subagent-parity",
    "traceability",
    "unlimited-subagent-turns",
}


# Test helpers deliberately reproduce public formats instead of calling private
# candidate/digest helpers.  Private functions are patched only at the explicit
# transaction-failure seams exercised below.
def canonical_json_bytes(value):
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode(
        "utf-8"
    )


def inventory_digest(files):
    inventory = [
        [name, executable, hashlib.sha256(data).hexdigest()]
        for name, (data, executable) in sorted(files.items())
    ]
    return hashlib.sha256(canonical_json_bytes(inventory)).hexdigest()


def scan_regular_tree(root):
    result = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        st = os.lstat(path)
        if stat.S_ISLNK(st.st_mode):
            raise AssertionError(f"unexpected link in regular tree: {path}")
        if path.is_file():
            result[relative] = (path.read_bytes(), bool(st.st_mode & 0o111))
    return result


def snapshot_entry(path):
    """Return a byte/target snapshot without following links."""

    if not os.path.lexists(path):
        return None
    st = os.lstat(path)
    if stat.S_ISLNK(st.st_mode):
        return ("link", os.readlink(path))
    if stat.S_ISREG(st.st_mode):
        return ("file", path.read_bytes(), bool(st.st_mode & 0o111))
    if not stat.S_ISDIR(st.st_mode):
        return ("other", stat.S_IFMT(st.st_mode))
    entries = {}
    with os.scandir(path) as iterator:
        for entry in sorted(iterator, key=lambda item: item.name):
            entries[entry.name] = snapshot_entry(Path(entry.path))
    return ("directory", entries)


def managed_snapshot(home):
    return {
        "generated": snapshot_entry(
            home / ".config" / "claude-code-chezmoi" / "generated-skills"
        ),
        "shared": snapshot_entry(home / ".agents" / "skills"),
        "marketplace": snapshot_entry(
            home
            / ".config"
            / "claude-code-chezmoi"
            / ".claude-plugin"
            / "marketplace.json"
        ),
        "receipt": snapshot_entry(
            home / ".config" / "claude-code-chezmoi" / ".skill-publisher.json"
        ),
    }


def path_mtimes(path):
    result = {}
    if not os.path.lexists(path):
        return result

    def visit(current, relative):
        st = os.lstat(current)
        result[relative] = st.st_mtime_ns
        if stat.S_ISDIR(st.st_mode) and not stat.S_ISLNK(st.st_mode):
            with os.scandir(current) as iterator:
                for entry in sorted(iterator, key=lambda item: item.name):
                    child_relative = f"{relative}/{entry.name}" if relative else entry.name
                    visit(Path(entry.path), child_relative)

    visit(path, "")
    return result


def directory_symlinks_available():
    with tempfile.TemporaryDirectory(prefix="skill-symlink-probe-") as temporary:
        root = Path(temporary)
        target = root / "target"
        link = root / "link"
        target.mkdir()
        try:
            os.symlink(str(target), str(link), target_is_directory=True)
            return link.is_symlink()
        except (NotImplementedError, OSError):
            return False


SYMLINKS_AVAILABLE = directory_symlinks_available()
SYMLINK_REASON = "directory symlinks are unavailable for isolated publication tests"


def normalized_link_target(path):
    """Normalize Windows' extended namespace spelling without resolving a link."""

    value = os.readlink(path)
    if os.name == "nt":
        folded = value.casefold()
        if folded.startswith("\\\\?\\unc\\"):
            value = "\\\\" + value[8:]
        elif folded.startswith("\\??\\unc\\"):
            value = "\\\\" + value[8:]
        elif folded.startswith("\\\\?\\") or folded.startswith("\\??\\"):
            value = value[4:]
        return os.path.normcase(value.replace("/", "\\"))
    return value


@contextlib.contextmanager
def held_writer_lock(home):
    """Hold the contract's byte-range writer lock without publisher internals."""

    path = home / ".config/claude-code-chezmoi/.skill-publisher.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"chezmoi skill publisher lock\n")
    lock_file = path.open("r+b", buffering=0)
    try:
        if os.name == "nt":
            import msvcrt

            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        if os.name == "nt":
            import msvcrt

            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        lock_file.close()


def skill_bytes(name, *, description="fixture skill", body="body\n", bom=False, crlf=False):
    newline = "\r\n" if crlf else "\n"
    text = (
        f"---{newline}"
        f"name: {name}{newline}"
        f"description: {description}{newline}"
        f"---{newline}"
        f"{body.replace(chr(10), newline)}"
    )
    data = text.encode("utf-8")
    return (b"\xef\xbb\xbf" + data) if bom else data


def write_bytes(path, data, *, executable=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    if executable:
        os.chmod(path, 0o755)
    return path


def write_skill(root, relative, name=None, **kwargs):
    relative_path = Path(relative)
    declared_name = name if name is not None else relative_path.name
    marker = root / relative_path / "SKILL.md" if relative != "." else root / "SKILL.md"
    write_bytes(marker, skill_bytes(declared_name, **kwargs))
    return marker


class PublisherCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="agent-skills-test-")
        self.root = Path(self.temporary.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.base = self.root / "marketplace-base.json"
        self.base.write_bytes(canonical_json_bytes(BASE_MARKETPLACE))

    def tearDown(self):
        self.temporary.cleanup()

    def source_root(self, source_id="example", suffix=None):
        name = suffix or source_id
        root = self.home / "inputs" / name
        root.mkdir(parents=True, exist_ok=True)
        return root

    def declaration(self, root, include=None, exclude=None):
        value = {
            "directory": root.relative_to(self.home).as_posix(),
            "include": list(include or ["."]),
        }
        if exclude is not None:
            value["exclude"] = list(exclude)
        return value

    def simple_source(self, source_id="example", skill_name="one", *, extra_files=None):
        root = self.source_root(source_id)
        write_skill(root, f"skills/{skill_name}", skill_name)
        for name, data in (extra_files or {}).items():
            write_bytes(root / name, data)
        return root, {source_id: self.declaration(root)}

    def publish(self, sources, **kwargs):
        return publisher.publish(self.home, sources, self.base, **kwargs)

    def require_symlinks(self):
        if not SYMLINKS_AVAILABLE:
            self.skipTest(SYMLINK_REASON)


class SelectionContractTests(PublisherCase):
    def test_selection_retains_nested_support_license_excludes_overlaps_and_literal_brackets(self):
        self.require_symlinks()
        root = self.source_root()
        marker = write_skill(root, "nested/one", "one")
        write_bytes(root / "nested" / "one" / "reference.txt", b"reference\n")
        write_bytes(root / "nested" / "drop.txt", b"drop\n")
        write_bytes(root / "LICENSE", b"license\n")
        write_bytes(root / "[literal].txt", b"brackets\n")
        sources = {
            "example": self.declaration(
                root,
                include=["nested", "nested/one", "LICENSE", "[literal].txt"],
                exclude=["nested/drop.txt", "nested/absent"],
            )
        }

        report = self.publish(sources)
        view = self.home / ".config/claude-code-chezmoi/generated-skills/example"
        self.assertEqual(report.plugins, ["example"])
        self.assertEqual((view / "nested/one/SKILL.md").read_bytes(), marker.read_bytes())
        self.assertEqual((view / "nested/one/reference.txt").read_bytes(), b"reference\n")
        self.assertEqual((view / "LICENSE").read_bytes(), b"license\n")
        self.assertEqual((view / "[literal].txt").read_bytes(), b"brackets\n")
        self.assertFalse((view / "nested/drop.txt").exists())

    def test_selection_refuses_missing_unsafe_wildcard_and_empty_results_before_publication(self):
        root = self.source_root()
        write_skill(root, "skills/one", "one")
        output_root = self.home / ".config" / "claude-code-chezmoi"

        invalid_includes = [
            "missing",
            "/absolute",
            "C:/absolute",
            "skills\\one",
            "skills//one",
            "skills/../one",
            "skills/one.",
            "skills/<bad>",
            "skills/\x01bad",
            "skills/NUL.txt",
            "skills/*",
            "",
        ]
        for invalid in invalid_includes:
            with self.subTest(include=repr(invalid)):
                sources = {"example": self.declaration(root, include=[invalid])}
                with self.assertRaises(publisher.PublicationError):
                    self.publish(sources, dry_run=True)
                self.assertFalse(output_root.exists())

        with self.assertRaisesRegex(publisher.PublicationError, "contains no skills"):
            self.publish(
                {"example": self.declaration(root, include=["skills"], exclude=["."])},
                dry_run=True,
            )
        self.assertFalse(output_root.exists())

    def test_recursive_selection_refuses_real_control_filename_before_output_creation(self):
        root = self.source_root()
        write_skill(root, "skills/one", "one")
        unsafe = write_bytes(root / "skills/one/support\x7f.txt", b"unsafe name\n")
        sources = {"example": self.declaration(root, include=["skills"])}

        for dry_run in (True, False):
            with self.subTest(dry_run=dry_run):
                with self.assertRaisesRegex(publisher.PublicationError, "control character"):
                    self.publish(sources, dry_run=dry_run)
                self.assertFalse(os.path.lexists(self.home / ".config"))
                self.assertFalse(os.path.lexists(self.home / ".agents"))
                self.assertEqual(unsafe.read_bytes(), b"unsafe name\n")

    def test_recursive_selection_refuses_unsafe_skill_ancestor_before_output_creation(self):
        # Windows needs the extended namespace to retain a literal trailing dot.
        if os.name == "nt":
            self.home = Path("\\\\?\\" + str(self.home))
        try:
            root = self.source_root()
            marker = write_skill(root, "skills/levels./two", "two")
            self.assertEqual([entry.name for entry in (root / "skills").iterdir()], ["levels."])
            sources = {"example": self.declaration(root, include=["skills"])}

            for dry_run in (True, False):
                with self.subTest(dry_run=dry_run):
                    with self.assertRaisesRegex(publisher.PublicationError, "ending in a space or dot"):
                        self.publish(sources, dry_run=dry_run)
                    self.assertFalse(os.path.lexists(self.home / ".config"))
                    self.assertFalse(os.path.lexists(self.home / ".agents"))
                    self.assertEqual(marker.read_bytes(), skill_bytes("two"))
        finally:
            # Ordinary Windows cleanup would normalize the unsafe component.
            shutil.rmtree(self.home)

    def test_excluded_and_unselected_subtrees_with_unsafe_entries_remain_untraversed(self):
        self.require_symlinks()
        root = self.source_root()
        marker = write_skill(root, "skills/one", "one")
        ignored = root / "ignored"
        write_bytes(ignored / "support\x7f.txt", b"ignored unsafe name\n")
        outside = self.root / "unselected-target"
        write_bytes(outside / "keep.txt", b"outside selection\n")
        os.symlink(str(outside), str(ignored / "directory-link"), target_is_directory=True)
        before = snapshot_entry(ignored)
        outside_before = snapshot_entry(outside)
        original_scandir = os.scandir

        def guarded_scandir(path):
            if isinstance(path, (str, os.PathLike)):
                scanned = Path(path)
                self.assertNotEqual(scanned, ignored, "ignored subtree was traversed")
                self.assertNotIn(ignored, scanned.parents, "ignored descendant was traversed")
            return original_scandir(path)

        for selection, declaration in (
            ("excluded", self.declaration(root, include=["."], exclude=["ignored"])),
            ("unselected", self.declaration(root, include=["skills"])),
        ):
            with self.subTest(selection=selection):
                with mock.patch.object(os, "scandir", side_effect=guarded_scandir):
                    preview = self.publish({"example": declaration}, dry_run=True)
                    report = self.publish({"example": declaration})
                self.assertEqual(preview.actions, report.actions)
                view = self.home / ".config/claude-code-chezmoi/generated-skills/example"
                self.assertEqual((view / "skills/one/SKILL.md").read_bytes(), marker.read_bytes())
                self.assertFalse(os.path.lexists(view / "ignored"))
                self.assertEqual(snapshot_entry(ignored), before)
                self.assertEqual(snapshot_entry(outside), outside_before)

    def test_selection_refuses_source_output_overlap_and_unknown_declaration_fields(self):
        cases = [
            {
                "directory": ".config/claude-code-chezmoi/raw",
                "include": ["."],
            },
            {"directory": ".agents", "include": ["skills"]},
            {"directory": "inputs/example", "include": ["."], "adopt": True},
        ]
        for declaration in cases:
            with self.subTest(declaration=declaration):
                with self.assertRaises(publisher.PublicationError):
                    self.publish({"example": declaration}, dry_run=True)


class DiscoveryContractTests(PublisherCase):
    def test_discovery_accepts_bom_crlf_quoted_names_and_preserves_marker_bytes(self):
        self.require_symlinks()
        root = self.source_root()
        single = write_skill(
            root,
            "skills/one",
            "'one' # literal quote and comment",
            description=">",
            bom=True,
            crlf=True,
            body="line one\nline two\n",
        )
        double_data = (
            b"---\nname: \"two\"\ndescription: |\n---\nsecond body\n"
        )
        double = write_bytes(root / "skills/two/SKILL.md", double_data)

        self.publish({"example": self.declaration(root)})
        view = self.home / ".config/claude-code-chezmoi/generated-skills/example"
        self.assertEqual((view / "skills/one/SKILL.md").read_bytes(), single.read_bytes())
        self.assertEqual((view / "skills/two/SKILL.md").read_bytes(), double.read_bytes())
        manifest = json.loads((view / ".claude-plugin/plugin.json").read_text("utf-8"))
        self.assertEqual(manifest["skills"], ["./skills/one", "./skills/two"])

    def test_discovery_accepts_a_root_skill_without_directory_name_inference(self):
        root = self.source_root()
        write_skill(root, ".", "root-skill")
        report = self.publish({"example": self.declaration(root)}, dry_run=True)
        self.assertIn("publish source example", report.actions)

    def test_discovery_refuses_marker_casing_name_description_duplicates_and_nested_roots(self):
        cases = []

        wrong_case = self.source_root(suffix="wrong-case")
        write_bytes(wrong_case / "skills/one/skill.md", skill_bytes("one"))
        cases.append(("named exactly SKILL.md", {"example": self.declaration(wrong_case)}))

        mismatch = self.source_root(suffix="mismatch")
        write_skill(mismatch, "skills/one", "two")
        cases.append(("directory basename", {"example": self.declaration(mismatch)}))

        no_description = self.source_root(suffix="no-description")
        write_bytes(
            no_description / "skills/one/SKILL.md",
            b"---\nname: one\ndescription:   \n---\nbody\n",
        )
        cases.append(("nonempty description", {"example": self.declaration(no_description)}))

        nested = self.source_root(suffix="nested")
        write_skill(nested, "outer", "outer")
        write_skill(nested, "outer/inner", "inner")
        cases.append(("nested skill roots", {"example": self.declaration(nested)}))

        duplicate_a = self.source_root(suffix="duplicate-a")
        duplicate_b = self.source_root(suffix="duplicate-b")
        write_skill(duplicate_a, "skills/one", "one")
        write_skill(duplicate_b, "other/one", "one")
        cases.append(
            (
                "duplicate skill name",
                {
                    "first": self.declaration(duplicate_a),
                    "second": self.declaration(duplicate_b),
                },
            )
        )

        for expected, sources in cases:
            with self.subTest(expected=expected):
                with self.assertRaisesRegex(publisher.PublicationError, expected):
                    self.publish(sources, dry_run=True)

    def test_discovery_refuses_reserved_herdr_and_repo_authored_names(self):
        for name in ("herdr", "traceability"):
            with self.subTest(name=name):
                root = self.source_root(suffix=f"reserved-{name}")
                write_skill(root, f"skills/{name}", name)
                with self.assertRaisesRegex(publisher.PublicationError, "reserved"):
                    self.publish(
                        {"example": self.declaration(root)},
                        dry_run=True,
                        reserved_names=("herdr", "traceability"),
                    )


class MetadataContractTests(PublisherCase):
    def test_metadata_is_preserved_paths_are_validated_and_skills_are_normalized(self):
        self.require_symlinks()
        root = self.source_root()
        write_skill(root, "skills/one", "one")
        write_bytes(root / "agents/reviewer.md", b"reviewer\n")
        write_bytes(root / "styles/concise.md", b"concise\n")
        write_bytes(root / "scripts/run.ps1", b"Write-Output ok\n")
        manifest = {
            "name": "example",
            "version": "99.1.0",
            "description": "upstream description",
            "author": {"name": "Fixture Author", "email": "author@example.test"},
            "homepage": "https://example.test/home",
            "repository": "https://example.test/repository",
            "license": "MIT",
            "keywords": ["one", "two"],
            "skills": ["./skills/unselected", "./skills/one"],
            "agents": "./agents/reviewer.md",
            "outputStyles": ["styles/concise.md"],
            "hooks": {
                "hooks": {
                    "SessionStart": [
                        {
                            "matcher": "startup",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "pwsh ${CLAUDE_PLUGIN_ROOT}/scripts/run.ps1",
                                    "timeout": 10,
                                }
                            ],
                        }
                    ]
                }
            },
        }
        write_bytes(root / ".claude-plugin/plugin.json", canonical_json_bytes(manifest))

        self.publish({"example": self.declaration(root)})
        generated = json.loads(
            (
                self.home
                / ".config/claude-code-chezmoi/generated-skills/example/.claude-plugin/plugin.json"
            ).read_text("utf-8")
        )
        for field in (
            "description",
            "author",
            "homepage",
            "repository",
            "license",
            "keywords",
            "agents",
            "outputStyles",
            "hooks",
        ):
            self.assertEqual(generated[field], manifest[field])
        self.assertEqual(generated["skills"], ["./skills/one"])
        self.assertRegex(generated["version"], r"\A0\.0\.0-s[0-9a-f]{64}\Z")
        self.assertNotEqual(generated["version"], manifest["version"])

    def test_metadata_synthesizes_manifest_and_description_when_absent(self):
        self.require_symlinks()
        root = self.source_root()
        write_skill(root, "skills/one", "one")
        self.publish({"example": self.declaration(root)})
        manifest_path = (
            self.home
            / ".config/claude-code-chezmoi/generated-skills/example/.claude-plugin/plugin.json"
        )
        manifest = json.loads(manifest_path.read_text("utf-8"))
        self.assertEqual(manifest["name"], "example")
        self.assertEqual(manifest["description"], "Selected example skills managed by chezmoi.")
        self.assertEqual(manifest["skills"], ["./skills/one"])

    def test_metadata_refuses_malformed_duplicate_and_unsupported_active_manifest_fields(self):
        root = self.source_root()
        write_skill(root, "skills/one", "one")
        manifest_path = root / ".claude-plugin/plugin.json"
        invalid_documents = {
            "malformed": b"{not-json",
            "duplicate": b'{"name":"example","name":"example"}\n',
            "commands": canonical_json_bytes({"name": "example", "commands": ["./commands/x"]}),
            "mcpServers": canonical_json_bytes({"name": "example", "mcpServers": {}}),
            "wrong-name": canonical_json_bytes({"name": "another"}),
        }
        for label, data in invalid_documents.items():
            with self.subTest(label=label):
                write_bytes(manifest_path, data)
                with self.assertRaises(publisher.PublicationError):
                    self.publish({"example": self.declaration(root)}, dry_run=True)

    def test_metadata_refuses_missing_hook_agent_style_and_plugin_root_dependencies(self):
        root = self.source_root()
        write_skill(root, "skills/one", "one")
        manifest_path = root / ".claude-plugin/plugin.json"
        manifests = {
            "agent": {"name": "example", "agents": "agents/missing.md"},
            "style": {"name": "example", "outputStyles": ["styles/missing.md"]},
            "hook-reference": {
                "name": "example",
                "hooks": {
                    "hooks": {
                        "SessionStart": [
                            {
                                "hooks": [
                                    {
                                        "type": "command",
                                        "command": "${CLAUDE_PLUGIN_ROOT}/scripts/missing.py",
                                    }
                                ]
                            }
                        ]
                    }
                },
            },
        }
        for label, manifest in manifests.items():
            with self.subTest(label=label):
                write_bytes(manifest_path, canonical_json_bytes(manifest))
                with self.assertRaisesRegex(publisher.PublicationError, "not retained"):
                    self.publish({"example": self.declaration(root)}, dry_run=True)

    def test_metadata_validates_default_hooks_and_rejects_double_registration(self):
        root = self.source_root()
        write_skill(root, "skills/one", "one")
        write_bytes(
            root / "hooks/hooks.json",
            canonical_json_bytes(
                {
                    "hooks": {
                        "SessionStart": [
                            {"hooks": [{"type": "command", "command": "echo ok"}]}
                        ]
                    }
                }
            ),
        )
        manifest_path = root / ".claude-plugin/plugin.json"
        write_bytes(
            manifest_path,
            canonical_json_bytes({"name": "example", "hooks": "hooks/hooks.json"}),
        )
        with self.assertRaisesRegex(publisher.PublicationError, "automatically loaded"):
            self.publish({"example": self.declaration(root)}, dry_run=True)

        write_bytes(manifest_path, canonical_json_bytes({"name": "example"}))
        report = self.publish({"example": self.declaration(root)}, dry_run=True)
        self.assertIn("publish source example", report.actions)

        write_bytes(root / "hooks/hooks.json", canonical_json_bytes({"hooks": []}))
        with self.assertRaisesRegex(publisher.PublicationError, "hooks must be an object"):
            self.publish({"example": self.declaration(root)}, dry_run=True)

    def test_metadata_preserves_nondefault_hooks_file_and_retained_command_reference(self):
        self.require_symlinks()
        hook_bytes = (
            b'{"hooks":{"SessionStart":[{"hooks":[{"type":"command",'
            b'"command":"pwsh ${CLAUDE_PLUGIN_ROOT}/scripts/run.ps1"}]}]}}\n'
        )
        _, sources = self.simple_source(extra_files={
            ".claude-plugin/plugin.json": canonical_json_bytes(
                {"name": "example", "hooks": "config/custom-hooks.json"}
            ),
            "config/custom-hooks.json": hook_bytes,
            "scripts/run.ps1": b"Write-Output fixture\n",
        })
        preview = self.publish(sources, dry_run=True)
        self.assertFalse(os.path.lexists(self.home / ".config"))
        self.assertEqual(self.publish(sources).actions, preview.actions)
        view = self.home / ".config/claude-code-chezmoi/generated-skills/example"
        manifest = json.loads((view / ".claude-plugin/plugin.json").read_bytes())
        self.assertEqual(manifest["hooks"], "config/custom-hooks.json")
        self.assertEqual((view / "config/custom-hooks.json").read_bytes(), hook_bytes)
        self.assertEqual((view / "scripts/run.ps1").read_bytes(), b"Write-Output fixture\n")

    def test_metadata_refuses_invalid_nondefault_hooks_files_and_missing_captured_support(self):
        root, _ = self.simple_source()
        write_bytes(root / ".claude-plugin/plugin.json", canonical_json_bytes(
            {"name": "example", "hooks": "config/custom-hooks.json"}
        ))
        valid_hooks = (
            b'{"hooks":{"SessionStart":[{"hooks":[{"type":"command",'
            b'"command":"pwsh ${CLAUDE_PLUGIN_ROOT}/scripts/run.ps1"}]}]}}\n'
        )
        hook_path = root / "config/custom-hooks.json"
        support_path = root / "scripts/run.ps1"
        cases = [
            ("missing-file", None, True, [], "manifest hooks.*not retained"),
            ("excluded-file", valid_hooks, True, ["config/custom-hooks.json"], "manifest hooks.*not retained"),
            ("malformed-json", b"{not-json", True, [], "not valid JSON"),
            ("duplicate-json", b'{"hooks":{},"hooks":{}}', True, [], "duplicate JSON key"),
            ("invalid-shape", b'{"hooks":[]}', True, [], "hooks must be an object"),
            ("missing-support", valid_hooks, False, [], "plugin-root reference.*not retained"),
            ("excluded-support", valid_hooks, True, ["scripts/run.ps1"], "plugin-root reference.*not retained"),
        ]
        for label, data, has_support, exclude, expected in cases:
            with self.subTest(case=label):
                if data is None:
                    hook_path.unlink(missing_ok=True)
                else:
                    write_bytes(hook_path, data)
                if has_support:
                    write_bytes(support_path, b"Write-Output fixture\n")
                else:
                    support_path.unlink()
                before = snapshot_entry(root)
                sources = {"example": self.declaration(root, exclude=exclude)}
                for dry_run in (True, False):
                    with self.subTest(dry_run=dry_run):
                        with self.assertRaisesRegex(publisher.PublicationError, expected):
                            self.publish(sources, dry_run=dry_run)
                        self.assertFalse(os.path.lexists(self.home / ".config"))
                        self.assertFalse(os.path.lexists(self.home / ".agents"))
                        self.assertEqual(snapshot_entry(root), before)

    def test_metadata_refuses_unsupported_root_content_installers_and_package_activity(self):
        unsupported = [
            ".git/config",
            "commands/run.md",
            ".claude-plugin/marketplace.json",
            ".mcp.json",
            ".lsp.json",
            "package-lock.json",
            "npm-shrinkwrap.json",
            "yarn.lock",
            "bun.lock",
            "bun.lockb",
            "pnpm-lock.yaml",
        ]
        for index, relative in enumerate(unsupported):
            with self.subTest(relative=relative):
                root = self.source_root(suffix=f"unsupported-{index}")
                write_skill(root, "skills/one", "one")
                write_bytes(root / relative, b"{}\n")
                with self.assertRaises(publisher.PublicationError):
                    self.publish({"example": self.declaration(root)}, dry_run=True)

        for field in ("dependencies", "devDependencies", "optionalDependencies", "scripts"):
            with self.subTest(package_field=field):
                root = self.source_root(suffix=f"package-{field}")
                write_skill(root, "skills/one", "one")
                write_bytes(root / "package.json", canonical_json_bytes({field: {"x": "1"}}))
                with self.assertRaisesRegex(publisher.PublicationError, field):
                    self.publish({"example": self.declaration(root)}, dry_run=True)

    def test_every_known_matt_dependency_omission_is_rejected(self):
        def dependency_closure(skill):
            selected = {skill}
            for prerequisite in EXPECTED_MATT_DEPENDENCIES.get(skill, ()):
                selected.update(dependency_closure(prerequisite))
            return selected

        for skill, prerequisites in EXPECTED_MATT_DEPENDENCIES.items():
            with self.subTest(skill=skill, selected="complete closure"):
                root = self.source_root(suffix=f"matt-{skill}")
                for name in sorted(dependency_closure(skill) | {"one"}):
                    write_skill(root, f"skills/{name}", name)
                report = self.publish(
                    {"mattpocock-skills": self.declaration(root)}, dry_run=True
                )
                self.assertEqual(report.plugins, ["mattpocock-skills"])

            for omitted in prerequisites:
                with self.subTest(skill=skill, omitted=omitted):
                    excluded = [f"skills/{omitted}"]
                    expected = f"Matt skill {skill!r} requires selected skills {omitted}"
                    with self.assertRaisesRegex(publisher.PublicationError, re.escape(expected) + r"\Z"):
                        self.publish(
                            {"mattpocock-skills": self.declaration(root, exclude=excluded)},
                            dry_run=True,
                        )
                    # An absent dependent imposes no requirement on that edge.
                    report = self.publish(
                        {"mattpocock-skills": self.declaration(
                            root, exclude=[*excluded, f"skills/{skill}"]
                        )},
                        dry_run=True,
                    )
                    self.assertEqual(report.plugins, ["mattpocock-skills"])
                    self.assertFalse(os.path.lexists(self.home / ".config"))
                    self.assertFalse(os.path.lexists(self.home / ".agents"))


@unittest.skipUnless(SYMLINKS_AVAILABLE, SYMLINK_REASON)
class VersioningAndNoOpContractTests(PublisherCase):
    def test_versions_change_only_for_retained_content_or_filter_changes_and_receipt_is_final_digest(self):
        root = self.source_root()
        write_skill(root, "skills/one", "one")
        write_bytes(root / "skills/one/support.txt", b"support-v1\n")
        write_bytes(root / "skills/one/optional.txt", b"optional\n")
        write_bytes(root / "LICENSE", b"license\n")
        write_bytes(root / "unselected.txt", b"outside\n")
        manifest_path = root / ".claude-plugin/plugin.json"
        write_bytes(
            manifest_path,
            canonical_json_bytes({"name": "example", "version": "1.0.0"}),
        )
        declaration = self.declaration(
            root,
            include=["skills/one", "LICENSE", ".claude-plugin/plugin.json"],
        )
        sources = {"example": declaration}
        self.publish(sources)
        view = self.home / ".config/claude-code-chezmoi/generated-skills/example"

        def version():
            return json.loads((view / ".claude-plugin/plugin.json").read_text("utf-8"))[
                "version"
            ]

        first = version()
        write_bytes(root / "skills/one/support.txt", b"support-v2\n")
        self.publish(sources)
        second = version()
        self.assertNotEqual(first, second, "selected support-file changes must change version")

        filtered = {
            "example": self.declaration(
                root,
                include=["skills/one", "LICENSE", ".claude-plugin/plugin.json"],
                exclude=["skills/one/optional.txt"],
            )
        }
        self.publish(filtered)
        third = version()
        self.assertNotEqual(second, third, "filters changing retained files must change version")

        equivalent = {
            "example": self.declaration(
                root,
                include=[
                    "skills/one",
                    "skills/one/SKILL.md",
                    "LICENSE",
                    ".claude-plugin/plugin.json",
                ],
                exclude=["skills/one/optional.txt", "absent"],
            )
        }
        report = self.publish(equivalent)
        self.assertEqual(report.actions, [])
        self.assertEqual(version(), third, "selection edits yielding identical content are a no-op")

        write_bytes(
            manifest_path,
            canonical_json_bytes({"name": "example", "version": "999.0.0"}),
        )
        report = self.publish(equivalent)
        self.assertEqual(report.actions, [])
        self.assertEqual(version(), third, "upstream version alone must not affect generated version")

        write_bytes(root / "unselected.txt", b"changed but still outside selection\n")
        report = self.publish(equivalent)
        self.assertEqual(report.actions, [])
        self.assertEqual(version(), third, "unselected changes must not affect generated version")

        files = scan_regular_tree(view)
        generated_manifest = json.loads(files[".claude-plugin/plugin.json"][0].decode("utf-8"))
        generated_version = generated_manifest.pop("version")
        seed_files = dict(files)
        seed_files[".claude-plugin/plugin.json"] = (
            canonical_json_bytes(generated_manifest),
            False,
        )
        self.assertEqual(generated_version, "0.0.0-s" + inventory_digest(seed_files))
        receipt = json.loads(
            (
                self.home / ".config/claude-code-chezmoi/.skill-publisher.json"
            ).read_text("utf-8")
        )
        self.assertEqual(receipt["sources"]["example"]["digest"], inventory_digest(files))

    def test_dry_run_is_pure_actions_match_real_run_and_no_op_preserves_mtimes(self):
        root, sources = self.simple_source(extra_files={"LICENSE": b"license\n"})
        market_root = self.home / ".config/claude-code-chezmoi"
        shared_root = self.home / ".agents/skills"

        preview = self.publish(sources, dry_run=True)
        self.assertFalse(market_root.exists(), "dry-run must not create lock/work/output parents")
        self.assertFalse(shared_root.exists(), "dry-run must not create shared link parents")
        real = self.publish(sources)
        self.assertEqual(preview.actions, real.actions)
        self.assertEqual(preview.plugins, real.plugins)
        self.assertEqual(preview.removed, real.removed)
        self.assertFalse((market_root / ".skill-publisher-work").exists())

        watched = [
            market_root / "generated-skills/example",
            shared_root / "one",
            market_root / ".claude-plugin/marketplace.json",
            market_root / ".skill-publisher.json",
            market_root / ".skill-publisher.lock",
        ]
        before = {str(path): path_mtimes(path) for path in watched}
        time.sleep(0.02)
        no_op = self.publish(sources)
        after = {str(path): path_mtimes(path) for path in watched}
        self.assertEqual(no_op.actions, [])
        self.assertEqual(before, after)


@unittest.skipUnless(SYMLINKS_AVAILABLE, SYMLINK_REASON)
class RemovalRepairAndMovementContractTests(PublisherCase):
    def test_explicit_removal_deletes_only_owned_views_and_links(self):
        first_root = self.source_root("first")
        second_root = self.source_root("second")
        write_skill(first_root, "skills/one", "one")
        write_skill(second_root, "skills/two", "two")
        unrelated = self.home / ".agents/skills/local-owner"
        write_bytes(unrelated / "keep.txt", b"keep\n")
        sources = {
            "first": self.declaration(first_root),
            "second": self.declaration(second_root),
        }
        self.publish(sources)

        report = self.publish({"first": self.declaration(first_root)})
        self.assertEqual(report.removed, ["second"])
        self.assertFalse(
            (self.home / ".config/claude-code-chezmoi/generated-skills/second").exists()
        )
        self.assertFalse(os.path.lexists(self.home / ".agents/skills/two"))
        self.assertEqual((unrelated / "keep.txt").read_bytes(), b"keep\n")
        self.assertTrue(os.path.lexists(self.home / ".agents/skills/one"))

    def test_missing_input_is_error_not_removal(self):
        root, sources = self.simple_source()
        self.publish(sources)
        before = managed_snapshot(self.home)
        shutil.rmtree(root)
        with self.assertRaises(publisher.PublicationError):
            self.publish(sources)
        self.assertEqual(managed_snapshot(self.home), before)

    def test_missing_owned_view_and_link_are_repaired(self):
        root, sources = self.simple_source()
        self.publish(sources)
        view = self.home / ".config/claude-code-chezmoi/generated-skills/example"
        link = self.home / ".agents/skills/one"

        shutil.rmtree(view)
        view_report = self.publish(sources)
        self.assertIn("repair source example", view_report.actions)
        self.assertTrue(view.is_dir())
        self.assertTrue(link.is_symlink())

        link.unlink()
        link_report = self.publish(sources)
        self.assertIn("repair shared skill one", link_report.actions)
        self.assertTrue(link.is_symlink())

    def test_dangling_owned_directory_link_is_preserved_when_view_is_repaired(self):
        _, sources = self.simple_source()
        self.publish(sources)
        before = managed_snapshot(self.home)
        view = self.home / ".config/claude-code-chezmoi/generated-skills/example"
        link = self.home / ".agents/skills/one"
        leaf = os.lstat(link)
        if os.name == "nt":
            self.assertTrue(leaf.st_file_attributes & stat.FILE_ATTRIBUTE_DIRECTORY)
        shutil.rmtree(view)
        self.assertTrue(link.is_symlink())
        self.assertFalse(link.exists())

        preview = self.publish(sources, dry_run=True)
        self.assertEqual(preview.actions, ["repair source example"])
        self.assertFalse(view.exists(), "preview must leave the link dangling")
        self.assertTrue(os.path.samestat(leaf, os.lstat(link)))
        report = self.publish(sources)
        self.assertEqual(report.actions, preview.actions)
        self.assertEqual(managed_snapshot(self.home), before)
        self.assertTrue(os.path.samestat(leaf, os.lstat(link)))
        self.assertEqual(os.lstat(link).st_mtime_ns, leaf.st_mtime_ns)
        self.assertEqual(self.publish(sources).actions, [])

    def test_skill_can_move_between_sources_with_link_retarget(self):
        first_root = self.source_root("first")
        second_root = self.source_root("second")
        write_skill(first_root, "skills/one", "one")
        write_skill(second_root, "different/one", "one")
        self.publish({"first": self.declaration(first_root)})

        report = self.publish({"second": self.declaration(second_root)})
        link = self.home / ".agents/skills/one"
        expected = (
            self.home
            / ".config/claude-code-chezmoi/generated-skills/second/different/one"
        )
        self.assertIn("retarget shared skill one", report.actions)
        self.assertEqual(report.removed, ["first"])
        self.assertEqual(normalized_link_target(link), os.path.normcase(str(expected)))
        self.assertFalse(
            os.path.lexists(
                self.home / ".config/claude-code-chezmoi/generated-skills/first"
            )
        )


@unittest.skipUnless(SYMLINKS_AVAILABLE, SYMLINK_REASON)
class OwnershipContractTests(PublisherCase):
    def test_foreign_generated_directory_is_refused_without_clobbering(self):
        _, sources = self.simple_source()
        foreign = self.home / ".config/claude-code-chezmoi/generated-skills/example"
        write_bytes(foreign / "foreign.txt", b"foreign\n")
        before = snapshot_entry(foreign)
        with self.assertRaisesRegex(publisher.PublicationError, "unowned publication"):
            self.publish(sources)
        self.assertEqual(snapshot_entry(foreign), before)

    def test_unowned_same_target_link_and_foreign_shared_directory_are_refused(self):
        _, sources = self.simple_source()
        shared = self.home / ".agents/skills"
        shared.mkdir(parents=True)
        expected = (
            self.home
            / ".config/claude-code-chezmoi/generated-skills/example/skills/one"
        )
        link = shared / "one"
        os.symlink(str(expected), str(link), target_is_directory=True)
        with self.assertRaisesRegex(publisher.PublicationError, "unowned shared skill"):
            self.publish(sources)
        self.assertEqual(normalized_link_target(link), os.path.normcase(str(expected)))

        link.unlink()
        write_bytes(link / "foreign.txt", b"foreign\n")
        with self.assertRaisesRegex(publisher.PublicationError, "unowned shared skill"):
            self.publish(sources)
        self.assertEqual((link / "foreign.txt").read_bytes(), b"foreign\n")

    def test_modified_view_marketplace_and_retargeted_link_are_each_refused(self):
        root, sources = self.simple_source(extra_files={"LICENSE": b"license\n"})
        self.publish(sources)
        view_file = (
            self.home
            / ".config/claude-code-chezmoi/generated-skills/example/skills/one/SKILL.md"
        )
        original_view = view_file.read_bytes()
        view_file.write_bytes(original_view + b"modified\n")
        with self.assertRaisesRegex(publisher.PublicationError, "does not match its receipt"):
            self.publish(sources)
        self.assertTrue(view_file.read_bytes().endswith(b"modified\n"))
        view_file.write_bytes(original_view)

        marketplace = (
            self.home
            / ".config/claude-code-chezmoi/.claude-plugin/marketplace.json"
        )
        original_marketplace = marketplace.read_bytes()
        marketplace.write_bytes(original_marketplace + b" ")
        with self.assertRaisesRegex(publisher.PublicationError, "marketplace does not match"):
            self.publish(sources)
        self.assertTrue(marketplace.read_bytes().endswith(b" "))
        marketplace.write_bytes(original_marketplace)

        link = self.home / ".agents/skills/one"
        link.unlink()
        other = self.home / "other-target"
        other.mkdir()
        os.symlink(str(other), str(link), target_is_directory=True)
        with self.assertRaisesRegex(publisher.PublicationError, "target is not owned"):
            self.publish(sources)
        self.assertEqual(normalized_link_target(link), os.path.normcase(str(other)))

    @unittest.skipUnless(os.name == "nt", "native file/directory symlink kinds are Windows-only")
    def test_receipt_owned_windows_file_link_is_refused_for_dangling_and_present_targets(self):
        _, sources = self.simple_source()
        self.publish(sources)
        view = self.home / ".config/claude-code-chezmoi/generated-skills/example"
        target = view / "skills/one"
        link = self.home / ".agents/skills/one"
        stored_target = os.readlink(link)
        self.assertTrue(os.path.isabs(stored_target))
        link.unlink()
        saved = self.root / "saved-view"
        view.rename(saved)
        # Python infers directory kind from existing targets, even when False.
        self.assertFalse(os.path.lexists(target))
        os.symlink(stored_target, str(link), target_is_directory=False)
        leaf = os.lstat(link)
        self.assertTrue(stat.S_ISLNK(leaf.st_mode))
        self.assertFalse(leaf.st_file_attributes & stat.FILE_ATTRIBUTE_DIRECTORY)
        self.assertEqual(os.readlink(link), stored_target)
        view_bytes = snapshot_entry(saved)

        for target_present in (False, True):
            if target_present:
                saved.rename(view)
            before = managed_snapshot(self.home)
            for dry_run in (True, False):
                with self.subTest(target_present=target_present, dry_run=dry_run):
                    with self.assertRaisesRegex(publisher.PublicationError, "not a real directory symlink"):
                        self.publish(sources, dry_run=dry_run)
                    self.assertEqual(managed_snapshot(self.home), before)
                    self.assertTrue(os.path.samestat(leaf, os.lstat(link)))
                    self.assertEqual(os.lstat(link).st_mtime_ns, leaf.st_mtime_ns)
                    self.assertEqual(os.lstat(link).st_file_attributes, leaf.st_file_attributes)
                    self.assertEqual(os.path.lexists(target), target_present)
                    self.assertEqual(snapshot_entry(view if target_present else saved), view_bytes)
                    self.assertFalse(os.path.lexists(view.parent.parent / ".skill-publisher-work"))

    def test_invalid_receipts_are_refused_and_preserved(self):
        _, sources = self.simple_source()
        market_root = self.home / ".config/claude-code-chezmoi"
        market_root.mkdir(parents=True)
        receipt = market_root / ".skill-publisher.json"
        invalid_values = [
            b"{not-json",
            canonical_json_bytes({"schema": True, "sources": {}, "marketplace": "0" * 64}),
            canonical_json_bytes(
                {"schema": 1, "sources": {}, "marketplace": "0" * 64, "extra": True}
            ),
            canonical_json_bytes(
                {
                    "schema": 1,
                    "sources": {
                        "example": {"digest": "bad", "skills": {"one": "skills/one"}}
                    },
                    "marketplace": "0" * 64,
                }
            ),
            canonical_json_bytes(
                {
                    "schema": 1,
                    "sources": {
                        "example": {
                            "digest": "1" * 64,
                            "skills": {"one": "../escape"},
                        }
                    },
                    "marketplace": "0" * 64,
                }
            ),
        ]
        for data in invalid_values:
            with self.subTest(receipt=data[:40]):
                receipt.write_bytes(data)
                with self.assertRaises(publisher.PublicationError):
                    self.publish(sources)
                self.assertEqual(receipt.read_bytes(), data)

    def test_case_collisions_are_refused_without_touching_the_existing_entry(self):
        _, sources = self.simple_source()
        collision = self.home / ".agents/skills/One"
        write_bytes(collision / "foreign.txt", b"case collision\n")
        with self.assertRaisesRegex(publisher.PublicationError, "case-spelling collision"):
            self.publish(sources)
        self.assertEqual((collision / "foreign.txt").read_bytes(), b"case collision\n")

    def test_selected_symlinks_and_output_parent_reparse_points_are_refused(self):
        root = self.source_root()
        write_skill(root, "skills/one", "one")
        outside_file = self.root / "outside.txt"
        outside_file.write_bytes(b"outside\n")
        selected_link = root / "skills/one/linked.txt"
        os.symlink(str(outside_file), str(selected_link))
        with self.assertRaisesRegex(publisher.PublicationError, "symlink or reparse point"):
            self.publish({"example": self.declaration(root)}, dry_run=True)
        self.assertEqual(outside_file.read_bytes(), b"outside\n")

        selected_link.unlink()
        outside_parent = self.root / "outside-agents"
        outside_parent.mkdir()
        os.symlink(
            str(outside_parent),
            str(self.home / ".agents"),
            target_is_directory=True,
        )
        with self.assertRaisesRegex(publisher.PublicationError, "symlink or reparse point"):
            self.publish({"example": self.declaration(root)})
        self.assertEqual(list(outside_parent.iterdir()), [])

    @unittest.skipUnless(os.name == "nt", "directory junctions are a Windows-only prerequisite")
    def test_selected_windows_junction_is_refused(self):
        root = self.source_root()
        outside = self.root / "junction-target"
        write_skill(outside, "one", "one")
        junction = root / "one"
        result = subprocess.run(
            ["cmd", "/d", "/c", "mklink", "/J", str(junction), str(outside)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            self.skipTest(f"Windows junction creation unavailable: {result.stderr or result.stdout}")
        with self.assertRaisesRegex(publisher.PublicationError, "symlink or reparse point"):
            self.publish({"example": self.declaration(root)}, dry_run=True)


@unittest.skipUnless(SYMLINKS_AVAILABLE, SYMLINK_REASON)
class TransactionContractTests(PublisherCase):
    def test_concurrent_writer_is_rejected(self):
        _, sources = self.simple_source()
        with held_writer_lock(self.home):
            with self.assertRaisesRegex(publisher.PublicationError, "another skill publisher"):
                self.publish(sources)
        self.assertFalse(
            (self.home / ".config/claude-code-chezmoi/.skill-publisher.json").exists()
        )

    def test_foreign_lock_marker_is_preserved(self):
        _, sources = self.simple_source()
        lock = self.home / ".config/claude-code-chezmoi/.skill-publisher.lock"
        write_bytes(lock, b"foreign lock marker\n")
        with self.assertRaisesRegex(publisher.PublicationError, "foreign or incomplete marker"):
            self.publish(sources)
        self.assertEqual(lock.read_bytes(), b"foreign lock marker\n")

    @unittest.skipUnless(os.name == "nt", "Windows lock opener regression")
    def test_dangling_windows_lock_symlink_is_refused_without_creating_its_target(self):
        _, sources = self.simple_source()
        lock = self.home / ".config/claude-code-chezmoi/.skill-publisher.lock"
        lock.parent.mkdir(parents=True)
        target = self.root / "foreign-lock-target"
        self.assertFalse(os.path.lexists(target))
        os.symlink(str(target), str(lock), target_is_directory=False)
        leaf = os.lstat(lock)
        before = managed_snapshot(self.home)
        lock_before = snapshot_entry(lock)

        with self.assertRaisesRegex(publisher.PublicationError, "symlink or reparse point"):
            self.publish(sources)
        self.assertFalse(os.path.lexists(target), "refusal must not create the foreign target")
        self.assertEqual(snapshot_entry(lock), lock_before)
        self.assertTrue(os.path.samestat(leaf, os.lstat(lock)))
        self.assertEqual(os.lstat(lock).st_mtime_ns, leaf.st_mtime_ns)
        self.assertEqual(managed_snapshot(self.home), before)
        self.assertFalse(os.path.lexists(lock.parent / ".skill-publisher-work"))

    @unittest.skipUnless(os.name == "nt", "Windows native lock-create race regression")
    def test_dangling_windows_lock_symlink_arriving_before_native_create_is_preserved(self):
        _, sources = self.simple_source()
        lock = self.home / ".config/claude-code-chezmoi/.skill-publisher.lock"
        target = self.root / "foreign-lock-target"
        before = managed_snapshot(self.home)
        original = publisher._open_lock_descriptor
        leaf = None
        lock_before = None

        def foreign_arrival(path, *, create):
            nonlocal leaf, lock_before
            if create:
                self.assertEqual(Path(path), lock)
                self.assertFalse(os.path.lexists(lock))
                self.assertFalse(os.path.lexists(target))
                os.symlink(str(target), str(lock), target_is_directory=False)
                leaf = os.lstat(lock)
                lock_before = snapshot_entry(lock)
            return original(path, create=create)

        with mock.patch.object(publisher, "_open_lock_descriptor", side_effect=foreign_arrival):
            with self.assertRaisesRegex(publisher.PublicationError, "symlink or reparse point"):
                self.publish(sources)
        self.assertIsNotNone(leaf, "the foreign link must arrive before native creation")
        self.assertFalse(os.path.lexists(target), "native creation must not follow the foreign link")
        self.assertEqual(snapshot_entry(lock), lock_before)
        self.assertTrue(os.path.samestat(leaf, os.lstat(lock)))
        self.assertEqual(os.lstat(lock).st_mtime_ns, leaf.st_mtime_ns)
        self.assertEqual(managed_snapshot(self.home), before)
        self.assertFalse(os.path.lexists(lock.parent / ".skill-publisher-work"))

    def test_foreign_work_after_preflight_or_native_mkdir_collision_is_preserved(self):
        for arrival in ("after-preflight", "native-mkdir"):
            with self.subTest(arrival=arrival):
                self.home = self.root / arrival
                self.home.mkdir()
                _, sources = self.simple_source()
                work = self.home / ".config/claude-code-chezmoi/.skill-publisher-work"
                before = managed_snapshot(self.home)
                native_mkdir = os.mkdir
                original_preflight = publisher._preflight
                leaf = None

                def seed_foreign_work():
                    nonlocal leaf
                    native_mkdir(work)
                    (work / "foreign.txt").write_bytes(b"foreign work evidence\n")
                    leaf = os.lstat(work)

                def after_preflight(*args, **kwargs):
                    plan = original_preflight(*args, **kwargs)
                    seed_foreign_work()
                    return plan

                def colliding_mkdir(path, *args, **kwargs):
                    if Path(path) == work:
                        seed_foreign_work()
                    return native_mkdir(path, *args, **kwargs)

                injection = (
                    mock.patch.object(publisher, "_preflight", side_effect=after_preflight)
                    if arrival == "after-preflight" else
                    mock.patch.object(os, "mkdir", side_effect=colliding_mkdir)
                )
                with injection:
                    with self.assertRaisesRegex(publisher.PublicationError, "unowned work was preserved"):
                        self.publish(sources)
                self.assertIsNotNone(leaf)
                self.assertTrue(os.path.samestat(leaf, os.lstat(work)))
                self.assertEqual((work / "foreign.txt").read_bytes(), b"foreign work evidence\n")
                self.assertEqual(managed_snapshot(self.home), before)
                with self.assertRaisesRegex(publisher.PublicationError, "inspect it manually"):
                    self.publish(sources)
                self.assertEqual((work / "foreign.txt").read_bytes(), b"foreign work evidence\n")

    def test_interrupted_work_mkdir_preserves_unknown_acquisition_but_cleans_proven_acquisition(self):
        for completion in ("unknown", "proven"):
            with self.subTest(completion=completion):
                self.home = self.root / completion
                self.home.mkdir()
                _, sources = self.simple_source()
                work = self.home / ".config/claude-code-chezmoi/.skill-publisher-work"
                before = managed_snapshot(self.home)
                native_mkdir = os.mkdir
                original_acquire = publisher._acquire_directory
                interrupted = False

                def interrupt_work(path):
                    nonlocal interrupted
                    if Path(path) == work:
                        interrupted = True
                        (work / "evidence.txt").write_bytes(b"interrupted acquisition\n")
                        raise KeyboardInterrupt("after work mkdir")

                def after_native_mkdir(path, *args, **kwargs):
                    result = native_mkdir(path, *args, **kwargs)
                    interrupt_work(path)
                    return result

                def after_acquisition(acquisition):
                    result = original_acquire(acquisition)
                    interrupt_work(acquisition.path)
                    return result

                injection = (
                    mock.patch.object(os, "mkdir", side_effect=after_native_mkdir)
                    if completion == "unknown" else
                    mock.patch.object(publisher, "_acquire_directory", side_effect=after_acquisition)
                )
                expected = "recovery was incomplete" if completion == "unknown" else "previous outputs were restored"
                with injection:
                    with self.assertRaisesRegex(publisher.PublicationError, expected):
                        self.publish(sources)
                self.assertTrue(interrupted)
                self.assertEqual(managed_snapshot(self.home), before)
                if completion == "unknown":
                    self.assertEqual((work / "evidence.txt").read_bytes(), b"interrupted acquisition\n")
                    with self.assertRaisesRegex(publisher.PublicationError, "inspect it manually"):
                        self.publish(sources)
                else:
                    self.assertFalse(os.path.lexists(work))

    def test_interrupt_after_native_backup_or_view_install_restores_previous_outputs(self):
        for boundary, existing in (
            ("backup-view", True), ("backup-link", True),
            ("install-view", False), ("install-view", True),
        ):
            with self.subTest(boundary=boundary, existing=existing):
                self.home = self.root / f"{boundary}-{existing}"
                self.home.mkdir()
                root, sources = self.simple_source()
                if existing:
                    self.publish(sources)
                before = managed_snapshot(self.home)
                if existing:
                    shutil.rmtree(root / "skills/one")
                    write_skill(root, "moved/one", "one", body="updated\n")
                work = self.home / ".config/claude-code-chezmoi/.skill-publisher-work"
                view = work.parent / "generated-skills/example"
                destination = {
                    "backup-view": work / "old-views/example",
                    "backup-link": work / "old-links/one",
                    "install-view": view,
                }[boundary]
                native_rename = os.rename
                interrupted = False

                def after_native_rename(source, target, *args, **kwargs):
                    nonlocal interrupted
                    result = native_rename(source, target, *args, **kwargs)
                    if Path(target) == destination and not interrupted:
                        interrupted = True
                        self.assertTrue(os.path.lexists(target))
                        raise KeyboardInterrupt(f"after native {boundary}")
                    return result

                with mock.patch.object(os, "rename", side_effect=after_native_rename):
                    with self.assertRaisesRegex(publisher.PublicationError, "previous outputs were restored"):
                        self.publish(sources)
                self.assertTrue(interrupted)
                self.assertEqual(managed_snapshot(self.home), before)
                self.assertFalse(os.path.lexists(work))

    def test_foreign_same_target_final_link_survives_native_install_refusal(self):
        _, sources = self.simple_source()
        link = self.home / ".agents/skills/one"
        link.parent.mkdir(parents=True)
        before = managed_snapshot(self.home)
        original_install = publisher._install_directory_link
        leaf = None
        stored_target = None
        native_refused = False

        def colliding_install(transfer):
            nonlocal leaf, stored_target, native_refused
            if transfer.destination != link:
                return original_install(transfer)
            stored_target = os.readlink(transfer.source)
            os.symlink(stored_target, str(link), target_is_directory=True)
            leaf = os.lstat(link)
            try:
                return original_install(transfer)
            except FileExistsError:
                native_refused = True
                raise

        with mock.patch.object(publisher, "_install_directory_link", side_effect=colliding_install):
            with self.assertRaisesRegex(publisher.PublicationError, "previous outputs were restored"):
                self.publish(sources)
        self.assertTrue(native_refused, "the real native install must refuse the foreign link")
        self.assertEqual(snapshot_entry(link), ("link", stored_target))
        self.assertTrue(os.path.samestat(leaf, os.lstat(link)))
        self.assertEqual(os.lstat(link).st_mtime_ns, leaf.st_mtime_ns)
        after = managed_snapshot(self.home)
        for name in ("generated", "marketplace", "receipt"):
            self.assertEqual(after[name], before[name])
        self.assertFalse(os.path.lexists(self.home / ".config/claude-code-chezmoi/.skill-publisher-work"))

    def test_same_byte_foreign_commit_files_survive_precheck_and_native_link_refusals(self):
        for writer_name, snapshot_key in (("_write_marketplace", "marketplace"), ("_write_receipt", "receipt")):
            for arrival in ("precheck", "native-link"):
                with self.subTest(writer=writer_name, arrival=arrival):
                    self.home = self.root / f"{writer_name}-{arrival}"
                    self.home.mkdir()
                    _, sources = self.simple_source()
                    market_root = self.home / ".config/claude-code-chezmoi"
                    (market_root / ".claude-plugin").mkdir(parents=True)
                    before = managed_snapshot(self.home)
                    original_writer = getattr(publisher, writer_name)
                    native_link = os.link
                    path = leaf = payload = None
                    native_refused = False

                    def seed_foreign_file(write):
                        nonlocal path, leaf, payload
                        path, payload = write.path, write.new
                        with path.open("xb") as output:
                            output.write(payload)
                        leaf = os.lstat(path)

                    def colliding_write(write):
                        self.assertIsNone(write.old)
                        if arrival == "precheck":
                            seed_foreign_file(write)
                            return original_writer(write)

                        def colliding_link(source, destination, *args, **kwargs):
                            nonlocal native_refused
                            if Path(destination) == write.path:
                                seed_foreign_file(write)
                            try:
                                return native_link(source, destination, *args, **kwargs)
                            except FileExistsError:
                                native_refused = True
                                raise

                        with mock.patch.object(os, "link", side_effect=colliding_link):
                            return original_writer(write)

                    with mock.patch.object(publisher, writer_name, side_effect=colliding_write):
                        with self.assertRaisesRegex(publisher.PublicationError, "destination appeared before atomic write"):
                            self.publish(sources)
                    self.assertIsNotNone(leaf)
                    if arrival == "native-link":
                        self.assertTrue(native_refused)
                    self.assertEqual(path.read_bytes(), payload)
                    self.assertTrue(os.path.samestat(leaf, os.lstat(path)))
                    self.assertEqual(os.lstat(path).st_mtime_ns, leaf.st_mtime_ns)
                    after = managed_snapshot(self.home)
                    for name in before.keys() - {snapshot_key}:
                        self.assertEqual(after[name], before[name])
                    self.assertEqual(list(path.parent.glob(f".{path.name}.*")), [])
                    self.assertFalse(os.path.lexists(market_root / ".skill-publisher-work"))

    def test_traced_commit_temp_acquisition_interruptions_close_descriptors_and_restore_outputs(self):
        atomic_write = publisher._atomic_replace_file
        source, first_line = inspect.getsourcelines(atomic_write)
        function = ast.parse("".join(source)).body[0]
        preparation = next(node for node in function.body if isinstance(node, ast.Try))
        assignments = {
            ast.unparse(node.targets[0]): node
            for node in preparation.body if isinstance(node, ast.Assign)
        }
        self.assertEqual(ast.unparse(assignments["output"].value.func), "os.fdopen")
        boundaries = {
            "before-fdopen": first_line + assignments["output"].lineno - 1,
            "before-prepared": first_line + assignments["write.prepared"].lineno - 1,
        }
        for writer, relative in (
            ("marketplace", ".claude-plugin/marketplace.json"),
            ("receipt", ".skill-publisher.json"),
        ):
            for boundary, line in boundaries.items():
                with self.subTest(writer=writer, boundary=boundary):
                    self.home = self.root / f"{writer}-{boundary}"
                    self.home.mkdir()
                    root, sources = self.simple_source()
                    self.publish(sources)
                    before = managed_snapshot(self.home)
                    write_skill(root, "skills/one", "one", body="updated\n")
                    _, second = self.simple_source("second", "two")
                    sources.update(second)
                    market_root = self.home / ".config/claude-code-chezmoi"
                    destination = market_root / relative
                    observed = {}

                    def interrupt(frame, event, arg):
                        if (
                            observed or event != "line" or frame.f_code is not atomic_write.__code__
                            or frame.f_lineno != line or frame.f_locals["write"].path != destination
                        ):
                            return interrupt
                        sys.settrace(None)  # One interruption only; never interrupt recovery.
                        descriptor = frame.f_locals["descriptor"]
                        temporary = Path(frame.f_locals["temporary_name"])
                        witness = os.fstat(descriptor)
                        observed.update(
                            descriptor=descriptor, temporary=temporary, witness=witness,
                            output=frame.f_locals["output"], prepared=frame.f_locals["write"].prepared,
                            same_temporary=os.path.samestat(witness, os.lstat(temporary)),
                        )
                        raise KeyboardInterrupt(f"traced commit acquisition {boundary}")

                    previous_trace = sys.gettrace()
                    try:
                        try:
                            sys.settrace(interrupt)
                            with self.assertRaisesRegex(publisher.PublicationError, "previous outputs were restored") as raised:
                                self.publish(sources)
                        finally:
                            sys.settrace(previous_trace)
                        self.assertTrue(observed, "the acquisition boundary must be reached")
                        self.assertIsInstance(raised.exception.__cause__, KeyboardInterrupt)
                        self.assertIsNone(observed["prepared"])
                        self.assertTrue(observed["same_temporary"])
                        self.assertEqual(observed["temporary"].parent, destination.parent)
                        if boundary == "before-fdopen":
                            self.assertIsNone(observed["output"])
                        else:
                            self.assertIsNotNone(observed["output"])
                            self.assertTrue(observed["output"].closed)
                        with self.assertRaises(OSError):
                            os.fstat(observed["descriptor"])
                        self.assertFalse(os.path.lexists(observed["temporary"]))
                        self.assertEqual(list(destination.parent.glob(f".{destination.name}.*")), [])
                        self.assertEqual(managed_snapshot(self.home), before)
                        self.assertFalse(os.path.lexists(market_root / ".skill-publisher-work"))
                    finally:
                        # Close only a demonstrably leaked fixture descriptor, after assertions.
                        if observed:
                            try:
                                leftover = os.fstat(observed["descriptor"])
                            except OSError:
                                pass
                            else:
                                if os.path.samestat(leftover, observed["witness"]):
                                    if observed["output"] is not None and not observed["output"].closed:
                                        observed["output"].close()
                                    else:
                                        os.close(observed["descriptor"])

    def test_unknown_commit_temp_acquisition_preserves_temporary_and_work_blocker(self):
        for writer, relative in (
            ("marketplace", ".claude-plugin/marketplace.json"),
            ("receipt", ".skill-publisher.json"),
        ):
            with self.subTest(writer=writer):
                self.home = self.root / f"unknown-{writer}"
                self.home.mkdir()
                root, sources = self.simple_source()
                self.publish(sources)
                before = managed_snapshot(self.home)
                write_skill(root, "skills/one", "one", body="updated\n")
                _, second = self.simple_source("second", "two")
                sources.update(second)
                market_root = self.home / ".config/claude-code-chezmoi"
                destination = market_root / relative
                work = market_root / ".skill-publisher-work"
                native_mkstemp = tempfile.mkstemp
                acquired = {}
                evidence = b"unreported temporary acquisition\n"

                def lose_acquisition_result(*args, **kwargs):
                    descriptor, name = native_mkstemp(*args, **kwargs)
                    if (
                        not acquired and Path(kwargs["dir"]) == destination.parent
                        and kwargs["prefix"] == f".{destination.name}."
                    ):
                        try:
                            os.write(descriptor, evidence)
                            acquired.update(descriptor=descriptor, path=Path(name), witness=os.fstat(descriptor))
                        finally:
                            os.close(descriptor)
                        raise KeyboardInterrupt("mkstemp did not return its acquisition identity")
                    return descriptor, name

                with mock.patch.object(tempfile, "mkstemp", side_effect=lose_acquisition_result):
                    with self.assertRaisesRegex(publisher.PublicationError, "recovery was incomplete") as raised:
                        self.publish(sources)
                self.assertTrue(acquired)
                self.assertIn("commit temporary acquisition is uncertain", str(raised.exception))
                with self.assertRaises(OSError):
                    os.fstat(acquired["descriptor"])
                self.assertEqual(acquired["path"].read_bytes(), evidence)
                self.assertTrue(os.path.samestat(acquired["witness"], os.lstat(acquired["path"])))
                self.assertEqual(list(destination.parent.glob(f".{destination.name}.*")), [acquired["path"]])
                self.assertEqual(managed_snapshot(self.home), before)
                self.assertTrue(work.is_dir())
                work_leaf = os.lstat(work)
                with self.assertRaisesRegex(publisher.PublicationError, "inspect it manually"):
                    self.publish(sources)
                self.assertTrue(os.path.samestat(work_leaf, os.lstat(work)))
                self.assertEqual(acquired["path"].read_bytes(), evidence)
                self.assertTrue(os.path.samestat(acquired["witness"], os.lstat(acquired["path"])))

    def test_completed_commit_writes_restore_previous_outputs_after_errors_and_interruptions(self):
        for writer_name in ("_write_marketplace", "_write_receipt"):
            for existing in (False, True):
                for failure in (OSError, KeyboardInterrupt):
                    with self.subTest(writer=writer_name, existing=existing, failure=failure.__name__):
                        self.home = self.root / f"{writer_name}-{existing}-{failure.__name__}"
                        self.home.mkdir()
                        root, sources = self.simple_source()
                        if existing:
                            self.publish(sources)
                        before = managed_snapshot(self.home)
                        if existing:
                            write_skill(root, "skills/one", "one", body="updated\n")
                            _, second = self.simple_source("second", "two")
                            sources.update(second)  # Also changes marketplace bytes.
                        original_writer = getattr(publisher, writer_name)
                        written = []

                        def after_completed_write(write):
                            original_writer(write)
                            self.assertEqual(write.path.read_bytes(), write.new)
                            written.append(write.path)
                            raise failure(f"after completed {writer_name}")

                        with mock.patch.object(publisher, writer_name, side_effect=after_completed_write):
                            with self.assertRaisesRegex(publisher.PublicationError, "previous outputs were restored"):
                                self.publish(sources)
                        self.assertEqual(len(written), 1)
                        self.assertEqual(managed_snapshot(self.home), before)
                        self.assertEqual(list(written[0].parent.glob(f".{written[0].name}.*")), [])
                        self.assertFalse(os.path.lexists(self.home / ".config/claude-code-chezmoi/.skill-publisher-work"))

    def test_completed_final_link_install_restores_initial_and_previous_publications_on_interrupt(self):
        for existing in (False, True):
            with self.subTest(existing=existing):
                self.home = self.root / f"link-install-{existing}"
                self.home.mkdir()
                root, sources = self.simple_source()
                if existing:
                    self.publish(sources)
                before = managed_snapshot(self.home)
                if existing:
                    shutil.rmtree(root / "skills/one")
                    write_skill(root, "moved/one", "one", body="updated\n")
                link = self.home / ".agents/skills/one"
                original_install = publisher._install_directory_link
                interrupted = False

                def after_install(transfer):
                    nonlocal interrupted
                    original_install(transfer)
                    if transfer.destination == link:
                        interrupted = True
                        self.assertTrue(link.is_symlink())
                        raise KeyboardInterrupt("after final link installation")

                with mock.patch.object(publisher, "_install_directory_link", side_effect=after_install):
                    with self.assertRaisesRegex(publisher.PublicationError, "previous outputs were restored"):
                        self.publish(sources)
                self.assertTrue(interrupted)
                self.assertEqual(managed_snapshot(self.home), before)
                self.assertFalse(os.path.lexists(self.home / ".config/claude-code-chezmoi/.skill-publisher-work"))

    def test_changed_installed_view_identity_preserves_foreign_data_and_owned_backup(self):
        root, sources = self.simple_source()
        self.publish(sources)
        before = managed_snapshot(self.home)
        work = self.home / ".config/claude-code-chezmoi/.skill-publisher-work"
        view = work.parent / "generated-skills/example"
        old_view = snapshot_entry(view)
        write_skill(root, "skills/one", "one", body="updated\n")
        displaced = self.root / "displaced-installed-view"
        native_rename = os.rename
        foreign_leaf = None

        def replace_completed_install(source, destination, *args, **kwargs):
            nonlocal foreign_leaf
            result = native_rename(source, destination, *args, **kwargs)
            if Path(source) == work / "new/example" and Path(destination) == view:
                native_rename(view, displaced)
                write_bytes(view / "foreign.txt", b"foreign replacement\n")
                foreign_leaf = os.lstat(view)
                raise KeyboardInterrupt("installed view identity replaced")
            return result

        with mock.patch.object(os, "rename", side_effect=replace_completed_install):
            with self.assertRaisesRegex(publisher.PublicationError, "recovery was incomplete") as raised:
                self.publish(sources)
        self.assertIn("uncertain completion", str(raised.exception))
        self.assertIsNotNone(foreign_leaf)
        self.assertTrue(os.path.samestat(foreign_leaf, os.lstat(view)))
        self.assertEqual((view / "foreign.txt").read_bytes(), b"foreign replacement\n")
        self.assertEqual(snapshot_entry(work / "old-views/example"), old_view)
        self.assertEqual((displaced / "skills/one/SKILL.md").read_bytes(), skill_bytes("one", body="updated\n"))
        after = managed_snapshot(self.home)
        for name in ("shared", "marketplace", "receipt"):
            self.assertEqual(after[name], before[name])
        with self.assertRaisesRegex(publisher.PublicationError, "inspect it manually"):
            self.publish(sources)
        self.assertEqual(snapshot_entry(work / "old-views/example"), old_view)
        self.assertEqual((view / "foreign.txt").read_bytes(), b"foreign replacement\n")

    def test_injected_link_failure_restores_previous_outputs(self):
        root, sources = self.simple_source()
        self.publish(sources)
        before = managed_snapshot(self.home)
        write_bytes(root / "skills/one/SKILL.md", skill_bytes("one", body="updated\n"))
        write_skill(root, "skills/two", "two")
        original = publisher._create_directory_link

        def fail_new_skill(link, target):
            if Path(link).name == "two":
                raise OSError("injected link failure")
            return original(link, target)

        with mock.patch.object(publisher, "_create_directory_link", side_effect=fail_new_skill):
            with self.assertRaisesRegex(publisher.PublicationError, "previous outputs were restored"):
                self.publish(sources)
        self.assertEqual(managed_snapshot(self.home), before)
        self.assertFalse(
            (self.home / ".config/claude-code-chezmoi/.skill-publisher-work").exists()
        )

    def test_injected_receipt_write_failure_restores_views_links_and_marketplace(self):
        first_root, first_sources = self.simple_source("first", "one")
        self.publish(first_sources)
        before = managed_snapshot(self.home)
        second_root = self.source_root("second")
        write_skill(second_root, "skills/two", "two")
        updated_sources = {
            "first": self.declaration(first_root),
            "second": self.declaration(second_root),
        }
        with mock.patch.object(
            publisher, "_write_receipt", side_effect=OSError("injected receipt failure")
        ):
            with self.assertRaisesRegex(publisher.PublicationError, "previous outputs were restored"):
                self.publish(updated_sources)
        self.assertEqual(managed_snapshot(self.home), before)

    def test_failed_recovery_retains_backups_and_blocks_next_run(self):
        root, sources = self.simple_source()
        self.publish(sources)
        write_bytes(root / "skills/one/SKILL.md", skill_bytes("one", body="updated\n"))
        write_skill(root, "skills/two", "two")
        original = publisher._create_directory_link

        def fail_new_skill(link, target):
            if Path(link).name == "two":
                raise OSError("injected link failure")
            return original(link, target)

        with mock.patch.object(publisher, "_create_directory_link", side_effect=fail_new_skill), mock.patch.object(
            publisher, "_recover", return_value=["injected recovery failure"]
        ):
            with self.assertRaisesRegex(publisher.PublicationError, "recovery was incomplete"):
                self.publish(sources)

        work = self.home / ".config/claude-code-chezmoi/.skill-publisher-work"
        self.assertTrue((work / "old-views/example").is_dir())
        with self.assertRaisesRegex(publisher.PublicationError, "inspect it manually"):
            self.publish(sources)
        self.assertTrue((work / "old-views/example").is_dir())

    def test_post_commit_cleanup_failure_keeps_committed_outputs_and_does_not_roll_back(self):
        root, sources = self.simple_source()
        self.publish(sources)
        old_marker = (
            self.home
            / ".config/claude-code-chezmoi/generated-skills/example/skills/one/SKILL.md"
        ).read_bytes()
        write_bytes(root / "skills/one/SKILL.md", skill_bytes("one", body="committed update\n"))

        with mock.patch.object(
            publisher, "_cleanup_work", side_effect=OSError("injected cleanup failure")
        ):
            with self.assertRaisesRegex(publisher.PublicationError, "publication committed") as raised:
                self.publish(sources)
        self.assertTrue(raised.exception.committed)
        self.assertIsNotNone(raised.exception.report)
        new_marker = (
            self.home
            / ".config/claude-code-chezmoi/generated-skills/example/skills/one/SKILL.md"
        ).read_bytes()
        self.assertNotEqual(new_marker, old_marker)
        receipt = json.loads(
            (
                self.home / ".config/claude-code-chezmoi/.skill-publisher.json"
            ).read_text("utf-8")
        )
        files = scan_regular_tree(
            self.home / ".config/claude-code-chezmoi/generated-skills/example"
        )
        self.assertEqual(receipt["sources"]["example"]["digest"], inventory_digest(files))
        work = self.home / ".config/claude-code-chezmoi/.skill-publisher-work"
        self.assertTrue(work.exists())
        with self.assertRaisesRegex(publisher.PublicationError, "inspect it manually"):
            self.publish(sources)


@unittest.skipUnless(SYMLINKS_AVAILABLE, SYMLINK_REASON)
class LegacyAndOtherOwnersContractTests(PublisherCase):
    def test_legacy_show_me_link_is_refused_until_fixture_explicitly_removes_it(self):
        root = self.source_root("humanlayer")
        write_skill(root, "plugins/show-me/skills/show-me", "show-me")
        sources = {"humanlayer": self.declaration(root)}
        legacy_target = self.home / ".local/share/llm-agents/skills/show-me"
        write_skill(legacy_target, ".", "show-me")
        legacy_link = self.home / ".agents/skills/show-me"
        legacy_link.parent.mkdir(parents=True)
        os.symlink(str(legacy_target), str(legacy_link), target_is_directory=True)

        with self.assertRaisesRegex(publisher.PublicationError, "unowned shared skill"):
            self.publish(sources)
        self.assertEqual(
            normalized_link_target(legacy_link), os.path.normcase(str(legacy_target))
        )
        self.assertTrue(legacy_target.is_dir())

        # This is fixture-only explicit legacy handoff, not publisher adoption.
        legacy_link.unlink()
        self.publish(sources)
        new_target = (
            self.home
            / ".config/claude-code-chezmoi/generated-skills/humanlayer/plugins/show-me/skills/show-me"
        )
        self.assertEqual(normalized_link_target(legacy_link), os.path.normcase(str(new_target)))
        self.assertTrue(legacy_target.is_dir(), "publisher must not delete legacy backing data")

    def test_repo_authored_skill_copies_and_herdr_entry_survive_publish_update_and_removal(self):
        source_skills = REPO_ROOT / "dot_agents" / "skills"
        actual_names = {path.name for path in source_skills.iterdir() if path.is_dir()}
        self.assertEqual(actual_names, REPO_SKILL_NAMES)
        shared = self.home / ".agents/skills"
        shared.mkdir(parents=True)
        owner_snapshots = {}
        for name in sorted(REPO_SKILL_NAMES):
            destination = shared / name
            shutil.copytree(source_skills / name, destination)
            owner_snapshots[name] = snapshot_entry(destination)

        herdr_target = self.home / ".local/share/herdr/agents/skills/herdr"
        write_skill(herdr_target, ".", "herdr")
        herdr_link = shared / "herdr"
        os.symlink(str(herdr_target), str(herdr_link), target_is_directory=True)
        herdr_snapshot = snapshot_entry(herdr_link)
        herdr_target_snapshot = snapshot_entry(herdr_target)

        root, sources = self.simple_source()
        self.publish(sources)
        write_bytes(root / "skills/one/SKILL.md", skill_bytes("one", body="update\n"))
        self.publish(sources)
        self.publish({})

        for name, expected in owner_snapshots.items():
            with self.subTest(repo_skill=name):
                self.assertEqual(snapshot_entry(shared / name), expected)
        self.assertEqual(snapshot_entry(herdr_link), herdr_snapshot)
        self.assertEqual(snapshot_entry(herdr_target), herdr_target_snapshot)


class CliReportingContractTests(PublisherCase):
    def setUp(self):
        super().setUp()
        self.simple_source()
        self.base.write_bytes(canonical_json_bytes({**BASE_MARKETPLACE, "name": "custom"}))
        self.config = self.root / "publisher-config.toml"
        self.config.write_text(
            '[agent_skills.sources.example]\ndirectory = "inputs/example"\ninclude = ["skills"]\n',
            encoding="utf-8",
        )

    def run_cli(self, *arguments):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr), mock.patch.object(
            subprocess, "run", side_effect=AssertionError("suggestions must not execute native commands")
        ):
            status = publisher.main([
                "--home", str(self.home), "--config", str(self.config),
                "--base", str(self.base), *arguments,
            ])
        self.assertEqual(status, 0, stderr.getvalue())
        self.assertEqual(stderr.getvalue(), "")
        return stdout.getvalue()

    def test_main_custom_marketplace_preview_suggests_its_identity_without_writes(self):
        before = snapshot_entry(self.home)
        output = self.run_cli("--dry-run")
        self.assertIn("Publication preview:", output)
        self.assertIn("claude plugin marketplace update custom", output)
        self.assertIn("claude plugin update example@custom --scope user", output)
        self.assertIn("claude plugin install example@custom --scope user", output)
        self.assertNotIn("@chezmoi", output)
        self.assertNotIn("marketplace update chezmoi", output)
        self.assertEqual(snapshot_entry(self.home), before)

    def test_main_custom_marketplace_publish_and_removal_suggestions_use_its_identity(self):
        self.require_symlinks()
        output = self.run_cli()
        self.assertIn("Publication actions:", output)
        self.assertIn("claude plugin marketplace update custom", output)
        self.assertIn("claude plugin update example@custom --scope user", output)
        self.assertIn("claude plugin install example@custom --scope user", output)
        self.assertNotIn("@chezmoi", output)
        market_root = self.home / ".config/claude-code-chezmoi"
        marketplace = market_root / ".claude-plugin/marketplace.json"
        self.assertEqual(json.loads(marketplace.read_bytes())["name"], "custom")

        self.config.write_text("[agent_skills.sources]\n", encoding="utf-8")
        before = managed_snapshot(self.home)
        preview = self.run_cli("--dry-run")
        self.assertEqual(managed_snapshot(self.home), before)
        removed = self.run_cli()
        for result in (preview, removed):
            self.assertIn("claude plugin marketplace update custom", result)
            self.assertIn("claude plugin uninstall example@custom --scope user", result)
            self.assertNotIn("claude plugin install example@", result)
            self.assertNotIn("@chezmoi", result)
            self.assertNotIn("marketplace update chezmoi", result)
        self.assertFalse(os.path.lexists(market_root / "generated-skills/example"))
        self.assertFalse(os.path.lexists(self.home / ".agents/skills/one"))
        self.assertEqual(json.loads(marketplace.read_bytes())["name"], "custom")


class RepositoryDeclarationTests(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls):
        cls.data = tomllib.loads((REPO_ROOT / ".chezmoidata.toml").read_text("utf-8"))

    def test_exact_two_source_selection_and_pins_are_declared(self):
        sources = self.data["agent_skills"]["sources"]
        self.assertEqual(set(sources), {"mattpocock-skills", "humanlayer"})
        self.assertEqual(
            sources["mattpocock-skills"],
            {
                "directory": ".local/share/llm-agents/plugins/mattpocock-skills",
                "include": [".claude-plugin/plugin.json", "LICENSE", *MATT_SKILL_ROOTS],
            },
        )
        self.assertEqual(len(MATT_SKILL_ROOTS), 25)
        self.assertEqual(
            sources["humanlayer"],
            {
                "directory": ".local/share/llm-agents/sources/humanlayer",
                "include": ["plugins/show-me/skills/show-me", "LICENSE"],
            },
        )
        pins = self.data["external_resources"]["pins"]
        self.assertEqual(
            pins["humanlayer_skills"],
            {
                "url": "https://github.com/humanlayer/skills/archive/3c2629142c5d437428269b1b722b08c0b87f574d.tar.gz",
                "sha256": "9366a25c3e7072fe30ed1ebedf71b0df2f1a229592f03ee29f0a82de38227bcf",
            },
        )
        self.assertNotIn("humanlayer_show_me", pins)
        self.assertFalse(any("superpowers" in name.casefold() for name in pins))
        self.assertEqual(
            pins["mattpocock_skills"]["url"],
            "https://github.com/mattpocock/skills/archive/refs/tags/v1.2.3.tar.gz",
        )
        self.assertEqual(
            pins["mattpocock_skills"]["sha256"],
            "238fac54d0f53d3e2d0501c1b38c9c0e4e9bc26f6b057b53a7328ea15d43b66f",
        )

    def test_obsolete_sources_are_absent_and_new_humanlayer_archive_is_exact(self):
        obsolete = [
            "dot_local/share/llm-agents/skills/.chezmoiexternal.toml.tmpl",
            "dot_config/claude-code-chezmoi/dot_claude-plugin/marketplace.json",
            "dot_config/claude-code-chezmoi/plugins/symlink_mattpocock-skills.tmpl",
            "dot_config/claude-code-chezmoi/plugins/symlink_superpowers.tmpl",
        ]
        for relative in obsolete:
            with self.subTest(path=relative):
                self.assertFalse((REPO_ROOT / relative).exists())

        humanlayer_manifest = tomllib.loads(
            (
                REPO_ROOT
                / "dot_local/share/llm-agents/sources/.chezmoiexternal.toml.tmpl"
            )
            .read_text("utf-8")
            .replace(
                "{{ .external_resources.pins.humanlayer_skills.url | toJson }}",
                json.dumps(self.data["external_resources"]["pins"]["humanlayer_skills"]["url"]),
            )
            .replace(
                "{{ .external_resources.pins.humanlayer_skills.sha256 | toJson }}",
                json.dumps(
                    self.data["external_resources"]["pins"]["humanlayer_skills"]["sha256"]
                ),
            )
        )
        self.assertEqual(
            humanlayer_manifest,
            {
                "humanlayer": {
                    "type": "archive",
                    "url": self.data["external_resources"]["pins"]["humanlayer_skills"]["url"],
                    "stripComponents": 1,
                    "exact": True,
                    "checksum": {
                        "sha256": self.data["external_resources"]["pins"]["humanlayer_skills"][
                            "sha256"
                        ]
                    },
                }
            },
        )
        plugin_manifest = (
            REPO_ROOT / "dot_local/share/llm-agents/plugins/.chezmoiexternal.toml.tmpl"
        ).read_text("utf-8")
        self.assertNotIn("superpowers", plugin_manifest.casefold())
        self.assertIn('[' + '"mattpocock-skills"' + ']', plugin_manifest)

    def test_ignore_base_marketplace_and_repo_skill_declarations_are_exact(self):
        ignored = {
            line.strip()
            for line in (REPO_ROOT / ".chezmoiignore").read_text("utf-8").splitlines()
            if line.strip()
        }
        required = {
            "manage_skills.py",
            ".config/claude-code-chezmoi/generated-skills/",
            ".config/claude-code-chezmoi/.claude-plugin/marketplace.json",
            ".config/claude-code-chezmoi/.skill-publisher*",
            "**/__pycache__/",
            "**/*.pyc",
        }
        self.assertTrue(required <= ignored, f"missing ignores: {sorted(required - ignored)}")

        base = json.loads(
            (
                REPO_ROOT / "dot_config/claude-code-chezmoi/marketplace-base.json"
            ).read_text("utf-8")
        )
        self.assertEqual(
            base,
            {
                "name": "chezmoi",
                "description": "Local marketplace managed by chezmoi for the claude-code-chezmoi MCP plugin.",
                "owner": {"name": "ningw"},
                "plugins": [
                    {
                        "name": "user-mcps",
                        "description": "User-scope MCP servers.",
                        "source": "./plugins/user-mcps",
                    }
                ],
            },
        )
        self.assertNotIn("superpowers", json.dumps(base).casefold())
        self.assertNotIn("mattpocock", json.dumps(base).casefold())
        actual_repo_skills = {
            path.name
            for path in (REPO_ROOT / "dot_agents/skills").iterdir()
            if path.is_dir()
        }
        self.assertEqual(actual_repo_skills, REPO_SKILL_NAMES)

    def test_python_dsc_resource_is_version_aware_idempotent_and_uses_managed_scoop_paths(self):
        document = (REPO_ROOT / "configuration.dsc.yaml").read_text("utf-8")
        matches = list(
            re.finditer(
                r"(?ms)^    - resource: PSDscResources/Script\r?\n"
                r"      id: ScoopPython\r?\n"
                r"(?P<body>.*?)(?=^    - resource:|\Z)",
                document,
            )
        )
        self.assertEqual(len(matches), 1)
        body = matches[0].group("body")
        required_fragments = [
            "dependsOn:\n        - ScoopBootstrap",
            '$python = "$env:USERPROFILE\\scoop\\apps\\python\\current\\python.exe"',
            '$scoop = "$env:USERPROFILE\\scoop\\shims\\scoop.cmd"',
            "Test-Path -LiteralPath $python -PathType Leaf",
            "3.11.0",
            "$LASTEXITCODE -ne 0",
            "if ($conforming) { return }",
            "& $scoop update python",
            "& $scoop install python",
            "Managed Python failed version verification after Scoop completed.",
            "NotInstalled",
            "InstalledButUnusable",
            "Outdated $version",
        ]
        normalized = body.replace("\r\n", "\n")
        for fragment in required_fragments:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, normalized)
        self.assertGreaterEqual(normalized.count("return $false"), 2)


def configured_choices(variable_name):
    text = (REPO_ROOT / ".chezmoi.toml.tmpl").read_text("utf-8")
    match = re.search(
        rf"\${re.escape(variable_name)}\s*:=\s*list\s+([^\r\n]+)", text
    )
    if match is None:
        raise AssertionError(f"could not find {variable_name} choices")
    return tuple(re.findall(r'"([^"]+)"', match.group(1)))


def isolated_environment(destination, root):
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith("CHEZMOI_")
    }
    env.update(
        {
            "HOME": str(destination),
            "USERPROFILE": str(destination),
            "XDG_CONFIG_HOME": str(root / "xdg-config"),
            "XDG_CACHE_HOME": str(root / "xdg-cache"),
            "XDG_DATA_HOME": str(root / "xdg-data"),
            "XDG_STATE_HOME": str(root / "xdg-state"),
            "APPDATA": str(root / "appdata"),
            "LOCALAPPDATA": str(root / "localappdata"),
        }
    )
    return env


def render_claude_and_wrapper(root, data):
    source = root / "source"
    templates = source / ".chezmoitemplates"
    templates.mkdir(parents=True, exist_ok=True)
    destination = root / "destination"
    destination.mkdir(parents=True, exist_ok=True)
    config = root / "config.json"
    config.write_text("{}", encoding="utf-8")
    (source / ".chezmoidata.json").write_text(json.dumps(data), encoding="utf-8")
    (templates / "claude-settings").write_text(
        (REPO_ROOT / "dot_claude/settings.json.tmpl").read_text("utf-8"),
        encoding="utf-8",
    )
    (templates / "skills-wrapper").write_text(
        (
            REPO_ROOT / ".chezmoiscripts/run_after_shared-agent-skills.ps1.tmpl"
        ).read_text("utf-8"),
        encoding="utf-8",
    )
    bundle = (
        '{"settings": {{ includeTemplate "claude-settings" . | toJson }},'
        '"wrapper": {{ includeTemplate "skills-wrapper" . | toJson }}}'
    )
    result = subprocess.run(
        [
            CHEZMOI,
            "execute-template",
            "--config",
            str(config),
            "--config-format",
            "json",
            "--source",
            str(source),
            "--destination",
            str(destination),
            "--persistent-state",
            str(root / "state.boltdb"),
            "--cache",
            str(root / "cache"),
            "--override-data",
            json.dumps(data),
            "--refresh-externals=never",
            "--no-tty",
            "--no-pager",
        ],
        input=bundle,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=root,
        env=isolated_environment(destination, root),
        timeout=30,
        check=True,
    )
    return json.loads(result.stdout), source, destination


def assert_powershell_parses(testcase, text, root):
    script = root / "parse-target.ps1"
    script.write_text(text, encoding="utf-8")
    parser_command = (
        "$tokens=$null; $errors=$null; "
        "[System.Management.Automation.Language.Parser]::ParseFile($env:PARSE_TARGET,"
        "[ref]$tokens,[ref]$errors) | Out-Null; "
        "if ($errors.Count) { $errors | ForEach-Object { [Console]::Error.WriteLine($_) }; exit 1 }"
    )
    env = os.environ.copy()
    env["PARSE_TARGET"] = str(script)
    result = subprocess.run(
        [POWERSHELL, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", parser_command],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=30,
        check=False,
    )
    testcase.assertEqual(result.returncode, 0, result.stderr)


@unittest.skipUnless(CHEZMOI, "chezmoi is not on PATH; isolated rendering requires it")
@unittest.skipUnless(POWERSHELL, "PowerShell is not on PATH; rendered PowerShell parsing requires it")
class TemplateRenderingIntegrationTests(unittest.TestCase):
    maxDiff = None

    def test_all_configured_themes_providers_and_populated_or_empty_registries_render_in_isolation(self):
        themes = configured_choices("colorscheme_choices")
        providers = configured_choices("codex_provider_choices")
        self.assertTrue(themes, "no colorscheme choices extracted from the source template")
        self.assertTrue(providers, "no provider choices extracted from the source template")
        self.assertEqual(len(themes), len(set(themes)), "duplicate colorscheme choices")
        self.assertEqual(len(providers), len(set(providers)), "duplicate provider choices")
        repository_data = tomllib.loads(
            (REPO_ROOT / ".chezmoidata.toml").read_text("utf-8")
        )
        wrappers = set()
        settings_without_plugins = None

        with tempfile.TemporaryDirectory(prefix="skill-template-render-") as temporary:
            parent = Path(temporary)
            for registry_label, registry in (
                ("populated", repository_data["agent_skills"]["sources"]),
                ("empty", {}),
            ):
                for theme in themes:
                    for provider_name in providers:
                        with self.subTest(
                            registry=registry_label,
                            colorscheme=theme,
                            codex_provider=provider_name,
                        ):
                            data = {
                                "colorscheme": theme,
                                "codex_provider": provider_name,
                                "password_manager": "bitwarden",
                                "git_username": "Fixture User",
                                "git_useremail": "fixture@example.test",
                                "git_signingkey": "FIXTURE",
                                "agent_skills": {"sources": copy.deepcopy(registry)},
                            }
                            case_root = parent / "isolated-render"
                            case_root.mkdir(exist_ok=True)
                            rendered, source, destination = render_claude_and_wrapper(
                                case_root, data
                            )
                            settings = json.loads(rendered["settings"])
                            expected_plugins = {
                                **{f"{name}@chezmoi": True for name in registry},
                                "user-mcps@chezmoi": True,
                            }
                            self.assertEqual(settings["enabledPlugins"], expected_plugins)
                            self.assertNotIn("apiKeyHelper", settings)
                            for key in (
                                "ANTHROPIC_BASE_URL",
                                "ANTHROPIC_MODEL",
                                "ANTHROPIC_DEFAULT_OPUS_MODEL",
                                "ANTHROPIC_DEFAULT_SONNET_MODEL",
                                "ANTHROPIC_DEFAULT_HAIKU_MODEL",
                                "ANTHROPIC_DEFAULT_FABLE_MODEL",
                            ):
                                self.assertNotIn(key, settings["env"])
                            self.assertEqual(
                                settings["modelSettings"]["claude-opus-5-5"][
                                    "effortLevel"
                                ],
                                "xhigh",
                            )
                            comparison = copy.deepcopy(settings)
                            comparison.pop("enabledPlugins")
                            if settings_without_plugins is None:
                                settings_without_plugins = comparison
                            else:
                                self.assertEqual(comparison, settings_without_plugins)
                            wrappers.add(rendered["wrapper"])
                            self.assertIn(
                                source.as_posix() + "/manage_skills.py", rendered["wrapper"]
                            )
                            self.assertIn(
                                destination.as_posix()
                                + "/scoop/apps/python/current/python.exe",
                                rendered["wrapper"],
                            )

            self.assertEqual(len(wrappers), 1)
            assert_powershell_parses(self, next(iter(wrappers)), parent)


@unittest.skipUnless(CHEZMOI, "chezmoi is not on PATH; wrapper rendering requires it")
@unittest.skipUnless(POWERSHELL, "PowerShell is not on PATH; wrapper execution requires it")
class RenderedWrapperExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="skills-wrapper-test-")
        self.root = Path(self.temporary.name)
        data = {
            "colorscheme": "catppuccin-mocha",
            "codex_provider": "litellm",
            "password_manager": "bitwarden",
            "git_username": "Fixture User",
            "git_useremail": "fixture@example.test",
            "git_signingkey": "FIXTURE",
            "agent_skills": {"sources": {"example": {}}},
        }
        rendered, self.source, self.destination = render_claude_and_wrapper(self.root, data)
        self.wrapper_text = rendered["wrapper"]
        self.wrapper = self.root / "rendered wrapper.ps1"
        self.wrapper.write_text(self.wrapper_text, encoding="utf-8")
        self.spy = self.root / "python spy.ps1"
        self.spy.write_text(
            "[IO.File]::WriteAllText($env:SPY_OUTPUT, "
            "(ConvertTo-Json -Compress -InputObject @($args)))\n"
            "$global:LASTEXITCODE = [int]$env:SPY_EXIT\n",
            encoding="utf-8",
        )
        self.spy_output = self.root / "spy arguments.json"

    def tearDown(self):
        self.temporary.cleanup()

    def run_wrapper(self, *arguments, exit_code=0):
        env = os.environ.copy()
        env["SPY_OUTPUT"] = str(self.spy_output)
        env["SPY_EXIT"] = str(exit_code)
        return subprocess.run(
            [
                POWERSHELL,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(self.wrapper),
                *map(str, arguments),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=self.root,
            env=env,
            timeout=30,
            check=False,
        )

    def test_rendered_wrapper_passes_exact_spaced_home_dry_run_and_publisher_arguments(self):
        spaced_home = self.root / "home with spaces"
        spaced_home.mkdir()
        result = self.run_wrapper(
            "-HomeRoot",
            spaced_home,
            "-PythonExecutable",
            self.spy,
            "-DryRun",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        arguments = json.loads(self.spy_output.read_text("utf-8-sig"))
        self.assertEqual(
            arguments,
            [
                "-X",
                "utf8",
                self.source.as_posix() + "/manage_skills.py",
                "--home",
                str(spaced_home),
                "--dry-run",
            ],
        )
        self.assertIn(
            self.destination.as_posix() + "/scoop/apps/python/current/python.exe",
            self.wrapper_text,
        )
        self.assertNotIn("Get-Command python", self.wrapper_text)

    def test_rendered_wrapper_refuses_missing_managed_python(self):
        result = self.run_wrapper(
            "-HomeRoot",
            self.root / "home",
            "-PythonExecutable",
            self.root / "missing-python.exe",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Managed Python is missing", result.stderr)
        self.assertFalse(self.spy_output.exists())

    def test_rendered_wrapper_propagates_nonzero_spy_exit(self):
        result = self.run_wrapper(
            "-HomeRoot",
            self.root / "home",
            "-PythonExecutable",
            self.spy,
            exit_code=19,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Shared skill publication failed (exit 19)", result.stderr)
        self.assertIn("No migration or Claude cache operations were attempted", result.stderr)


class NativeAcceptancePrerequisiteTests(unittest.TestCase):
    def test_missing_symlinks_block_native_acceptance_but_missing_cli_is_a_skip(self):
        # Re-evaluate the actual decorators under each capability disposition.
        node = next(
            node for node in ast.parse(Path(__file__).read_text("utf-8")).body
            if isinstance(node, ast.ClassDef) and node.name == "NativeClaudeAcceptanceTests"
        )
        code = compile(ast.Module(body=[node], type_ignores=[]), __file__, "exec")
        for cli in (None, "fixture-claude"):
            with self.subTest(cli_available=bool(cli)):
                namespace = dict(globals(), CLAUDE=cli, SYMLINKS_AVAILABLE=False)
                exec(code, namespace)
                case = namespace[node.name](
                    "test_native_claude_cache_updates_to_new_content_derived_version"
                )
                result = unittest.TestResult()
                with mock.patch.object(
                    tempfile, "TemporaryDirectory", side_effect=AssertionError("native fixture must not start")
                ), mock.patch.object(
                    subprocess, "run", side_effect=AssertionError("native subprocess must not run")
                ):
                    case.run(result)
                self.assertEqual(result.testsRun, 1)
                self.assertEqual(result.errors, [])
                if cli:
                    self.assertEqual(result.skipped, [])
                    self.assertEqual(len(result.failures), 1)
                    self.assertIn("Native Claude acceptance blocked:", result.failures[0][1])
                else:
                    self.assertEqual(result.failures, [])
                    self.assertEqual(len(result.skipped), 1)
                    self.assertIn("claude CLI is unavailable", result.skipped[0][1])


@unittest.skipUnless(CLAUDE, "claude CLI is unavailable; native plugin acceptance cannot run")
class NativeClaudeAcceptanceTests(unittest.TestCase):
    def test_native_claude_cache_updates_to_new_content_derived_version(self):
        self.assertTrue(
            SYMLINKS_AVAILABLE,
            "Native Claude acceptance blocked: " + SYMLINK_REASON,
        )
        with tempfile.TemporaryDirectory(prefix="native-claude-skills-") as temporary:
            root = Path(temporary)
            home = root / "home"
            home.mkdir()
            source = home / "raw/example"
            write_skill(source, "skills/one", "one")
            write_skill(source, "skills/two", "two")
            base = root / "marketplace-base.json"
            base.write_bytes(
                canonical_json_bytes(
                    {"name": "chezmoi", "owner": {"name": "test"}, "plugins": []}
                )
            )
            declaration = {
                "directory": "raw/example",
                "include": ["skills/one", "skills/two"],
            }
            publisher.publish(home, {"example": declaration}, base)
            generated = home / ".config/claude-code-chezmoi/generated-skills/example"
            marketplace_root = home / ".config/claude-code-chezmoi"
            first_manifest = json.loads(
                (generated / ".claude-plugin/plugin.json").read_text("utf-8")
            )
            first_version = first_manifest["version"]

            env = os.environ.copy()
            env.update(
                {
                    "HOME": str(home),
                    "USERPROFILE": str(home),
                    "CLAUDE_CONFIG_DIR": str(home / ".claude"),
                    "DISABLE_TELEMETRY": "1",
                    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
                    "APPDATA": str(home / "AppData/Roaming"),
                    "LOCALAPPDATA": str(home / "AppData/Local"),
                    "XDG_CONFIG_HOME": str(home / ".config"),
                    "XDG_CACHE_HOME": str(home / ".cache"),
                    "XDG_DATA_HOME": str(home / ".local/share"),
                    "XDG_STATE_HOME": str(home / ".local/state"),
                }
            )

            def run_claude(*arguments):
                try:
                    return subprocess.run(
                        [CLAUDE, *map(str, arguments)],
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        cwd=root,
                        env=env,
                        timeout=90,
                        check=True,
                    )
                except subprocess.CalledProcessError as exc:
                    self.fail(
                        f"native Claude command failed (exit {exc.returncode}): "
                        f"{exc.cmd!r}\nstdout:\n{exc.stdout}\nstderr:\n{exc.stderr}"
                    )
                except subprocess.TimeoutExpired as exc:
                    self.fail(f"native Claude command timed out: {exc.cmd!r}")

            cli_version = run_claude("--version").stdout.strip()
            self.assertTrue(cli_version, "claude --version must report a version")
            run_claude("plugin", "validate", generated)
            run_claude("plugin", "marketplace", "add", marketplace_root)
            run_claude("plugin", "install", "example@chezmoi", "--scope", "user")

            registry_path = home / ".claude/plugins/installed_plugins.json"
            first_registry = json.loads(registry_path.read_text("utf-8"))
            first_record = first_registry["plugins"]["example@chezmoi"][0]
            self.assertEqual(first_record["version"], first_version)
            first_install_path = first_record["installPath"]

            declaration = {
                "directory": "raw/example",
                "include": ["skills/one", "skills/two"],
                "exclude": ["skills/two"],
            }
            publisher.publish(home, {"example": declaration}, base)
            second_manifest = json.loads(
                (generated / ".claude-plugin/plugin.json").read_text("utf-8")
            )
            second_version = second_manifest["version"]
            self.assertNotEqual(second_version, first_version)
            run_claude("plugin", "marketplace", "update", "chezmoi")
            run_claude("plugin", "update", "example@chezmoi", "--scope", "user")

            second_registry = json.loads(registry_path.read_text("utf-8"))
            second_record = second_registry["plugins"]["example@chezmoi"][0]
            self.assertEqual(second_record["version"], second_version)
            self.assertNotEqual(second_record["version"], first_record["version"])
            self.assertNotEqual(
                second_record["installPath"],
                "",
                f"claude {cli_version} returned an empty plugin install path",
            )
            install_path = Path(second_record["installPath"])
            if not install_path.is_absolute():
                install_path = home / install_path
            try:
                install_path.resolve().relative_to(home.resolve())
            except ValueError:
                self.fail(f"Claude cache escaped fixture home: {install_path}")
            self.assertNotEqual(first_install_path, "")
            self.assertTrue((install_path / "skills/one/SKILL.md").is_file())
            self.assertFalse((install_path / "skills/two").exists())
            cached_manifest = json.loads(
                (install_path / ".claude-plugin/plugin.json").read_text("utf-8")
            )
            self.assertEqual(cached_manifest["skills"], ["./skills/one"])
            self.assertEqual(cached_manifest["version"], second_version)
            self.assertFalse(os.path.lexists(home / ".agents/skills/two"))


if __name__ == "__main__":
    unittest.main()
