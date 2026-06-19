#!/usr/bin/env python3
"""Unified statusline for LLM agent CLIs (claude-code, copilot-cli).

Starship passthrough (left) + session metrics (right), separated by a flex gap
that right-aligns the metrics group. A shared ``Statusline`` base owns the look
-- the left starship segments, colours, the context bar, the flex/margin
arithmetic, and payload capture -- while a thin per-agent subclass maps that
agent's stdin JSON schema into the component contract (cost, tokens, context,
model, effort). Every component is guaranteed present and rendered
unconditionally.

Invoked as ``statusline.py <claude|copilot>`` by a per-agent shell wrapper;
``statusline.py test`` runs the in-file unittest suite.

Cross-platform (Linux / macOS / Windows): stdlib only; the sole external program
is ``starship``. Width is probed from the controlling terminal (``/dev/tty`` or
``CONOUT$``) since stdout is a pipe here.
"""

import json
import math
import os
import pathlib
import re
import subprocess
import sys

# Keep glyphs/arrows intact on Windows consoles (cp1252 default).
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass


# --- colour primitives -------------------------------------------------------


def fg(hex_color):
    """24-bit foreground SGR escape from a #RRGGBB hex string (stdlib only)."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"\033[38;2;{r};{g};{b}m"


# catppuccin-mocha
TEAL = fg("#94E2D5")  # cost
MAROON = fg("#EBA0AC")  # tokens + context bar
FLAMINGO = fg("#F2CDCD")  # model + effort
RESET = "\033[0m"

ANSI = re.compile(r"\x1b\[[0-9;]*m")

# Nerd-font progress-bar cells (Private Use Area): (left-cap, middle, right-cap),
# empty vs filled. Written as \u escapes rather than the raw glyphs so the source
# survives any encoding/HTML round-trip -- an earlier copy mangled these into
# "&#60931;" entities, which then printed literally in the statusline.
CTX_EMPTY = ("\uee00", "\uee01", "\uee02")
CTX_FILLED = ("\uee03", "\uee04", "\uee05")


# --- number / text helpers ---------------------------------------------------


def jround(x):
    """Round half away from zero, like jq/C round (not Python's banker's)."""
    return math.floor(x + 0.5)


def num(x):
    """Minimal number formatting, like jq: 2.0 -> '2', 15.5 -> '15.5'."""
    return f"{x:g}"


def fmt_tokens(n):
    """Compact token count: 1234 -> '1.2k', 1_500_000 -> '1.5M'."""
    if n >= 1_000_000:
        return f"{num(jround(n / 1_000_000 * 10) / 10)}M"
    if n >= 1_000:
        return f"{num(jround(n / 1_000 * 10) / 10)}k"
    return num(n)


def context_bar(pct, width=10):
    """Render a ``width``-cell PUA progress bar filled to ``pct`` percent."""
    filled = jround(pct / 100 * width)
    cells = []
    for i in range(width):
        caps = CTX_FILLED if i < filled else CTX_EMPTY
        cells.append(caps[0] if i == 0 else caps[2] if i == width - 1 else caps[1])
    return "".join(cells)


def vlen(s):
    """Visible width: strip SGR escapes, count codepoints (all width-1 here)."""
    return len(ANSI.sub("", s))


def term_width(default=120):
    """Probe the controlling terminal's column count (stdout is a pipe here)."""
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


def starship(module, cwd):
    """Render a single starship module in ``cwd``; '' on any failure."""
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


def parse_payload(raw):
    """Parse stdin JSON to a dict; '' / invalid / non-dict -> {} (with a warning)."""
    if not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"statusline: invalid JSON payload: {exc}", file=sys.stderr)
        return {}
    return parsed if isinstance(parsed, dict) else {}


def padding_env(name, default):
    """Read a non-negative int env var, falling back to ``default``."""
    value = os.environ.get(name, str(default))
    return int(value) if value.isdigit() else default


# --- statusline base ---------------------------------------------------------


