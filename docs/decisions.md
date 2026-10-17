# Decisions

Design decisions that shape the code, newest last. Each says what was decided, why, and what follows. The evidence for most of them is in `docs/qloo-findings.md`. The author delegated decisions 1 to 5 on 15 October 2026 ("do this how you feel fit and document the decisions").

## 1. One location profile per location and species, shared by every animal

**Decided:** the Qloo work that depends only on the place and the kind of animal runs once per location and species, is cached, and is shared by every animal there. That covers the pet-themed titles, their local ranking, the venues and the map. Each animal then gets a short listing run: names, bio and hook.

**Why:** almost none of the Qloo answers depend on the individual animal. The key is rate-limited (about 12 calls in 20 minutes when sent in bursts), so a full run per animal would spend about 8 calls to learn nothing new. A shared profile also keeps one shelter's venues and map consistent across its animals.

**Follows:**
- A profile for a new location costs about 8 calls; the presets are precomputed and cost nothing in the demo.
- Profiles are keyed by location and species (`dog`, `cat`), since a dog show and a cat show reach different fans.
- The listing run makes at most a couple of `describe` calls, to check a name's reference.

## 2. Venues: a code screen first, then the agent's judgement, never the agent alone

**Decided:**
- Plain code drops venues whose description matches a fixed list: adult venues, nightlife, hookah and smoke shops, cannabis, firearms.
- The agent then judges the rest for an adoption event or a flyer, and picks about three, each with a stated reason.
- It may only choose from venues Qloo returned. Code rejects any venue ID that is not in the list.

**Why:** the keyword screen is predictable and testable but blind to context. It caught Astoria's hookah lounges but not Austin's sorority houses, which are private residences. The agent reads descriptions well but can be talked into anything, and a free model can be careless. Using both covers each one's weakness. Restricting the agent to Qloo's list keeps every venue traceable to Qloo's evidence.

**Follows:** each chosen venue shows Qloo's rank and the comparison with the baseline (what Qloo returned), separately from the agent's reason (our reading).

**Revised 17 October:** the "stands out" badge is yes-or-no, so a place ranked 15th of 15 for pet-show fans earned it as readily as the 1st. The agent now sees each venue's position in Qloo's list (top, middle or bottom third) and is told to prefer the top, then the middle, and to give a reason when it picks from the bottom. Each venue card states the rank plainly ("2nd of 15 · near the top of Qloo's list"). The author chose this over withholding the badge from low-ranked places.

## 3. Ranking titles: one small `rank` call, with a stated fallback

**Decided:**
- The agent ranks at most 5 resolved titles with one `rank` call per profile.
- If that call fails, the agent keeps its own order and the profile says so.
- It never retries `rank` beyond the client's single retry.

**Why:**
- `rank` with ten options was refused four times in a row, while other workflows sent in between went through. It seems to cost more than other calls.
- Ordering by `recommend` results instead does not work: `recommend` cannot be limited to a given set of titles, so the titles we care about may not appear at all.
- Ranking matters less now that venues and the map compare against a baseline anyway.

**Follows:** a profile records whether its order came from Qloo or from the agent. The Why panel shows which.

## 4. Venues stay a list, not pins on the map

**Decided:** venues are listed with their neighbourhood and address. The map shows the lift cells and the shelter's area only.

**Why:**
- Qloo returns no venue coordinates; `describe` on a place returns only its ID, name and type.
- Pins would need an outside geocoder: another dependency, another failure point, and another service to name in the README.
- The evidence that matters, each venue's rank and its comparison with the baseline, is text anyway.
- The result screenshot already has a map.

**Follows:** revisit in milestone 4 only if time allows. If done, geocode at profile-build time with a cached, rate-respecting service, never from the browser.

## 5. Agent-chosen Qloo calls go through our client, not `qloo mcp`

**Decided:**
- The agent's Qloo tools are PydanticAI function tools that call `QlooClient`, which runs `qloo exec`.
- They are not tools attached from `qloo mcp`.
- The model still chooses which calls to make and with what input.

**Why:**
- Calls made through `qloo mcp` would bypass the cache, the recordings, the spacing between live calls, and replay mode. That breaks the rules that every live result is cached and that tests never reach Qloo.
- With function tools, every agent call is cached, spaced, recorded for replay, and can be faked in tests.
- Function tools can also return a trimmed, typed view of each answer instead of the full envelope, which suits a small model.

**Follows:**
- The theme requirement still holds: the model decides what to look up and what to do with the answer.
- `qloo mcp` stays available for exploring by hand. `AGENTS.md`'s stack table now names the client.

