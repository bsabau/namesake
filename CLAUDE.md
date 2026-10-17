@AGENTS.md

## Claude Code

You are the builder described under "Who does what". When a milestone's work is ready, stop and say so, so the diff can be reviewed before anything else is built on it.

Every change gets two reviews, run in parallel, before you report it done:

- **First reviewer:** Codex on GPT-6-Astra. When Codex is out of usage, OpenCode with DeepSeek (`opencode-go/deepseek-v4-pro`) takes its place.
- **Second reviewer:** muse (`opencode-go/muse-spark-1.3-contributor`) through OpenCode. When muse is out of usage, list the models with `opencode models` and use a free OpenCode Go one (a name ending in `-free` or `-contributor`).

OpenCode reviewers run on the read-only Plan agent. Start every reviewer unattended, so none waits for the author's input. All follow "Review guidelines" above.

- **First review of a change:** a fresh session per reviewer, free to read around the diff.
- **Re-check after fixes:** continue each reviewer's own session (`opencode --session <id>`, `codex exec resume`), with the fix diff in the prompt. It re-reads only the files the fix changed and confirms each of its earlier findings is closed.
- **Every brief says:** open nothing outside the repository (no `.env`, `~/.qloo/`, `~/.local/share/opencode/`), print no environment variables, and work from the code and the synthetic fixtures.
- **Each review runs in its own named Herdr pane**, never one another session may be using.
