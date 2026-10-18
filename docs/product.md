# Product design

What Namesake produces, and how Qloo feeds each part. The rules that apply everywhere (listing, naming, claims, provenance) are in `AGENTS.md`; this file is the design behind them. The evidence for these choices is in `docs/research/adoption-evidence-review.md`.

## The pitch, and its limits

Every animal gets an accurate, named listing and a plan to get it seen, in about a minute, from facts the volunteer enters. Qloo's part is aimed at pet interest: it finds shows, films, books, brands and artists with a pet theme that are strong near the shelter, and the venues their fans favour. That targeting is an experiment, and the tool records what it needs to test it.

The review found no study showing that names or wording speed adoption. Being seen in person and through personal networks has the largest associations, and overselling an animal raises returns. The design follows from that: accuracy first, exposure second, the cultural layer clearly labelled as the experiment.

## Demo

- **Lead animal:** `dog-02`, a large brindle adult with a broad head, eight months in the shelter. That's the profile the research names as the US bottleneck, and it exercises the strictest name screening.
- **Second example:** the kitten litter, named as a set, listed for two neighbourhoods side by side.
- **Locations:** two New York neighbourhoods and one other US city, from `data/locations.json`, confirmed in milestone 1.

## Output 1: the listing

**Input is a fact sheet.**
- Observed traits: `temperament` and `facts`.
- `yes`, `no` or `unknown` for: good with children, good with dogs, good with cats, house-trained, bite history.
- Anything not recorded stays `unknown`, and the listing leaves it out.

**The bio:**
- Third person, behaviour toward people first, plain wording, 75 to 150 words.
- Every sentence traces to a fact. Code checks this after the model writes.
- Difficult behaviour is stated plainly with a management suggestion.

**Generic and local versions** share the same bio. The generic version takes a common pet name from a fixed list; the local version takes the chosen name from Qloo's titles and adds one hook line. The toggle therefore shows exactly what Qloo contributed (`docs/decisions.md` #8).

**Volunteer approval.** The volunteer edits and approves the text, then copies a block ready to paste into shelter software.

## Output 2: name options

Name options come from three sources. Each option carries a badge naming its source:

| Source | Where it comes from |
|---|---|
| Pet-themed, strong here | Pet-themed entities that survive the local-lift check (pipeline steps A–C) |
| Loved here generally | The area's top tastes by type (step E). Screened harder, because these lists lean on national hits and identity-coded titles. |
| Has a lookalike in … | One or two titles the agent looks up for this animal: a film, show or book with an animal that shares its recorded look. Never the first name, so the local version stays local (`docs/decisions.md` #14). |

Each option shows the Qloo entity, its type and the evidence (affinity, popularity, lift). Our reading of why it suits the animal is shown separately. The volunteer picks one. Ranking uses both affinity and popularity, so a recognisable reference beats a niche one.

## Output 3: the exposure plan

The plan is a checklist the volunteer can carry out without an ad budget:

1. People near the shelter, and the personal networks of foster carers and volunteers.
2. In-person visibility: outings, events, an "Adopt Me" vest.
3. Timing: Friday, Saturday and early evening.
4. For New York dogs: rescue partners and foster recruitment.
5. **Venues (Qloo):** about three places near the shelter that fans of the surviving pet-themed entities favour, for flyers and events. Each venue shows its evidence.
6. **One channel beyond the usual audience.** It comes from that location's `community_channels` entry in `data/locations.json` and is labelled as our suggestion.

The plan's success measure is adoptions and returns; likes and reach are left out.

## How Qloo is used

| Step | Harness workflow | Who decides | Cached per |
|---|---|---|---|
| A. Find pet tags (dog, cat, pets, animals) | `find_tags` | probed in milestone 1 only: as filters the tags returned almost nothing, so the app does not use them | global |
| B. Pet-themed entities strong here | `describe` for the titles the agent proposes; then `recommend` with one of them as the signal plus `signal_location`, per type (decision 20). Pet tags as filters returned almost nothing (milestone 1) | agent proposes and searches; a classifier sorts the search results; agent judges the unclear ones | location |
| C. Local lift against a baseline | `where_popular` for the top two entities and the area's top two shows (decision 18); lift = the entities' averaged score in a cell minus the baseline shows' | code computes; agent drops entities with no lift | entity and city |
| D. Venues fans favour | `recommend` for places, surviving entities as signals, location near the shelter | agent picks about three, with reasons | location |
| E. General local tastes | `recommend` with `signal_location` per type | agent proposes, screens, keeps | location |
| F. Check each name's reference | resolve and `describe`; `needs_input` goes to candidate buttons or a pick with a stated reason | agent | entity |

Steps A to E run once per location and every animal reuses them, so quota cost grows with locations, not animals. Fixed calls, such as the heatmap, use `qloo exec` from code. Calls the agent chooses go through function tools over the same client, so they are cached and spaced too (`docs/decisions.md` #5).

**Use lift, not raw affinity.** Raw affinity saturates near 1.0, and a broad entity's heatmap mostly shows where people are. Lift against a baseline entity is the number that carries taste. See `docs/qloo-findings.md`.

## The result screen

The result screen must be legible in a single screenshot. It shows:
- the photo and chosen name
- the generic/local toggle
- the name options with their source badges
- a map of local lift, with the venues listed beside it (`docs/decisions.md` #4)
- the exposure checklist
- a "Why" drawer with two columns, "Qloo returned" and "How Namesake read it"

## Measurement

Each listing records an ID, the animal, the location, the variant (`generic` or `local`), the chosen name and its source, and the time. The README describes the trial the tool enables:
- **Design:** randomise generic against local at intake.
- **Primary outcome:** time to adoption, analysed as time-to-event.
- **Safety outcomes:** returns within 30 and 90 days, plus total shelter adoptions to check that spotlighting one animal isn't taking adopters from another.
- **Sample size:** about 190 adoptions to detect a 50% faster rate.

The hackathon build records the data; it doesn't run the trial.