## 6. Native structured output, and OpenCode Go's session headers

**Decided:** both agents return their typed output as native JSON-schema output, set by `AGENT_OUTPUT_MODE` (`native`, `prompted` or `tool`). Every model request sends `x-opencode-session` with a fresh ID per agent run, and a `namesake/0.1` user agent.

**Why:**
- The development model (muse-spark through OpenCode Go) accepts only `tool_choice: "auto"`. PydanticAI's default tool-based output asks for `"required"` and is refused.
- Native output worked first time: a tool call plus typed output in about 5 seconds. Prompted output also worked, but was slower.
- OpenCode Go refuses direct API calls without a session header. Its documentation allows calling it directly, provided each conversation sends a stable session ID and the client uses its own user agent. Endpoints that are not OpenCode ignore both headers.

**Follows:**
- The paid model chosen in milestone 5 can use whichever mode suits it, by changing the setting.
- OpenCode Go is designed for coding-agent traffic. That is one more reason the judged demo runs on a paid model, as planned.

## 7. Code writes the risky sentences; the model only restates facts

**Decided:**
- The listing agent writes the bio from the temperament, look and recorded facts only. Every fact must appear, and no word may appear that the cited facts lack. That includes new negations, and anything about children, other animals, house-training or bites.
- The sentences for the shelter's confirmed checks (children, dogs, cats, house-training, bite history) come from fixed templates appended by code.
- The hook is built by code from the first name's reference: "Named after Bingo, a puppy in Bluey."
- Each name's reason must restate the facts. Its reference must name its title. A name already given to another animal at the same shelter is refused, except within a litter.

**Why:** the review of milestone 3 showed that word-overlap checks alone could not stop a model from contradicting a fact ("no bite on record" when a bite was recorded; "aggressive" citing "strong but gentle") or from making claims in the hook and the reasons. The safest sentence is one the model never writes. The rest are held to the facts' own words: both real drafts already met that standard, so the cost in quality is small.

**Follows:**
- A bite on record is always stated, in the same words.
- The agent's bio can be stiff when the facts are few, which is the honest outcome.
- The hook can never describe temperament or tastes.

**Tightened after review (15 October):**
- Each cited fact must appear word for word, phrase by phrase. The temperament and look are split at their commas, semicolons and colons. That stops reordering ("guards toys but not food") and slipped-in conditions ("but not when she has toys").
- A name's character is a proper name: capitalised words, plus the joining words names use, such as "Puss in Boots".
- Code writes the reference from that name, a role from a fixed list, and Qloo's title. The hook therefore carries no description written by the model.

**Remaining risk, stated plainly:** checking text by rule cannot prove that the meaning was kept, only that the words were. The rules make the safe path the easy one: copy the shelter's phrases, add only joining words. A volunteer still reviews the listing before using it (milestone 4 adds approval).

## 8. The generic version gets a plain pet name, so the toggle isolates Qloo

**Decided:** both versions share the bio. The generic version is named from a fixed list of common pet names (`GENERIC_NAMES` in `app/listing.py`). The local version uses the agent's name from Qloo's titles and adds the one hook line. The volunteer picks a version with the toggle, and approval records which one.

**Why:**
- A real listing needs a name, and the demo animals have none.
- If only the local version had a name, a trial would compare "named" against "unnamed". With a name in both, the difference is exactly what Qloo adds: where the name comes from, and the hook.
- The list has no human first names, so it is safe for every dog, including the strictest screen. A test runs every name through that screen.

**Follows:** the generic name skips names already given at the shelter. It is picked by the animal's place in the roster, so it stays the same between visits.

## 9. What a visitor does stays theirs; shared results are never changed by a visit

**Decided:**
- Refined listings, added animals and their photos live in an in-memory session behind a random cookie. They are never written to disk and expire after two hours, or on restart.
- The cookie is set only when a visit has something to keep. Its ID is always made by the server: an ID a client presents is used only if the server issued it. Over HTTPS the cookie takes the `__Host-` prefix, so a sibling subdomain cannot plant one.
- Precomputed and shared listings change only through a run for an animal that has none, or through `scripts/precompute_examples.py`.
- Approval records the approval ID, animal, area, version, name, the name's source, whether the text was edited, and the time. The text itself is never recorded. An added animal is recorded by its random ID, which identifies nothing outside the visit.

**Why:** the demo has no accounts, and every judge sees the same examples. If one visitor's "less childish" overwrote the shared result, the next visitor would see it. Keeping the text out of the log keeps free text, which could contain anything, out of storage. The trial needs only the version and the name.

