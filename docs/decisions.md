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
- It never retries `rank` beyond the client's retries. Revised 18 October (decision 20): the client gives `rank` two retries after a rate limit, 20 and 40 seconds apart, because a refusal costs the titles their order and one retry after 5 seconds was not enough at the 2-second spacing; still never more, and only when Qloo marks the error retryable.

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

**Revised 18 October:** the probe is the area's own most-watched TV show (the profile's local-tastes call, so it is cached for the profile), and the seed show as well when that list is not a plain answer or its top show has too few cells, the seed's candidates or failure speaking for the place, else the fuller map deciding. A US seed show alone made neighbourhoods abroad look thin: Gràcia, Barcelona had 2 cells for *Yellowstone* and 20 for its own top show (`docs/qloo-findings.md`). About two calls a check, three when the top show is thin there (the seed show's `describe` is cached after the first time). A list that is not cached while live calls are off makes the check "unavailable", so it is tried live later instead of refused from the seed show's map alone. Passing now says Qloo has data for the area, not that its pet titles map well; the result page says when the map is thin.

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
- The seed show stays only as the fallback probe for a typed area (decision 12, revised 18 October: the area's own top show probes first).
- Shows whose name or description mentions a religion, race or politics are left out of the comparison too (18 October, after a live run for Hoboken took a documentary about a president's portraits): the Why panel names the comparison as what people here tend to watch, and that must not read as a claim about who they are. The test is decision 19's `identity_coded` plus everyday category words for descriptions only (`mentions_identity`); it is a word list, so the page says "mentions". The next show down takes the place. A saved profile whose comparison fails it is finished again by the next visitor's run or `app.upgrade_profiles` (`needs_finishing`): fixed calls only, the AI's titles and venues kept, about three live calls for the new comparison's venues and maps, asked again on each run until they arrive. Until then the page does not name the failing show.
- The baseline is fixed before Namesake's AI runs, so its venue choices are judged against the comparison the page shows; a baseline show is refused as a pet title or a venue signal. When Qloo's list of top shows is not a plain `ok` (partial, degraded, `needs_input`), or every top show mentions animals, a religion, race or politics, the seed show stands in, and a note says so.
- A profile is complete when every map arrived and the venues were compared. An unfinished one is still saved, so a listing made from it keeps its titles' evidence, and the next run finishes it around the same titles with fixed calls only (`finish_profile`); cached calls cost nothing. The map asks for the first pet title, then the baseline, then the second pet title, so a refusal at the end costs an extra title, not the comparison.
- Saved profiles carry a version. Version 1 profiles still load and render as they were; `python -m app.upgrade_profiles` brings them to version 2 without rerunning the AI, so titles, names and listings stay valid, and saves only a complete result. It is run on the host after the deploy, and spaces calls at least 120 seconds apart whatever the setting says (`deploy/README.md`).

**Why:** a baseline chosen by us was the weakest part of the comparison: "stands out" meant "not on Yellowstone's list". The area's own top shows ask the question a volunteer cares about, where pet-show fans differ from this neighbourhood's usual tastes. Two titles each way, not three, because each is one more `where_popular` per area and the key is refused after about 12 calls in 20 minutes: a new area now costs about 12 to 14 calls (decision 1 said about 8), most of them cached once made.

**Follows:** Qloo's `trends` was considered for a "rising lately" signal and dropped: it has no location, returned nothing for July to October 2026, and was flat for 2025 (`docs/qloo-findings.md`).


## 19. The name screen checks real people and identity-coded references in code

**Decided** (the author, 17 October, after a review of `docs/architecture.md` found these two screens were model instructions only, while the README and AGENTS.md promise a screen; "1st option": fix the code rather than the wording):
- A name, or the character it refers to, is refused when it is on a short list of famous real people, or on a list of words coded to a religion, a race or a political identity. The model can also declare a name's role as "person", which is refused; before this the code checked a role the model could not choose.
- The title a name comes from is screened as Qloo returned it. A title whose name or description marks it as about real people (a talk show, reality show, documentary, biopic, memoir and so on) gives only animals' names: Marley in a memoir about a dog, never the author. A title coded to an identity gives no names. Descriptions name the cast, so they are searched only for words nobody bears as a name but the figure itself: the first dry run on saved listings refused every kitten's name from The Aristocats over the voice actor Phil Harris. A refusal names the category, not the matched word, because the step log is shown to visitors.
- There is no list of human first names for bully-type dogs: that screen stays a rule on sources (pet-themed and lookalike titles only), since a list of names perceived as Black would itself be the stereotype.
- Checks version 9. The deploy's recheck applies the screen to saved listings with their saved profile's titles, so no live call; a listing whose titles are gone runs again. On a copy of the local cache, 13 of 14 saved listings passed and stayed current.

**Why:** "screens names" is one of the four claims the README and Devpost text may make, and the published penalty for some names on pit-bull-type dogs is the reason for it. A claim judges can check should rest on code they can read, not on a prompt.

**Follows:** lists cannot be complete. The model is still told to avoid real people and identity-coded names, and the volunteer chooses and approves; the lists catch the famous cases when the model does not.

## 20. Pet titles from the area's own lists, sorted by a classifier; the Qloo spacing revisited

**Decided** (the author, 17 October, after the probes in `docs/qloo-findings.md`: "lets do it now, also the limit change"):
- Namesake's AI gets a fourth tool, `find_local_titles`: for one of its found pet titles and a kind (TV, films, books), `recommend` with that title as the signal plus `signal_location`, 20 results: what people around the area who like it also like. Up to three searches per profile. The titles found join the AI's own in the one `rank` call for the area, now up to 8 titles.
- TypeSafe's Jev sorts the results: for each title, the probability that pets are central, that it is about dogs, cats or real people, and that it suits a family audience. Code keeps a title at pets ≥ 0.8 and family ≥ 0.6, sets it aside at pets ≤ 0.3, and leaves the rest to the AI, which judges from Qloo's description. Titles set aside are never offered to the AI's plan. Without `TYPESAFE_API_KEY` the classifier is off and the AI judges all of them.
- Jev gets a title's name, kind and Qloo's description, nothing about a visitor, an animal or a place. Answers are cached in SQLite by the title as described (name, kind and description), the questions and the model, so a title is classified once; any failure of Jev or its cache leaves the title to the AI, and after the first failure a run stops asking. Its privacy policy says inputs are not used for training; retention is "as long as reasonably necessary", and it is hosted in the US.
- A pet title coded to a religion, race or political identity is refused by `check_plan`, with the word lists of decision 19 (the area's lists carry such titles). A title the classifier marks as about real people (≥ 0.8) gives only animals' names, like one whose description says so (checks version 10).
- Revised 18 October: the AI no longer picks which titles the venues are asked for. It sends the titles it keeps, and code takes the top three by evidence: Qloo's ranking for the area first, then titles found in the area's lists by their place there, then the AI's order (`evidence_order`). A place is the title's position as a share of its list, so lists of different lengths sort together; lists from different searches are not strictly comparable, so this is the fallback for when the ranking is refused. A title keeps its best place across the area's lists: where it was found, or a better place in a later search, which is also where a title the AI proposed keeps its place (`listed_in`); the Why panel shows it; the search's own signal earns no place in its own list. An identity-coded title is never a venue signal (`check_plan` would refuse it). The map's two titles follow the same order; `find_venues` tells the AI which titles it used, and `check_plan` refuses a plan that leaves one out. In Hoboken the ranking was refused, so the AI's first three went to the venues and PAW Patrol, with one map cell there, led the map, while Nature Cat, 9th in Hoboken's own list, was used for neither.
- Qloo's `recommend` answers give only the generic type `urn:entity`, so a found title, and each of the area's top shows, takes the kind that was asked for (`entity_type`); Jev reads that kind too. For profiles saved before this, the page takes the kind from where the title was found, else "TV show" (a lookalike, which may be anything, reads "title") (18 October: the Why panel printed "Nature Cat (urn:entity)"). The Why panel's line about the venues names the titles they were asked for, not every pet title.
- The page shows where each found title came from ("3rd of 20 in Qloo's list of TV shows people around Austin who like PAW Patrol tend to like") in Qloo's column of the Why panel, and the classifier's scores in the reading column, with a credit in the footer. A name from a found title is badged "liked here by fans of PAW Patrol".
- The Qloo spacing dropped from 5 to 2 seconds (`QLOO_MIN_INTERVAL`), and the profile upgrade's from 120 to 10: 30 calls 10 seconds apart passed on 17 October. On 18 October `rank` was refused at 2 seconds in a live run for Hoboken, even after its retry, so the default went back to 5; a rate limit now waits 20 seconds before the retry, and `rank`, which runs once per profile, gets a second retry after 40. Both spacings are settings; `deploy/make_env.py` now passes `QLOO_MIN_INTERVAL` and the `TYPESAFE_*` settings to the host.

**Why:** the AI proposes titles a broad US audience knows, so its list does not change with the area; only the ranking reorders it. Searching from its titles into the area's own lists finds pet titles that are strong there: in one recorded run for Austin the two titles Qloo ranked were both found this way, and in a probe for Barcelona the AI's own titles mostly had no ranking at all (`docs/qloo-findings.md`). The area's top lists alone hold almost no pet titles (1 of 30 in Park Slope), so the search starts from a pet title. A classifier, rather than the AI alone, sorts the 20 results because it gives a probability per question and is cheap (about $0.001 for 60 titles in the probes); the AI still decides every unclear case, with a reason, and Qloo's ranking still decides the order.

**Follows:** a new area costs about 15 to 17 Qloo calls (decision 18 said 12 to 14; 18 to 20 since decision 22). Profiles made before this have no found titles and render as they were. A pet-mindedness score per area or per age or gender group was probed and not built: every list held one or two pet titles at most, so differences between groups were noise, and a score for groups of people invites the "matching" claim AGENTS.md rules out.

## 21. A warm skin as the default UI; classic kept

**Decided** (the author, 18 October: "keep the wireframe as it is now", "more friendly, suitable for a pet adoption center"; palette, typeface and decoration chosen from options):
- A second UI folder, `app/ui/warm/`, copied from `classic` and restyled. The wireframes are the same: every screen keeps its layout, DOM order, ids, `data-role`s and the attribute order the tests read, so the view models and the API did not change, and the tests that read the default UI's markup needed no change; the contract tests were extended to run every skin and to check the font. Markup changed in three places only: a paw mark beside the brand, a paw in place of the busy dot, and a span around each plan step's text.
- The look: a cream page, white cards with soft shadows, 16 px corners, Nunito. Each hue has a bright value for fills and borders and a darker "ink" value for text, so every text pairing passes WCAG AA (the lowest is the Qloo pill's white on terracotta, 4.98:1; bright coral on white is 3.44:1, so it is never used for text), and field borders and the selected area card's edge reach 3:1. Dark mode is kept.
- Colour carries provenance. Coral is the brand. Terracotta means "what Qloo returned" and sage means "how Namesake read it": the two lines under every name option and venue carry a rule and a swatch in those colours, and the Why panel's columns the same. Honey marks a choice (the picked name, "stands out") or a note. None of the four stands in for another.
- Nunito is served from `app/ui/warm/static/fonts/` with its OFL licence beside it, so a visitor's browser makes no request to a font service. The contract test bans the Google Fonts hosts in every UI's files.
- The `UI` setting's default is `warm`. `classic` stays as it was, for `?ui=classic` and as a fallback; the contract test runs against both.

**Why:** design is a quarter of the score and judges may see one screenshot. The classic look, flat and grey-bordered, read as a prototype for an office tool; a shelter volunteer's tool should look like somewhere an animal lives. The seam built in milestone 2 made this a second folder rather than a rewrite, and keeping classic lets the two be compared on the same data.

**Revised 18 October, the map tiles:** the warm skin keeps OpenStreetMap's standard tiles, quieted by a CSS filter on the tile pane only (lower saturation, a slight warm tint; inverted and dimmed in dark mode), so the lift cells and the shelter's circle read first. CARTO's quieter Voyager and Positron styles, chosen first, now answer every tile with "API KEY REQUIRED", and a keyed provider would put a key in the browser, which AGENTS.md forbids. Classic keeps the plain tiles.

**Follows:** UI work that was waiting on this (the "Qloo's part" strip, the venue lift line, the per-run graph) will be built into `warm`, not classic. The README screenshot still shows classic until it is retaken at the end, once the examples are rebuilt on the final code. Classic gets no new features; it is deleted when it is no longer useful for comparison.

## 22. Pet titles start from Qloo's own lists, and stay only with Qloo's evidence

**Decided** (the author, 18 October: "i still dont like it because the AI choose these titles without qloo help", and "why i want this is that to give more importance to qloo"; the probe run that night):
- Before Namesake's AI runs, code asks `recommend` for TV shows, films and books with Qloo's four pet tags as signals (`signal_tags`, union) plus the area (`signal_location`), 20 each, and the classifier of decision 20 sorts them (`pet_lists`). Kept and unsure titles are given to the AI in its prompt as its main titles; set-aside ones never reach it. Three calls per new area, cached.
- The AI may add up to four well-known titles of its own (Bluey and PAW Patrol never appear in the tag lists), looks them up and may search the area's lists with them as before. A title stays only with Qloo's evidence for the area: `rank` returns it, or it sits in one of the area's lists (`found_in`, `listed_in`). Code leaves out the others after the AI answers, whenever any title has that evidence, and the step log and the Why panel name them. When no title has evidence (Qloo answered nothing here), the AI's own titles stay and the page says so (`titles_confirmed`).
- The venues are asked for backed titles only (`find_venues`); when the AI sends none while Qloo backs others, the tool refuses and names them. A title the venues were asked for is never left out, since the venues and the map rest on it.
- `check_plan` sends back a plan that keeps none of the titles Qloo backs, when one is ranked here or kept by the classifier from Qloo's lists, and the instructions say so; if the AI still fails, the run falls back to the fixed lookup, as for any failed check. The AI is asked to add at most four titles of its own; nothing counts them.
- A pet-themed list whose `interpretation` shows no tags is not used: Qloo ignores what it does not understand, and the list would be the area's ordinary top titles. Without a classifier every listed title is unsure, so it cannot seed a search of the area's lists (decision 20's rule); the AI judges them all.
- The Why panel shows a title from the tag lists as "2nd of 20 in Qloo's list of pet-themed TV shows people around Park Slope tend to like", and "Who chose" says Qloo listed the titles and the AI judged and added.

**Why:** the brief's test is that the app must not work the same without Qloo, and technological implementation is the tie-break. The tags failed as filters (milestone 1: two TV shows, no films) but work as signals with the area: on 18 October they gave 3, 5, 8 and 5 pet titles in Park Slope, Astoria, Austin and Hoboken (12 calls, `docs/qloo-findings.md`). The lists barely differ by area and lean towards shows about real people, so they do not replace the AI's ideas; Qloo's evidence decides which of all the candidates stay.

**Follows:** profiles saved before this keep their titles until rebuilt; the examples are rebuilt at the end. A new area costs about 18 to 20 Qloo calls. The fixed lookup (no model) still uses the seed titles. PR #16 (the story skin) also numbered its decision 22; it takes the next number when it lands.
