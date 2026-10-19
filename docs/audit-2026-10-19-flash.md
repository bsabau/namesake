> Final audit by DeepSeek Flash, 19 October 2026, of `main` at `a163ba7`, on the brief in the fix list's header. Its findings are tracked in [`audit-2026-10-19-fixes.md`](audit-2026-10-19-fixes.md); another project's network name is redacted.

# Namesake — final audit before Devpost submission

**Scope:** `main` at `a163ba7` (19 October 2026), deployed at https://namesake.bogdansabau.eu. `uv run pytest -q` → **621 passed**; `uv run ruff check .` and `ruff format --check .` clean. I read the docs, `app/`, `tests/`, `scripts/`, `deploy/` and `.github/`, fetched only GET pages on the live site and GitHub, and made no POSTs, no Qloo/model/classifier calls, and no ssh.

## Verdict

Namesake is a strong, genuinely agentic entry with a polished demo and unusually honest documentation, but **it is not ready to submit**. Two P0s block it: the Code link judges will click returns 404, and tracked images/docs carry Qloo response data beyond the names-and-scores permission. Two P1s also need fixing first: the demo is still on the free model, and a volunteer's edit can state facts the shelter never recorded. Fix those four, enforce the cross-animal reference rule, and this is a credible winner.

## Scores

| Criterion | Score | Reason | The single change that would raise it most |
|---|---|---|---|
| **Technological implementation** (tie-break) | **8/10** | Deep, skilful Qloo use: pet-tag lists, local searches, `describe`, `rank`, places, heatmaps, lift against the area's own top shows, a classifier, and code checks on every return. The model really chooses the calls (`look_up_title`, `find_local_titles`, `rank_titles`, `find_venues`, `look_up_lookalike`). Gaps: partial/degraded answers, no per-run Qloo budget, and the free demo model. | Switch the demo to the paid model and make the agent's Qloo calls robust (partial/degraded handled; per-run budgets enforced). |
| **Design** | **7/10** | A complete flow with three skins, examples, add-animal, refine, approve, copy, a JSON view-model API and thoughtful provenance. Deductions: the add-animal form loses everything on a validation error, the result is a 4,685 px page at 1024 px, and the JSON API cannot start or approve a run. | Make the add-animal form keep its input and validate inline. |
| **Potential impact** | **7/10** | Specific audience (shelter volunteers, large adult dogs), cited problem numbers, a research-led exposure plan, and a measurement design. No outcome evidence, no named partner, and the plan omits the equity/non-English channel its own evidence review recommends. | Add the equity/non-English channel the evidence review recommends, with a basis line. |
| **Quality of the idea** | **8/10** | Local taste data for names *and* venues, with a generic/local toggle, a screen grounded in the name-penalty research, and provenance everywhere, is a creative and non-obvious use of Qloo. | Enforce cross-animal reference uniqueness and show Qloo's evidence for every name source, including general local tastes. |

## Findings

### A1 · P0 · The Code link is dead (repo private or missing)
**Where:** `README.md:5`, `README.md:130`; `docs/devpost.md:10`; `docs/video-script.md:16`.
**What:** All point to `https://github.com/bsabau/namesake`. `https://api.github.com/repos/bsabau/namesake` returns **404**, and `github.com/bsabau` lists three public repos, none named `namesake`. **Why it matters:** Devpost requires a public GitHub/GitLab/Bitbucket repo with an open-source licence visible in About; a judge clicking “Code” gets 404, which can disqualify the entry.
**Fix:** Publish (or create) the repo publicly; set About (description, website, MIT — the `LICENSE` is MIT), add topics. Before flipping: the repo has 13+ branches (`author-items-*`, `story-*`, `worktree-agent-*`, …) and an untracked worktree; prune/scan them. `git log --all` shows no real key (only the fake test key), but the branches are unreviewed. Verify the About licence after publishing.

