# Qloo findings (milestone 1)

What the hackathon key can tell us about pet interest near a shelter, and what that means for the agent. The milestone 1 numbers come from `scripts/probe_m1.py`, which replays the recorded responses in `var/qloo-recordings/` without spending quota; "Building the location profiles" comes from `scripts/build_profiles.py` (milestone 2); the later sections, each dated, come from the probes and runs they name. The recordings themselves stay out of the repo, as Qloo's terms require. Entity names and scores are quoted here; Qloo confirmed that is fine.

Probed from 3 October 2026 (milestone 1 on 15 October) with harness 0.1.26, schemas read from `qloo_capabilities` (no quota); later sections carry their own dates.

## Summary

| Question | Answer | Consequence |
|---|---|---|
| Can a location alone say what people like? | Partly. Results come back, but mostly as national hits with affinity near 1.0. Artists with a location returned nothing. | The agent starts from entities, not from the area alone. |
| Do pet tags work? | Tags exist, but filtering TV to them leaves 2 shows and films to none. Lifestyle tags (`dog_ownership`) used as a signal are sent but change nothing: every venue scores exactly 0.5. | The agent proposes pet-themed titles itself and checks them; tags are not enough as filters. (18 October: as signals with the area they are a source, and the app now starts from them; see the last sections and decision 22.) |
| Do venue searches near the shelter work? | Yes, with entities as signals. Fans of two pet shows give 15 venues in and around Park Slope, scored 0.70 to 0.73. | Venues are the backbone of the exposure plan. |
| Are those venues about pets? | Only partly. 9 of the 15 also come back for a show with nothing to do with pets. | Venues are ranked against a baseline; the distinctive ones are shown first. |
| Does location change a ranking? | Yes, the order changes, but raw scores saturate near 1.0. Rank scores are not comparable across calls. | Use order within a call and lift against a baseline, never raw affinity. |
| Is the citywide heatmap useful near a shelter? | Rarely. It returns only the top 20 cells for the city, and for 4 of 5 entities none falls within 3 km of either shelter. | Heatmaps for the map are taken within the neighbourhood. |
| Does a heatmap within the neighbourhood work? | Yes. It returns 12 to 15 cells about 150 m across, scored by rank from 0 to 1 within the area. Against a baseline show, 8 cells overlap and give a lift map. | The map shows lift against a baseline inside the neighbourhood. |
| Do names resolve? | Often not: 6 of 10 pet-show names were ambiguous and came back as candidates. | Choosing among candidates, with a stated reason, is a real agent step. |
| How much can we call? | Rate-limited after about 12 calls in 20 minutes. After a 20-minute pause, 7 calls spaced 5 seconds apart went through, except `rank`, which was refused twice more. | Cache everything, space live calls, precompute the demo, give the agent a call budget, and keep `rank` calls rare. |
| Are the venues suitable? | Not all. Near Astoria the list mixes a museum, a sculpture park and a cinema with nightclubs and an adult venue. | Venues are screened for event suitability by the agent and by code. |

## Pet tags (P1, P2)

`find_tags` returns pet tags in several families: media genres and keywords (`genre:media:dogs`, `keyword:media:pet_dogs`, `subgenre:qloo:pets`, `keyword:qloo:cats`), lifestyle (`lifestyle:qloo:dog_ownership`, `pet_ownership`), audience (`target_audience:qloo:cat_loving`) and place categories (`category:place:pets`).

As filters they are thin. TV filtered to the four media tags gives two shows in every location: *My Cat from Hell* and *Trailer Park Boys*. Their order flips in Austin, and their affinities (0.95 to 0.98) are not saturated, so location does carry signal here. Films filtered to the same tags give nothing.

## Venues near the shelter (P3)

| Signal | Result |
|---|---|
| Lifestyle tags `dog_ownership` and `pet_ownership` | 15 venues, every one at affinity 0.5: the signal was sent (the request shows `signal.interests.tags`) but had no effect. |
| Two pet shows (*Bluey*, *My Cat from Hell*) | 15 venues, affinity 0.702 to 0.735. |
| One show unrelated to pets (*Yellowstone*), as a baseline | 15 venues, affinity 0.800 to 0.848. |

9 of the 15 pet-show venues also appear for the baseline, so most of the list is "popular places near Park Slope": Barclays Center, an archery range, a CrossFit gym. Six appear only for the pet shows: Royal Palms Shuffleboard Club, Union Hall, Brooklyn Arts Exchange, Littlefield, The Bell House and Hotel Le Bleu. Several of those are event spaces, which suits adoption events.

