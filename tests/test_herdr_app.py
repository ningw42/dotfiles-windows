"""Check the HerdR desktop defaults and parity with the declared TUI shortcuts."""

import json
import os
import subprocess
import tomllib
import unittest
from pathlib import Path


from llm_test_support import CHEZMOI, POWERSHELL, render_template

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "dot_config/herdr-app"
HOME_HOOK = "dot_config/herdr-app/run_after_set-herdr-app-home.ps1.tmpl"


class HerdrAppTests(unittest.TestCase):
    def test_appearance_defaults_to_dark_mocha_and_has_a_light_counterpart(self):
        settings = json.loads((APP / "settings.json").read_text("utf-8"))
        self.assertEqual(settings["appearance"], "dark")
        self.assertEqual(settings["theme"], {"light": "catppuccin-latte", "dark": "catppuccin-mocha"})


@unittest.skipUnless(CHEZMOI, "chezmoi is required to render the keymap")
class HerdrAppKeymapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.keys = json.loads(render_template(APP / "keys.json.tmpl"))

    def test_tui_shortcuts_reach_the_corresponding_desktop_actions(self):
        tui = tomllib.loads((ROOT / "AppData/Roaming/herdr/config.toml").read_text("utf-8"))["keys"]
        keys = self.keys
        actions = {
            "goto": "mod.open:picker",
            "new_tab": "tab.new",
            "next_tab": "tab.next", "previous_tab": "tab.prev",
            "next_workspace": "space.next", "previous_workspace": "space.prev",
            "next_agent": "agent.next", "previous_agent": "agent.prev",
        }

        def check_binding(shortcut, expected):
            prefix = tui["prefix"].replace("+", "-")
            binding = shortcut.replace("prefix+", prefix + " ").replace("+", "-")
            with self.subTest(binding=binding):
                self.assertEqual(keys["global"][binding], expected)
                self.assertNotIn(binding, keys["terminal"], "terminal focus shadows the global binding")

        for action, expected in actions.items():
            shortcuts = tui[action]
            for shortcut in [shortcuts] if isinstance(shortcuts, str) else shortcuts:
                check_binding(shortcut, expected)
        lazygit = next(c for c in tui["command"] if c["command"] == "lazygit")
        check_binding(lazygit["key"], {"command": "pane.split", "args": {"direction": "right", "argv": ["lazygit"]}})

    def test_arrow_overrides_leave_pane_navigation_and_terminal_shortcuts_available(self):
        keys = self.keys
        for key, direction in zip("hjkl", ("left", "down", "up", "right")):
            self.assertEqual(keys["global"]["alt-" + key], "pane.go:" + direction)
        self.assertEqual(keys["terminal"]["ctrl-shift-c"], "terminal.copy")
        self.assertEqual(keys["terminal"]["ctrl-shift-v"], "terminal.paste")


@unittest.skipUnless(CHEZMOI and POWERSHELL, "chezmoi and PowerShell are required")
class HerdrAppHomeTests(unittest.TestCase):
    def test_hook_restores_app_home_after_scoop_override(self):
        home = "C:/Users/O'Brien $fixture"
        expected = home + "/.config/herdr-app"
        hook = render_template(HOME_HOOK, home=home)
        # Redirect both registry operations to this disposable child process. Never
        # execute a User-scope write in a test, even if the template changes.
        self.assertEqual(hook.count(", 'User')"), 2)
        hook = hook.replace(", 'User')", ", 'Process')")
        self.assertNotIn("'User'", hook)
        env = {**os.environ, "HERDR_APP_HOME": "C:/scoop/apps/herdr-app/current/data"}
        result = subprocess.run(
            [POWERSHELL, "-NoProfile", "-NonInteractive", "-Command",
             "$ErrorActionPreference = 'Stop'\n" + hook + "\n$env:HERDR_APP_HOME"],
            env=env, capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), expected)

    def test_windows_hook_is_empty_on_other_platforms(self):
        data = {"chezmoi": {"os": "linux", "homeDir": "/home/fixture"}}
        self.assertFalse(render_template(HOME_HOOK, extra_data=data).strip())


if __name__ == "__main__":
    unittest.main()
