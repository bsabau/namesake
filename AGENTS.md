# Namesake

Shared instructions for every coding agent that works in this repository. `CLAUDE.md` imports this file, so make changes here.

Working name; it appears in the package name and the page title only, so it is cheap to change.

Namesake is a web app for animal-shelter volunteers. A volunteer picks an animal and the shelter's location. An agent produces three things:

- an accurate adoption listing written only from the facts the volunteer entered
- name options drawn from Qloo taste data, each labelled with its source
- a plan for getting the animal seen, including local venues favoured by fans of pet-themed shows, films, books and brands

A generic version of the listing sits beside the local one, so Qloo's contribution is visible. The full design is in `docs/product.md`: read it before building any screen, agent output or Qloo call.

This is an entry for the Qloo Agentic Hackathon on Devpost. The author is one developer, a senior data engineer who works in Python and is new to front-end work.

## What the judges need to see

These shape most decisions below, so keep them in mind when making trade-offs. Checked against the Devpost rules on 15 October 2026.

- **Dates:** submissions close 30 October 2026, 23:45 US Eastern; aim to submit on the 29th. Judging runs 2 November 12:00 to 16 November 23:45 Eastern, and the demo and the Qloo key must stay live throughout. Winners are announced around 23 November.
- **Required:** a link to a working demo; a public GitHub, GitLab or Bitbucket repo with an open-source licence that shows in the repo's About section; and an English text description. A video is optional.
- **Theme check (pass or fail):** the project must be agentic. A fixed pipeline with a model only writing the final text would be a risk, so the model has to choose at least some of the Qloo calls.
- **Scoring, four equal parts:**
  - technological implementation: how deeply and skilfully Qloo is used
  - design: a complete product, not a proof of concept
  - potential impact: a credible, specific case for a real audience
  - quality of the idea: a creative, non-obvious use of Qloo that shows an understanding of the problem

  **Ties are broken on technological implementation.**
- **Key test from the brief:** if the app would work the same without Qloo, it is the wrong app. The generic-versus-local comparison exists to answer this.
- Judges may not run the app, and judging may be partly automated. They may judge from the description, screenshots and video, so the result screen must be legible in a single screenshot, and the README and description must state plainly what the app does.

## Rules that always apply

