# Namesake

Shared instructions for every coding agent that works in this repository. `CLAUDE.md` imports this file, so make changes here.

Working name; it appears in the package name and the page title only, so it is cheap to change.

Namesake is a web app for animal-shelter volunteers. A volunteer picks an animal and the shelter's location, and an agent produces an adoption listing tuned to what people in that area love: a name, a short bio, and a small promotion plan, each backed by taste data from Qloo. The same listing is also shown in a generic version so the difference is visible.

This is an entry for the Qloo Agentic Hackathon on Devpost. The author is one developer, a senior data engineer who works in Python and is new to front-end work.

## What the judges need to see

These shape most decisions below, so keep them in mind when making trade-offs.

- **Deadline:** 30 October 2026, 23:45 US Eastern. Judging runs 2 to 16 November, and the demo must stay live throughout.
- **Required:** a publicly hosted working demo, a public repo with an open-source licence file visible on the repo page, and a text description.
- **Theme check (pass or fail):** the project must be agentic. A fixed pipeline with a model only writing the final text would be a risk, so the model has to choose at least some of the Qloo calls.
- **Scoring, four equal parts:** depth and skill of the Qloo integration; a complete product experience, not a proof of concept; credible impact for a real user; a creative, non-obvious use of Qloo.
- **Key test from the brief:** if the app would work the same without Qloo, it is the wrong app. The generic-versus-local comparison exists to answer this.
- Judges may not run the app at all and may judge from the description and screenshots, so the result screen has to be legible in a single screenshot.

## Rules that always apply

- **Secrets:** keys live in environment variables or the harness's private config. Never write a key into the repo, a log line, a test fixture, a browser bundle, or model prompts. `.env` is git-ignored; `.env.example` holds names only.
- **No personal data to Qloo:** send cultural entities and places, never names, emails or identifiers. The app has no accounts.
- **How results are worded:** Qloo returns aggregate affinities. Write "people in this area tend to like X", never a claim or probability about an individual. Do not infer sensitive traits (politics, health, finances) from taste data.
- **Provenance:** in the UI, keep what Qloo returned visibly separate from the app's interpretation of it.
- **Ambiguity:** when Qloo cannot resolve a name it returns candidates. Show them or pick with a stated reason; do not force a fuzzy match through.
- **Quota:** the hackathon key's quota is not published, so treat live calls as scarce. Tests never call Qloo or a model; they run on recorded fixtures. Cache every live Qloo result.
- **Supported Qloo surfaces:** only the harness commands `qloo mcp`, `qloo exec` and `qloo api`. Do not call the HTTP API directly from Python.

## Who does what

Several coding agents work in this repo, and all of them read this file. Each has one job. Stay in yours unless the author says otherwise.

| Agent | Job |
| --- | --- |
| Claude Code | Builds. Owns the milestone in progress: the design, the implementation, and the tests that go with it. |
| Codex | Reviews. Reads a diff and reports what is wrong with it. It does not change files. |
| OpenCode | Small, bounded tasks handed over by name: tests written against existing fixtures, typed models for a recorded response, docstrings, README sections. |

- One agent writes at a time. If the working tree holds changes you did not make, leave them alone and say so.
- Only the builder makes live Qloo or model calls, and only where a milestone calls for them. The reviewer, and anyone doing a bounded task, works from the code and the recorded fixtures.
- The milestone rule below applies to every agent: nobody starts the next milestone on their own.

## Review guidelines

For whoever is reviewing a diff. Report findings only: do not edit files, do not run `qloo`, and do not call a model.

Check these first. Each one can sink the entry or leak something.

- A key or token anywhere it should not be: source, a log line, a test fixture, a template or static file, a model prompt.
- Anything sent to Qloo other than cultural entities and places.
- A test that would reach Qloo or a model instead of a recorded fixture, or a live Qloo result that is not cached.
- A direct HTTP call to the Qloo API from Python, in place of the harness commands.
- Wording that makes a claim about an individual, or infers a sensitive trait, from taste data.
- UI that blends what Qloo returned with the app's reading of it.
- An envelope status left unhandled (`ok`, `empty`, `needs_input`, `partial`, `degraded`, `error`), a retry when `retryable` is false, or a `needs_input` forced through as a match.
- A model name, endpoint or key written into code instead of read from the four `AGENT_*` variables.
- Work that belongs to a later milestone than the current one.

