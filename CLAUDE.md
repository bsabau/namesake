@AGENTS.md

## Claude Code

You are the builder described under "Who does what". When a milestone's work is ready, stop and say so, so the diff can be reviewed before anything else is built on it.

Every change gets two reviews, run in parallel, before you report it done:

- **First reviewer:** Codex on `gpt-6.1-sol` (`codex exec -m gpt-6.1-sol -s read-only`), which uses less of the ChatGPT allowance than GPT-6-Astra. When Codex is out of usage, OpenCode with DeepSeek takes its place, on the author's own key (`deepseek/deepseek-flash` or `deepseek/deepseek-v4-pro`) first, so reviews don't use up the Go plan the demo runs on.
- **Second reviewer:** muse (`opencode-go/muse-spark-1.3-contributor`) through OpenCode. When muse or the Go plan is out of usage, list the models with `opencode models` and use a free one (a name ending in `-free` or `-contributor`; the `opencode/…-free` models don't use the Go plan). Avoid expensive models such as Grok unless the author asks: one Grok review used up the Go plan's window.

OpenCode reviewers run on the read-only Plan agent. Start every reviewer unattended, so none waits for the author's input. All follow "Review guidelines" above.

- **First review of a change:** a fresh session per reviewer, free to read around the diff.
- **Re-check after fixes:** continue each reviewer's own session (`opencode --session <id>`, `codex exec resume`), with the fix diff in the prompt. It re-reads only the files the fix changed and confirms each of its earlier findings is closed.
- **Every brief says:** open nothing outside the repository (no `.env`, `~/.qloo/`, `~/.local/share/opencode/`), print no environment variables, and work from the code and the synthetic fixtures.
- **Each review runs in its own named Herdr pane**, never one another session may be using.