### A2 · P0 · Qloo response data in tracked files
**Where:** `docs/img/result.png` (the “Places to ask” cards show Qloo's `short_description` and a real street address for three venues); `docs/img/yankees-mets-heatmap.jpg` (unreferenced; a plot of Qloo's top-20 heatmap cells); `docs/qloo-findings.md:66-77` (real geohash cells with lift values).
**What:** AGENTS records Qloo's permission for **entity names and scores** in screenshots, not for descriptions, addresses or raw cell positions. `tests/test_no_qloo_data.py` scans only text files for UUIDs/envelopes/databases, so all three pass. **Why it matters:** Qloo's terms forbid publishing response data; a reviewer or Qloo could treat this as a leak. The unused heatmap is unambiguous; the screenshot is a gray area because the live app shows the same data.
**Fix:** Delete the unused heatmap; replace the geohash table with a summary; crop or blur the description/address lines in the screenshot, or ask Qloo in `#api-help` and paste the written answer. Extend the data test with a manual allowlist or an image check.

### A3 · P1 · The judged demo still runs the free model
**Where:** `README.md:144`, `README.md:174`; `AGENTS.md:207` and milestone 5.
**What:** “The demo runs a free model through OpenCode Go.” AGENTS says the judged demo will switch to a paid one; milestone 5 lists “switch to the paid model” as a deliverable. The README also says the free model “sometimes needs its one repair round”. **Why it matters:** the Go plan is shared with reviews and can be exhausted (`CLAUDE.md`); a judge's live run then falls back to the template, and the OpenCode Go plan is not a production model service.
**Fix:** Set the host's `AGENT_*` to the paid model, run one live area + listing, update the README limitation, and keep the key live through 16 November.

### A4 · P1 · A volunteer's edit can state unrecorded facts
**Where:** `app/main.py:531-533` (length only) and `:559-573` (only `missing_cautions`); `app/listing.py:193-215`; `app/ui/story/templates/result.html:138`.
**What:** Any 1–3,000-character edit is accepted if it keeps the caution phrases. Replace dog-02's bio with “She is great with kids and loves everyone” (children unknown) and approve: it records and shows that text as the listing. **Why it matters:** AGENTS requires every sentence to trace to the record; the evidence review's main harm is overselling. The code checks the model's draft but not the volunteer's final text.
**Fix:** Run the existing record check over the edit — content words against the union of the animal's facts, plus `UNKNOWN_TOPICS`, `BACKSTORY`, `PITY_URGENCY` and first person — and refuse with the extra words. Keep the caution check. Allow rewording through the word-set, not the per-sentence citation.

### A5 · P1 · Two animals can share a reference
**Where:** `app/agent/pipeline.py:252-266` (`taken_names` compares lowercased names only); `app/agent/listing_agent.py:428-432` (duplicate name) and `:464-487` (`repeated_titles` is per animal); `app/main.py:549-557`.
**What:** “Scooby” and “Scooby-Doo” from the same lookalike title are two names but one reference; “Bingo” and “Bluey” from *Bluey* are two names from one title. The AGENTS rule says two animals never share a reference; decision 13 says the same. **Why it matters:** the review guidelines list this as a sink-the-entry item, and the page calls the character/title the name's “reference”.
**Fix:** Keep a per-shelter set of `(entity_id, character/title)` (add `entity_id` to `Approval`), refuse a reference another animal has, with the litter exception; add tests for the Scooby/Bingo cases.

### A6 · P2 · The documented example rebuild crashes with the classifier on
**Where:** `scripts/precompute_examples.py:36-45`; `scripts/run_agent.py:54-60`; `app/agent/profile_agent.py:438-442`.
**What:** The wrapper `def echo(kind, text)` does not accept `actor=`, which `sort_list` passes when the classifier answers. With `TYPESAFE_API_KEY` set — which `deploy/make_env.py` passes to the host — the profile build raises `TypeError` and the examples script fails. **Why it matters:** the README's rebuild command is broken in the deployed configuration; the examples are a judge-facing asset.
**Fix:** `def echo(kind, text, **kwargs)` and forward; add a test that the wrapper accepts the actor.

