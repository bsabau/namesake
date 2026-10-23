# Product design

What Namesake produces, and how Qloo feeds each part. The rules that apply everywhere (listing, naming, claims, provenance) are in `AGENTS.md`; this file is the design behind them. The evidence for these choices is in `docs/research/adoption-evidence-review.md`.

## The pitch, and its limits

Every animal gets an accurate, named listing and a plan to get it seen, in about a minute, from facts the volunteer enters. Qloo's part is aimed at pet interest: it finds shows, films, books, brands and artists with a pet theme that are strong near the shelter, and the venues their fans favour. That targeting is an experiment, and the tool records what it needs to test it.

The review found no study showing that names or wording speed adoption. Being seen in person and through personal networks has the largest associations, and overselling an animal raises returns. The design follows from that: accuracy first, exposure second, the cultural layer clearly labelled as the experiment.

## Demo

- **Lead animal:** `dog-02`, a large brindle adult with a broad head, eight months in the shelter. That's the profile the research names as the US bottleneck, and it exercises the strictest name screening.
- **Second example:** `cat-01`, a shy black senior five months in the shelter, listed for two neighbourhoods side by side. Older cats are among those that wait longest (`docs/research/adoption-evidence-review.md`), and her listing has to stay honest about shyness. The kitten litter, the second example until 22 October, is still named as a set when a visitor picks a kitten (decision 30).
- **Locations:** two New York neighbourhoods and one other US city, from `data/locations.json`, confirmed in milestone 1, and Barcelona outside the US (decision 30).

- **Your own animals:** a volunteer can add up to three of their own, with an optional photo, and edit or remove them. They are kept in a workspace in that browser for 7 days after the last visit, with a link that opens it elsewhere; there is no sign-up (decision 34).

## Output 1: the listing

**Input is a fact sheet.**
- Observed traits: `temperament` and `facts`.
- `yes`, `no` or `unknown` for: good with children, good with dogs, good with cats, house-trained, bite history.
- Anything not recorded stays `unknown`, and the listing leaves it out.