**Follows:**
- Photos are checked by their first bytes (JPEG, PNG or WebP, at most 3 MB). They are served only to the session that added them, with `no-store`. No model ever sees them.
- Uploads stay in memory: Starlette's spool limit is raised above the largest accepted request, and larger requests, or ones without a declared size, are refused before they are read.
- A run over an added animal or a refined listing, its Working page and its event stream are visible only to the session that started it.
- An added animal's facts go to the model, never to Qloo. The listing checks hold them to the same rules as the roster's facts.

## 10. A volunteer's edit may reword a listing, never drop a caution

**Decided:** approval is refused if the edited text no longer contains the cautions the shelter recorded, word for word:
- each confirmed "no" (for example "would do best in a home without cats")
- a bite on record
- any recorded phrase about biting, nipping, guarding, growling, snapping, snarling, scratching, swatting, lunging, aggression or resource guarding, in any form ("guarded", "lunges")

The refusal keeps the edit and names the missing words.

**Why:** "a bite history or guarding is stated plainly, every time" applies to what leaves the app, and the volunteer's edit is the last step before posting. Overselling is the harm the evidence review found.

## 11. Limits on live work, and nothing else

**Decided:**
- Saved results open freely.
- Live work is limited: each visitor may start 6 new runs or location checks an hour, counted in memory by client address. The whole app may start 60 new runs and check 10 new locations a day, counted in SQLite so a restart does not reset them.
- All of these numbers are settings.

**Why:** the hackathon key's quota is unknown and the development model is a coding plan. A judge clicking around must never exhaust either. The daily caps protect the quota even if per-visitor counting is fooled, for example behind a shared proxy.

**Follows:**
- Only work that can reach Qloo or a model is counted. With no model and Qloo in replay, a run is a free fallback.
- A location check is tried against the cache first. An answer Qloo gave before, even a thin or ambiguous one, is free. A check that needs Qloo reserves its slot before the call, so two at once cannot both pass a cap. The slot is given back if no live call was made.
- Reopening an added animal's result, kept in the session, is free like any saved result.
- uvicorn runs with `--proxy-headers`. `FORWARDED_ALLOW_IPS` is the IPv4 subnet of the proxy's Docker network, so the client address is the real visitor's. Revised 17 October: Caddy's own address changes when its container restarts, so the whole subnet is trusted; any container on that network could forge a visitor address and dodge the per-visitor limit, while the daily caps still hold. Acceptable on a host with one operator (`deploy/README.md`).

## 12. A typed location goes to Qloo as typed, and is checked once before any run

**Decided:**
- One fixed call checks a typed area: the baseline title's heatmap within it. The profile later makes the same call, so the check costs nothing extra.
- Five or more cells: the area is accepted. Its map centre and zoom come from the cells.
- Fewer cells: the app says the data is too thin and stops.
- `needs_input`: Qloo's candidates become buttons.
- Text with digits is refused, which keeps street addresses away from Qloo.

**Why:**
- Qloo returns no coordinates for a place name.
- Its locality lookup (`describe` with type `locality`) did not help. Probed live on 15 October:
  - "Springfield" gave five candidates all named "Springfield", with no state.
  - "Springfield, IL" and "Williamsburg, Brooklyn" still came back ambiguous, mixed with unrelated places.
  - Describing a candidate by ID returned only its name.
- Buttons that all read "Springfield" would not help anyone. The heatmap tells us both whether Qloo has data there and where "there" is.

**Follows:** accepted areas are kept in the store, so typing the same text again costs nothing. A new area's first run builds its profile, at about 8 Qloo calls.

## 13. A litter is named as a set by the first member's choice

**Decided:**
- A litter run builds one profile, then writes each member's listing in turn.
- All of the first member's name options come from one title, which becomes the litter's title.
- Every later member may draw names only from that title, and no name repeats within the litter: a litter shares a title, never a name.
- Members already named are kept, and their title is followed. Naming the litter again only fills the gaps, and so does writing or refining one member on its own. Only `scripts/precompute_examples.py --force` rewrites them.
- Approval refuses a name another animal at the shelter has, whether it is that animal's saved first name or a name approved for it. Every name check, for the agent and the generic list too, counts approved names as taken.
- Names approved for an animal a visitor added count only within that visit: they bind the visitor's other animals, never the shared roster or other visitors.
- The generic name is approved only as the volunteer saw it. If another animal took it meanwhile, approval is refused instead of quietly recording a different name.
- When every generic name is taken at a shelter, the generic version says so instead of reusing one.