### A7 · P2 · Partial/degraded answers are used as complete for venues and describes
**Where:** `app/agent/profile_agent.py:563-573` (`find_venues` checks only `has_results`), `:206-220` (`look_up_title`) and `:360-372` (`_look_up`).
**What:** `has_results` is true for `partial` and `degraded`. `list_failure` (`:356-367`) and `rank_titles` (`:471-480`) correctly reject non-`ok`; venues and describes do not. **Why it matters:** a partial list may have lost the location signal; the venue picks and the “stands out” badges then rest on an incomplete answer.
**Fix:** Treat non-`ok` as unavailable (or note it) for venues and describes; use `tests/fixtures/qloo/synthetic/recommend__partial.json`; add tests.

### A8 · P2 · No per-run cap on the agent's Qloo calls
**Where:** `app/agent/profile_agent.py:179-220` (`look_up_title`) and `:519-603` (`find_venues`); `app/agent/pipeline.py:50` (`PROFILE_LIMITS` tool_calls 18).
**What:** Nothing counts the AI's own title lookups (the instructions say up to four) or repeated venue searches; the only guard is the 18-tool-call budget. A model can spend 10+ lookups and 5 venue calls, over the documented 18–20 Qloo calls and the key's rate limit. **Why it matters:** the quota is the scarce resource; the daily cap counts runs, not calls.
**Fix:** Cap own-title lookups at 4 and venue searches at 2–3, return “unavailable” beyond, log it, and test.

### A9 · P2 · The add-animal form loses everything on a server-side refusal
**Where:** `app/main.py:655-659`; `app/ui/story/templates/add_animal.html:26-46`, `:33`.
**What:** `refuse` rebuilds `AddAnimalView` with only the error; the template has no values for age/look/temperament/facts, and the facts textarea has no `maxlength`. A fact over 120 characters, more than six facts, a >3 MB/wrong-type photo or a missing field returns a blank form; the photo must be re-picked. **Why it matters:** a judge trying “Add your own animal” sees a hostile form; design is a quarter of the score.
**Fix:** Carry the submitted values (and a “re-add the photo” note) into the view and prefill; add `maxlength=120` per fact; test a refusal keeps the text.

### A10 · P2 · Free runs are uncapped, `RUNS` grows forever, and POSTs have no CSRF guard
**Where:** `app/runs.py:56`, `:130-139`, `:186-190`; `app/main.py:440-463`.
**What:** A saved listing returns `_saved(_new_run(...))` with no charge, and `RUNS` is never pruned; a bot can POST `/runs` for `dog-02@park-slope` repeatedly and grow memory. POSTs carry no CSRF token or Origin check, so another site can start runs (and burn the 60/day cap) without a cookie. **Why it matters:** a public demo with unknown quota; the daily cap is the only protection.
**Fix:** Redirect saved results straight to `/result`; prune `RUNS` on a TTL/size; rate-limit POST `/runs`; add a CSRF token or Origin check.

### A11 · P2 · Uploads and sessions can exhaust memory
**Where:** `app/session.py:24-26`, `:65-105`; `app/main.py:661`, `:693-701`.
**What:** 3 photos × 3 MB × 500 sessions ≈ 4.5 GB; there is no per-IP cap on adding animals or creating sessions. A bot with a 3 MB JPEG can fill memory and take the demo down during judging. **Why it matters:** availability is part of the submission.
**Fix:** Cap total photo bytes per session and globally, lower `MAX_SESSIONS`, or spool photos to a quota'd directory; test the cap.