**The bio:**
- Third person, behaviour toward people first, plain wording, 75 to 150 words.
- Every sentence traces to a fact. Code checks this after the model writes.
- It describes the animal as it is now: the model adds no backstory, pity or urgency. A recorded fact that tells a past ("was brought in as a stray") is restated as recorded, never dropped, since it may carry a warning, and the page points it out so the volunteer can edit it out before approving (decision 36).
- A fact about what the animal needs from an adopter gets its own sentence, never joined to a fact about what the animal does, so the animal's behaviour is never read as the adopter's.
- Difficult behaviour is stated plainly, as recorded. (No management suggestion is added: the bio may only restate the shelter's facts.)

**Generic and local versions** share the same bio. The generic version takes a common pet name from a fixed list; the local version takes the chosen name from Qloo's titles and adds one hook line. The toggle therefore shows exactly what Qloo contributed (`docs/decisions.md` #8); the local button says "Local" only when Qloo's data for the area backs the name's title, and "With Qloo" otherwise (decision 22).

**Refine.** One line asks Namesake's AI for a change ("shorter sentences", "other names"). It keeps the names unless the request asks for other ones, and the note on the refined listing says which; a refine that does not finish leaves the listing as it was (`docs/decisions.md` #37).

**Volunteer approval.** The volunteer edits and approves the text, then copies a block ready to paste into shelter software.

**Flyer and checklist.** "Print a flyer" prints two pages from the result: the flyer to post (the name, the photo, the listing, who to ask, and a contact line the volunteer types in, which is printed and never saved), and the volunteer's checklist of the places to ask, numbered as on the map, and the other ways to help (decision 35). After approving, the approval page prints the same flyer with the approved text.

## Output 2: name options

Name options come from three sources. Each option carries a badge with what Qloo returned for its title:

| Source | Where it comes from |
|---|---|
| Pet-themed, strong here | Pet-themed titles with Qloo's evidence for the area (decision 22): ranked here by Qloo ("ranked 1st of 8 here by Qloo"), or placed in one of the area's lists, asked with Qloo's pet tags or for fans of another pet title ("in Qloo's list for this area, asked with its pet tags", "liked here by fans of Bluey"). A pet-themed title the AI added with no such evidence (decision 22, when Qloo answered nothing for the area) says "not in the lists Qloo returned for this area", and its name is not called local. |
| Loved here generally | The area's top TV shows (step E). Screened harder, because these lists lean on national hits and identity-coded titles. |
| Title found, or Offered as a candidate (a lookalike) | One or two titles the agent looks up for this animal: a film, show or book with an animal that shares its recorded look. Qloo's line says only that it found the title, or offered it among candidates when it asked which was meant; the match ("A lookalike, matched on this animal's recorded look (brindle coat).", after the reference that names the character) is on the AI's line. Never the first name, so the local version stays local (`docs/decisions.md` #14). |

Each option shows the Qloo title, its kind and Qloo's evidence for the area (its rank here, or its place in one of the area's lists); a lookalike has no area evidence, only the title. Our reading, how the name fits the animal's recorded look, is shown separately; it never mentions temperament, so the reference cannot imply how the animal behaves. Each option comes from a different title while another of the area's open titles is unused (lookalike titles never count), except a litter named as a set. Where Qloo returns a clear lean, an option also says who tends to like its title, from Qloo's audience demographics: the age bands and gender its fans lean toward, with Qloo's skew, across all of Qloo's audiences (never the area's or a person's), and only leans of +0.15 or more; a title with no answer or no clear lean says nothing. Warm and classic show it beside the option, story in "Why these names?". It is there for the volunteer to read and plays no part in choosing names (decision 31). The volunteer picks one. The titles come in the order Qloo's `rank` gave them for the area, or the AI's when ranking is unavailable; raw affinity is never used to order them.

## Output 3: the exposure plan

The plan is a checklist the volunteer can carry out without an ad budget:

1. People near the shelter, and the personal networks of foster carers and volunteers.
2. In-person visibility: outings, events, an "Adopt Me" vest.
3. Timing: in US shelter data, adoptions cluster on Saturdays (where shelters open then) and between 5 and 8 pm.
4. For New York dogs: rescue partners and foster recruitment.
5. **Venues (Qloo):** about three places near the shelter that fans of up to three of the pet-themed entities favour, for flyers and events. Code picks those titles by their evidence for the area (Qloo's ranking, else their best place in the area's lists), titles only about another animal last, never an identity-coded one, and the agent picks the venues: among suitable places near the top or middle of Qloo's list, those that stand out against the area's top shows first, then the rest by rank, never a listed national chain, and asked to pass over fast food (decision 23). Qloo is asked only for kinds of place that can host a stand or take a flyer, in three groups (cafes and breweries, bookshops and pet shops, community places), each in for a stated reason, and the page says which kinds were not asked for and why, and that the places are the same for every animal of that species at the shelter (decision 23). Each venue shows its evidence, and apart from it the agent's reason: why the place could host an adoption event or show a flyer, from its name and Qloo's description only. For an animal recorded as not good with children, venues whose name or Qloo description mentions children are skipped, and the plan says which (decision 2).

The plan's success measure is adoptions and returns; likes and reach are left out.

## How Qloo is used

