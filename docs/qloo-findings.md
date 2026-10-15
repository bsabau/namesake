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

Within the neighbourhood (`within: "Park Slope, Brooklyn"`) the heatmap behaves differently: 15 cells for *Bluey* and 12 for *Yellowstone*, each about 150 m across (7-character geohashes, against 6 citywide). Scores are ranks spread evenly from 0 to 1 inside the area, so they compare within one map, not across maps or with citywide scores.

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

About 12 calls went through in roughly 20 minutes before Qloo answered `QLOO_RATE_LIMIT`. The harness marks it retryable; a retry after 5 seconds failed too, and so did later attempts over several minutes. The window is not published. The wrapper retries once, as the harness's recovery text says, and never caches an error.

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

**Location profile (agent and code, about 8 live calls, cached):**

1. *Agent:* propose about ten pet-themed titles for the species (TV, films, books, brands), since pet tags alone return almost nothing.
2. *Agent:* resolve them. Where Qloo returns candidates, pick one with a stated reason, for example "the 2018 children's series, not the 1976 crime drama", or drop the title.
3. *Agent and Qloo:* rank them in the location and keep the strongest. If fewer than three survive, propose more once.
4. *Code:* venues for fans of the survivors and for a fixed baseline show, near the shelter, and the rank difference between the two lists.
5. *Agent and code:* screen the venues for event suitability (code drops adult venues and nightlife by category; the agent judges the rest) and choose about three, each with a reason.
6. *Code:* heatmaps within the neighbourhood for the top title and the baseline, and the lift map.
7. *Code:* the area's general tastes (TV and films with a location signal), the second source for names.

**Listing run (per animal, at most a couple of `describe` calls):**

8. *Agent:* propose name options from both sources (characters and titles from the kept pet entities, and from the general tastes), each tied to its Qloo entity.
9. *Code:* the name screen, with the stricter screen for bully-type dogs, and the duplicate check.
10. *Agent:* write the bio and the hook from the facts. *Code:* check that every sentence traces to a fact, the length, and that the hook says nothing about temperament.

The agentic steps are 1, 2, 3, 5 and 8: the model reads Qloo's answers and decides what to try next. The three presets are precomputed, so the demo spends no quota. A custom location costs about 8 calls, roughly a minute with the spacing, shown in the live log.

**Decided:** see `docs/decisions.md`, entries 1 to 5 (15 October 2026).