### A12 · P2 · Local-taste names carry no Qloo evidence and are missing from the Why panel
**Where:** `app/views/build.py:449-450` (`source == "local"` → “Watched locally”), `:1077-1110` (`why()` loops only `pet_entities` + baselines); `app/profile.py:598-630` (`tastes` entities have no `found_in`).
**What:** A name drawn from the area's general top tastes shows no rank or position, and its title never appears in the “What Qloo returned” column; `qloo_part` does not count it. **Why it matters:** `docs/product.md` and the README promise Qloo's evidence for each option; this is the one source where provenance is thin.
**Fix:** Record the position in the area's top list (a `FoundIn` with a “top tastes” signal) and show it; add the title to the Why returned column; test with a local name.

### A13 · P2 · The README screenshot is too small to read
**Where:** `docs/img/result.png` (1024×4685); `README.md:17`.
**What:** At 1024 px the 0.7 rem Qloo/Namesake lines and venue evidence are about 7 px; the first 900 px show only the name and introduction, not the map or venues. **Why it matters:** the brief says the result must be legible in one screenshot, and judges may score from it.
**Fix:** Add a 1440×900 above-the-fold shot (name, Qloo strip, introduction) and a 1440-wide full-page second image; keep the current as a fallback.

### A14 · P2 · The JSON API cannot drive the flow
**Where:** `app/main.py:411-422`, `:717-750`, `:845-863` (GET only); the write routes (`/runs`, `/refine`, `/approve`, `/locations`, `/animals`) are HTML only. Claimed at `AGENTS.md:136` and `docs/architecture.md:241`.
**What:** A different interface can read view models but cannot start a run, refine, or approve; the SSE stream is reachable only for a run ID it cannot create. **Why it matters:** the “UI is a replaceable skin / API alone” claim is a documented strength; a judge trying the API finds it read-only.
**Fix:** Add JSON POST endpoints, or reword AGENTS/architecture to “read the same data”; test the contract.

### A15 · P2 · The character/title attribution is the model's, unverified
**Where:** `app/agent/listing_agent.py:581-588`; `app/agent/checks.py:476-483`; `app/views/build.py:485-496`.
**What:** The hook and the approval source present “Bingo, a puppy in *Bluey*” as the name's origin. Qloo confirms the title, not the character; the model can name a character not in the title. For lookalikes the match is labelled as the AI's reading; for pet titles it is not. **Why it matters:** the reference is the product's central cultural claim; accuracy is the pitch.
**Fix:** Label the character as the AI's reading on the page and in the README (or use the title alone when no character is verifiable).

### A16 · P2 · Bully-type detection is keyword-only
**Where:** `app/agent/checks.py:14`, `:147-148`.
**What:** The strict screen triggers only on `broad head`, `pit bull`, `pitbull`, `bully`, `staffordshire`, `amstaff`. A dog described “blocky head”, “boxy head”, “XL bully” or “muscular” skips it. **Why it matters:** the README says bully-type dogs get the strictest screen, and the research penalty is the reason for the screen.
**Fix:** Broaden the markers, ask the volunteer, and document the limit; test.

### A17 · P2 · The exposure plan omits the equity/non-English channel its evidence review recommends
**Where:** `app/views/build.py:889-933`; `docs/research/adoption-evidence-review.md:188`.
**What:** The review explicitly recommends “at least one channel that reaches communities under-represented among adopters, including non-English channels”; the plan has networks, outings, timing, NY rescue partners and Qloo venues, but no equity channel (the language noticeboards were removed in decision 23). **Why it matters:** potential impact; the plan claims to lead with the research.
**Fix:** Add a “Research” item to ask a community organisation and translate the flyer where a partner can, without claiming an area's demographics.

### A18 · P2 · The Devpost text says “280+ tests”
**Where:** `docs/devpost.md:41`.
**What:** The suite is 621 tests; the README says “about 600”. **Why it matters:** a judge may check; it is needlessly stale.
**Fix:** “Over 600”.

