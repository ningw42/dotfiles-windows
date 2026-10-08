import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
LAZYGIT_SOURCE = REPO_ROOT / "AppData/Local/lazygit"
REQUIRED_TOOLS = ("chezmoi", "git", "perl", "delta")


@unittest.skipUnless(
    os.name == "nt" and all(shutil.which(tool) for tool in REQUIRED_TOOLS),
    "requires Windows, chezmoi, git, perl, and delta",
)
class LazygitDiffTests(unittest.TestCase):
    def test_external_diff_receives_renderer_width_without_legacy_environment(self):
        rendered = subprocess.run(
            ["chezmoi", "--source", str(REPO_ROOT), "execute-template"],
            input=(LAZYGIT_SOURCE / "config.yml.tmpl").read_text(encoding="utf-8"),
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        command_match = re.search(r"(?m)^    - command: (.+)$", rendered)
        self.assertIsNotNone(command_match, rendered)
        command = command_match.group(1).strip()
        # Decode the single-quoted YAML scalar used for a quoted executable path.
        if command.startswith("'") and command.endswith("'"):
            command = command[1:-1].replace("''", "'")
        wrapper_match = re.match(r'"?([^"\r\n]+?[/\\]diff\.bat)"?(?:\s|$)', command)
        self.assertIsNotNone(wrapper_match, command)
        deployed_wrapper = wrapper_match.group(1)

        env = os.environ.copy()
        env.pop("LAZYGIT_COLUMNS", None)
        with tempfile.TemporaryDirectory(prefix="lazygit-diff-test-") as directory:
            fixture = Path(directory)
            wrapper = fixture / "diff.bat"
            shutil.copyfile(LAZYGIT_SOURCE / "diff.bat", wrapper)
            (fixture / "old.txt").write_text("before\n", encoding="utf-8")
            (fixture / "new.txt").write_text("after\n", encoding="utf-8")
            command = command.replace(deployed_wrapper, wrapper.as_posix())

            renderings = {}
            for width in (80, 132):
                with self.subTest(width=width):
                    result = subprocess.run(
                        [
                            "git", "--no-pager",
                            "-c", f"diff.external={command.replace('{{width}}', str(width))}",
                            "diff", "--no-index", "--ext-diff", "--", "old.txt", "new.txt",
                        ],
                        cwd=fixture,
                        env=env,
                        capture_output=True,
                        text=True,
                    )
                    renderings[width] = result.stdout
                    # git diff --no-index returns 1 when the files differ.
                    self.assertEqual(result.returncode, 1, result.stderr)
                    self.assertNotIn("Invalid value for width", result.stderr)
                    self.assertNotIn("external diff died", result.stderr)
                    self.assertIn("before", result.stdout)
                    self.assertIn("after", result.stdout)
                    self.assertIn("lazygit-edit://", result.stdout)
                    self.assertIn("{{width}}", command)

            self.assertNotEqual(renderings[80], renderings[132])


if __name__ == "__main__":
    unittest.main()