**Why:** "two animals in one shelter never share a reference, except a litter named as a set." Letting the first listing choose keeps the agent's judgement, and restricting the others to one title is a check code can enforce: a name from another title is refused like any invented ID.

**Follows:** a member whose draft cannot be fixed falls back to the template, as any listing does. The result page lists the litter's names with links.

## 14. Lookalike names: titles with an animal that looks like this one

**Decided** (the author agreed on 17 October):
- The listing agent may look up one or two films, TV shows or books with an animal that looks like this one, through a `look_up_lookalike` tool over `QlooClient` (`describe`, cached and spaced like every call).
- It must quote the shared look from the animal's recorded `look`. Code refuses the lookup, before any Qloo call, when a quoted word is not in the record, or when the words are only ones every animal of that size shares ("large", "mixed breed").
- Only films, TV shows and books: a story with an animal in it. Brands are left out.
- A found title gives at most one name: that animal's own, with an animal role. Code checks both the offered name and the character against the animal the agent looked up. The name may shorten it ("Scooby" for "Scooby-Doo") but never add to it ("Rex the Brave" for "Rex"). The character keeps a two-way match, since a story may use a longer or shorter form of the same name.
- Any `needs_input` answer is a choice, even with one candidate: the name needs a stated reason, and the Why panel says the agent chose among Qloo's candidates instead of "found in Qloo". The reason may only say which work it is; a taste claim or a temperament word is sent back, for the profile agent's title choices too.
- The name is offered as an option with the badge "Has a lookalike in <title>". It is never the first name, so the local version still shows what the area's taste data adds.
- The strict screen for bully-breed dogs allows lookalike names, since they must be an animal's own name.
- Not used for a litter, which is named as a set.
- The Why panel shows what Qloo returned for the title, and separately the agent's reading of the match. It says Qloo confirmed the title (or, after `needs_input`, that the agent chose it among Qloo's candidates), never how its animals look.

**Why:** the area's titles are chosen per location and species (decision 1), so they know nothing about the individual animal. A lookalike makes a name personal at one or two cached calls per listing, without making the venues and map per animal, which would cost about 8 calls each. Matching on the recorded look only, never breed reputation or temperament, keeps it within the listing rules.

**Follows:** a live listing run costs up to two more Qloo calls. Qloo says nothing about local strength for these titles; checking that (a heatmap against the baseline) would be one more call each and is left for later.

## 15. No tone setting: the listing rules fix the voice, and the refine line takes follow-ups

**Decided** (17 October, closing a finding of the codebase audit in `docs/audit-2026-10-17.md`):
- The start screen has no tone setting. The words are struck from the screen list in `AGENTS.md`; `docs/product.md` never had them.
- The voice of every listing is set by the listing rules: third person, plain words, behaviour toward people first, the animal as it is now, no pity or urgency, and nothing beyond the recorded facts. Those rules apply to the generic and the local version alike, so a tone control would have nothing to move that the rules do not already fix.
- A volunteer who wants a listing worded differently uses the refine line on the result screen ("less childish"), which reruns the listing within the same rules. That covers the one case a tone setting was for, per result and without a second setting to explain.

**Why:** the evidence review (`docs/research/adoption-evidence-review.md`) found tone was not associated with engagement in the one study that measured it (Morrison 2024) and lists the effect of a listing's tone on returns as an open question. A setting with no evidence behind it, and no design in `docs/product.md`, would add a choice to the start screen that the judges and volunteers would have to understand, for no measured gain. The audit rated the gap major only because the brief and the design disagreed; this entry makes them agree.

**Follows:** the start view model, the form and the JSON API stay as they are. If a tone experiment is ever wanted, it belongs in the measurement design first, as a recorded variant, and only then on the screen.

## 16. Saved listings are rechecked, not rerun, when only the record checks change

