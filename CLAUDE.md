@AGENTS.md

## Claude Code

You are the builder described under "Who does what". When a milestone's work is ready, stop and say so, so the diff can be reviewed before anything else is built on it.

## Reviews

Every change is reviewed before you report it done. Reviewers run in parallel and follow "Review guidelines" above.

**The reviewers:**

- **Codex** on `gpt-6.1-sol` (`codex exec -m gpt-6.1-sol -s read-only`), which uses less of the ChatGPT allowance than GPT-6-Astra.
- **Muse** (`opencode-go/muse-spark-1.3-contributor`) through OpenCode.
- **DeepSeek Flash** on the author's own key (`deepseek/deepseek-flash`) through OpenCode, for the reviews that need a third.

**How many, by kind of change:**

| Change | Reviewers |
|---|---|
| A small change: docs, wording, comments | muse |
| Any other change | Codex + muse |
| Milestone end, deploy, a new Qloo tool or agent tool, or text the judges read (README, Devpost, UI copy) | Codex + muse + DeepSeek Flash |
| Re-check after fixes | the reviewers who raised the findings, each continuing its own session |
| A third or later re-check, after two rounds that found only new P3s | Codex + muse only, even if another reviewer raised them |

**When one is out of usage:**

- Codex out (the ChatGPT limit covers the whole account): DeepSeek Flash on the author's own key (`deepseek/deepseek-flash`) takes its place. DeepSeek V4 Pro is not used: on 17 October it found nothing Flash or the others missed, slower and at about four times the cost.
- Muse or the Go plan out: a free model from `opencode models` (a name ending in `-free`; the `opencode/…-free` models don't use the Go plan).
- The demo's agent runs on the Go plan too, so reviews use the author's own key and free models before spending the Go plan. Use expensive models such as Grok only when the author asks: one Grok review used up the Go plan's window.

**How each review runs:**

- **First review of a change:** a fresh session per reviewer, free to read around the diff.
- **Re-check after fixes:** continue each reviewer's own session (`opencode --session <id>`, `codex exec resume`), with the fix diff in the prompt. It re-reads only the files the fix changed and confirms each of its earlier findings is closed.
- **Unattended:** OpenCode reviewers on the read-only Plan agent with `--auto`, Codex with `-s read-only`, so none waits for the author's input.
- **Every brief says:** open nothing outside the repository (no `.env`, `~/.qloo/`, `~/.local/share/opencode/`), print no environment variables, and work from the code and the synthetic fixtures.
- **Each review runs in its own named Herdr pane**, never one another session may be using.
