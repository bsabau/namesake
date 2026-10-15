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
- Precomputed and shared listings change only through a run for an animal that has none, or through `scripts/precompute_examples.py`.
- Approval records the approval ID, animal, area, version, name, the name's source, whether the text was edited, and the time. The text itself is never recorded. An added animal is recorded as `added`.

**Why:** the demo has no accounts, and every judge sees the same examples. If one visitor's "less childish" overwrote the shared result, the next visitor would see it. Keeping the text out of the log keeps free text, which could contain anything, out of storage. The trial needs only the version and the name.

**Follows:**
- Photos are checked by their first bytes (JPEG, PNG or WebP, at most 3 MB). They are served only to the session that added them, with `no-store`. No model ever sees them.
- An added animal's facts go to the model, never to Qloo. The listing checks hold them to the same rules as the roster's facts.

## 10. A volunteer's edit may reword a listing, never drop a caution

**Decided:** approval is refused if the edited text no longer contains the cautions the shelter recorded, word for word:
- each confirmed "no" (for example "would do best in a home without cats")
- a bite on record
- any recorded phrase about biting, nipping, guarding, growling, snapping or scratching

The refusal keeps the edit and names the missing words.

**Why:** "a bite history or guarding is stated plainly, every time" applies to what leaves the app, and the volunteer's edit is the last step before posting. Overselling is the harm the evidence review found.

## 11. Limits on live work, and nothing else

**Decided:**
- Saved results open freely.
- Live work is limited: each visitor may start 6 new runs or location checks an hour, counted in memory by client address. The whole app may start 60 new runs and check 10 new locations a day, counted in SQLite so a restart does not reset them.
- All of these numbers are settings.

**Why:** the hackathon key's quota is unknown and the development model is a coding plan. A judge clicking around must never exhaust either. The daily caps protect the quota even if per-visitor counting is fooled, for example behind a shared proxy.

**Follows:** uvicorn runs with `--proxy-headers`. `FORWARDED_ALLOW_IPS` names the host's proxy, so the client address is the real visitor's.

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

**Decided:** a litter run builds one profile, then writes each member's listing in turn. The first member's first name sets the title. Every later member may draw names only from that title, and no name repeats within the litter.

**Why:** "two animals in one shelter never share a reference, except a litter named as a set." Letting the first listing choose keeps the agent's judgement, and restricting the others to one title is a check code can enforce: a name from another title is refused like any invented ID.

**Follows:** a member whose draft cannot be fixed falls back to the template, as any listing does. The result page lists the litter's names with links.
