#!/usr/bin/env python3
"""Claude Code statusline.

Starship passthrough (left) + session metrics (right), separated by a flex gap
that right-aligns the metrics group. Reads Claude Code's StatusJSON on stdin and
prints one line. Mirrors the prior ccstatusline config.

Cross-platform (Linux / macOS / Windows): stdlib only; the sole external program
is `starship`. Width is probed from the controlling terminal (`/dev/tty` or
`CONOUT$`) since stdout is a pipe here. Tune the right margin with
CC_STATUSLINE_RESERVE (default 4).
"""

import json
import math
import os
import re
import subprocess
import sys

# Keep glyphs/arrows intact on Windows consoles (cp1252 default).
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass


def fg(hex_color):
    """24-bit foreground SGR escape from a #RRGGBB hex string (stdlib only)."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"\033[38;2;{r};{g};{b}m"


# catppuccin-mocha (matches the old ccstatusline `hex:` colors)
TEAL = fg("#94E2D5")  # session cost
MAROON = fg("#EBA0AC")  # tokens + context bar
FLAMINGO = fg("#F2CDCD")  # model + effort
RESET = "\033[0m"

ANSI = re.compile(r"\x1b\[[0-9;]*m")


def jround(x):
    """Round half away from zero, like jq/C round (not Python's banker's)."""
    return math.floor(x + 0.5)


def num(x):
    """Minimal number formatting, like jq: 2.0 -> '2', 15.5 -> '15.5'."""
    return f"{x:g}"


def fmt_tokens(n):
    if n is None:
        return "?"
    if n >= 1_000_000:
        return f"{num(jround(n / 1_000_000 * 10) / 10)}M"
    if n >= 1_000:
        return f"{num(jround(n / 1_000 * 10) / 10)}k"
    return num(n)


def context_bar(pct, width=10):
    filled = jround(pct / 100 * width)
    cells = []
    for i in range(width):
        if i < filled:
            cells.append("" if i == 0 else "" if i == width - 1 else "")
        else:
            cells.append("" if i == 0 else "" if i == width - 1 else "")
    return "".join(cells)


def starship(module, cwd):
    try:
        out = subprocess.run(
            ["starship", "module", module],
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            encoding="utf-8",
            errors="replace",
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.strip()


def vlen(s):
    """Visible width: strip SGR escapes, count codepoints (all width-1 here)."""
    return len(ANSI.sub("", s))


def term_width(default=120):
    env = os.environ.get("COLUMNS")
    if env and env.isdigit():
        return int(env)
    for fd in (2, 1):  # stderr / stdout may still be a tty
        try:
            return os.get_terminal_size(fd).columns
        except OSError:
            pass
    for dev in ("/dev/tty", "CONOUT$"):  # the real terminal, not the pipe
        try:
            fd = os.open(dev, os.O_RDWR)
            try:
                return os.get_terminal_size(fd).columns
            finally:
                os.close(fd)
        except OSError:
            pass
    return default


def main():
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        data = {}

    cwd = (data.get("workspace") or {}).get("current_dir") or data.get("cwd") or "."
    if not os.path.isdir(cwd):
        cwd = None

    # left: starship modules, rendered in the session's cwd
    left = starship("directory", cwd)
    for module in ("git_branch", "git_status"):
        seg = starship(module, cwd)
        if seg:
            left += " " + seg

    # right: colored metrics straight from the payload
    cw = data.get("context_window") or {}
    cost = (data.get("cost") or {}).get("total_cost_usd", 0) or 0

    tin = cw.get("total_input_tokens")
    tout = cw.get("total_output_tokens")
    tokens = (
        ""
        if tin is None and tout is None
        else f"↑{fmt_tokens(tin)} ↓{fmt_tokens(tout)}"
    )

    pct = cw.get("used_percentage", 0) or 0
    size = cw.get("context_window_size")
    ctx = f"{context_bar(pct)} {num(pct)}%/{fmt_tokens(size)}"

    model_obj = data.get("model") or {}
    model = model_obj.get("display_name") or model_obj.get("id") or ""
    # Drop the " (1M context)" suffix the [1m] trick adds to display names.
    model = re.sub(r"\s*\(1M context\)$", "", model, flags=re.IGNORECASE)
    thinking = (data.get("thinking") or {}).get("enabled")
    effort = (data.get("effort") or {}).get("level", "") if thinking else ""

    pieces = [
        (TEAL, f"${cost:.2f}"),
        (MAROON, tokens),
        (MAROON, ctx),
        (FLAMINGO, model),
        (FLAMINGO, effort),
    ]
    right = " ".join(f"{color}{text}{RESET}" for color, text in pieces if text)

    # flex separator: gap = width - reserve - visible(left) - visible(right).
    # Claude Code keeps a small right margin even with padding=0, so reserve a
    # few columns or the right group wraps / runs off-screen. Tune by eye.
    reserve_env = os.environ.get("CC_STATUSLINE_RESERVE", "4")
    reserve = int(reserve_env) if reserve_env.lstrip("-").isdigit() else 4
    width = term_width() - reserve
    gap = max(1, width - vlen(left) - vlen(right))

    print(left + " " * gap + right)


if __name__ == "__main__":
    main()