### A19 · P2 · Stale docs contradict the code
**Where:** `AGENTS.md:165` (names `where_popular__bluey__nyc.json`; recordings are `<operation>__<sha16>.json`, `app/qloo/exec.py:149-152`); `AGENTS.md:233` (field list omits `history`/`checks`; still says milestone 2 adds the checks); `AGENTS.md:253` (“Astoria is untested”, but it is an example and tested); `docs/decisions.md:12` (“about 8 calls”), `:278` (“12 to 14”) vs the README/decision 22 (“18 to 20”); `docs/decisions.md:276` (“at least 120 seconds” for upgrades; `app/upgrade_profiles.py:33` defaults to 10, decision 20); `docs/product.md:44` (names ranked by affinity and popularity — the code uses Qloo's `rank`), `:64` (“agent drops entities with no lift” — the map is computed after the AI), `:66` (“agent proposes, screens, keeps” general local tastes — code fetches them); `docs/qloo-findings.md:3` (“every number … probe_m1.py”; “3 and 15 October”, though later sections are 18–20 October).
**Why it matters:** AGENTS says a PR that leaves docs stale is unfinished; a judge may read these.
**Fix:** One docs pass, updating or dating the lines.

### A20 · P2 · An untracked worktree holds a full copy including `var/` and `.env`
**Where:** `git status` shows `?? .claude/worktrees/`; the worktree at `.claude/worktrees/agent-a0b1d2391a3d9103c/` contains `var/`, `.venv`, `.env` (I did not open the files). `tests/test_no_qloo_data.py:18-19` does not skip `.claude`, but nested repositories are skipped by `git ls-files --others`, so the test cannot see it.
**What/why:** a `git add -A`/`-f` or a whole-tree leak scan could publish real Qloo data or a key; the repo is about to go public.
**Fix:** Delete the worktree, add `.claude/worktrees/` to `.gitignore`, and scan the whole tree (not just tracked files) before publishing.

### A21 · P3 · The hook can end with “!.”
**Where:** `app/agent/listing_agent.py:585-588`.
**What:** `hook_for` always appends a period; a title ending in “!” gives “Named after Scooby-Doo, a dog in Scooby Doo, Where Are You!.” in the local version. **Fix:** strip the title's terminal punctuation or omit the final period when the reference already ends with one.

### A22 · P3 · A typed area reads “Typed location” in the result topline
**Where:** `app/custom_location.py:107` (`region="Typed location"`).
**What:** “Shelter area: Williamsburg, Brooklyn, Typed location.” **Fix:** use the typed text as the region or omit it.

### A23 · P3 · No favicon, meta description or Open Graph tags
**Where:** `app/ui/story/templates/base.html:1-9`.
**What:** The tab shows a default icon and a Devpost/social link has no preview. **Fix:** Add a small favicon, a description, and `og:title`/`og:description`/`og:image` (the result screenshot).

### A24 · P3 · Leaflet is a third-party runtime dependency
**Where:** `app/ui/story/templates/leaflet.html:1-4` (unpkg, pinned with SRI).
**What:** If unpkg is blocked or down, both maps are blank; the rest of the page works. **Fix:** Self-host the pinned 1.9.4 files (keeping SRI), or add a visible fallback note.

### A25 · P3 · No security headers
**Where:** `deploy/Caddyfile.snippet:2-6`; `app/main.py:168-193`.
**What:** Only HSTS and `-Server`; no CSP, `X-Content-Type-Options`, `Referrer-Policy` or `X-Frame-Options`. **Why it matters:** without auth the clickjacking risk is low, but a judge or reviewer may check, and a CSP would harden the inline JSON and scripts. **Fix:** Add a minimal CSP (self, unpkg for Leaflet, CARTO/OSM tiles) plus `nosniff` and `Referrer-Policy`.

### A26 · P3 · The copy button can fail silently
**Where:** `app/ui/story/static/copy.js:13-17`.
**What:** The clipboard promise has no `catch`; a denied permission leaves the button unchanged. **Fix:** Add `.catch` and a fallback that selects the text.

### A27 · P3 · The working page's live region is cleared and re-filled
**Where:** `app/ui/story/static/working.js:49`.
**What:** On the first streamed step the list is emptied and the steps re-added, so screen readers may re-announce. **Fix:** Append only steps after the server-rendered ones, or announce via a status line.

### A28 · P3 · The map has `role="img"` around focusable controls
**Where:** `app/ui/story/templates/result.html:247`, `start.html:101`.
**What:** Leaflet injects focusable controls into a container whose role makes descendants presentational to some AT. **Fix:** Use a labelled figure/region with a separate text description, or remove the role.

### A29 · P3 · `<legend><h3>` is invalid HTML
**Where:** `app/ui/story/templates/start.html:47`.
**What:** `legend` takes phrasing content. **Fix:** Use a `span`/heading outside the legend.

### A30 · P3 · Dead fields
**Where:** `app/agent/results.py:46` (`steps` saved at `pipeline.py:397`/`:464` but never read; it also holds Qloo titles in the private cache); `app/views/models.py:146` (`examples_heading` unused by story, which hardcodes “Read a finished story” at `start.html:30`).
**What/why:** dead weight and a place for Qloo data to accumulate. **Fix:** Drop them, or show the step log on the result if it is meant to be there.

### A31 · P3 · 404s are raw JSON
**Where:** `app/main.py` (`HTTPException` at `:227`, `:231`, `:244`, `:605`).
**What:** A judge bookmarking `/runs/{id}` after a restart, or mistyping `/result?animal=…`, sees `{"detail": ...}` instead of the styled notice. **Fix:** Add a 404 handler that renders `notice.html`.

### A32 · P3 · The location field can send a street name to Qloo
**Where:** `app/custom_location.py:34-55`, `:101-103`.
**What:** Digits are refused, but “Main Street” passes though the hint says “never a street address”. No personal data (no number), but the copy overpromises. **Fix:** Reject street suffixes or soften the hint.

### A33 · P3 · The deploy script's default network is another project's name
**Where:** `deploy/deploy.sh:25` (`<another project's network>`).
**What:** A real internal project name in a public repo. **Fix:** Use a neutral default and require `PROXY_NETWORK`.

## Top 10 changes for the ten days left

1. **Make the repo public and set About** (description, website, MIT), after pruning/scanning the 13+ branches. — S
2. **Scrub Qloo response data from tracked files**: delete the unused heatmap, replace the geohash table, crop/blur the screenshot descriptions/addresses — or get Qloo's written OK. — S/M
3. **Switch the demo to the paid model** and verify one live area + listing. — S
4. **Re-check the volunteer's edit against the record** (not just cautions). — M
5. **Enforce cross-animal reference uniqueness** (title/character, not just name). — M
6. **Fix the `scripts/*` `log.add` wrapper** so the documented example rebuild works with the classifier on. — S
7. **Fix the add-animal form** to keep its input and add `maxlength` to facts. — S
8. **Handle partial/degraded Qloo answers and cap the agent's Qloo calls** per run. — S/M
9. **Protect the demo from free-run/CSRF and photo-memory DoS**: prune `RUNS`, rate-limit POSTs, cap photo bytes. — M
10. **Add a 1440×900 screenshot, favicon/OG tags, and do the docs pass** (A18, A19, A21, A22). — S

## Checked and clean

- **Tests and lint:** 621 tests pass; ruff and format clean; CI runs the same commands on Ubuntu with the lockfile.
- **Secrets:** no key/token in source, templates, static files, fixtures or prompts; `.env.example` holds names only; `.env` is ignored; `MAP_TILES_KEY` is never committed (a search for the key finds nothing); only fake keys in tests; the live basemap key appears in `/api/start` by design (public, domain-restricted).
- **Qloo data containment (text):** no real UUIDs, envelopes or databases in tracked text; synthetic fixtures use invented IDs; the cache/recordings live in `var/`; exceptions are A2/A20.
- **Qloo access:** every call goes through `qloo exec` via `QlooClient`; no direct HTTP to Qloo from Python; the harness env is passed; every success is cached; errors are not; spacing is cross-process; retries happen only when `retryable` is true; `rank` gets its two retries. Only Photon and TypeSafe are called over HTTPS, both by design.
- **No personal data:** Qloo receives cultural entities and place names; the classifier receives a title's name, kind and Qloo's description; no accounts; the picked spot stays in the session and Qloo gets the area's name.
- **Listing rules:** the bio is checked sentence by sentence against cited facts, every fact other than the look is used, 150 words max, a short bio says so; the confirmed checks come from fixed code sentences; bite history and guarding are always appended; the hook is built by code; name reasons may use only the record's look; names pass the screen (blocklist, villains, real people, identity, unflattering) with the bully-type branch; one name per title; the litter rule; the approval re-checks cautions and taken names; A4/A5/A16 are the gaps.
- **Provenance:** view models carry Qloo's answer and Namesake's reading in separate fields; every skin labels them (“Qloo:”, “Namesake's AI:”, “Namesake:”, “Qloo returned”, “How Namesake read it”); venue descriptions sit on the Qloo line; name titles carry the Qloo pill; the map caption counts match the JS colours (tested); A12/A15 are the thin spots.
- **UI:** three skins; the contract test runs all three; fonts are self-hosted with OFL; the UI never calls Qloo, the agent or the cache; the tile URL is a view-model field and the story scripts read it from the page; the CARTO fallback is exercised in node; reduced motion, focus rings, dark mode and 480/600/720/960 breakpoints are present. I computed the text pairs: the lowest is white on the Qloo pill at 4.98:1, the rest are 5.1:1 or better; field borders reach 3.3:1.
- **Forms and inputs:** refine 3–200 chars; approve 1–3,000 with cautions and taken names; add-animal fields, yes/no/unknown checks and photo types; custom location refuses digits/underscores and caps length; uploads are size-checked before parsing; A4/A9/A32 are the gaps.
- **Sessions and cookies:** server-made IDs only, `__Host-` over HTTPS, `httponly`, `samesite=lax`, `secure`, two-hour TTL, 500-cap, no fixation; photos are magic-byte checked, kept in memory, served only to the session with `no-store`/`nosniff`; A11 is the capacity gap.
- **Limits, runs and SSE:** the per-visitor and daily counters are atomic, the location check reserves its slot and refunds a cached answer, saved results are free; the step log gives every step exactly once, the error precedes `done`, private runs are hidden from other visitors; A10/A27 are the gaps.
- **Deployment:** pinned GitHub actions and harness, rollback of source/compose/env/image, `/health` and proxy checks, a pinned host key, `.env` never written from CI, `var/` private mode 700; A25/A33 are the gaps.
- **The live demo:** `/`, the four example results, `/api/results/...`, `/api/start`, `/health`, and `?ui=warm`/`?ui=classic` all return 200; a bad animal returns 404; I made no POSTs. The README screenshot's first venue badge matches the live data, and the four examples open instantly.
- **Claims:** no “faster adoption”, “saves lives or money”, or “matching” in the README, Devpost text or UI, except the explicit disclaimers and the trial design; the wording is aggregate (“people in this area tend to like…”); the evidence review is careful and flags its own limits. I did not re-verify the external papers.
- **Agentic requirement:** the model chooses `describe`, `find_local_titles`, `rank`, `find_venues` and `look_up_lookalike`, reads the answers and adapts; fixed calls are in code. This passes the theme check.

**Not done:** no live POST, model, Qloo or classifier call; no ssh; no `var/`, `.env` or `~/.qloo` file opened; no phone/AT or screen-reader run; no independent check of the cited papers.

