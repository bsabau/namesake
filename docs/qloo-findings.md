# Qloo findings (milestone 1)

What the hackathon key can tell us about pet interest near a shelter, and what that means for the agent. Every number below comes from `scripts/probe_m1.py`, which replays the recorded responses in `var/qloo-recordings/` without spending quota. The recordings themselves stay out of the repo, as Qloo's terms require. Entity names and scores are quoted here; Qloo confirmed that is fine.

Probed 3 October and 15 October 2026 with harness 0.1.26, schemas read from `qloo_capabilities` (no quota).

## Summary

| Question | Answer | Consequence |
|---|---|---|
| Can a location alone say what people like? | Partly. Results come back, but mostly as national hits with affinity near 1.0. Artists with a location returned nothing. | The agent starts from entities, not from the area alone. |
| Do pet tags work? | Tags exist, but filtering TV to them leaves 2 shows and films to none. Lifestyle tags (`dog_ownership`) used as a signal are sent but change nothing: every venue scores exactly 0.5. | The agent proposes pet-themed titles itself and checks them; tags are not enough. |
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

Eight cells appear in both. The difference in score is the lift for the pet show:

| Cell | Lift for *Bluey* over *Yellowstone* | Distance from the shelter |
|---|---|---|
| dr5rk66 | +0.48 | 1.4 km |
| dr5rkk2 | +0.28 | 1.2 km |
| dr5rks5 | +0.11 | 0.1 km |
| dr5rkmk | +0.08 | 1.1 km |
| dr5rkwh | 0.00 | 1.2 km |
| dr5rke2 | −0.37 | 0.5 km |
| dr5rku2 | −0.46 | 0.7 km |
| dr5rkmq | −0.62 | 0.9 km |

That is a usable map layer: where in the neighbourhood the pet show's fans stand out against the baseline. Eight cells is a small sample, and the reading is relative, so the map labels it as such.

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
- **Venues have no coordinates.** Place results carry an address and a neighbourhood name but no latitude or longitude, and `describe` on a place returns only its ID, name and type. Venues are therefore listed, not pinned on the map. Pins would need a geocoder outside Qloo.

## Preset locations

Keep the provisional three: **Park Slope**, **Astoria** and **Austin**.

- Park Slope and Astoria both resolve cleanly in every workflow tried, and their venue lists share nothing, which shows the result changing at neighbourhood scale.
- Austin resolves and orders the pet-tagged shows differently from New York, which shows it is not only a New York effect.
- Untested: Austin venues and heatmaps. The other candidates (Bushwick, Harlem, the Upper West Side, Tampa, Portland) were not probed, to save quota.

## Proposal: how the agent should work

Most Qloo work depends on the location and the species, not the individual animal. So the agent builds a **location profile** once per location and species, which is cached and shared by every animal there, and then a short **listing run** per animal.

**Location profile (agent and code, about 8 live calls when proposed; about 12 to 14 since decision 18, cached):**

1. *Agent:* propose about ten pet-themed titles for the species (TV, films, books, brands), since pet tags alone return almost nothing.
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

The agentic steps are 1, 2, 3, 5 and 8: the model reads Qloo's answers and decides what to try next. The three presets are precomputed, so the demo spends no quota. A custom location costs about 8 calls, roughly a minute with the spacing, shown in the live log.

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

**Park Slope as a Qloo locality**: `describe` with type `locality` for "Park Slope, Brooklyn" answers `needs_input`, with Park Slope first among Brooklyn Park, Sunset Park, Sunset Park West and Marine Park. The `signal_location` text is resolved by Qloo's API, and `interpretation` echoes only the text sent, so which place it matched cannot be seen from the answer.

**Barcelona, old against new** (4 calls): the five TV titles Namesake's AI proposed for Park Slope (Bluey, PAW Patrol, Clifford, Lassie, Scooby-Doo), against "people around Barcelona who like Bluey also like…" (TV, films, books, 20 each, sorted by Jev), then one `rank` for "Barcelona, Spain" over both.
- Jev kept 3 of 60: *The Pack* (dogs 0.92) and *Cesar Millan: Better Human Better Dog*, both about real people (0.96, 0.98), and the guinea-pig book again. No middle cases.
- `rank` over seven TV titles returned only three: *The Pack* (0.960), *Cesar Millan* (0.958), Bluey (0.870). PAW Patrol, Clifford, Lassie and Scooby-Doo came back with nothing for Barcelona.
- So outside the US the AI's US-known titles mostly drop out, while the signal-led source finds pet titles that rank above Bluey there; names from both would be animals' names only, as both shows are about real people.