Then ordinary correctness: logic errors, unhandled failures of the `qloo` subprocess, new behaviour with no test.

Leave style to ruff. For each finding give the file and line, what goes wrong, and how serious it is. If nothing is wrong, say so in one line.

To run a review from the repo root:

```sh
codex review --uncommitted     # staged, unstaged and untracked changes
codex review --base main       # a branch against main
```

These flags cannot be combined with a custom prompt, which is why the guidelines live in this file.

## Stack

| Layer | Choice |
| --- | --- |
| Language and tooling | Python 3.12, uv, ruff, pytest |
| Web | FastAPI, Jinja templates, HTMX, server-sent events for the agent's live log |
| Map | Leaflet with OpenStreetMap tiles (keep the attribution) |
| Agent | PydanticAI 2.x with structured output |
| Qloo, agent-chosen calls | `qloo mcp` attached over stdio |
| Qloo, fixed calls | `qloo exec` as a subprocess returning JSON |
| Cache | SQLite |
| Packaging | One Docker image containing Python, Node 22.19+ and the harness |
| Licence | MIT |

One container serves everything. There is no separate front-end build step, which is deliberate: the author is not a front-end developer.

## The Qloo harness: what is known

The harness is the npm package `@qloo/qloo-harness` (0.1.26 on the dev machine; pin that version in the image). It needs Node 22.19 or newer.

**Configuration.** A hackathon key works only against `https://hackathon.api.qloo.com`; the harness defaults to production and rejects the key with a 401 unless the base URL is set and trusted. On the dev machine this is already stored in `~/.qloo/config`, so nothing is needed locally. In the container, set all three:

```
QLOO_API_KEY=...
QLOO_BASE_URL=https://hackathon.api.qloo.com
QLOO_TRUSTED_BASE_URL=https://hackathon.api.qloo.com
```

A child process only sees these if the parent passes its environment through.

**Workflows.** Confirmed working from the command line: `find_tags`, `where_popular`. The MCP server exposes these tools: `qloo_capabilities`, `qloo_find_tags`, `qloo_describe`, `qloo_recommend`, `qloo_rank`, `qloo_where_popular`, `qloo_compare_audiences`, `qloo_audience_demographics`, `qloo_entity_tags`, `qloo_trends`. Read exact input schemas from the harness (`qloo exec --help`, or the `qloo_capabilities` tool, which costs no quota) instead of guessing field names. Inputs are validated before Qloo is called, so a wrong field costs nothing.

**A call that is known to work:**

```sh
qloo exec where_popular --input '{"entity":"F6013EAC-8F32-4080-B1ED-2BFABB9C706E","within":"New York City"}'
```

That ID is the TV show Bluey. Passing the name "Bluey" instead returns `needs_input`, because an author has the same name.

**Result envelope.** Every workflow returns one JSON object:

- `status`: `ok`, `empty`, `needs_input`, `partial`, `degraded` or `error`.
- `results`: a list. For `where_popular`, each item is a map cell: `location.latitude`, `location.longitude`, `location.geohash` (six characters, roughly a kilometre across) and `query.affinity`, `query.popularity`.
- `resolution.issues[].candidates[]` when status is `needs_input`: each has `id`, `name`, `type`, `popularity`, `description`.
- `provenance.requests[]`: the underlying API request. The heatmap is `GET /v2/insights` with `filter.type=urn:heatmap`.
- `error.code`, `error.retryable`, `error.recovery` when status is `error`. Retry only when `retryable` is true.
- `execution.duration_ms`: the heatmap call took about 2.5 seconds, which is why results are cached.

`qloo exec` exit codes: 2 for bad input, 4 for missing credentials, 1 for other failures.

**Deployment constraint.** `qloo mcp` is a local stdio process with no hosted URL. Qloo's kit says to run on a VM or container and that serverless functions are unsupported, so the app needs a long-lived process.

## Open questions about the data

