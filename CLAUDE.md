@AGENTS.md

## Claude Code

You are the builder described under "Who does what". When a milestone's work is ready, stop and say so, so the diff can be reviewed before anything else is built on it.

Work reaches `main` through a pull request, after its reviews and CI pass. Merging deploys the demo (`deploy/README.md`, "Automatic deploys"), so merge only what is ready to go live.

## Reviews

Every change is reviewed before you report it done. Reviewers run in parallel and follow "Review guidelines" above.

**The reviewers:**

- **Gemini Argon** (`opencode-go/gemini-4-argon`) through OpenCode. It replaced Codex on 11 November 2026: Codex stopped accepting `gpt-6.1-sol` on the author's ChatGPT account, and the author dropped it. Codex is not used for reviews.
- **Muse** (`opencode-go/muse-spark-1.3-contributor`) through OpenCode.
- **DeepSeek Flash** on the author's own key (`deepseek/deepseek-flash`) through OpenCode, for the reviews that need a third.

**How many, by kind of change:**

| Change | Reviewers |
|---|---|
| A small change: docs, wording, comments | muse |
| Any other change | Gemini Argon + muse |
| Milestone end, deploy, a new Qloo tool or agent tool, or text the judges read (README, Devpost, UI copy) | Gemini Argon + muse + DeepSeek Flash |
| Re-check after fixes | the reviewers who raised the findings, each continuing its own session |
| From the third re-check on, when the two re-checks before it found only new P3s | Gemini Argon + muse only; Flash takes part in the first two |

**When one is out of usage:**

- Gemini Argon out: DeepSeek Flash on the author's own key (`deepseek/deepseek-flash`) takes its place. DeepSeek V4 Pro is not used: on 17 October it found nothing Flash or the others missed, slower and at about four times the cost.
- Muse out: a free model from `opencode models` (a name ending in `-free`; the `opencode/…-free` models don't use the Go plan).
- The Go plan out: Gemini Argon and muse both run on it, so both are out. DeepSeek Flash takes Argon's place and a free model muse's (on 11 November, `opencode/glm-5.3-flash-free`). Not `opencode/longcat-2.5-free`: on 11 November it ran Docker commands on the author's machine during a review, against its brief.
- The demo's agent runs on the Go plan too, so reviews use the author's own key and free models before spending the Go plan. Use expensive models such as Grok only when the author asks: one Grok review used up the Go plan's window.

**How each review runs:**

- **First review of a change:** a fresh session per reviewer, free to read around the diff.
- **Re-check after fixes:** continue each reviewer's own session (`opencode run --session <id>`), with the fix diff in the prompt. It re-reads only the files the fix changed and confirms each of its earlier findings is closed.
- **Unattended:** every reviewer runs through OpenCode on the read-only Plan agent with `--auto` (`opencode run --standalone --model <model> --agent plan --auto`), so none waits for the author's input.
- **Every brief says:** open nothing outside the repository (no `.env`, `~/.qloo/`, `~/.local/share/opencode/`), print no environment variables, run no `docker` commands, and work from the code and the synthetic fixtures.
- **Each review runs in its own named Herdr pane**, never one another session may be using.