## Venue titles when the ranking is refused (Hoboken, 18 October, one live run)

`rank` was refused with `QLOO_RATE_LIMIT`, even after its retry, so the titles kept the order Namesake's AI proposed them in. The venues were asked for its first three (PAW Patrol, Bluey, Scooby-Doo), and the map's first title, PAW Patrol, scored one cell within Hoboken. The titles with evidence for the area, *Nature Cat* (9th in Qloo's list of what people around Hoboken who like PAW Patrol also like) and *My Cat from Hell*, went to neither. So code now orders the venue and map titles by evidence (decision 20, revised): Qloo's ranking, else each title's place in the area's lists, then the AI's order.

## Children's against adult pet titles as venue signals (18 October, 8 calls)

The author asked why the app avoids age demographics yet uses children's shows. Jev's "Is this title made mainly for children?" split 20 pet titles cleanly: children's at 0.85 or more (PAW Patrol 0.98, Clifford 0.98, Bluey 0.97, The Aristocats 0.94, Scooby-Doo 0.92, Bunnicula 0.90), family films between 0.6 and 0.85, and adult-audience titles under 0.1 (Rin Tin Tin, Arthur the King, It's Me or the Dog, My Cat from Hell). But venues for fans of the children's set (Bluey, PAW Patrol, Dogs in Space) and of the adult set shared 10, 11, 7 and 11 of 15 in Park Slope, Astoria, Austin and Hoboken; the children's lists already held an archery range, an arena, a biergarten and a nightclub, and the adult set mostly added bars, breweries and a hookah lounge. So a second venue set per animal was not built. What follows from the animal's record instead: for one not good with children, venues described as for children are left out (decision 4, revised).

## A pet index per audience, and the rate limit (17 October, 30 calls)

Top 20 TV shows, films and books for Astoria and Barcelona, for everyone and with `demographic` added (women, men, "millennials", "adults 55-64"); Jev marked the pet titles, and each list was scored as the sum of `p_pets / log2(position + 1)`.
- The demographic input takes natural language and reports what it sent: "women" → `gender: female`, "millennials" → `age: 30_to_34,35_to_44`, "adults 55-64" → `age: 55_and_older`. "35 and younger", "55 and older" and "baby boomers" came back `needs_input` before any request reached Qloo (nothing was cached).
- Of 30 lists (600 places), seven held a pet title, one or two each: *Peanut Goes for the Gold* (three lists), *Isle of Dogs* (two), *DC League of Super-Pets*, *The Labrador Pact*, *Evie and the Animals*, *Love in Lowercase*. Every index is one or two titles, so differences between areas or groups are noise, and no claim about a group is supported.
- The splits do widen the search: five of those pet titles appeared only in a split list, not in the area's own top 20.
- Rate limit: 30 calls about 10 seconds apart, in about 8 minutes, with no refusal. On 15 October the key was refused after about 12 calls in 20 minutes, so the limit has risen or was a burst limit; `QLOO_MIN_INTERVAL` could be lowered after a check on the server.

**The feature, one live run** (`scripts/run_agent.py dog-03 austin --fresh`, 17 October, 12 live Qloo calls, the rest cached): Namesake's AI proposed PAW Patrol, Scooby-Doo, Lady and the Tramp, 101 Dalmatians and Clifford, then searched TV for PAW Patrol's fans, films for 101 Dalmatians' and books for Clifford's. Of 60 titles, Jev kept 4 and left 4 to the AI. The AI sent four TV titles to `rank`; Qloo ranked two for Austin, Bluey (1st in the PAW Patrol list) and Nature Cat (3rd), both found in the area's lists, and returned nothing for the AI's own TV titles. One run, one area: it shows the mechanism works, not how often it changes the result.