These are not yet answered and they decide how the agent works. Milestone 1 exists to answer them.

1. **Area to tastes:** can a location be the signal on its own ("what do people here love?"), or does every query need an entity to start from? If it needs an entity, the agent must work by proposing candidates and testing each one.
2. **Does location change a ranking?** Rank the same shortlist for two different places and compare.
3. **Is the heatmap about taste or foot traffic?** For Bluey in New York City, the ten strongest cells were mostly Midtown, Central Park and Lower Manhattan, with affinity bunched between 0.97 and 1.0. Compare with a very different entity. If the maps look alike, the top cells mostly show busy places, and the useful reading is the score near the shelter instead.
4. **How small an area is accepted?** Try a neighbourhood such as "Park Slope, Brooklyn".

The demo uses New York City because US coverage is likely to be deepest.

## Model configuration

The agent's model is configuration, never code. Four variables:

```
AGENT_BASE_URL=https://opencode.ai/zen/go/v1
AGENT_API_KEY=...
AGENT_MODEL=muse-spark-1.3-contributor
AGENT_API=responses        # or "chat"
```

Development uses a free model through OpenCode Go; the judged demo will switch to a paid one by changing these values. Some models speak the OpenAI "responses" format and others "chat completions", hence `AGENT_API`.

PydanticAI's names changed in 2.x, so use these and not the older `MCPServerStdio` or `mcp_servers=`. This construction is checked against 2.53:

```python
import os
from pydantic_ai import Agent
from pydantic_ai.mcp import MCPToolset, StdioTransport
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIResponsesModel
from pydantic_ai.providers.openai import OpenAIProvider

provider = OpenAIProvider(base_url=os.environ["AGENT_BASE_URL"],
                          api_key=os.environ["AGENT_API_KEY"])
model_cls = (OpenAIResponsesModel if os.environ.get("AGENT_API", "chat") == "responses"
             else OpenAIChatModel)
model = model_cls(os.environ["AGENT_MODEL"], provider=provider)
qloo = MCPToolset(StdioTransport(command="qloo", args=["mcp"], env=dict(os.environ)))
agent = Agent(model, toolsets=[qloo], instructions="...")
```

Install with `uv add "pydantic-ai-slim[openai,mcp]"`.

## Demo data

Twelve fictional animals plus one group photo of a litter, all AI-generated. The source of truth is `data/animals/animals.json`; the photos sit beside it as `<id>.jpg`.