- **Secrets:** keys live in environment variables or the harness's private config. Never write a key into the repo, a log line, a test fixture, a browser bundle, or model prompts. `.env` is git-ignored; `.env.example` holds names only. The map tile key (`MAP_TILES_KEY`) is the one exception that reaches the browser, because tile requests come from the visitor's browser: it is a public basemap key, restricted by domain in CARTO's dashboard, and it is still never committed.
- **Qloo data stays out of the repo.** Qloo's terms forbid publishing its response data in a public repository. Live responses go to the SQLite cache and to the git-ignored `var/qloo-recordings/`. Tests use the hand-written envelopes in `tests/fixtures/qloo/synthetic/`, with invented IDs (`00000000-0000-4000-8000-…`) and invented names. `tests/test_no_qloo_data.py` enforces this. Precomputed examples live in the cache database, which is deployed privately and never committed. Screenshots and the README may show entity names and scores; Qloo confirmed this on Discord.
- **No personal data to Qloo:** send cultural entities and places, never names, emails or identifiers. The app has no accounts. The same holds for the classifier (TypeSafe's Jev, decision 20): it gets a title's name, kind and Qloo's description, nothing else.
- **How results are worded:** Qloo returns aggregate affinities. Write "people in this area tend to like X", never a claim or probability about an individual. Do not infer sensitive traits (politics, health, finances, race, religion) from taste data.
- **Provenance:** in the UI, keep what Qloo returned visibly separate from the app's interpretation of it.
- **Ambiguity:** when Qloo cannot resolve a name it returns candidates. Show them or pick with a stated reason; do not force a fuzzy match through.
- **Quota:** the hackathon key's quota is not published, so treat live calls as scarce. Tests never call Qloo or a model. Cache every live Qloo result. The key is rate-limited (refused after about 12 calls in 20 minutes on 15 October; 30 calls 10 seconds apart passed on 17 October; at 2 seconds `rank` was refused on 18 October), so every live call goes through `QlooClient`, which spaces calls at least `QLOO_MIN_INTERVAL` seconds apart (default 5) across processes, waits longer after a rate limit, and retries `rank` twice. Raise it if Qloo starts refusing.
- **Supported Qloo surfaces:** only the harness commands `qloo mcp`, `qloo exec` and `qloo api`. Do not call the HTTP API directly from Python.
- **Listings state only recorded facts.**
  - Every sentence of a bio traces to the animal's recorded facts. Anything unrecorded stays unmentioned.
  - A bite history or guarding is stated plainly, every time.
  - Write in the third person, with behaviour toward people first, in plain words, at 75 to 150 words. When the recorded facts cannot fill 75 words, the listing stays short and says so; it is never padded.
  - Describe the animal as it is now. Leave out backstories, pity and urgency.
  - The cultural reference appears only in the name and one hook line, and neither the hook nor a name's reason says anything about temperament.
- **Names are screened.**
  - Names are short and easy to say, at one to three syllables.
  - Every option passes a screen for villains, violent or tragic characters, weapon and aggression words, words that put an animal down (garbage, scat, rat), living celebrities, and references coded to a race, religion or political identity.
  - Dogs of bully-breed type get the strictest screen, because research found a measured penalty for names perceived as Black on pit-bull-type dogs.
  - Two animals in one shelter never share a reference, except a litter named as a set. One animal's options come from different titles while another of the area's open titles is unused (lookalike titles never count).
- **Docs stay current.** A change updates, in the same PR, every document it makes stale or incomplete: `docs/architecture.md` (the technical tour and its diagrams), the README, `docs/decisions.md` (a new entry, or a dated line in the one it revises), `docs/qloo-findings.md` for anything learned from live calls, `docs/product.md` for the design, and this file. A reviewer treats a PR that changes behaviour without updating those documents as unfinished.
- **Claims stay within the evidence.** The README, Devpost text and UI may say the tool:
  - drafts accurate listings, name options and an exposure plan quickly
  - follows the published research on listing style
  - screens names
  - uses local taste data as a labelled experiment, and records what is needed to test it

  They never say it gets animals adopted faster, saves lives or money, or matches animals to "the right people". The evidence is in `docs/research/adoption-evidence-review.md`: read it before writing README, Devpost or UI copy.

## Who does what

Several coding agents work in this repo, and all of them read this file. Each has one job. Stay in yours unless the author says otherwise.

| Agent | Job |
| --- | --- |
| Claude Code | Builds. Owns the milestone in progress: the design, the implementation, and the tests that go with it. |
| Codex | Reviews. Reads a diff and reports what is wrong with it. It does not change files. |
| OpenCode | Small, bounded tasks handed over by name: tests written against existing fixtures, typed models for a recorded response, docstrings, README sections. |

- One agent writes at a time. If the working tree holds changes you did not make, leave them alone and say so.
- Only the builder makes live Qloo or model calls, and only where a milestone calls for them. The reviewer, and anyone doing a bounded task, works from the code and the synthetic fixtures.
- The milestone rule below applies to every agent: nobody starts the next milestone on their own.

## Review guidelines

For whoever is reviewing a diff. Report findings only: do not edit files, do not run `qloo`, and do not call a model.

Check these first. Each one can sink the entry or leak something.

- A key or token anywhere it should not be: source, a log line, a test fixture, a template or static file, a model prompt.
- Qloo response data in a tracked file: a recorded envelope, a real entity ID or correlation ID, or a cache or examples database.
- Anything sent to Qloo other than cultural entities and places.
- A test that would reach Qloo or a model instead of a synthetic fixture or a fake model, or a live Qloo result that is not cached.
- A direct HTTP call to the Qloo API from Python, in place of the harness commands.
- Wording that makes a claim about an individual, or infers a sensitive trait, from taste data.
- A listing path that can state something not in the animal's facts, soften a bite history, or let the hook describe temperament.
- A name path that skips the screen, or the stricter screen for bully-breed dogs.
- README, Devpost or UI copy that claims faster adoption, saved lives or money, or matching.
- UI that blends what Qloo returned with the app's reading of it.
- A per-animal venue filter that drops a venue without naming it, or reads anything but the animal's record and the venue's own name and description.
- A UI folder that calls Qloo, the agent or the cache, or computes data that belongs in a view model.
- An envelope status left unhandled (`ok`, `empty`, `needs_input`, `partial`, `degraded`, `error`), a retry when `retryable` is false, or a `needs_input` forced through as a match.
- A model name, endpoint or key written into code instead of read from the four `AGENT_*` variables.
- Work that belongs to a later milestone than the current one.
- A change that leaves `docs/architecture.md`, the README, `docs/decisions.md`, `docs/qloo-findings.md`, `docs/product.md` or this file describing something the code no longer does, or that adds something they should name (a route, a setting, a table, a Qloo call, a screen) without naming it.

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
| Map | Leaflet with OpenStreetMap tiles (keep the attribution); the story skin draws CARTO's Positron and Dark Matter when `MAP_TILES_KEY` is set, falling back to OpenStreetMap (decision 24) |
| Agent | PydanticAI 2.x with structured output |
| Qloo, agent-chosen calls | PydanticAI function tools over `QlooClient` (`qloo exec`), so every call is cached and spaced; see `docs/decisions.md` #5 |
| Qloo, fixed calls | `QlooClient` (`qloo exec` as a subprocess returning JSON) |
| Title classifier | TypeSafe's Jev over HTTPS (`app/classify.py`), optional, answers cached in SQLite; see `docs/decisions.md` #20 |
| Cache | SQLite |
| Packaging | One Docker image containing Python, Node 22.19+ and the harness |
| Licence | MIT |

One container serves everything. There is no separate front-end build step, which is deliberate: the author is not a front-end developer.

## The UI is a replaceable skin

The author wants to try more than one interface, so no screen's logic lives in a template.

- **View models.** Each screen has a typed view model in `app/views/`, such as `StartView` or `ResultView`. Routes build it from domain objects. It holds everything the screen shows, already worded and in display order, and it contains no HTML.
- **JSON API.** The same view models are served as JSON under `/api/` (`/api/start`, `/api/results/{id}`, and the SSE step log at `/api/runs/{id}/events`). A different interface, even a single static HTML page with a script, can be built on the API alone.
- **UIs.** Each UI is a folder of templates and static files: `app/ui/<name>/templates/` and `app/ui/<name>/static/`. A UI only renders view models. It never calls Qloo, the agent or the cache, and it never re-derives data. The `UI` setting picks the default UI (`story`, which tells the result as a story; `warm`, the default before it, and `classic`, the first skin, are kept for comparison), and `?ui=<name>` switches UI per request so two can be compared side by side. See `docs/decisions.md` #21 and #24.
- **Shared test contract.** Tests check the view models and the API. One smoke test, run against every UI, checks that each screen renders the elements that must be there, found by `data-role` attributes: the name, the provenance split, the map, the photo credit and the Qloo credit. A new UI passes that test or isn't finished.

## The Qloo harness: what is known

The harness is the npm package `@qloo/qloo-harness` (0.1.26 on the dev machine; pin that version in the image). It needs Node 22.19 or newer.

**Configuration.** A hackathon key works only against `https://hackathon.api.qloo.com`; the harness defaults to production and rejects the key with a 401 unless the base URL is set and trusted. On the dev machine this is already stored in `~/.qloo/config`, so nothing is needed locally. In the container, set all three:

```
QLOO_API_KEY=...
QLOO_BASE_URL=https://hackathon.api.qloo.com
QLOO_TRUSTED_BASE_URL=https://hackathon.api.qloo.com
```

A child process only sees these if the parent passes its environment through.

**Terms, as confirmed by Qloo on Discord:**
- Server-side caching is allowed with no time limit.
- Showing scores and entity names in the demo and screenshots is fine.
- Credit Qloo in text only ("Taste data from the Qloo API") and state that the project isn't affiliated with Qloo.
- Keys are deactivated after the hackathon closes.
- To raise a quota, ask in `#api-help` on Discord.

**Workflows.** Confirmed working from the command line: `find_tags`, `where_popular`, `recommend`, `rank`. The MCP server exposes these tools: `qloo_capabilities`, `qloo_find_tags`, `qloo_describe`, `qloo_recommend`, `qloo_rank`, `qloo_where_popular`, `qloo_compare_audiences`, `qloo_audience_demographics`, `qloo_entity_tags`, `qloo_trends`. Read exact input schemas from the harness (`qloo exec --help`, or the `qloo_capabilities` tool, which costs no quota) instead of guessing field names. Inputs are validated before Qloo is called, so a wrong field costs nothing.

Qloo silently ignores parameters it does not recognise and then returns empty results. After a call, check `interpretation` to confirm what was actually sent. Tags and audiences must be passed as IDs, not free text.

**A call that is known to work:** `where_popular` for the TV show Bluey within New York City. The input, with Bluey's entity ID, is recorded in `var/qloo-recordings/where_popular__bluey__nyc.json`. Passing the name "Bluey" instead returns `needs_input`, because an author has the same name.

**Result envelope.** Every workflow returns one JSON object:

- `status`: `ok`, `empty`, `needs_input`, `partial`, `degraded` or `error`.
- `results`: a list.
  - For `where_popular`, each item is a map cell: `location.latitude`, `location.longitude`, `location.geohash` (six characters, about a kilometre, for a city; seven, about 150 m, within a neighbourhood) and `query.affinity`, `query.popularity`.
  - For `recommend` and `rank`, each item is an entity: `entity_id`, `name`, `type`, `popularity`, `affinity`.
- `interpretation`: what the harness actually sent, for example `signal_location` or `target_type`.
- `resolution.issues[].candidates[]` when status is `needs_input`: each has `id`, `name`, `type`, `popularity`, `description`.
- `provenance.requests[]`: the underlying API request. The heatmap is `GET /v2/insights` with `filter.type=urn:heatmap`.
- `error.code`, `error.retryable`, `error.recovery` when status is `error`. Retry only when `retryable` is true. A rate limit (`QLOO_RATE_LIMIT`) is retryable.
- `execution.duration_ms`: the heatmap call took about 2.5 seconds, which is why results are cached.

`qloo exec` exit codes: 2 for bad input, 4 for missing credentials, 1 for other failures.

**Deployment constraint.** `qloo mcp` is a local stdio process with no hosted URL. Qloo's kit says to run on a VM or container and that serverless functions are unsupported, so the app needs a long-lived process.

## What the data shows

`docs/qloo-findings.md` has the milestone 1 answers and the proposal for the agent, and `docs/decisions.md` what was decided from it; read both before building anything that calls Qloo. In short:

- Pet tags exist but filter TV and films down to almost nothing, and lifestyle tags change nothing as a signal. As signals with the area they give each area its own list of pet-themed titles, which the agent starts from (decision 22); it may add its own, kept only with Qloo's evidence, and searches what people around the area who like them also like; a classifier sorts every list (decision 20).
- Pet-themed titles as signals give venues near the shelter. Most are just popular nearby, whatever the titles, so venues are asked only within kinds of place that can host a stand (decision 23), compared with those of the area's own top shows (decision 18), screened for event suitability, and never a listed national chain (decision 23).
- Citywide heatmaps rarely reach the shelter. Heatmaps within the neighbourhood work, and the map layer is the lift of the top two pet titles over the area's top two shows; a title that maps thinly there gives way to the next.
- Names are often ambiguous; resolving them with a stated reason is an agent step.
- Raw affinity saturates; use order within a call and lift against a baseline.
- The key is rate-limited, `rank` most of all.

The demo uses New York City because US coverage is likely to be deepest.

## Model configuration

The agent's model is configuration, never code. Four variables, plus `AGENT_OUTPUT_MODE` (see `docs/decisions.md` #6):

```
AGENT_BASE_URL=https://opencode.ai/zen/go/v1
AGENT_API_KEY=...
AGENT_MODEL=muse-spark-1.3-contributor
AGENT_API=responses        # or "chat"
```

Development uses a free model through OpenCode Go; the judged demo will switch to a paid one by changing these values. Some models speak the OpenAI "responses" format and others "chat completions", hence `AGENT_API`.

`app/agent/model.py` builds the model from these settings, with the session header OpenCode Go requires. The agents' Qloo tools are function tools over `QlooClient`, not `qloo mcp` (`docs/decisions.md` #5). For reference, PydanticAI 2.x attaches an MCP server like this, checked against 2.53:

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

- Fields per animal: `id`, `species`, `group`, `sex`, `age`, `look`, `temperament`, `facts` (a list), `image`. The four kittens share `litter: "litter-a"`. The `litter-group` entry has `members` and no profile. Milestone 2 adds the `yes`/`no`/`unknown` fields listed in `docs/product.md`.
- Animals have no names on purpose. Naming them is the app's job.
- `dog-02` leads the demo and the litter is the second example; `docs/product.md` says why.
- The photos and JSON were produced by a separate project outside this repo (`../image_generation`, which also holds `ANIMALS.md` with each animal's role in the demo). It is not part of this app; do not import from it or run it.
- The app serves web-sized copies from `app/static/animals`, made by `scripts/make_web_photos.py`. The UI labels the photos as AI-generated, and the app never edits or generates animal images.

The shelter is fictional too. Do not use real shelter names, logos or photos.

## How the product works

`docs/product.md` holds the design: the three outputs, the Qloo pipeline step by step, the result screen and the measurement log. In short:

**Screens**

1. **Start:** a grid of the animals, a choice of three preset locations, a custom location field, and a "try an example" button that loads a precomputed result instantly. There is no tone setting: the listing rules fix the voice, and the refine line takes follow-ups (`docs/decisions.md` #15).
2. **Working:** a live log of the agent's steps, streamed as they happen: entities proposed, each one checked against Qloo, which were kept and which dropped.
3. **Result:** the listing with a toggle between the generic and the locally tuned version; name options with source badges; a map of local lift; the venues as a list with their evidence, under a note on which kinds of place were asked for and why, and that listed national chains are left out (`docs/decisions.md` #23), and as numbered pins on the map from OpenStreetMap (`docs/decisions.md` #4, revised), skipping those that mention children for an animal recorded as not good with them (`docs/decisions.md` #2); the exposure checklist.
4. **Why:** for each choice, the Qloo result behind it, separate from the app's reading of it.
5. **Refine:** one text line for follow-ups such as "less childish". When Qloo returns `needs_input`, show the candidates here as buttons.

**Preset locations.** The start screen offers three: two New York City neighbourhoods and one other US city. Two neighbourhoods in the same city show that results change at fine detail; the third shows it is not only a New York effect. Do not choose them by reputation. Milestone 1 keeps the three that Qloo resolves cleanly and whose results differ most. Candidates: Park Slope, Bushwick, Astoria, Harlem and the Upper West Side in New York; Tampa, Austin and Portland elsewhere. Each preset is a place name plus a centre point for the fictional shelter, never a real shelter or a street address. The presets live in `data/locations.json`: `query` is the text sent to Qloo as the location signal, and `city` is the wider area for the heatmap. The current three (Park Slope, Astoria, Austin) are provisional, and Astoria is untested.

**The agent's job.** Given an animal's facts and a location:
1. Find pet-themed entities that are strong locally, and check each one's lift against a baseline. Keep the strong ones, and try again once if too few survive.
2. Pick venues that their fans favour.
3. Propose name references from both sources, plus up to two titles with an animal that looks like this one, resolve and screen each one.
4. Write the listing from the facts.

The steps where the model reads results and decides what to try next are what make this an agent. Calls that are always made the same way, such as the heatmap for the map, go through `qloo exec` in plain code. Plain code also checks the agent's output: that every fact traces, the name screen, duplicate references, and word count.

**Output** is a typed object, not free text. It holds:
- the name options, each with its source, Qloo entity ID, type, evidence and screen result
- the generic bio and the local hook
- the venues with their evidence
- the exposure plan
- the map cells
- the step log

## Layout

```
app/
  main.py            FastAPI app and routes
  config.py          settings from the environment
  agent/             the two PydanticAI agents, their checks, the step log and the run pipeline
  runs.py, store.py  web runs (background task + step log), saved agent results, approvals
  session.py         per-visitor state in memory: added animals, photos, refined listings
  limits.py          per-visitor and daily limits on live runs and new locations
  custom_location.py checks a typed shelter area with Qloo before any run
  qloo/              exec wrapper, envelope types, cache, geohash helpers
  views/             UI-neutral view models, one per screen, also served as JSON
  ui/<name>/         one folder per UI: templates/ and static/ (story is the default; warm and classic are kept)
  static/            shared assets: web-sized animal photos
data/animals/        animals.json and original photos
data/locations.json  the preset shelter locations
docs/                architecture.md, decisions.md, product.md, qloo-findings.md, research/, img/
scripts/             probe scripts, photo and example builders
tests/
  fixtures/qloo/synthetic/   hand-written envelopes, invented data
var/                 git-ignored: real Qloo recordings, never committed
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
uv run python scripts/build_profiles.py       # fixed-lookup profiles from the cache; --live fills gaps from Qloo
uv run python scripts/run_agent.py dog-02 park-slope   # one live agent run (Qloo and the model), steps printed
uv run python scripts/precompute_examples.py  # the start page's examples into var/cache.sqlite, live
uv run python -m app.venue_points             # pin saved profiles' venues from OpenStreetMap, once
uv run pytest
uv run pytest tests/test_app.py::test_health   # one test (-k <expr> also works)
uv run ruff check . && uv run ruff format --check .
docker build -t namesake .
```

## Milestones

Work on one milestone at a time, in order, and stop at the end of each for review. Dates are targets. Current milestone: **5**. Design decisions are recorded in `docs/decisions.md`; read it before changing how the agent, the profile or the venues work, and add an entry when you make a decision of that size.

**0. Scaffold.** Done 15 October. The uv project, the settings module, a health route, the start page with the animal grid and web-sized photos, and a Dockerfile with Python, Node and the pinned harness.

**1. Qloo layer and findings.** Done 15 October; see `docs/qloo-findings.md`. The original brief:
- Write a typed wrapper around `qloo exec` that:
  - parses the envelope and handles every status
  - caches in SQLite at `settings.cache_db`
  - can replay from `var/qloo-recordings/`
  - has tests that use the synthetic fixtures
- Write probe scripts for the gaps listed under "What the data shows so far", with about 15 live calls in total. Save every response to `var/`.
- Choose the three presets.
- Record the answers in `docs/qloo-findings.md`.
- Then propose how the agent should work given what was found, and wait for a decision.

**2. Thin end-to-end slice.** Done 15 October. The original brief: No agent yet. Choose an animal and a location, run one fixed lookup (heatmap lift and venues, from the cache), and draw the cells and venue pins on the map. (Venues became a list rather than pins; see `docs/decisions.md` #4.) Render a templated listing from the facts. Add the `yes`/`no`/`unknown` fact fields. Build the UI seam described under "The UI is a replaceable skin": move the start page into `app/ui/classic/`, add view models and `/api/`, and add the shared smoke test. This proves the whole path from form to result.

**3. The agent (16–24 October).** Done 15 October. The original brief: Add the PydanticAI agent with the Qloo tools, structured output, the plain-code checks with one repair round and a templated fallback, and the live step log over server-sent events. Two runs, per `docs/decisions.md`: a profile run per location and species (titles, ranking, venues), and a listing run per animal (names, bio, hook). Tests use PydanticAI's `TestModel` or `FunctionModel` and the synthetic fixtures.

**4. Product (25–27 October).** Done 17 October.
- The generic-versus-local toggle, the Why panel, the refine line, and candidate buttons for `needs_input`.
- Edit and approve, and a copy-ready block.
- Precomputed examples, built by a script into the cache database: `dog-02` and the litter in two neighbourhoods.
- A per-visitor rate limit and a daily cap on live runs.
- The "try your own" path:
  - A custom location field. A custom location goes to Qloo as typed; on `needs_input`, show the candidates as buttons. Where the data is thin, say so instead of producing a weak listing. The field suggests area names as you type, and a spot picked on the map becomes an area's name, with the spot kept as that visit's pin (`docs/decisions.md` #17).
  - A form to add one animal: species, age, look, temperament, a couple of facts, the `yes`/`no`/`unknown` fields, and an optional photo. The added animal and its photo are kept for the session only and never stored.

Out of scope: accounts, an admin area, creating, editing or deleting stored animals, and reading or altering photos with a model.

**5. Ship (28–29 October, with the 30th as a buffer).**
- Deploy the container on a long-lived instance, with the cache database on a private volume, and switch to the paid model.
- Finish the README:
  - the problem, with cited numbers
  - which Qloo workflows are used and why
  - a walkthrough from request to result
  - the measurement design
  - setup from a clean machine
  - known limitations: uneven coverage outside the US, saturated affinity scores, and no outcome evidence yet
- Write the Devpost description, take one result-screen screenshot, and record a short video.
