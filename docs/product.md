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

Name options come from three sources. Each option carries a badge with what Qloo returned for its title:

| Source | Where it comes from |
|---|---|
| Pet-themed, strong here | Pet-themed titles with Qloo's evidence for the area (decision 22): ranked here by Qloo ("ranked 1st of 8 here by Qloo"), or placed in one of the area's lists, asked with Qloo's pet tags or for fans of another pet title ("in Qloo's list for this area asked with its pet tags", "liked here by fans of Bluey") |
| Loved here generally | The area's top tastes by type (step E). Screened harder, because these lists lean on national hits and identity-coded titles. |
| Title found, or Offered as a candidate (a lookalike) | One or two titles the agent looks up for this animal: a film, show or book with an animal that shares its recorded look. Qloo's line says only that it found the title, or offered it among candidates when it asked which was meant; the match ("A lookalike, matched on this animal's recorded look (brindle).", after the reference that names the character) is on the AI's line. Never the first name, so the local version stays local (`docs/decisions.md` #14). |

Each option shows the Qloo title, its kind and Qloo's evidence for the area (its rank here, or its place in one of the area's lists); a lookalike has no area evidence, only the title. Our reading of why it suits the animal is shown separately. The volunteer picks one. Ranking uses both affinity and popularity, so a recognisable reference beats a niche one.

## Output 3: the exposure plan

The plan is a checklist the volunteer can carry out without an ad budget:

1. People near the shelter, and the personal networks of foster carers and volunteers.
2. In-person visibility: outings, events, an "Adopt Me" vest.
3. Timing: Friday, Saturday and early evening.
4. For New York dogs: rescue partners and foster recruitment.
5. **Venues (Qloo):** about three places near the shelter that fans of up to three of the pet-themed entities favour, for flyers and events. Code picks those titles by their evidence for the area (Qloo's ranking, else their best place in the area's lists), never an identity-coded one, and the agent picks the venues. Each venue shows its evidence. For an animal recorded as not good with children, venues whose name or Qloo description mentions children are skipped, and the plan says which (decision 2).
6. **One channel beyond the usual audience.** It comes from that location's `community_channels` entry in `data/locations.json` and is labelled as our suggestion.

The plan's success measure is adoptions and returns; likes and reach are left out.

## How Qloo is used

| Step | Harness workflow | Who decides | Cached per |
|---|---|---|---|
| A. Pet-themed titles the area likes | `recommend` per type with the four pet tags as signals plus `signal_location` (decision 22). As filters the tags returned almost nothing (milestone 1) | code asks; a classifier sorts; agent judges the unclear ones | location |
| B. More pet-themed entities strong here | `describe` for titles the agent adds; then `recommend` with one of them as the signal plus `signal_location`, per type (decision 20) | agent adds and searches; a classifier sorts the search results; agent judges the unclear ones; code keeps only titles Qloo ranks or lists here | location |
| C. Local lift against a baseline | `where_popular` for the top two entities (a thin first one gives way to the next) and the area's top two shows (decision 18); lift = the entities' averaged score in a cell minus the baseline shows' | code computes; agent drops entities with no lift | entity and city |
| D. Venues fans favour | `recommend` for places, up to three entities with the strongest evidence as signals, never an identity-coded one (code picks them), location near the shelter | agent picks about three venues, with reasons | location |
| E. General local tastes | `recommend` with `signal_location` per type | agent proposes, screens, keeps | location |
| F. Check each name's reference | resolve and `describe`; `needs_input` goes to candidate buttons or a pick with a stated reason | agent | entity |

Steps A to E run once per location and every animal reuses them, so quota cost grows with locations, not animals. Fixed calls, such as the heatmap, use `qloo exec` from code. Calls the agent chooses go through function tools over the same client, so they are cached and spaced too (`docs/decisions.md` #5).

**Use lift, not raw affinity.** Raw affinity saturates near 1.0, and a broad entity's heatmap mostly shows where people are. Lift against a baseline entity is the number that carries taste. See `docs/qloo-findings.md`.

## The result screen

The result screen must be legible in a single screenshot. It shows:
- at the top, Qloo's part and Namesake's AI's part, apart: what Qloo returned for this result and what the AI did with it
- the photo and chosen name
- the generic/local toggle, each button showing its version's name
- the name options with what Qloo returned for each title
- a map of local lift, its caption counting the cells where pet-show fans stand out (unless the map is thin), with the venues listed beside it and pinned on it by number, each card saying which cell it sits in and how far it is from the shelter (`docs/decisions.md` #4)
- the exposure checklist
- a "Why" drawer with two columns, "Qloo returned" and "How Namesake read it"

## Measurement

Each listing records an ID, the animal, the location, the variant (`generic` or `local`), the chosen name and its source, and the time. The README describes the trial the tool enables:
- **Design:** randomise generic against local at intake.
- **Primary outcome:** time to adoption, analysed as time-to-event.
- **Safety outcomes:** returns within 30 and 90 days, plus total shelter adoptions to check that spotlighting one animal isn't taking adopters from another.
- **Sample size:** about 190 adoptions to detect a 50% faster rate.

The hackathon build records the data; it doesn't run the trial.
