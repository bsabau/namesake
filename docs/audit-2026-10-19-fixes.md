# What to fix, from the final audits (19 October)

Merged from two audits of `main` at `a163ba7`:
- [`audit-2026-10-19-fable.md`](audit-2026-10-19-fable.md) (Fable 5.1, xhigh): IDs **F1–F28**
- [`audit-2026-10-19-flash.md`](audit-2026-10-19-flash.md) (DeepSeek Flash): IDs **D1–D33**

GPT-6-Astra ran out of usage partway and wrote no audit.

**Size:** S is under an hour, M is a few hours. **Checked:** the claim was confirmed against the code or the live site, beyond the auditor's word.


## Status (19 October, evening)

Done and live, each reviewed by muse and DeepSeek Flash (Codex was out of usage) and merged:
- #42 model fallbacks (Muse, then Claude Opus 5.5, then DeepSeek Flash), timeouts, the rebuild script fix
- #44 example quality and rules (sections 1 and 4)
- #45 the agent's work on saved results (section 2)
- #46 hardening (section 3)
- #47 copy, docs and accessibility (section 5)
- #48 and #49 screenshots and the map wording they exposed (section 6)
- Example rebuild 7 on the server (12 live Qloo calls), after #45

Changed from the list: the paid-model item became fallbacks behind Muse (decision 25); "Label the character as the AI's reading" was left out, since the character already sits on the "Namesake selected" side (decision 27).

Still open, for the author: the video, making the repo public (with the branch cleanup), and the optional outside voice and outreach channel.

## 1. Example quality (judges open these first)

- [x] **Species-aware venue and map signals.** The lead dog's places and map come from cat shows ("ranked for fans of Nature Cat, My Cat from Hell and Bluey"). Prefer titles whose classifier verdict matches the species, in `evidence_order` and `find_venues` and for the map, and tell the AI the same. F1 · M · checked on the live page.
- [x] **Screen a title's own name.** The Park Slope litter is named after *My Cat from Hell*, and the hook reads "a cat in My Cat from Hell". Make `check_title` refuse the blocklist, the unflattering words and "hell", "from hell", "nightmare", "worst"; add the rule to the instructions and to `open_title`. F2 · S · checked (rebuild 6 output).
- [x] **Run the hook check on the character only, not the title span.** *The Call of the Wild* or *Must Love Dogs* trips the temperament screen on Qloo's words. F11 · S
- [x] **Name reasons that aren't filler.** "It suits a grey tabby" three times. Make the reason optional, or fall back to "A short name, easy to say." F20 · S
- [x] **Rebuild the four examples** after the items above, then re-pin their places. About 30 Qloo calls, plus model runs on the Go plan. F1, F2, F21 · S (mostly waiting)

## 2. Show the agent's work (technological implementation decides ties)

- [x] **"Searched Qloo's lists with X"** in the Qloo/AI strip and the process steps, when a title was found by the AI's own search. F7 · S
- [x] **The saved run log on the result page**, folded under "Behind this story", reusing the working page's timeline. `ListingResult.steps` is saved but never shown. F7, D30 · M
- [x] **The Why panel's call list includes the agent's calls** (`describe`, the title searches, `rank`), not just the assembly's. F23 · S
- [x] **A "Write her story" button** on a result page with no saved listing (for example `/result?animal=dog-03&location=austin`). F24 · S

## 3. Hardening the live demo

- [x] **Model client timeout:** `timeout=60s, max_retries=1`, plus an overall `wait_for` per agent run; count `TimeoutError` as an agent failure. F6 · S
- [x] **Memory caps:**
  - a global byte budget for photos, and an allowance on `POST /animals`
  - `RUNS` capped and expired after an hour
  - non-multipart POST bodies capped at 64 KB
  - `mem_limit` in compose

  F4, F5, F10, D10, D11 · S
- [x] **Reject cross-site POSTs** with a `Sec-Fetch-Site` or `Origin` check. F18, D10 · S
- [x] **Security headers:** a CSP, `nosniff`, `Referrer-Policy` and `frame-ancestors` in the Caddyfile. F16, D25 · S
- [x] **The rebuild script crashes with the classifier on:** `echo(kind, text)` in `scripts/precompute_examples.py` and `run_agent.py` doesn't take `actor=`. Must be fixed before the rebuild in section 1. D6 · S · checked.
- [x] **Partial or degraded Qloo answers** count as complete in `find_venues`, `look_up_title` and `_look_up`. Treat them as unavailable, or add a note. D7 · S
- [x] **A per-run cap on the agent's own Qloo calls:** title lookups ≤ 4, venue searches ≤ 3. D8 · S
- [x] **The add-animal form keeps its input** on a refusal, with `maxlength` on facts. D9 · S
- [x] **404s render the notice page**, not raw JSON. D31 · S