| Step | Harness workflow | Who decides | Cached per |
|---|---|---|---|
| A. Pet-themed titles the area likes | `recommend` per type with the four pet tags as signals plus `signal_location` (decision 22). As filters the tags returned almost nothing (milestone 1) | code asks; a classifier sorts; agent judges the unclear ones | location |
| B. More pet-themed entities strong here | `describe` for titles the agent adds; then `recommend` with one of them as the signal plus `signal_location`, per type (decision 20) | agent adds and searches; a classifier sorts the search results; agent judges the unclear ones; code keeps only titles Qloo ranks or lists here | location |
| C. Local lift against a baseline | `where_popular` for the top two entities (a thin first one gives way to the next) and the area's top two shows (decision 18); lift = the entities' averaged score in a cell minus the baseline shows', both ranked among the cells scored for both | code computes; nothing is dropped by lift: the map shows it | entity and city |
| D. Venues fans favour | `recommend` for places, up to three entities with the strongest evidence as signals, titles about another animal only last, never an identity-coded one (code picks them), location near the shelter | agent picks about three venues, with reasons | location |
| E. General local tastes | `recommend` for TV shows with `signal_location` | code asks; they are the names' second source, screened like the rest | location |
| F. Check each name's reference | resolve and `describe`; on `needs_input` the agent picks a candidate with a stated reason (candidate buttons are for typed areas only) | agent | entity |
| G. Who tends to like each name's title | `audience_demographics` with the title's ID, after the listing (decision 31) | code asks; shown only, never used to choose | entity |

Steps A to E run once per location and every animal reuses them, so quota cost grows with locations, not animals. Fixed calls, such as the heatmap, use `qloo exec` from code. Calls the agent chooses go through function tools over the same client, so they are cached and spaced too (`docs/decisions.md` #5).

**Use lift, not raw affinity.** Raw affinity saturates near 1.0, and a broad entity's heatmap mostly shows where people are. Lift against a baseline entity is the number that carries taste. See `docs/qloo-findings.md`.

## The result screen

The result screen must be legible in a single screenshot. It shows:
- on the first screen, what Qloo returned for this result and what Namesake's AI did with it, apart: at the top in the warm and classic skins; in story, one line under the name options saying what came from Qloo's data for the area, with the two parts at the top of "How Namesake made this", after the places (`docs/decisions.md` #24, #33)
- the photo and chosen name
- the generic/local toggle, each button showing its version's name; the local one reads "With Qloo" when the name's title has no Qloo evidence for the area
- the name options with what Qloo returned for each title
- a map of local lift, its caption (folded under "About this map" in story, decision 33) counting the cells fans of pet-themed titles rank higher than fans of the area's top shows, a comparison of parts of the area rather than of how many fans (unless the map is thin or has one compared cell or none), with the venues listed beside it under a note on which kinds of place were asked for and why (decision 23), and pinned on it by number, each card saying which cell it sits in and how far it is from the shelter (`docs/decisions.md` #4)
- the exposure checklist
- a "Why" drawer with two columns, "Qloo returned" and "How Namesake read it", the Qloo calls behind the result listed under Qloo's
- in the story skin, the saved run's own step log, folded, each step marked by who did it; and, where the animal has no listing yet, a button that starts a run (for a litter member, the litter's) (decision 27)
- in the story skin, the outcome first: the listing, then the map and the places to ask, then "How Namesake made this", which ends with the trial the local version would need; each place shows Qloo's rank before the AI's reason, and the rest of each place's evidence and the names' Qloo answers are folded one click away (decision 33)
- in the story skin, "Print a flyer" under the copy button, for the version and name shown (decision 35)

The skins that render this screen are a separate choice (`docs/decisions.md` #21 for warm and classic, #24 for story); each keeps every item above, except the three marked as the story skin's.

## Measurement

Each listing records an ID, the animal, the location, the variant (`generic` or `local`), the chosen name and its source, and the time. The README describes the trial the tool enables:
- **Design:** randomise generic against local at intake.
- **Primary outcome:** time to adoption, analysed as time-to-event.
- **Safety outcomes:** returns within 30 and 90 days, plus total shelter adoptions to check that spotlighting one animal isn't taking adopters from another.
- **Sample size:** about 190 adoptions to detect a 50% faster rate.

The hackathon build records the data; it doesn't run the trial.
