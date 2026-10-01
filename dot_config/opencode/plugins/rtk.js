// V2 adapter for RTK's V1-only OpenCode hook. Keep rewrite policy in rtk.
import { execFile } from "node:child_process";
import { promisify } from "node:util";

const run = promisify(execFile);

export default {
  id: "rtk",
  async setup(ctx) {
    await ctx.tool.hook("execute.before", async (event) => {
      if (event.tool !== "shell") return;
      const input = event.input;
      if (!input || typeof input.command !== "string" || !input.command) return;

      try {
        const { stdout } = await run("rtk", ["rewrite", input.command], {
          timeout: 5000,
        }).catch((error) => {
          // Match the upstream hook's .nothrow(): RTK can emit a valid
          // rewrite with a nonzero exit code (the pinned build returns 3).
          if (typeof error.code === "number" && !error.killed && !error.signal) return error;
          throw error;
        });
        const rewritten = stdout.trim();
        if (rewritten) input.command = rewritten;
      } catch {
        // A missing rewrite or failed RTK invocation must not block the command.
      }
    });
  },
};