- Fields per animal: `id`, `species`, `group`, `sex`, `age`, `look`, `temperament`, `facts` (a list), `image`. The four kittens share `litter: "litter-a"`. The `litter-group` entry has `members` and no profile.
- Animals have no names on purpose. Naming them is the app's job.
- The photos and JSON were produced by a separate project outside this repo (`../image_generation`, which also holds `ANIMALS.md` with each animal's role in the demo). It is not part of this app; do not import from it or run it.
- The photos are about 650 KB each. Produce web-sized copies (around 800 pixels, under 150 KB) for the app to serve.

The shelter is fictional too. Do not use real shelter names, logos or photos.

## How the product works

**Screens**

1. **Start:** a grid of the animals, a choice of three preset locations, a tone setting, and a "try an example" button that loads a precomputed result instantly.
2. **Working:** a live log of the agent's steps, streamed as they happen: candidates proposed, each one checked against Qloo, which were kept and which dropped.
3. **Result:** the listing with a toggle between the generic and the locally tuned version; a map of local affinity; a short promotion plan.
4. **Why:** for each choice, the Qloo result behind it, separate from the app's reading of it.
5. **Refine:** one text line for follow-ups such as "less childish". When Qloo returns `needs_input`, show the candidates here as buttons.

**Preset locations.** The start screen offers three: two New York City neighbourhoods and one other US city. Two neighbourhoods in the same city show that results change at fine detail; the third shows it is not only a New York effect. Do not choose them by reputation. Milestone 1 tests the candidates and keeps the three that Qloo resolves cleanly and whose results differ most. Candidates: Park Slope, Bushwick, Astoria, Harlem and the Upper West Side in New York; Tampa, Austin and Portland elsewhere. Each preset is a place name plus a centre point for the fictional shelter, never a real shelter or a street address. The presets live in `data/locations.json`: `query` is the text sent to Qloo as the location signal, `city` is the wider area for the heatmap. The current three (Park Slope, Astoria, Austin) are provisional until Milestone 1 confirms them; Astoria is untested.

**The agent's job.** Given an animal's profile and a location: propose cultural references that fit the animal's look and character; resolve each to a Qloo entity; measure how strong each is locally; keep the strong ones and try again once if too few survive; then write the name, bio and promotion plan from the survivors. The steps where the model reads results and decides what to try next are what make this an agent. Calls that are always made the same way, such as the heatmap for the map, go through `qloo exec` in plain code.

**Output** is a typed object, not free text: the name, the generic bio, the local bio, the cultural hooks (each with its Qloo entity ID, type and the evidence for it), the promotion plan, the map cells, and the step log.

The litter is the showcase: four kittens named as a set after something the neighbourhood loves, and the same litter listed differently for a second neighbourhood.

## Layout

```
app/
  main.py            FastAPI app and routes
  config.py          settings from the environment
  agent/             the PydanticAI agent, instructions, output types
  qloo/              exec wrapper, envelope types, cache, geohash helpers
  templates/         Jinja templates and HTMX partials
  static/            CSS, small JS for the map, web-sized animal photos
data/animals/        animals.json and original photos
data/locations.json  the preset shelter locations
docs/                qloo-findings.md
scripts/             probe scripts
tests/
  fixtures/qloo/     recorded Qloo responses
Dockerfile
.env.example
LICENSE
README.md
```

## Commands

```sh
uv sync
uv run uvicorn app.main:app --reload
uv run python scripts/make_web_photos.py      # web-sized photos into app/static/animals
uv run pytest
uv run pytest tests/test_app.py::test_health   # one test (-k <expr> also works)
uv run ruff check . && uv run ruff format --check .
docker build -t namesake .
```

## Milestones

Work on one milestone at a time, in order, and stop at the end of each for review. Current milestone: **0**.

**0. Scaffold.** The photos and `animals.json` are already in `data/animals/`. The repo root is not a git repository yet. Add `.DS_Store` to `.gitignore`. Create the rest of the layout, the uv project, ruff and pytest configuration, `.gitignore`, `.env.example`, the MIT licence and a README skeleton. Add a settings module, a health route, and a start page that renders the animal grid from `animals.json` with web-sized photos. Write the Dockerfile with Python, Node and the pinned harness. Done when the tests pass, the page shows all twelve animals, and the image builds.

**1. Qloo layer and findings.** Write a typed wrapper around `qloo exec` that parses the envelope, handles every status, caches in SQLite, and can replay from fixtures. Write probe scripts that answer the four open questions with as few live calls as possible, save the responses as fixtures, and record the answers in `docs/qloo-findings.md`. Use the same probes to choose the three preset locations. Then propose how the agent should work given what was found, and wait for a decision.

**2. Thin end-to-end slice.** No agent yet: choose an animal and a location, run one fixed Qloo lookup, draw the cells on the map, and render a templated listing. This proves the whole path from form to result.

**3. The agent.** Add the PydanticAI agent with the Qloo tools, structured output, and the live step log over server-sent events.

**4. Product.** The generic-versus-local toggle, the Why panel, the refine line, candidate buttons for `needs_input`, precomputed examples, a per-visitor rate limit and a daily cap on live runs. Then the "try your own" path: a custom location field, and a form to add one animal (species, age, look, temperament, a couple of facts, an optional photo). A custom location goes to Qloo as typed; on `needs_input` show the candidates as buttons, and where the data is thin say so instead of producing a weak listing. The added animal and its photo are kept for the session only and never stored. Optional: reading the uploaded photo to fill in the animal's look, with temperament and facts still entered by the volunteer. Out of scope: accounts, an admin area, and creating, editing or deleting stored animals.

**5. Ship.** Deploy the container on a long-lived instance, switch to the paid model, and finish the README: the problem, which Qloo workflows are used and why, a walkthrough from request to result, setup from a clean machine, and known limitations including uneven coverage outside the US.