## 4. Rules

- [x] **Two animals must not share a reference,** only a name: compare the title (entity ID) and the character too, keeping the litter exception. D5 · M
- [x] **Bully-breed markers:** pit mix, pittie, pitty, staffy, staffie, bull terrier, bulldog mix, blocky head; with a test. F9, D16 · S
- [x] **`taken_names` reads every saved listing,** not just current ones. F22 · S
- [ ] **Label the character as the AI's reading** where Qloo confirms only the title ("Bingo, a puppy in *Bluey*"). D15 · S
- [x] **A name from the area's general top tastes shows Qloo's evidence** (its position in the list) and appears in the Why panel. D12 · S

## 5. Copy and docs

- [x] Devpost: "280+ tests" becomes "600+". F12, D18 · S · checked
- [x] Align the names with the story skin in the README, the video script and the start page: "Try an example" vs "Read a finished story", the Why drawer's label, "Get her seen". Let story print `view.examples_heading`. F13 · S
- [x] The posting-time item: say what was measured ("Adoptions cluster on Saturdays and between 5 and 8 pm"). F27 · S
- [x] Label the plan item "Ask X, Y and Z" as "Qloo, picked by Namesake's AI". F19 · S
- [x] Remove the unused `docs/img/yankees-mets-heatmap.jpg`; replace the geohash table in `docs/qloo-findings.md` with counts. F25, D2 · S
- [x] `docs/product.md`: four features the code doesn't have (management suggestions, affinity plus popularity ranking, dropping by lift, name candidate buttons). F14, D19 · S
- [x] AGENTS.md: complete the Layout list. Fix the stale lines: the recordings' file name, "Astoria is untested", the call counts in decisions 1 and 20, the upgrade spacing. Say the JSON API reads the same data rather than "can be built on the API alone". F15, D14, D19 · S
- [x] Fix the README's double parenthetical (line 112). F28 · S
- [x] Fix the hook ending in "!." when the title ends with "!". D21 · S
- [x] Replace "Typed location" as a typed area's region. D22 · S
- [x] `deploy.sh`'s default network `<another project's network>` names another project: use a neutral name. D33 · S · checked
- [x] Favicon (the paw), `robots.txt`, meta description and Open Graph tags. F17, D23 · S
- [x] At phone width the tape covers "AI-" in the photo caption. F26 · S
- [x] Small a11y and HTML fixes:
  - `<legend><h3>` is invalid HTML
  - `role="img"` around the map's controls
  - the copy button has no `catch`
  - the working page re-announces its steps

  D26–D29 · S
- [x] Remove the dead `examples_heading` path, or use it (see the alignment item above). D30 · S

## 6. Screenshot and submission (after sections 1 and 5)

- [x] **A first-screen image at 1440×900** for Devpost (and the top of the README), after the rebuild. Keep the full page as a second image. F8, D13 · S
- [x] **Two neighbourhoods side by side:** the same dog in Park Slope and Astoria, in the Devpost text and one image. Fable's idea lever. · S
- [ ] ~~Record the video from `docs/video-script.md`, after the wording alignment. F top 10 · M~~ Dropped 22 October: Devpost asks for no video, only a demo judges can use.

## For the author

- [ ] **Switch the demo to the paid model** (`AGENT_*` on the host, `deploy.sh --env`), run one live listing, and update README lines 144 and 174. F3, D3 · checked
- [ ] **Make the repo public before the 30th** and check that the About section shows MIT. First:
  - prune the old branches
  - remove `.claude/worktrees/`, which holds a full copy with `var/` and `.env`
  - add it to `.gitignore`
  - scan the whole tree

  D1, D20 · checked (PRIVATE today)
- [ ] **Optional:** one outside voice (a volunteer or rescue that looked at a listing) for the Devpost "What's next". F impact lever
- [ ] **Optional:** a "Research" plan item for an outreach channel to under-represented communities, including non-English ones, as the evidence review recommends. D17

## Not fixing (with reasons)

- **D2, the screenshot as a Qloo data leak:** Qloo allowed names and scores in screenshots, the live app shows the same text, and Fable's scan of the whole history found no response data. The two real cases (the heatmap image and the geohash table) are in section 5.
- **D4, refusing a volunteer's edit that adds facts:** the volunteer is the person who keeps the record. The rule binds what the AI writes. A soft warning could come later.
- **D14, a JSON write API:** reword AGENTS.md and the architecture doc to "read the same data" instead (in the AGENTS.md docs item).
- **D24, self-hosting Leaflet:** it's pinned with SRI on unpkg. Low risk for two weeks of judging.
- **D32, street names in the area field:** no personal data reaches Qloo, so just soften the hint if it comes up.
