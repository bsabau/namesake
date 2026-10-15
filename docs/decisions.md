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
