"""Windows DPAPI and real chezmoi apply tests; all identities/state are disposable.

No test reads the user's ciphertext, native login stores, registry, or environment
credentials. The apply fixture supplies the renderer's public manifest contract.
"""

import concurrent.futures
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "dot_config/llm/credentials.ps1"
HOOK = ROOT / ".chezmoiscripts/run_before_llm-credentials.ps1.tmpl"
EXTRACTION = ROOT / ".chezmoitemplates/llm/credential-values.json.tmpl"
PWSH = shutil.which("pwsh")
CHEZMOI = shutil.which("chezmoi")
WINDOWS = os.name == "nt"


def ps_quote(value):
    return "'" + str(value).replace("'", "''") + "'"


@unittest.skipUnless(WINDOWS and PWSH, "Windows and PowerShell 7 are required for DPAPI")
class CredentialStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="llm credentials ' fixture ")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.store = self.root / "nested" / "store"

    def command(self, action="Publish", provider=None, store=None):
        args = [PWSH, "-NoLogo", "-NoProfile", "-NonInteractive", "-File", str(HELPER),
                "-Action", action, "-StoreDirectory", str(store or self.store)]
        if provider is not None:
            args += ["-Provider", provider]
        return args

    def invoke(self, action="Publish", provider=None, payload=None, raw=None, store=None):
        if payload is not None:
            raw = json.dumps({"schema_version": 1, "providers": payload}, ensure_ascii=False)
        return subprocess.run(self.command(action, provider, store), input=raw, capture_output=True,
                              text=True, encoding="utf-8", timeout=20, cwd=self.root)

    def publish(self, providers):
        result = self.invoke(payload=providers)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "")
        return result

    def assert_failed(self, result, *secrets):
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertTrue(result.stderr.strip())
        self.assertLess(len(result.stderr), 300)
        for secret in secrets:
            self.assertNotIn(secret, result.stderr)

    def powershell(self, script):
        return subprocess.run([PWSH, "-NoProfile", "-NonInteractive", "-Command", script],
                              capture_output=True, text=True, encoding="utf-8", timeout=20)

    def snapshot(self):
        path = self.store / "snapshot.json"
        return path.read_bytes(), path.stat().st_mtime_ns

    def test_roundtrip_private_dpapi_and_idempotency(self):
        providers = {"copilotd": "fixture-copilotd-unique", "magpie": "fixture-magpie-unique"}
        self.publish(providers)
        before = self.snapshot()
        outer = json.loads(before[0])
        self.assertEqual(set(outer), {"marker", "schema_version", "protection", "payload"})
        self.assertEqual(outer["protection"], "DPAPI-CurrentUser")
        for provider, value in providers.items():
            self.assertNotIn(value.encode(), before[0])
            result = self.invoke("Get", provider)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, value)
            self.assertEqual(result.stderr, "")
        self.publish(dict(reversed(list(providers.items()))))
        self.assertEqual(before, self.snapshot())
        self.assertEqual({p.name for p in self.store.iterdir()}, {"publish.lock", "snapshot.json"})

    def test_rotation_and_explicit_provider_removal(self):
        self.publish({"copilotd": "first", "magpie": "second"})
        before = self.snapshot()
        self.publish({"copilotd": "rotated"})
        self.assertNotEqual(before[0], self.snapshot()[0])
        self.assertEqual(self.invoke("Get", "copilotd").stdout, "rotated")
        self.assert_failed(self.invoke("Get", "magpie"))
        self.publish({})
        self.assert_failed(self.invoke("Get", "copilotd"))
        before = self.snapshot()
        self.publish({})
        self.assertEqual(before, self.snapshot())

    def test_canonically_equivalent_unicode_rotation_is_byte_exact(self):
        first, second = "fixture-caf\u00e9", "fixture-cafe\u0301"
        self.assertNotEqual(first.encode("utf-8"), second.encode("utf-8"))
        self.publish({"copilotd": first})
        before = self.snapshot()[0]
        self.publish({"copilotd": second})
        self.assertNotEqual(self.snapshot()[0], before)
        self.assertEqual(self.invoke("Get", "copilotd").stdout, second)

    def test_publish_and_get_use_utf8_under_non_utf8_console_encoding(self):
        wrapper = self.root / "nonutf8-console.ps1"
        # Set .NET console readers/writers to a legacy encoding in this child
        # only. The helper must use raw streams instead of those text wrappers.
        wrapper.write_text(
            "param($Helper,$Action,$Store)\n"
            "[Console]::InputEncoding = [Text.Encoding]::GetEncoding(437)\n"
            "[Console]::OutputEncoding = [Text.Encoding]::GetEncoding(437)\n"
            "if ($Action -eq 'Publish') { & $Helper -Action Publish -StoreDirectory $Store }\n"
            "else { & $Helper -Action Get -Provider copilotd -StoreDirectory $Store }\n",
            encoding="utf-8",
        )
        value = "fixture-café 汉字 🚀"
        command = [PWSH, "-NoProfile", "-NonInteractive", "-File", str(wrapper), str(HELPER)]
        published = subprocess.run(
            [*command, "Publish", str(self.store)],
            input=json.dumps({"schema_version": 1, "providers": {"copilotd": value}}, ensure_ascii=False).encode("utf-8"),
            capture_output=True, timeout=20,
        )
        self.assertEqual(published.returncode, 0, published.stderr)
        self.assertEqual(published.stdout, b"")
        result = subprocess.run([*command, "Get", str(self.store)], capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, value.encode("utf-8"))
        self.assertEqual(result.stderr, b"")

    def test_newline_provider_ids_are_rejected_before_publication(self):
        for provider in ("copilotd\n", "copilotd\r\n"):
            self.assert_failed(self.invoke(payload={provider: "fixture-secret"}), "fixture-secret")
            self.assertFalse(self.store.exists())
        self.publish({"copilotd": "retained"})
        before = self.snapshot()
        self.assert_failed(self.invoke(payload={"copilotd\n": "replacement"}))
        self.assert_failed(self.invoke("Get", "copilotd\n"))
        self.assertEqual(before, self.snapshot())

    def test_unusual_characters_are_exact_not_shell_or_template_code(self):
        value = '  fixture "quote" \'apostrophe\' \\ slash / $(`x`) ; & | < > % ! {{ braces }} café 汉字 🚀  '
        self.publish({"copilotd": value})
        self.assertEqual(self.invoke("Get", "copilotd").stdout, value)

    def test_invalid_input_never_mutates_valid_store_or_leaks(self):
        self.publish({"copilotd": "retained-fixture-secret"})
        before = self.snapshot()
        invalid = [
            "not-json-fixture-secret", "[]", "null", "{}",
            '{"schema_version":1,"schema_version":1,"providers":{}}',
            '{"schema_version":1,"providers":{"copilotd":"one","copilotd":"two"}}',
            '{"schema_version":1,"providers":{},"extra":"fixture-secret"}',
        ]
        invalid += [json.dumps({"schema_version": version, "providers": {}}) for version in [2, "1", True, 1.0]]
        invalid += [json.dumps({"schema_version": 1, "providers": providers}) for providers in [
            None, [], "fixture-secret", {"copilotd": None}, {"copilotd": 1}, {"copilotd": True},
            {"copilotd": []}, {"copilotd": {}}, {"copilotd": ""}, {"copilotd": "  "},
            {"bad/id": "fixture-secret"}, {"UPPER": "fixture-secret"}, {"": "fixture-secret"},
            {"copilotd": "fixture-secret\n"}, {"copilotd": "fixture-secret\0"},
            {"copilotd": "fixture-secret\x7f"}, {"copilotd": "fixture-secret\x85"},
        ]]
        for raw in invalid:
            with self.subTest(raw=raw):
                self.assert_failed(self.invoke(raw=raw), "fixture-secret", "retained-fixture-secret")
                self.assertEqual(before, self.snapshot())
        self.assert_failed(self.invoke("Get", "bad/id"))
        self.assert_failed(self.invoke("Invalid-action"))

    def test_invalid_input_does_not_create_store(self):
        self.assert_failed(self.invoke(payload={"copilotd": "bad\nvalue"}), "bad")
        self.assertFalse(self.store.exists())

    def test_missing_and_corrupt_snapshots_fail_closed(self):
        self.assert_failed(self.invoke("Get", "copilotd"))
        self.publish({"copilotd": "fixture-secret"})
        path = self.store / "snapshot.json"
        for corrupt in ['invalid fixture-secret', json.dumps({"marker": "foreign"}), json.dumps({
            "marker": "llm-credentials", "schema_version": 1,
            "protection": "DPAPI-CurrentUser", "payload": "Zm9yZWlnbi1maXh0dXJlLXBheWxvYWQ=",
        })]:
            path.write_text(corrupt, encoding="utf-8")
            self.assert_failed(self.invoke("Get", "copilotd"), "fixture-secret")
            self.assert_failed(self.invoke(payload={"copilotd": "replacement-fixture-secret"}), "fixture-secret")
            self.assertEqual(path.read_text(encoding="utf-8"), corrupt)

    def test_foreign_nonempty_directory_and_extra_entries_are_not_adopted(self):
        self.store.mkdir(parents=True)
        foreign = self.store / "foreign.txt"
        foreign.write_text("untouched", encoding="utf-8")
        self.assert_failed(self.invoke(payload={"copilotd": "fixture-secret"}), "fixture-secret")
        self.assertEqual(foreign.read_text(), "untouched")
        self.assertEqual(list(self.store.iterdir()), [foreign])
        shutil.rmtree(self.store)
        self.publish({"copilotd": "first"})
        before = self.snapshot()
        foreign.write_text("untouched", encoding="utf-8")
        self.assert_failed(self.invoke(payload={"copilotd": "second"}))
        self.assertEqual(before, self.snapshot())

    def test_acl_tampering_is_rejected_without_repair(self):
        self.publish({"copilotd": "fixture-secret"})
        before = self.snapshot()
        path = self.store / "snapshot.json"
        result = self.powershell(
            f"$p={ps_quote(path)}; $f=[IO.FileInfo]::new($p); "
            "$a=[IO.FileSystemAclExtensions]::GetAccessControl($f,[Security.AccessControl.AccessControlSections]::Access); "
            "$s=[System.Security.Principal.SecurityIdentifier]::new('S-1-1-0'); "
            "$r=[System.Security.AccessControl.FileSystemAccessRule]::new($s,'Read','Allow'); "
            "$a.AddAccessRule($r); [IO.FileSystemAclExtensions]::SetAccessControl($f,$a)"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_failed(self.invoke("Get", "copilotd"), "fixture-secret")
        self.assert_failed(self.invoke(payload={"copilotd": "replacement"}))
        self.assertEqual(before, self.snapshot())

    def test_unknown_lock_and_missing_lock_fail_closed(self):
        self.publish({"copilotd": "retained"})
        before = self.snapshot()
        lock = self.store / "publish.lock"
        lock.write_text("foreign-lock-marker", encoding="utf-8")
        self.assert_failed(self.invoke(payload={"copilotd": "replacement"}))
        self.assertEqual(lock.read_text(), "foreign-lock-marker")
        self.assertEqual(before, self.snapshot())
        lock.unlink()
        self.assert_failed(self.invoke(payload={"copilotd": "replacement"}))
        self.assertFalse(lock.exists())
        self.assertEqual(before, self.snapshot())
        self.assertEqual(self.invoke("Get", "copilotd").stdout, "retained")

    def test_inherited_acl_and_foreign_owner_are_rejected(self):
        self.publish({"copilotd": "fixture-secret"})
        path = self.store / "snapshot.json"
        before = self.snapshot()
        original = self.powershell(
            f"$f=[IO.FileInfo]::new({ps_quote(path)}); "
            "$a=[IO.FileSystemAclExtensions]::GetAccessControl($f); "
            "[Console]::Write($a.Sddl)"
        )
        self.assertEqual(original.returncode, 0, original.stderr)
        changed = self.powershell(
            f"$f=[IO.FileInfo]::new({ps_quote(path)}); "
            "$a=[IO.FileSystemAclExtensions]::GetAccessControl($f,[Security.AccessControl.AccessControlSections]::Access); "
            "$a.SetAccessRuleProtection($false,$true); [IO.FileSystemAclExtensions]::SetAccessControl($f,$a)"
        )
        self.assertEqual(changed.returncode, 0, changed.stderr)
        self.assert_failed(self.invoke("Get", "copilotd"))
        self.assert_failed(self.invoke(payload={"copilotd": "replacement"}))
        self.assertEqual(before, self.snapshot())
        # Foreign owner assignment may require privileges; the ACL assertion above
        # always runs, and the ownership check runs where Windows permits it.
        changed = self.powershell(
            f"$f=[IO.FileInfo]::new({ps_quote(path)}); "
            "$a=[Security.AccessControl.FileSecurity]::new(); "
            f"$a.SetSecurityDescriptorSddlForm({ps_quote(original.stdout)}); "
            "$a.SetOwner([Security.Principal.SecurityIdentifier]::new('S-1-5-32-544')); "
            "[IO.FileSystemAclExtensions]::SetAccessControl($f,$a)"
        )
        if changed.returncode == 0:
            self.assert_failed(self.invoke("Get", "copilotd"))
            self.assert_failed(self.invoke(payload={"copilotd": "replacement"}))
            self.assertEqual(before, self.snapshot())

    def test_interrupted_stage_is_not_adopted_or_automatically_deleted(self):
        self.publish({"copilotd": "retained"})
        before = self.snapshot()
        remnant = self.store / ".snapshot.fixture-crash.tmp"
        remnant.write_bytes(b"not-a-complete-snapshot")
        self.assert_failed(self.invoke(payload={"copilotd": "replacement"}))
        self.assertEqual(before, self.snapshot())
        self.assertEqual(remnant.read_bytes(), b"not-a-complete-snapshot")
        self.assertEqual(self.invoke("Get", "copilotd").stdout, "retained")

    def test_reparse_ancestor_is_rejected(self):
        target = self.root / "target"
        target.mkdir()
        link = self.root / "junction"
        result = self.powershell(
            f"New-Item -ItemType Junction -Path {ps_quote(link)} -Target {ps_quote(target)} | Out-Null"
        )
        if result.returncode:
            self.skipTest("Junction creation unavailable")
        try:
            self.assert_failed(self.invoke(payload={"copilotd": "fixture-secret"}, store=link / "store"))
            self.assertEqual(list(target.iterdir()), [])
        finally:
            link.rmdir()

    def test_reparse_snapshot_is_rejected_if_symlinks_available(self):
        self.publish({"copilotd": "retained"})
        snapshot = self.store / "snapshot.json"
        saved = self.root / "saved-snapshot.json"
        snapshot.replace(saved)
        result = self.powershell(
            f"New-Item -ItemType SymbolicLink -Path {ps_quote(snapshot)} -Target {ps_quote(saved)} | Out-Null"
        )
        if result.returncode:
            self.skipTest("File symlink creation unavailable")
        before = saved.read_bytes()
        self.assert_failed(self.invoke("Get", "copilotd"))
        self.assert_failed(self.invoke(payload={"copilotd": "replacement"}))
        self.assertEqual(saved.read_bytes(), before)

    def test_concurrent_initial_publishers_do_not_adopt_foreign_state(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda index: self.invoke(payload={"copilotd": f"fixture-{index}"}), range(4)))
        for result in results:
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "")
        self.assertRegex(self.invoke("Get", "copilotd").stdout, r"^fixture-[0-3]$")

    def test_concurrent_publishers_and_readers_observe_complete_snapshots(self):
        self.publish({"copilotd": "initial", "magpie": "initial"})
        def writer(index):
            return self.invoke(payload={"copilotd": f"fixture-{index}", "magpie": f"fixture-{index}"})
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            futures = [pool.submit(writer, index) for index in range(8)]
            reads = [pool.submit(self.invoke, "Get", "copilotd") for _ in range(5)]
            for future in futures:
                result = future.result()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, "")
            for future in reads:
                result = future.result()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertRegex(result.stdout, r"^(initial|fixture-[0-7])$")
        first = self.invoke("Get", "copilotd")
        second = self.invoke("Get", "magpie")
        self.assertEqual(first.stdout, second.stdout)
        self.assertEqual({p.name for p in self.store.iterdir()}, {"snapshot.json", "publish.lock"})

    def test_lock_timeout_preserves_snapshot(self):
        self.publish({"copilotd": "retained"})
        before = self.snapshot()
        script = (
            f"$f=[IO.File]::Open({ps_quote(self.store / 'publish.lock')},'Open','ReadWrite','None'); "
            "try { [Console]::Out.WriteLine('ready'); [Console]::Out.Flush(); Start-Sleep -Seconds 15 } "
            "finally { $f.Dispose() }"
        )
        process = subprocess.Popen([PWSH, "-NoProfile", "-Command", script], stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True, encoding="utf-8")
        try:
            self.assertEqual(process.stdout.readline().strip(), "ready")
            started = time.monotonic()
            self.assert_failed(self.invoke(payload={"copilotd": "replacement"}))
            self.assertLess(time.monotonic() - started, 12)
            self.assertEqual(before, self.snapshot())
        finally:
            process.kill()
            process.communicate(timeout=10)


