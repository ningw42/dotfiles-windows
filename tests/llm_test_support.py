"""Render actual LLM templates using isolated sources, never personal secrets/state."""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CHEZMOI = shutil.which("chezmoi")
POWERSHELL = shutil.which("pwsh")


def prepare_source(source):
    """Copy only public rendering dependencies; the age store is deliberately absent."""
    shutil.copytree(REPO_ROOT / ".chezmoidata", source / ".chezmoidata", dirs_exist_ok=True)
    shutil.copytree(REPO_ROOT / ".chezmoitemplates/llm", source / ".chezmoitemplates/llm", dirs_exist_ok=True)
    shutil.copyfile(REPO_ROOT / "render_llm_config.py", source / "render_llm_config.py")


def render_template(path, *, home="C:/Users/fixture", text=None, extra_data=None):
    import json

    if not CHEZMOI:
        raise RuntimeError("chezmoi is required for template rendering")
    with tempfile.TemporaryDirectory(prefix="llm render ") as temporary:
        root = Path(temporary)
        source = root / "source"
        source.mkdir()
        prepare_source(source)
        config = root / "config.json"
        config.write_text("{}", encoding="utf-8")
        data = {
            "chezmoi": {"homeDir": home, "destDir": home, "os": "windows"},
            "llm_python": sys.executable,
            "llm_pwsh": POWERSHELL or "C:/Program Files/PowerShell/7/pwsh.exe",
            "colorscheme": "catppuccin-mocha",
            **(extra_data or {}),
        }
        result = subprocess.run(
            [CHEZMOI, "execute-template", "--source", str(source),
             "--config", str(config), "--destination", str(root / "destination"),
             "--persistent-state", str(root / "state.boltdb"), "--cache", str(root / "cache"),
             "--override-data", json.dumps(data), "--no-tty", "--no-pager", "--refresh-externals=never"],
            input=text if text is not None else (REPO_ROOT / path).read_text("utf-8"),
            capture_output=True, text=True, encoding="utf-8", timeout=30,
            cwd=root,
            env={key: value for key, value in os.environ.items() if not key.upper().startswith("CHEZMOI_")},
        )
        if result.returncode:
            raise AssertionError(f"Template rendering failed: {result.stderr}")
        return result.stdout