class Statusline:
    """Shared statusline renderer; subclasses implement the component contract.

    The look (left starship modules, colours, context bar, flex/margin math,
    payload capture) lives here. Subclasses override only the per-agent
    payload-schema accessors and the margin policy. ``input_tokens`` /
    ``output_tokens`` present the latest model CALL (see the accessor note
    below) and ``context_limit`` reads the shared ``context_window`` shape; an
    agent with a different shape may override them.
    """

    # Per-agent capture filename stem (set by subclasses).
    CAPTURE_STEM = "statusline"
    # Starship modules rendered after `directory`, in order.
    LEFT_MODULES = ("git_branch", "git_status", "git_metrics")
    # Rendered for `effort()` when thinking/effort is genuinely disabled. A real
    # level (including "none"/"minimal") is shown verbatim and never collapses
    # into this marker. Switch to "N/A" here if preferred.
    EFFORT_DISABLED = "off"

    def __init__(self, data, raw="", starship=starship):
        self.data = data if isinstance(data, dict) else {}
        self.raw = raw
        # Injection seam: tests pass a fake to keep render() from shelling out.
        self._starship = starship

    # -- shared left side -----------------------------------------------------

    def cwd(self):
        workspace = self.data.get("workspace")
        if not isinstance(workspace, dict):
            workspace = {}
        cwd = workspace.get("current_dir") or self.data.get("cwd") or "."
        return cwd if os.path.isdir(cwd) else None

    def render_left(self):
        cwd = self.cwd()
        left = self._starship("directory", cwd)
        for module in self.LEFT_MODULES:
            seg = self._starship(module, cwd)
            if seg:
                left += " " + seg
        return left

    # -- shared payload accessors --------------------------------------------
    #
    # ``input_tokens`` / ``output_tokens`` present the LATEST MODEL CALL -- the
    # only token unit every agent can report identically. claude-code exposes
    # only the last call (its ``total_*`` IS that call); copilot-cli's
    # ``total_*`` is a per-turn aggregate (sum of the turn's tool-loop calls)
    # and is overridden below to its ``last_call_*``; pi's extension reads its
    # last assistant message. Both numbers are cache-inclusive: the full prompt
    # input of that one call (uncached + cache read + cache write).

    def _cw(self):
        cw = self.data.get("context_window")
        return cw if isinstance(cw, dict) else {}

    def input_tokens(self):
        # claude-code: total_input_tokens already IS the latest call.
        return self._cw().get("total_input_tokens") or 0

    def output_tokens(self):
        return self._cw().get("total_output_tokens") or 0

    def context_limit(self):
        return self._cw().get("context_window_size") or 0

    # -- per-agent contract (subclasses implement) ----------------------------

    def cost_usd(self):
        raise NotImplementedError

    def context_pct(self):
        raise NotImplementedError

    def model(self):
        raise NotImplementedError

    def effort(self):
        raise NotImplementedError

    # -- shared right side (every segment rendered unconditionally) -----------

    def _cost_seg(self):
        return (TEAL, f"${self.cost_usd():.2f}")

    def _tokens_seg(self):
        text = f"↑{fmt_tokens(self.input_tokens())} ↓{fmt_tokens(self.output_tokens())}"
        return (MAROON, text)

    def _context_seg(self):
        pct = self.context_pct()
        text = f"{context_bar(pct)} {num(pct)}%/{fmt_tokens(self.context_limit())}"
        return (MAROON, text)

    def _model_seg(self):
        return (FLAMINGO, self.model())

    def _effort_seg(self):
        return (FLAMINGO, self.effort())

    def render_right(self):
        pieces = [
            self._cost_seg(),
            self._tokens_seg(),
            self._context_seg(),
            self._model_seg(),
            self._effort_seg(),
        ]
        return " ".join(f"{color}{text}{RESET}" for color, text in pieces)

    # -- margin policy (subclasses override the two hooks) --------------------

    def margins(self):
        """(left_pad, right_pad) columns reserved around the line."""
        return (0, 0)

    def decorate(self, line):
        """Wrap the composed line (e.g. invisible RESET edge-guards)."""
        return line

    def compose_line(self, left, right):
        left_pad, right_pad = self.margins()
        width = term_width()
        gap = max(1, width - left_pad - right_pad - vlen(left) - vlen(right))
        line = " " * left_pad + left + " " * gap + right + " " * right_pad
        return self.decorate(line)

    def render(self):
        return self.compose_line(self.render_left(), self.render_right())

    # -- shared payload capture ----------------------------------------------

    @staticmethod
    def capture_enabled():
        # Opt-in: capture is OFF unless STATUSLINE_CAPTURE is explicitly truthy.
        value = os.environ.get("STATUSLINE_CAPTURE", "0").strip().lower()
        return value in {"1", "true", "yes", "on"}

    @staticmethod
    def capture_dir():
        configured = os.environ.get("STATUSLINE_CAPTURE_DIR")
        if configured:
            return pathlib.Path(configured).expanduser()
        return pathlib.Path.home() / ".config" / "statusline" / "captures"

    def capture(self):
        """Best-effort: dump raw stdin + pretty JSON for later schema inspection.

        The Copilot payload schema in particular is undocumented; capturing the
        latest payload per agent makes future schema checks easy. Opt-in (off by
        default; enable with STATUSLINE_CAPTURE=1). Never fatal -- the statusline
        must still print if the capture write fails.
        """
        try:
            d = self.capture_dir()
            d.mkdir(parents=True, exist_ok=True)
            (d / f"{self.CAPTURE_STEM}.raw.json").write_text(self.raw, encoding="utf-8")
            (d / f"{self.CAPTURE_STEM}.json").write_text(
                json.dumps(self.data, indent=2, ensure_ascii=False, sort_keys=True)
                + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            print(f"statusline: failed to capture payload: {exc}", file=sys.stderr)


# --- claude-code -------------------------------------------------------------


class ClaudeStatusline(Statusline):
    """Claude Code StatusJSON: structured cost/context/thinking/effort objects."""

    CAPTURE_STEM = "claude-code"
    # The "[1m]" model trick appends " (1M context)" to display names; drop it.
    MODEL_1M = re.compile(r"\s*\(1M context\)$", re.IGNORECASE)

    def cost_usd(self):
        cost = self.data.get("cost")
        if not isinstance(cost, dict):
            return 0.0
        return cost.get("total_cost_usd") or 0.0

    def context_pct(self):
        return self._cw().get("used_percentage") or 0

    def model(self):
        model = self.data.get("model")
        if not isinstance(model, dict):
            return ""
        name = model.get("display_name") or model.get("id") or ""
        return self.MODEL_1M.sub("", name)

    def effort(self):
        thinking = self.data.get("thinking")
        enabled = thinking.get("enabled") if isinstance(thinking, dict) else None
        if not enabled:
            return self.EFFORT_DISABLED
        effort = self.data.get("effort")
        level = effort.get("level") if isinstance(effort, dict) else None
        return level or self.EFFORT_DISABLED

    def margins(self):
        # Claude Code keeps a small right margin even at padding=0, so reserve a
        # few columns or the right group wraps / runs off-screen. Tune by eye.
        raw = os.environ.get("CC_STATUSLINE_RESERVE", "4")
        reserve = int(raw) if raw.lstrip("-").isdigit() else 4
        return (0, reserve)


# --- copilot-cli -------------------------------------------------------------


class CopilotStatusline(Statusline):
    """GitHub Copilot CLI: cost in nano-AIU; model/effort packed in display_name."""

    CAPTURE_STEM = "copilot-cli"
    # Copilot packs "<model> · <effort> · <context>" into one display_name string.
    SEGMENT_SEP = re.compile(r"\s*[·|]\s*")
    # "none" is recognized so a real none/minimal level renders verbatim rather
    # than collapsing into EFFORT_DISABLED.
    EFFORT_LEVELS = {"minimal", "low", "medium", "high", "xhigh", "max", "none"}

    def _display_segments(self):
        model = self.data.get("model")
        name = model.get("display_name") if isinstance(model, dict) else ""
        name = name or ""
        return [seg.strip() for seg in self.SEGMENT_SEP.split(name) if seg.strip()]

    def cost_usd(self):
        used = self.data.get("ai_used")
        nano = used.get("total_nano_aiu") if isinstance(used, dict) else None
        if nano is None:
            return 0.0
        # nano AIU -> AIC (/1e9), AIC -> USD (/100).
        return nano / 1_000_000_000 / 100

    def input_tokens(self):
        # Unify on the per-CALL figure. Copilot's total_input_tokens is a
        # per-turn aggregate (sum of the turn's tool-loop calls); last_call_* is
        # the single most recent call (cache-inclusive), matching claude-code's
        # total_input_tokens so both statuslines show the same unit.
        return self._cw().get("last_call_input_tokens") or 0

    def output_tokens(self):
        return self._cw().get("last_call_output_tokens") or 0

    def context_pct(self):
        return self._cw().get("current_context_used_percentage") or 0

    def context_limit(self):
        # Copilot leaves context_window_size null and reports the effective
        # ("displayed") limit in displayed_context_limit instead.
        cw = self._cw()
        return cw.get("displayed_context_limit") or cw.get("context_window_size") or 0

    def model(self):
        segments = [
            s for s in self._display_segments() if s.lower() not in self.EFFORT_LEVELS
        ]
        if segments:
            return self.format_model_label(segments[0])
        model = self.data.get("model")
        model_id = model.get("id") if isinstance(model, dict) else ""
        return self.format_model_label(model_id) if model_id else ""

    def effort(self):
        for segment in self._display_segments():
            if segment.lower() in self.EFFORT_LEVELS:
                return segment.lower()
        return self.EFFORT_DISABLED

    @staticmethod
    def format_model_label(value):
        """Turn a Copilot model id into a display label.

        Copilot reports the dotted id form (e.g. `claude-opus-4.8`, `gpt-5.5`).
        Split on -/_; drop a leading `claude` vendor prefix; keep version tokens
        (anything with a digit) verbatim, upcase `gpt`, and title-case the rest.
        GPT labels keep their hyphens (`GPT-5.5`); others are space-joined
        (`Opus 4.8`).
        """
        tokens = [tok for tok in re.split(r"[-_]+", value.strip()) if tok]
        if tokens and tokens[0].lower() == "claude":
            tokens = tokens[1:]
        is_gpt = bool(tokens) and tokens[0].lower() == "gpt"
        words = []
        for tok in tokens:
            if tok.lower() == "gpt":
                words.append("GPT")
            elif any(ch.isdigit() for ch in tok):
                words.append(tok)
            else:
                words.append(tok[:1].upper() + tok[1:])
        return ("-" if is_gpt else " ").join(words) if words else value.strip()

    def margins(self):
        return (
            padding_env("COPILOT_STATUSLINE_LEFT_PADDING", 1),
            padding_env("COPILOT_STATUSLINE_RIGHT_PADDING", 1),
        )

    def decorate(self, line):
        left_pad, right_pad = self.margins()
        # Copilot trims command stdout before rendering; invisible SGR resets keep
        # edge padding from becoming trim-boundary whitespace.
        if left_pad > 0:
            line = RESET + line
        if right_pad > 0:
            line = line + RESET
        return line


# --- dispatch ----------------------------------------------------------------


DISPATCH = {"claude": ClaudeStatusline, "copilot": CopilotStatusline}


def main(argv=None):
    argv = sys.argv if argv is None else argv
    flavor = argv[1] if len(argv) > 1 else ""
    if flavor == "test":
        return _run_tests(argv[2:])
    cls = DISPATCH.get(flavor)
    if cls is None:
        usage = "|".join(DISPATCH)
        print(
            f"statusline: usage: statusline.py {{{usage}|test}} (got {flavor!r})",
            file=sys.stderr,
        )
        return 2

    raw = sys.stdin.read()
    data = parse_payload(raw)
    sl = cls(data, raw)
    if sl.capture_enabled():
        sl.capture()
    print(sl.render())
    return 0


# --- self-tests (loaded only via `statusline.py test`) -----------------------


def _run_tests(argv):
    """Run the in-file unittest suite. Kept lazy so a normal render never imports
    unittest or builds the fixtures."""
    import unittest

    def fake_starship(mapping=None):
        mapping = mapping or {}
        return lambda module, cwd: mapping.get(module, "")

    claude_payload = {
        "workspace": {"current_dir": "/nonexistent-statusline-test-dir"},
        "cost": {"total_cost_usd": 1.234},
        "context_window": {
            "total_input_tokens": 1500,
            "total_output_tokens": 2500,
            "used_percentage": 18,
            "context_window_size": 200000,
        },
        "model": {"display_name": "Opus 4.8 (1M context)", "id": "claude-opus-4-8"},
        "thinking": {"enabled": True},
        "effort": {"level": "xhigh"},
    }
    # 123_000_000_000 nano-AIU -> 123 AIC -> $1.23.
    copilot_payload = {
        "workspace": {"current_dir": "/nonexistent-statusline-test-dir"},
        "ai_used": {"total_nano_aiu": 123_000_000_000},
        "context_window": {
            # total_* is the per-turn aggregate -- deliberately different from
            # last_call_* so the test proves the statusline shows the per-call
            # value, not the turn total.
            "total_input_tokens": 9000,
            "total_output_tokens": 8000,
            "last_call_input_tokens": 1500,
            "last_call_output_tokens": 2500,
            "current_context_used_percentage": 18,
            "context_window_size": None,
            "displayed_context_limit": 200000,
        },
        "model": {
            "display_name": "claude-opus-4.8 · xhigh · 200k",
            "id": "claude-opus-4.8",
        },
    }

    class PrimitiveTests(unittest.TestCase):
        def test_fmt_tokens(self):
            self.assertEqual(fmt_tokens(0), "0")
            self.assertEqual(fmt_tokens(999), "999")
            self.assertEqual(fmt_tokens(1000), "1k")
            self.assertEqual(fmt_tokens(1234), "1.2k")
            self.assertEqual(fmt_tokens(1_500_000), "1.5M")

        def test_num(self):
            self.assertEqual(num(2.0), "2")
            self.assertEqual(num(15.5), "15.5")

        def test_jround(self):
            self.assertEqual(jround(0.5), 1)
            self.assertEqual(jround(1.4), 1)
            self.assertEqual(jround(2.5), 3)

        def test_vlen_strips_sgr(self):
            self.assertEqual(vlen(f"{TEAL}abc{RESET}"), 3)

        def test_context_bar(self):
            self.assertEqual(len(context_bar(0)), 10)
            self.assertTrue(all(c in CTX_EMPTY for c in context_bar(0)))
            self.assertTrue(all(c in CTX_FILLED for c in context_bar(100)))

        def test_format_model_label(self):
            f = CopilotStatusline.format_model_label
            self.assertEqual(f("claude-opus-4.8"), "Opus 4.8")
            self.assertEqual(f("gpt-5.5"), "GPT-5.5")

    class ClaudeAccessorTests(unittest.TestCase):
        def setUp(self):
            self.sl = ClaudeStatusline(claude_payload)

        def test_cost(self):
            self.assertEqual(self.sl._cost_seg()[1], "$1.23")

        def test_tokens(self):
            self.assertEqual(self.sl.input_tokens(), 1500)
            self.assertEqual(self.sl.output_tokens(), 2500)

        def test_context(self):
            self.assertEqual(self.sl.context_pct(), 18)
            self.assertEqual(self.sl.context_limit(), 200000)

        def test_model_strips_1m(self):
            self.assertEqual(self.sl.model(), "Opus 4.8")

        def test_effort_level(self):
            self.assertEqual(self.sl.effort(), "xhigh")

        def test_effort_disabled_when_thinking_off(self):
            sl = ClaudeStatusline({**claude_payload, "thinking": {"enabled": False}})
            self.assertEqual(sl.effort(), "off")

        def test_effort_none_not_collapsed(self):
            sl = ClaudeStatusline(
                {
                    **claude_payload,
                    "thinking": {"enabled": True},
                    "effort": {"level": "none"},
                }
            )
            self.assertEqual(sl.effort(), "none")

    class CopilotAccessorTests(unittest.TestCase):
        def setUp(self):
            self.sl = CopilotStatusline(copilot_payload)

        def test_cost_nano(self):
            self.assertEqual(self.sl._cost_seg()[1], "$1.23")

        def test_tokens(self):
            # Per-call: reads last_call_*, NOT the per-turn total_* (9000/8000).
            self.assertEqual(self.sl.input_tokens(), 1500)
            self.assertEqual(self.sl.output_tokens(), 2500)

        def test_context_pct_key(self):
            self.assertEqual(self.sl.context_pct(), 18)
            # context_window_size is null for Copilot; limit comes from displayed_context_limit.
            self.assertEqual(self.sl.context_limit(), 200000)

        def test_context_limit_falls_back_to_window_size(self):
            payload = {
                **copilot_payload,
                "context_window": {
                    "current_context_used_percentage": 18,
                    "context_window_size": 128000,
                },
            }
            self.assertEqual(CopilotStatusline(payload).context_limit(), 128000)

        def test_model_from_packed_display_name(self):
            self.assertEqual(self.sl.model(), "Opus 4.8")

        def test_effort_from_packed_display_name(self):
            self.assertEqual(self.sl.effort(), "xhigh")

        def test_effort_none_recognized(self):
            payload = {
                **copilot_payload,
                "model": {"display_name": "claude-opus-4.8 · none · 200k", "id": "x"},
            }
            self.assertEqual(CopilotStatusline(payload).effort(), "none")

        def test_effort_disabled_when_absent(self):
            payload = {
                **copilot_payload,
                "model": {"display_name": "claude-opus-4.8", "id": "x"},
            }
            self.assertEqual(CopilotStatusline(payload).effort(), "off")

    class ContractTests(unittest.TestCase):
        def test_empty_payload_renders_all_segments(self):
            for cls in (ClaudeStatusline, CopilotStatusline):
                sl = cls({}, starship=fake_starship())
                right = sl.render_right()
                self.assertIn("$0.00", right)
                self.assertIn("↑0 ↓0", right)
                self.assertIn("0%/0", right)
                # five colour-reset-terminated segments, none dropped
                self.assertEqual(right.count(RESET), 5)

    class RenderTests(unittest.TestCase):
        def setUp(self):
            self._prev_columns = os.environ.get("COLUMNS")
            os.environ["COLUMNS"] = "120"

        def tearDown(self):
            if self._prev_columns is None:
                os.environ.pop("COLUMNS", None)
            else:
                os.environ["COLUMNS"] = self._prev_columns

        def test_left_includes_git_metrics(self):
            fake = fake_starship(
                {"directory": "~/proj", "git_branch": "main", "git_metrics": "+1"}
            )
            left = ClaudeStatusline(claude_payload, starship=fake).render_left()
            self.assertIn("~/proj", left)
            self.assertIn("main", left)
            self.assertIn("+1", left)

        def test_full_render(self):
            fake = fake_starship({"directory": "~/proj"})
            line = ClaudeStatusline(claude_payload, starship=fake).render()
            self.assertIn("~/proj", line)
            self.assertIn("Opus 4.8", line)
            self.assertIn("$1.23", line)

        def test_copilot_edge_guards(self):
            fake = fake_starship({"directory": "x"})
            line = CopilotStatusline(copilot_payload, starship=fake).render()
            self.assertTrue(line.startswith(RESET))
            self.assertTrue(line.endswith(RESET))

    class CaptureTests(unittest.TestCase):
        def setUp(self):
            self._prev = os.environ.get("STATUSLINE_CAPTURE")
            os.environ.pop("STATUSLINE_CAPTURE", None)

        def tearDown(self):
            if self._prev is None:
                os.environ.pop("STATUSLINE_CAPTURE", None)
            else:
                os.environ["STATUSLINE_CAPTURE"] = self._prev

        def test_disabled_by_default(self):
            self.assertFalse(Statusline.capture_enabled())

        def test_enabled_when_truthy(self):
            for value in ("1", "true", "yes", "on", "ON", "True"):
                os.environ["STATUSLINE_CAPTURE"] = value
                self.assertTrue(Statusline.capture_enabled())

        def test_disabled_when_falsy(self):
            for value in ("0", "false", "no", "off", ""):
                os.environ["STATUSLINE_CAPTURE"] = value
                self.assertFalse(Statusline.capture_enabled())

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for case in (
        PrimitiveTests,
        ClaudeAccessorTests,
        CopilotAccessorTests,
        ContractTests,
        RenderTests,
        CaptureTests,
    ):
        suite.addTests(loader.loadTestsFromTestCase(case))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