@unittest.skipUnless(WINDOWS and PWSH and CHEZMOI, "Windows, PowerShell 7, and chezmoi are required")
class CredentialApplyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="llm apply ' ‘ ’ fixture ")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        self.home = self.root / "home"
        self.source.mkdir()
        self.home.mkdir()
        self.config = self.root / "chezmoi.json"
        self.identity = self.root / "identity.txt"
        self.config.write_text("{}", encoding="utf-8")
        generated = self.chezmoi("age-keygen")
        self.assertEqual(generated.returncode, 0, generated.stderr)
        self.identity.write_text(generated.stdout, encoding="utf-8")
        recipient = self.chezmoi("age-keygen", "-y", str(self.identity))
        self.assertEqual(recipient.returncode, 0, recipient.stderr)
        self.config.write_text(json.dumps({
            "encryption": "age", "useBuiltinAge": True,
            "age": {"identity": str(self.identity), "recipient": recipient.stdout.strip()},
            "data": {"llm_pwsh": PWSH.replace("\\", "/")},
            "interpreters": {"ps1": {"command": PWSH, "args": ["-NoLogo", "-NoProfile", "-NonInteractive", "-File"]}},
        }), encoding="utf-8")
        for original, relative in [
            (HELPER, "dot_config/llm/credentials.ps1"),
            (HOOK, ".chezmoiscripts/run_before_llm-credentials.ps1.tmpl"),
            (EXTRACTION, ".chezmoitemplates/llm/credential-values.json.tmpl"),
        ]:
            target = self.source / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(original, target)
        (self.source / ".chezmoiignore").write_text("secrets.yaml.age\n", encoding="utf-8")
        self.renderer = self.source / ".chezmoitemplates/llm/render.json.tmpl"
        self.manifest({"copilotd": "copilotd_api_key", "magpie": "magpie_api_key"})
        self.encrypt({"copilotd_api_key": "fixture-copilotd-secret", "magpie_api_key": "fixture-magpie-secret",
                      "unrelated_secret": "never-extract-this-fixture-secret"})
        self.store = self.home / ".config/llm/store"

    def chezmoi(self, *args, input=None, env=None):
        return subprocess.run([
            CHEZMOI, "--config", str(self.config), "--source", str(self.source),
            "--destination", str(self.home), "--persistent-state", str(self.root / "parent-state.boltdb"),
            "--cache", str(self.root / "parent-cache"), "--no-tty", "--no-pager", "--refresh-externals=never",
            "--color=false", "--progress=false", *args,
        ], input=input, capture_output=True, text=True, encoding="utf-8", timeout=90, cwd=self.root, env=env)

    def manifest(self, bindings):
        # Stub only the parent's nonsecret renderer, not the extraction or hook.
        self.renderer.write_text(json.dumps({"schema_version": 1, "providers": {
            key: {"secret_field": field} for key, field in bindings.items()
        }}), encoding="utf-8")

    def encrypt(self, values):
        # JSON is a YAML subset. Fixture plaintext never goes to a file.
        result = self.chezmoi("encrypt", input=json.dumps(values, ensure_ascii=False))
        self.assertEqual(result.returncode, 0, result.stderr)
        (self.source / "secrets.yaml.age").write_text(result.stdout, encoding="utf-8")

    def get(self, provider):
        return subprocess.run([
            PWSH, "-NoProfile", "-NonInteractive", "-File", str(self.home / ".config/llm/credentials.ps1"),
            "-Action", "Get", "-Provider", provider,
        ], capture_output=True, text=True, encoding="utf-8", timeout=20, cwd=self.home)

    def assert_apply(self):
        result = self.chezmoi("apply", "--force")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("fixture-copilotd-secret", result.stdout + result.stderr)
        self.assertNotIn("fixture-magpie-secret", result.stdout + result.stderr)
        return result

    def test_fresh_diff_without_key_store_or_deployed_helper_does_not_decrypt(self):
        self.identity.unlink()
        (self.source / "secrets.yaml.age").unlink()
        result = self.chezmoi("diff")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.store.exists())
        self.assertFalse((self.home / ".config/llm/credentials.ps1").exists())
        self.assertNotIn("fixture-copilotd-secret", result.stdout + result.stderr)

    def test_actual_apply_refreshes_every_time_with_no_parent_lock_deadlock(self):
        self.assert_apply()
        self.assertEqual(self.get("copilotd").stdout, "fixture-copilotd-secret")
        self.assertEqual(self.get("magpie").stdout, "fixture-magpie-secret")
        self.assertNotEqual(self.get("unrelated_secret").returncode, 0)
        snapshot = self.store / "snapshot.json"
        before = snapshot.read_bytes(), snapshot.stat().st_mtime_ns
        self.assert_apply()
        self.assertEqual(before, (snapshot.read_bytes(), snapshot.stat().st_mtime_ns))
        unusual = 'rotated-fixture "quote" \' apostrophe \\ $(`x`) ; café 汉字 🚀'
        self.encrypt({"copilotd_api_key": unusual, "magpie_api_key": "fixture-magpie-secret"})
        self.assert_apply()
        self.assertEqual(self.get("copilotd").stdout, unusual)
        self.manifest({"copilotd": "copilotd_api_key"})
        self.assert_apply()
        self.assertNotEqual(self.get("magpie").returncode, 0)
        # Runtime lookup works after all source/ciphertext/identity files disappear.
        self.identity.unlink()
        shutil.rmtree(self.source)
        self.assertEqual(self.get("copilotd").stdout, unusual)

    def test_hook_paths_with_ascii_and_unicode_apostrophes_are_data(self):
        # Every apply fixture includes ASCII + both smart apostrophes in source,
        # destination, and config paths. Also cover executable override paths.
        bin_directory = self.root / "pwsh ' ‘ ’ executable"
        bin_directory.mkdir()
        # Hard-linking only the executable is not enough for PowerShell's runtime;
        # use a directory junction to its existing installation instead.
        runtime = bin_directory / "runtime"
        command = (
            "$p=$args[0]; $t=$args[1]; "
            "New-Item -ItemType Junction -Path $p -Target $t | Out-Null"
        )
        create = self.root / "create-junction.ps1"
        create.write_text(command, encoding="utf-8")
        result = subprocess.run([PWSH, "-NoProfile", "-File", str(create), str(runtime), str(Path(PWSH).parent)],
                                capture_output=True, text=True, encoding="utf-8", timeout=20)
        if result.returncode:
            self.skipTest("Directory junction unavailable for executable-path test")
        self.addCleanup(runtime.rmdir)
        config = json.loads(self.config.read_text(encoding="utf-8"))
        config["data"]["llm_pwsh"] = (runtime / Path(PWSH).name).as_posix()
        self.config.write_text(json.dumps(config), encoding="utf-8")
        self.assert_apply()
        self.assertEqual(self.get("copilotd").stdout, "fixture-copilotd-secret")

    def test_normal_apply_recreates_deleted_snapshot_and_deleted_store(self):
        self.assert_apply()
        (self.store / "snapshot.json").unlink()
        self.assert_apply()
        self.assertEqual(self.get("copilotd").stdout, "fixture-copilotd-secret")
        shutil.rmtree(self.store)
        self.assert_apply()
        self.assertEqual(self.get("copilotd").stdout, "fixture-copilotd-secret")
        self.assertEqual(self.get("magpie").stdout, "fixture-magpie-secret")

    def test_extraction_failure_leaves_previous_store_and_never_logs_values(self):
        self.assert_apply()
        snapshot = self.store / "snapshot.json"
        before = snapshot.read_bytes(), snapshot.stat().st_mtime_ns
        for invalid in [None, "", 42, ["fixture-sensitive-list"], "fixture-sensitive\nvalue"]:
            self.encrypt({"copilotd_api_key": invalid, "magpie_api_key": "fixture-magpie-secret"})
            result = self.chezmoi("apply", "--force")
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn("fixture-sensitive", result.stdout + result.stderr)
            self.assertNotIn("fixture-magpie-secret", result.stdout + result.stderr)
            self.assertEqual(before, (snapshot.read_bytes(), snapshot.stat().st_mtime_ns))
        self.encrypt({"magpie_api_key": "fixture-magpie-secret"})
        result = self.chezmoi("apply", "--force")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(before, (snapshot.read_bytes(), snapshot.stat().st_mtime_ns))
        self.identity.unlink()
        result = self.chezmoi("apply", "--force")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(before, (snapshot.read_bytes(), snapshot.stat().st_mtime_ns))

    def test_malformed_yaml_errors_do_not_leak_decrypted_plaintext(self):
        self.assert_apply()
        before = (self.store / "snapshot.json").read_bytes()
        result = self.chezmoi("encrypt", input='copilotd_api_key: [ fixture-sensitive-malformed-yaml')
        self.assertEqual(result.returncode, 0, result.stderr)
        (self.source / "secrets.yaml.age").write_text(result.stdout, encoding="utf-8")
        result = self.chezmoi("apply", "--force")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("fixture-sensitive", result.stdout + result.stderr)
        self.assertEqual(before, (self.store / "snapshot.json").read_bytes())

    def test_child_does_not_inherit_chezmoi_redirection_debug_or_paths(self):
        # Render the actual hook in the isolated fixture, then execute it with
        # hostile inherited child controls; the parent process stays untouched.
        rendered = self.chezmoi("execute-template", input=HOOK.read_text(encoding="utf-8"))
        self.assertEqual(rendered.returncode, 0, rendered.stderr)
        script = self.root / "rendered-hook.ps1"
        script.write_text(rendered.stdout, encoding="utf-8")
        trap = self.root / "must-not-exist.txt"
        environment = dict(os.environ, CHEZMOI_DEBUG="true", CHEZMOI_VERBOSE="true", CHEZMOI_OUTPUT=str(trap),
                           CHEZMOI_CONFIG=str(trap), CHEZMOI_SOURCE_DIR=str(trap), CHEZMOI_DEST_DIR=str(trap),
                           CHEZMOI_PERSISTENT_STATE_FILE=str(trap), CHEZMOI_CACHE_DIR=str(trap))
        result = subprocess.run([PWSH, "-NoProfile", "-NonInteractive", "-File", str(script)],
                                capture_output=True, text=True, encoding="utf-8", timeout=80, env=environment)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "")
        self.assertFalse(trap.exists())
        self.assertTrue((self.store / "snapshot.json").exists())
        for path in self.root.rglob("*"):
            if path.is_file():
                content = path.read_bytes()
                for secret in [b"fixture-copilotd-secret", b"fixture-magpie-secret", b"never-extract-this-fixture-secret"]:
                    self.assertNotIn(secret, content, str(path))

    def test_real_renderer_manifest_publishes_only_selected_provider_keys(self):
        import sys
        from llm_test_support import prepare_source

        prepare_source(self.source)  # Replace only the manifest stub with real public data/rendering.
        config = json.loads(self.config.read_text(encoding="utf-8"))
        config["data"]["llm_python"] = sys.executable
        self.config.write_text(json.dumps(config), encoding="utf-8")
        with (self.source / ".chezmoiignore").open("a", encoding="utf-8") as ignore:
            ignore.write("render_llm_config.py\n.config/llm/store/\n")
        self.assert_apply()
        self.assertEqual(self.get("copilotd").stdout, "fixture-copilotd-secret")
        self.assertEqual(self.get("magpie").stdout, "fixture-magpie-secret")
        self.assertNotEqual(self.get("deepseek").returncode, 0)
        self.assertFalse((self.home / "render_llm_config.py").exists())

    def test_newline_credential_references_fail_before_store_creation(self):
        for manifest in ({"copilotd\n": "copilotd_api_key"}, {"copilotd": "copilotd_api_key\n"}):
            self.manifest(manifest)
            result = self.chezmoi("apply", "--force")
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(self.store.exists())
            self.assertNotIn("fixture-copilotd-secret", result.stdout + result.stderr)

    def test_empty_manifest_removes_keys_without_age_identity(self):
        self.assert_apply()
        self.manifest({})
        self.identity.unlink()
        self.assert_apply()
        result = self.get("copilotd")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
