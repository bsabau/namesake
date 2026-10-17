@AGENTS.md

## Claude Code

You are the builder described under "Who does what". When a milestone's work is ready, stop and say so, so the diff can be reviewed before anything else is built on it.

Every change gets two reviews, run in parallel, before you report it done: Codex on GPT-6-Astra, and muse (`muse-spark-1.3-contributor`) through OpenCode's read-only Plan agent. When Codex is out of usage, muse reviews alone. Start both unattended, so neither waits for the author's input. Both follow "Review guidelines" above.