So a venue's evidence is its rank against the baseline, not its raw score. The agent also has to judge suitability: a shuffleboard club or an arts centre can host an adoption event, a tattoo studio or an axe-throwing range cannot.

Near Astoria, fans of the same two shows give a completely different list: Museum of the Moving Image, Socrates Sculpture Park, Kaufman Astoria Studios, Stuart Cinema & Cafe and Judy & Punch, alongside nightclubs and an adult venue. None of the 15 overlaps with Park Slope, so the location filter is doing real work. The mix also shows why every venue has to pass a suitability screen before it reaches a volunteer.

## Ranking pet shows by location (P4, P5)

Ranking ten pet-themed series by name returned `needs_input` in both Park Slope and Astoria. Six names were ambiguous: *Bluey* (the 2018 children's series or a 1976 crime drama), *Clifford the Big Red Dog* (2000 or 2019), *PAW Patrol*, *Pound Puppies*, *Lassie* (1954, 1997 or 2014) and *Too Cute* (an Animal Planet series or a 2023 anime). Four resolved directly. The probe settles each by a phrase in Qloo's description, which is the rule the agent will follow and state.

Ranking the resolved list was refused with `QLOO_RATE_LIMIT` on four attempts across two sessions, while other workflows sent in between went through. `rank` with ten options seems to have a tighter limit than the rest. Milestone 3 will rank shorter lists and record whether that helps.

**Later observation (milestone 4, 15 October).** Shorter lists (4 or 5 films) were not refused. Two such calls answered `ok` with no results, though. That was for Park Slope and Astoria, while building the cat and dog profiles for the examples. Qloo's `interpretation` showed every ID resolved and the location passed. Both lists included the film *Clifford the Big Red Dog*. No list that returned a ranking included it. That is a pattern from two calls, not a cause. The app treats an empty ranking like a refused one: it keeps the agent's order and says so on the result page (decision 3).

## Heatmaps (P6 and the earlier recordings)

From the five citywide heatmaps recorded on 3 October:

| Entity | Nearest cell to Park Slope | Within 3 km | Nearest cell to Astoria | Within 3 km |
|---|---|---|---|---|
| Bluey | 3.7 km | 0 | 4.5 km | 0 |
| Yellowstone | 4.3 km | 0 | 3.9 km | 0 |
| The Other Two | 0.3 km | 3 | 2.7 km | 1 |
| New York Mets | 8.1 km | 0 | 4.6 km | 0 |
| New York Yankees | 14.8 km | 0 | 3.6 km | 0 |

Entities tied to a place show real taste: the Mets' top cells are mostly in Queens and the Yankees' in the Bronx. Broad entities land in Manhattan, where most people are. Either way, the top 20 cells of a whole city rarely reach the shelter.

Within the neighbourhood (`within: "Park Slope, Brooklyn"`) the heatmap behaves differently: 15 cells for *Bluey* and 12 for *Yellowstone*, each about 150 m across (7-character geohashes, against 6 citywide). Scores are ranks spread evenly from 0 to 1 inside the area, so they compare within one map, not with citywide scores. As ranks (each cell's place within its own map), two maps of the same area can be set side by side: the lift is one map's rank minus the other's in the same cell, and since decision 18 the map averages the ranks of two pet titles and of two baseline shows per cell.

Eight cells appear in both. The difference in score is the lift for the pet show: from +0.48 to −0.62, four cells above zero, one level and three below, between 0.1 and 1.4 km from the shelter. (The cells themselves, Qloo's response data, stay in the git-ignored recordings.)

That is a usable map layer: where in the neighbourhood the pet show's fans stand out against the baseline. Eight cells is a small sample, and the reading is relative, so the map labels it as such.

**Hoboken, 18 October (one live run):** PAW Patrol, the first map title then, scored 1 cell within Hoboken while Bluey scored 9, so a widely known title can still map thinly in one place. The map now lets a thin first title give way to the next (decision 18, revised).

## Rate limit

About 12 calls went through in roughly 20 minutes before Qloo answered `QLOO_RATE_LIMIT`. The harness marks it retryable; a retry after 5 seconds failed too, and so did later attempts over several minutes. The window is not published. The wrapper retries once, as the harness's recovery text says, and never caches an error; since 18 October it waits 20 seconds after a rate limit, and gives `rank` a second retry after 40 (decision 20).

## Building the location profiles (milestone 2)

`scripts/build_profiles.py` runs the fixed lookup for every preset: resolve the seed titles, venues for the pet shows and for the baseline, and heatmaps within the area. With 5 seconds between calls, all 8 new calls went through without a rate limit.

| Location | Venues that stand out for pet-show fans | Also popular generally | Left out by the screen | Map cells with lift |
|---|---|---|---|---|
| Park Slope | 6 | 9 | 0 | 8 of 15 |
| Astoria | 3 | 12 | 3 (hookah lounges) | 8 of 8 |
| Austin | 9 | 6 | 0 | 3 of 20 |

- Astoria's pet-show venues overlap the baseline's far more than Park Slope's do, so there the venue list is mostly "popular nearby". The result says so through each venue's badge.
- Austin is a whole city, so its map cells are 6-character geohashes and overlap with the baseline is thin (3 cells).
- Austin's list includes two sorority houses: places the keyword screen cannot judge, which is why milestone 3 adds the agent's suitability check.
- **Venues have no coordinates.** Place results carry an address and a neighbourhood name but no latitude or longitude, and `describe` on a place returns only its ID, name and type. Venues were therefore listed, not pinned. (18 October: they are now also pinned, from OpenStreetMap by name and address; decision 4, revised.)

## Preset locations

Keep the provisional three: **Park Slope**, **Astoria** and **Austin**.

- Park Slope and Astoria both resolve cleanly in every workflow tried, and their venue lists share nothing, which shows the result changing at neighbourhood scale.
- Austin resolves and orders the pet-tagged shows differently from New York, which shows it is not only a New York effect.
- Untested: Austin venues and heatmaps. The other candidates (Bushwick, Harlem, the Upper West Side, Tampa, Portland) were not probed, to save quota.

## Proposal: how the agent should work

Most Qloo work depends on the location and the species, not the individual animal. So the agent builds a **location profile** once per location and species, which is cached and shared by every animal there, and then a short **listing run** per animal.

**Location profile (agent and code, about 8 live calls when proposed; about 12 to 14 since decision 18, cached):**

1. *Agent:* propose about ten pet-themed titles for the species (TV, films, books, brands), since pet tags alone return almost nothing. (Superseded on 18 October: Qloo's own pet-themed lists come first, decision 22.)
2. *Agent:* resolve them. Where Qloo returns candidates, pick one with a stated reason, for example "the 2018 children's series, not the 1976 crime drama", or drop the title.
3. *Agent and Qloo:* rank them in the location and keep the strongest. If fewer than three survive, propose more once.
4. *Code:* venues for fans of the survivors and for the baseline (since decision 18, the area's own top two shows; first a fixed show), near the shelter, and the rank difference between the two lists.
5. *Agent and code:* screen the venues for event suitability (code drops adult venues and nightlife by category; the agent judges the rest) and choose about three, each with a reason.
6. *Code:* heatmaps within the neighbourhood for the top title and the baseline, and the lift map (since decision 18, the top two titles against the two baseline shows, averaged).
7. *Code:* the area's general tastes (TV and films with a location signal), the second source for names.

**Listing run (per animal, at most a couple of `describe` calls):**

8. *Agent:* propose name options from both sources (characters and titles from the kept pet entities, and from the general tastes), each tied to its Qloo entity.
9. *Code:* the name screen, with the stricter screen for bully-type dogs, and the duplicate check.
10. *Agent:* write the bio and the hook from the facts. *Code:* check that every sentence traces to a fact, the length, and that the hook says nothing about temperament.

The agentic steps are 1, 2, 3, 5 and 8: the model reads Qloo's answers and decides what to try next. The examples are precomputed, so opening them spends no quota. A custom location costs about 8 calls, roughly a minute with the spacing, shown in the live log.

**Decided:** see `docs/decisions.md`, entries 1 to 5 (15 October 2026).

## Pet-supply brands as venue signals (17 October)

Question: fans of a pet-supply brand are more likely to own a pet than fans of a cartoon about one. Do their places suit an adoption flyer better? Probe: `scripts/probe_pet_brands.py`, 7 live calls (one wasted on a wrong input), Park Slope, compared with the saved dog profile, whose venue signals are *Bluey* and *PAW Patrol*.

| | Pet films (saved profile) | Brands: Chewy, BarkBox, Purina | Films plus Chewy |
|---|---|---|---|
| Resolving the names | *Bluey* had 2 entries, *Garfield* 5 elsewhere | 1 entry each, clearly the pet brand | — |
| Places also on Yellowstone's list | 7 of 15 | 2 of 15 | 2 of 15 |
| Places shared with the films' list | — | 2 of 15 | 2 of 15 |
| Kinds of place | arts centres, a music school, performance spaces, a gym, an arena | 4 hotels, bars, bakeries, a board-game café, a pet-supply shop | close to the brands' list; the films' arts centres drop out |
| Heatmap within Park Slope | 15 cells | 20 cells (Chewy) | — |

Reading:
- Brand fans' places differ much more from the baseline's, so more of them "stand out". But many are hotels and bars, which suit a flyer no better than the films' places do. The one clear gain is a pet-supply shop (Unleashed by Petco), 8th of 15.
- Mixing one brand into the films' signals does not combine the two: the brand dominates, and the films' distinctive arts venues (Brooklyn Arts Exchange, BAM Fisher) disappear.
- One area and one set of brands, so this is a hint, not a result.

**Not adopted for now.** The profile keeps pet-themed titles as venue signals. A brand-only list of pet-owner places, screened for hotels, could be a separate, labelled section later, at one more call per profile.

## Trends (17 October, 2 calls)

`trends` takes one to five entities of one type and a date range, and no location: it describes a title's popularity across all of Qloo's audiences, not one area's.

- Bluey and PAW Patrol, 1 July to 1 October 2026: status `ok`, both resolved, and every series empty.
- The same titles, 1 July to 1 October 2025: up to 10 points each (the default `limit`), about five days apart. Bluey's `population_percentile` moved from 0.6154 to 0.6159 and PAW Patrol's from 0.8660 to 0.8661; every velocity field was 0.

So it gives no recent signal and no local one. A "rising lately" badge was dropped (decision 18).

**Checked again 20 October (1 call):** the same two titles, 1 September to 19 October 2026, `limit` 20: status `ok`, both resolved, and both series still empty. Still no recent data, so still not adopted.


## The area's own top lists as a source of pet titles (17 October, about 14 calls)

The question: instead of Namesake's AI proposing pet titles and Qloo checking them, could the area's own top lists hold pet titles already? `recommend` returns at most 20 results a call and has no paging, so a "top 50" is not available through the harness.

**Top 10 per type for Park Slope**, `signal_location` only (4 calls):
- TV shows, films, books: status `ok`, 10 each. None is pet-themed by the keyword pass. One book is a picture book about a guinea pig, which the keyword list misses; a classifier would catch it. Bluey is not in the top 10.
- Brands: status `ok` with no results; brands combined with an area return nothing.
- The lists lean on national hits and are full of political and identity-coded titles (memoirs by politicians, a documentary about a president's portraits). The name screen of decision 19 refuses names from those.

**The area plus the four pet media tags as signals, not filters**, `signal_tags_operator: union`, limit 20 (2 calls):
- TV: the list is pulled toward family and animated shows. Two of 20 are about pets: *My Cat from Hell* (a reality series, so only an animal's name could come from it) and *Dogs in Space*, an animated series the seed list does not have. A few more feature animals that are not pets (a wildlife documentary, *Frog and Toad*).
- Films: none of 20 is about pets; the tags pull toward animation and family films only.
- The tags and the location both shape these lists, so neither result shows on its own that a title is strong *here*; that still needs `rank` or the heatmap lift.

**So:** the area's top lists are too thin to be the main source of pet titles, which matches the tag filters in milestone 1. The tag-signalled TV list is a modest source of candidates the AI might not think of (one in 20 here), for one extra call per area. A dedicated classifier (TypeSafe's Jev was considered) would be sorting about 20 titles once per area; Namesake's AI already reads lists of that size, so it adds speed and cost savings, not a capability.

**"People around the area who like a pet title also like…"**: `recommend` with Bluey as the signal plus `signal_location`, 20 each for TV, films and books (3 calls), sorted by TypeSafe's Jev (a yes/no classifier, five questions per title, about $0.001 for all 60):
- TV: *Nature Cat* (a cat, family: 0.96 for pets central) and *My Cat from Hell* (0.99, and 0.98 for real people). The rest is family animation.
- Films: none clearly; *Leo* (a classroom lizard) scored 0.57, the one case in the middle.
- Books: *Peanut Goes for the Gold* (a guinea pig, 0.95) and *Sea Sirens* (a cat, 0.89).
- None of these is among the five titles Namesake's AI proposed for Park Slope, so the source does add candidates, mostly for cats. Each would still need `rank` or the lift to show it is strong here.
- Jev's scores were decisive: of 60 titles, 59 scored above 0.85 or below 0.25 for "pets central", and it separated pets from animals in general (*Frog and Toad*, *My Little Pony*, *Sonic*) and caught a guinea pig the keyword list misses.

**Result types:** in every `recommend` answer recorded so far, each result has the generic type `urn:entity`, without the kind (TV show, film, book) that was asked for, while `describe` gives the full type (`urn:entity:tv_show`). Code takes the kind that was asked for (decision 20); the Why panel had printed "Nature Cat (urn:entity)".

**Park Slope as a Qloo locality**: `describe` with type `locality` for "Park Slope, Brooklyn" answers `needs_input`, with Park Slope first among Brooklyn Park, Sunset Park, Sunset Park West and Marine Park. The `signal_location` text is resolved by Qloo's API, and `interpretation` echoes only the text sent, so which place it matched cannot be seen from the answer.

**Barcelona, old against new** (4 calls): the five TV titles Namesake's AI proposed for Park Slope (Bluey, PAW Patrol, Clifford, Lassie, Scooby-Doo), against "people around Barcelona who like Bluey also like…" (TV, films, books, 20 each, sorted by Jev), then one `rank` for "Barcelona, Spain" over both.
- Jev kept 3 of 60: *The Pack* (dogs 0.92) and *Cesar Millan: Better Human Better Dog*, both about real people (0.96, 0.98), and the guinea-pig book again. No middle cases.
- `rank` over seven TV titles returned only three: *The Pack* (0.960), *Cesar Millan* (0.958), Bluey (0.870). PAW Patrol, Clifford, Lassie and Scooby-Doo came back with nothing for Barcelona.
- So outside the US the AI's US-known titles mostly drop out, while the signal-led source finds pet titles that rank above Bluey there; names from both would be animals' names only, as both shows are about real people.

## Venue titles when the ranking is refused (Hoboken, 18 October, one live run)

`rank` was refused with `QLOO_RATE_LIMIT`, even after its retry, so the titles kept the order Namesake's AI proposed them in. The venues were asked for its first three (PAW Patrol, Bluey, Scooby-Doo), and the map's first title, PAW Patrol, scored one cell within Hoboken. The titles with evidence for the area, *Nature Cat* (9th in Qloo's list of what people around Hoboken who like PAW Patrol also like) and *My Cat from Hell*, went to neither. So code now orders the venue and map titles by evidence (decision 20, revised): Qloo's ranking, else each title's place in the area's lists, then the AI's order.

## Qloo-first pet titles: the area plus the pet tags as signals (18 October, 12 calls of a 26-call probe run)

`recommend` with the four pet media tags as `signal_tags` (union) plus `signal_location`, limit 20, for TV shows, films and books (12 calls; the night's other 14 were the follow-up searches below and two probes that gave nothing usable, breed tags as filters and podcasts, which are not recorded here); 10 seconds apart, no refusals, and `interpretation` showed all four tags sent every time. Kept means Jev's pets ≥ 0.8 and family ≥ 0.6; nothing came back unsure.

| Area | TV | Films | Books | Kept |
|---|---|---|---|---|
| Park Slope | *My Cat from Hell* 1st, *Dogs in Space* 9th | none | *Rin Tin Tin: The Life and the Legend* 2nd | 3 |
| Astoria | *My Cat from Hell* 1st, *Dogs in Space* 8th | *A Dog's Way Home* 7th | *Rin Tin Tin* 2nd, *The Aristocats* 7th | 5 |
| Austin | *My Cat from Hell* 1st, *Dogs in Space* 8th, *It's Me or the Dog* 16th, *Bunnicula* 19th | *A Dog's Way Home* 4th, *A Dog's Journey* 11th | *Rin Tin Tin* 8th, *The Aristocats* 19th | 8 |
| Hoboken | *My Cat from Hell* 1st, *Dogs in Space* 6th | *A Dog's Way Home* 7th, *Arthur the King* 18th | *Rin Tin Tin* 5th | 5 |

- Every area gave at least three pet titles, where the tags as filters gave two TV shows and no films (milestone 1). So the lists are a source, and the app now starts from them (decision 22).
- The lists barely differ by area: the tags dominate, and the area shifts positions and adds a few. Bluey, PAW Patrol and Clifford never appear, and many kept titles are about real people (names then come only from the animals).
- One more search from each area's best kept title (*My Cat from Hell*, TV, with the area) added almost nothing: Bluey in Austin (11th), *Cesar Millan* in Hoboken (9th).
- So Qloo's lists come first and the AI may add titles, but only Qloo's evidence for the area (its ranking, or a place in the area's lists) keeps one.

## A pet index per audience, and the rate limit (17 October, 30 calls)

Top 20 TV shows, films and books for Astoria and Barcelona, for everyone and with `demographic` added (women, men, "millennials", "adults 55-64"); Jev marked the pet titles, and each list was scored as the sum of `p_pets / log2(position + 1)`.
- The demographic input takes natural language and reports what it sent: "women" → `gender: female`, "millennials" → `age: 30_to_34,35_to_44`, "adults 55-64" → `age: 55_and_older`. "35 and younger", "55 and older" and "baby boomers" came back `needs_input` before any request reached Qloo (nothing was cached).
- Of 30 lists (600 places), seven held a pet title, one or two each: *Peanut Goes for the Gold* (three lists), *Isle of Dogs* (two), *DC League of Super-Pets*, *The Labrador Pact*, *Evie and the Animals*, *Love in Lowercase*. Every index is one or two titles, so differences between areas or groups are noise, and no claim about a group is supported.
- The splits do widen the search: five of those pet titles appeared only in a split list, not in the area's own top 20.
- Rate limit: 30 calls about 10 seconds apart, in about 8 minutes, with no refusal. On 15 October the key was refused after about 12 calls in 20 minutes, so the limit has risen or was a burst limit; `QLOO_MIN_INTERVAL` could be lowered after a check on the server.

**The feature, one live run** (`scripts/run_agent.py dog-03 austin --fresh`, 17 October, 12 live Qloo calls, the rest cached): Namesake's AI proposed PAW Patrol, Scooby-Doo, Lady and the Tramp, 101 Dalmatians and Clifford, then searched TV for PAW Patrol's fans, films for 101 Dalmatians' and books for Clifford's. Of 60 titles, Jev kept 4 and left 4 to the AI. The AI sent four TV titles to `rank`; Qloo ranked two for Austin, Bluey (1st in the PAW Patrol list) and Nature Cat (3rd), both found in the area's lists, and returned nothing for the AI's own TV titles. One run, one area: it shows the mechanism works, not how often it changes the result.

## The probe show for a typed area (18 October, 16 calls)

The area check (decision 12) heatmapped the seed show *Yellowstone* within a typed area and accepted it at 5 or more cells. Gràcia, Barcelona was refused with 2 cells, though Qloo's top TV list and the "people here who like Bluey also like" search both answered well there; Girona and Ithaca passed as they were.

Cells from `where_popular` within each area (limit 20, geohash 7 in every case):

| Area | Yellowstone | Bluey | The area's own #1 TV show |
|---|---|---|---|
| Gràcia, Barcelona | 2 | 2 | 20 (*Late Motiv*) |
| Kreuzberg, Berlin | 19 | 9 | 20 (*Neo Magazin*) |
| Astoria, Queens | 14 | 8 | 20 (*Pose*) |

All three own top shows came back at the 20-cell limit, so their counts are a floor, and Kreuzberg's 19 against 20 says nothing. Gràcia is the case that matters: 2 against at least 20. So the check now probes with the area's own top show, with the seed show as well when the list fails or its show is thin, the fuller map deciding (decision 12 has the details). A globally known show is no better than the seed: Bluey came back weaker everywhere. Passing the check does not make the lift map rich: in Gràcia the pet titles themselves are weak (Bluey 2 cells).

## Children's against adult pet titles as venue signals (18 October, 8 calls)

A one-off probe (a scratchpad script through `QlooClient`, its answers in the local cache, nothing in the repo): the author asked why the app avoids age demographics yet uses children's shows. A one-off Jev question, "Is this title made mainly for children?" (not one the app asks), split 20 pet titles cleanly: children's at 0.85 or more (PAW Patrol 0.98, Clifford 0.98, Bluey 0.97, The Aristocats 0.94, Scooby-Doo 0.92, Bunnicula 0.90), family films between 0.6 and 0.85, and adult-audience titles under 0.1 (Rin Tin Tin, Arthur the King, It's Me or the Dog, My Cat from Hell). But venues for fans of the children's set (Bluey, PAW Patrol, Dogs in Space) and of the adult set shared 10, 11, 7 and 11 of 15 in Park Slope, Astoria, Austin and Hoboken; the children's lists already held an archery range, an arena, a biergarten and a nightclub, and the adult set mostly added bars, breweries and a hookah lounge. So a second venue set per animal was not built. What follows from the animal's record instead: for one not good with children, venues that mention children are skipped (decision 2, revised).

## Venues: the animal's titles change little, the kind of place a lot (18 October, 16 calls)

Park Slope, the dog profile's venue titles (*My Cat from Hell*, *Bluey*, *Dogs in Space*) and its comparison shows. Each `recommend` place asked for 15.
- **The lead dog's lookalike titles as signals** (*Scooby-Doo* and *Up*, together and each alone, 3 calls): about half of each list was new (8, 7 and 9 of 15 in neither the pet list nor the comparison's), but the top stayed the same: Barclays Center, Gotham Archery, Kick Axe Throwing. The new places were everyday ones (cafes, a bakery, Whole Foods, a board-game cafe, BK9). Both titles are very broadly popular, so this reads as the area's popular places, not this dog's.
- **The dog and cat lists** for the area were nearly the same places.
- **An audience by age** (`demographic: "adults aged 18-24"`): without `signal_location` the harness answers `needs_input` ("Demographic Qloo signals require signal_location"); with it, `ok` and no places.
- **Place categories** (`include_tags` with `urn:tag:category:place:…`, union; tag IDs from `find_tags`, 8 calls): dog parks and breweries gave 3 breweries and no dog park; bookshops and cafes for the cat titles gave 15 places, 14 new (cafes, bakeries, Ninth Street Espresso, a children's play cafe); the final ten categories gave 15 places for the pet titles and 15 for the comparison, 13 of them shared, with a few loosely tagged places (a record bar, a lounge, a diner). No park or pet shop came back for Park Slope. There is no `category:place:bakery` tag.

Decision 23 follows from this.

## Chains within the kinds of place (18 October, from the example rebuild)

With the venues asked within decision 23's kinds and standing-out places preferred, Astoria's dog profile picked McDonald's: Qloo tagged it as a cafe, and it was not among the places for the area's top shows, so it stood out. Park Slope's list held a beauty salon and vintage shop under the same tags. Qloo's category tags are broad: chains and loosely tagged places come through any kind filter, so the app leaves out listed chains by name and leaves the rest to Namesake's AI (decision 23, revised).

## Places matched to the animal's temperament (19 October, 6 calls)

Question: an animal recorded as active might suit a park, a shy one a bookshop or library. Does asking Qloo for places of the kind that fits each animal's record give a list worth tailoring? Each call was `recommend` place with the profile's pet titles as signals and `include_tags` set to the kinds that fit the record (union), 15 places asked for.

| Animal (record) | Area | Kinds asked for | What Qloo returned |
|---|---|---|---|
| Active dog | Park Slope | parks, dog parks | nothing, not even Prospect Park |
| Active dog | Astoria | parks, dog parks | 1: Socrates Sculpture Park, already among the area's places |
| Shy cat | Park Slope | bookshops, libraries | 3: Community Bookstore, Barnes & Noble, Central Library (Grand Army Plaza) |
| Calm dog | Astoria | bookshops, libraries | nothing |
| Confident cat | Park Slope | cafes, breweries, community centres | 15, nearly the same places as the area's list today (Starbucks among them) |
| Kittens | Park Slope | pet shops | 1: Unleashed by Petco |

Reading:
- Narrowed to a few kinds near a neighbourhood, Qloo's place data is thin: 0 to 3 places, often ones the page already shows. The wide kinds give back the area's usual list.
- Parks are the weakest kind: Prospect Park never appears, so "active dog, so a park" would give nothing in Park Slope.
- The quiet kinds found the one new place worth having (the Central Library for a shy cat), and a bookshop chain the chain list did not yet name.

**Not adopted.** The places stay the same for every animal of a species at a shelter, as the venue note says. A call or two per animal would mostly return empty lists or repeat the page, and tailoring would promise more than the data backs. Barnes & Noble and the other bookshop chains join the chain list (decision 23, revised 19 October).

## The lead dog in Barcelona (19 October, 13 calls)

The fourth example for an evening (decision 30; the litter in Astoria came back the same day), built live on the server with `precompute_examples.py --only barcelona`, "Barcelona, Spain" as the area.

- **Titles:** Qloo's area lists gave almost nothing pet-themed. Of the TV shows, films and books that people around Barcelona who like *Dogs in Space* also like (20 each), the classifier found no pet title, and left one film to Namesake's AI. `rank` ordered *Dogs in Space*, *My Cat from Hell*, *Bluey* and *It's Me or the Dog*. *My Cat from Hell* is about cats, and its own name rules it out for names (decision 26); the dog's saved profile holds the other three, as its titles and its venue signals.
- **Places:** Qloo returned 15 places for fans of those three titles, and 11 stand out against the area's top two shows (*Crims*, *BricoHeroes*). The ones Namesake's AI picked are tourist landmarks rather than neighbourhood spots: Park Güell (1st), La Pedrera's bookshop (6th) and Illa Fantasia (9th), a water park in Vilassar de Dalt outside the city. Two places were found in OpenStreetMap and placed on the map.
- **Map:** 20 cells for *Dogs in Space* and *Bluey*. Their fans stand out against fans of the area's top shows in none of the cells with a comparison, and the page says so.
- **Names:** Bluey (the general pet title), Hooch and Scooby (titles with a dog that shares this one's broad head). Both lookalike titles came back ambiguous. Namesake's AI chose a candidate for each and was sent back once to give its reason.

**Reading:** Qloo answers for Barcelona, but the pet-themed layer is thin. The titles are the US ones again, the map is flat, and the places are the city's best-known sights. The built result shows the uneven coverage the README names; it stays saved for a visitor who picks Barcelona, which remains a preset.

## A title's own tags (`entity_tags`, 20 October, 3 calls)

The question: could Qloo's tags for each chosen pet title show, in the Why panel, why it counts as pet-themed, in place of Namesake's AI and the classifier saying so?

`entity_tags` with one title's ID and `limit` 20 (the most), for Bluey and *Dogs in Space*: status `ok`, 20 tags each, every affinity between 0.998 and 1.
- **No pet tag in either list.** Not `genre:media:dogs`, `keyword:media:pet_dogs` or any of the pet tags the profile uses as signals (P1, P2).
- The tags describe the people who like the title, not what it is about. Bluey's include Motherhood, Infants, Parenting and Baby Clothing. *Dogs in Space*'s include Professionals, Incarceration, Drug Trafficking and a screamo music genre, next to Space Exploration and Best Friends.
- Only a few are content tags (Bluey: three `keyword:media` animation tags), and affinity does not set them apart.

**Together, as Qloo's "descriptive taste" of a combination** (1 more call): Park Slope's three pet TV shows in one call (*My Cat from Hell*, Bluey, *Dogs in Space*). The 20 tags are mostly the single titles' tags merged (Infants, Motherhood, Toddlers, Doctors, Professionals, the screamo genre). Two are new and fit a pet theme, Human-Animal Bond and Light-Hearted; all score between 0.9986 and 1, so affinity cannot pick them out. A line built from them would be the app choosing what it wants Qloo to have said.

**Not adopted.** The tags would not back the "pet-themed" call. Some would also read badly beside a shelter animal, and some come close to inferring traits about people (parenthood). The pet titles stay as they are: found with the pet tags as signals (decision 22), sorted by the classifier.

## Audience demographics (20 October, 14 calls)

`audience_demographics` takes one entity (a name or an ID; with an ID, no type is needed) and returns, for it, a skew from −1 to +1 against Qloo's average audience for six age bands (24 and under, 25 to 29, 30 to 34, 35 to 44, 45 to 54, 55 and over) and for gender.

**Titles** (5 calls): the leans differ by title.
- Bluey: 35 to 44 (+0.19) and 45 to 54 (+0.35), away from 30 to 34 (−0.63) and 55 and over (−0.75); women +0.16.
- *Dogs in Space*: 24 and under (+0.39) and 45 to 54 (+0.50), away from 35 to 44 and 55 and over; women +0.39.
- *101 Dalmatians*: 24 and under (+0.16); women +0.26.
- *My Cat from Hell*: 55 and over (+0.42); gender even (+0.01).
- Bluey by its ID alone gave the same answer as with `entity_type`.

**The area** (2 calls): "Park Slope, Brooklyn" as a locality came back `needs_input` (Park Slope first among Brooklyn Park, Sunset Park and others); by Park Slope's locality ID, status `ok` with no results.

**Venues** (7 calls): three of seven had no data. The others leaned mostly away from groups (Sip & Play: 35 to 44 −0.27) or by gender alone (one place in Astoria: men +0.75).

**Adopted for titles only** (decision 31), shown beside each name option; not for the area or venues.