**Decided** (17 October, from Codex's review of milestone 5):
- A saved listing is shown only if it was held to today's checks (`CHECKS_VERSION` in `app/agent/results.py`).
- When the checks change, `app/agent/recheck.py` re-runs the record checks, the bio and the names' reasons, on every saved draft. A draft that passes is saved as current; one that fails runs again when next opened. `deploy/deploy.sh` runs it on every deploy, before the new version starts.
- A recheck covers only those checks, since they need nothing but the animal's record. Drafts saved before the last change to any other check (the name screen, lookalike names) are rerun: `PLAIN_LISTINGS_FROM` and `LOOKALIKE_LISTINGS_FROM` say how far back a recheck is enough.

**Why:** version 8 allowed "puppy" and "kitten" only for an animal under a year. Saved drafts from before were never held to that. Rerunning every one would cost a model run each and leave the start page's examples to run live during judging. Of the 14 saved drafts, 13 passed the recheck; the 14th, from version 5 with a lookalike name, was already set to run again.

**Follows:** a change to any other check must raise those floors, or a saved draft that skipped it is shown.

## 17. The shelter's spot from the map: the pin stays in the visit, Qloo gets the area's name

**Decided** (the author, 17 October: point at the shelter on the map, "so we can use the neighbourhood after that"; Photon chosen as the geocoder):
- Right-click on the start map (long-press on a phone) offers the areas that spot lies in, most local first ("Williamsburg, Brooklyn", "Brooklyn, New York", "New York"). Choosing one sends that name through the custom-location check exactly as if typed (decision 12).
- The spot itself is that visit's pin: kept in the session, never stored or shared, never sent to Qloo, and drawn on the start and result maps with a note saying so. A pin more than 15 km from the area Qloo checked is dropped, so the result map stays close enough to read.
- The location field suggests area names as you type, ranked near the area on the map.
- Both lookups go through the app's own `/api/places`, which asks Photon (OpenStreetMap data, no key) for areas only and never shows an address. Typed text the location field would refuse (digits, so street addresses, or anything but a place name) is never sent. A picked spot is rounded to about 100 m in the browser already, so the exact spot stays out of URLs and logs; the ranking point to about 11 km; the pin kept in the visit to about 10 m.
- Answers are cached in memory. Only a call that reaches Photon counts: 30 a minute per visitor and 120 for everyone together, at most 4 at once, and a call that waits too long for one of the 4 counts for nothing. Both allowances live in the one server process and see visitors through the proxy's forwarded address (decision 11); a second process would double them.
- The pick is right-click or long-press only. A keyboard user chooses the area by typing, with suggestions, and gets the same check and listing, but no pin.
- A spot is named from the nearest object's address (its neighbourhood, district and city), never from the object: asked for areas only, Photon's nearest "area" in Williamsburg was a power station.

**Why:** Qloo's heatmap takes an area by name, not a point, and an address adds nothing it can use. A shelter's location can be a foster's home, so the exact spot stays with the visitor (AGENTS.md: no personal data to Qloo). Photon is free and built for type-ahead; if it is down or throttles, the field works as typed, so the demo never depends on it.

**Follows:** Photon's public server promises no uptime; swapping it is one setting (`geocoder_url`) and one module (`app/places.py`). Its terms ask for fair use, which the cache and the per-visitor allowance keep to.

## 18. The map combines the top pet titles; the baseline is the area's own top shows

**Decided** (the author, 17 October: "lets go with combined layer", and for the baseline "Local top shows instead"; profile version 2):
- The map layer is the top two pet titles (those the venues were asked for first), each heatmapped within the area and averaged per cell over the maps that scored it. It was the first title alone, so the map only ever said "fans of Bluey".
- The baseline is the two TV shows Qloo ranks highest for people around the area (the `recommend` already made for local tastes), leaving out any title Namesake's AI picked as a pet title and any show whose name or description is about animals. It replaces the single seed show, Yellowstone, which was arbitrary. Venues are compared with one `recommend` for the two shows' fans; the map cells with their two heatmaps, averaged the same way.
- The map carries a short key ("What the colours mean") drawn on the map; the caption keeps the long legend. The map and the step log name no baseline title: the Why panel lists them, as Qloo returned them, in the "people here tend to like" wording. Some of an area's top shows are identity-coded, and the map is no place to imply anything about who lives where.
- The seed show stays only as the probe that accepts a typed area (decision 12).
- Saved profiles carry a version. Version 1 profiles still load and render as they were; `python -m app.upgrade_profiles` brings them to version 2 without rerunning the AI, so titles, names and listings stay valid, and saves only a complete result.

**Why:** a baseline chosen by us was the weakest part of the comparison: "stands out" meant "not on Yellowstone's list". The area's own top shows ask the question a volunteer cares about, where pet-show fans differ from this neighbourhood's usual tastes. Two titles each way, not three, because each is one more `where_popular` per area and the key is refused after about 12 calls in 20 minutes: a new area now costs about 11 calls (decision 1 said about 8).

**Follows:** Qloo's `trends` was considered for a "rising lately" signal and dropped: it has no location, returned nothing for July to October 2026, and was flat for 2025 (`docs/qloo-findings.md`).

