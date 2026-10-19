# Devpost submission text

Paste-ready sections for the Devpost form. Same claim rules as the README: no "adopted faster", no "saves lives", no "matching".

**Project name:** Namesake

**Tagline (under 200 characters):** Namesake's AI writes accurate shelter-animal listings, screened names and a plan to get each animal seen, using Qloo taste data near the shelter, with a generic version beside it.

**Demo:** https://namesake.bogdansabau.eu
**Code:** https://github.com/bsabau/namesake (MIT)

---

## Inspiration

US shelters and rescues took in about 5.8 million dogs and cats in 2025. Large adult dogs wait longest: about 70% longer than small dogs before adoption. Volunteers write a listing for every animal, often in a hurry, and free AI bio writers are already common. None has outcome evidence, and a documented complaint about one is that it invents a backstory.

Before building, I read the research on what listings can and cannot do. No study shows that a name speeds adoption. Wording effects with real outcomes are about 1 to 3 days. The measurable harm is overselling: adopters who found a dog more work than expected had about ten times the odds of returning it. Being seen in person, and through foster carers' own networks, shows the largest associations. And nobody has tested whether local taste data helps at all.

So the idea became: use Qloo for what it can plausibly do, which is finding pet-interested audiences and places near a shelter, and make the rest of the tool accurate, careful and measurable.

## What it does

A volunteer picks an animal and the shelter's area. In about a minute Namesake's AI produces:

- **An accurate listing**, written only from the facts the shelter recorded. Third person, behaviour toward people first, plain words. A bite history is always stated, and anything the shelter marked unknown is left out. Code checks each bio sentence against the facts and sends back content words they don't contain.
- **Name options from Qloo taste data**, each with what Qloo returned for its title: a pet-themed title strong in the area, or something the area tends to watch. A title with an animal that looks like this one is also offered; Qloo finds the title (or offers candidates when it is ambiguous), and the match is labelled as the reading of Namesake's AI. Every name is screened for villains, tragic or violent characters, aggression words, real people and identity-coded references, with the strictest screen for bully-breed dogs.
- **A plan to get the animal seen**: foster and volunteer networks, outings in an "Adopt Me" vest, timing for Saturdays and early evenings, rescue partners for New York dogs, and up to three local venues that fans of pet-themed shows and films favour, each with Qloo's rank and its comparison against the shows the area watches most.

A **Generic / Local, with Qloo** toggle shows both versions of the listing, each button carrying its version's name. They share the same bio; the local one adds a name from Qloo's titles and one line saying where it comes from. That is exactly what Qloo contributes, visible in one click.

A **Why** drawer separates "Qloo returned" from "How Namesake read it" for every choice. The volunteer can refine with one line, edit, approve, and copy a block ready to paste into shelter software. Typing a new area works too: Qloo checks it first, and if the data is thin the app says so instead of producing a weak result.

## How I built it

- **Namesake's AI: two PydanticAI agents with Qloo tools.** The area agent starts from the pet-themed titles Qloo lists for the area, may add its own, looks each up with Qloo's `describe`, settles ambiguous ones with a stated reason, ranks them with `rank`, asks `recommend` for places their fans favour, and judges which venues suit an adoption event, choosing first those that stand out against the area's own top shows. The listing agent writes the bio and name options, and can look up up to two titles featuring an animal that shares this one's recorded look.
- **Plain code around them.** The area's own top two shows, as a baseline, and `where_popular` heatmaps within the neighbourhood (the top two pet titles against those two shows, averaged per cell) give each venue and map cell a comparison: lift, not raw affinity, because raw scores saturate near 1.0. Code picks which titles the venues are asked for, by Qloo's evidence, and checks that every title and venue came from Qloo in that run, that every bio sentence cites recorded facts and adds no content word they lack, that names pass the screen, that no two animals at a shelter share a name, that one animal's options come from different titles, and that a name's reason uses only the recorded look, never temperament. One repair round, then a templated listing that says why.
- **The official Qloo harness** (`qloo exec`), wrapped in a typed client that handles every envelope status, caches every answer in SQLite, and spaces calls 5 seconds apart, because the hackathon key is rate-limited.
- **FastAPI, Jinja and a little JavaScript**, with server-sent events for the live step log, Leaflet and OpenStreetMap for the map, and view models also served as JSON so the interface is replaceable.
- **One Docker image** with Python, Node and the pinned harness, on a long-lived VM behind Caddy, with the cache on a private volume.
- **Tests that never touch Qloo or a model**: over 650 of them, on hand-written envelopes with invented IDs, plus a test that fails if real Qloo data ever enters the repo.

## Challenges I ran into

- **Pet tags as filters weren't enough; as signals they were.** Filtering TV and film to Qloo's pet tags left two shows and no films. With the tags and the area as signals, Qloo listed 3 to 8 pet-themed titles for each area we probed, so those come first, and a title Namesake's AI adds stays only if Qloo ranks or lists it there (in an area where no title has that evidence, the AI's own stay, and the page says so).
- **Names are ambiguous.** 6 of 10 pet-themed titles looked up by name came back as candidates: *Bluey* is a children's series and a 1976 crime drama. Choosing with a stated reason became a real agent step, and any `needs_input` answer is shown as the choice of Namesake's AI, never as a confirmed match.
- **Popular is not the same as pet-loving.** 9 of the first 15 venues near Park Slope also came back for *Yellowstone*, an unrelated show. Comparing against a baseline turned a list of popular places into evidence, and the baseline is now the area's own top shows, so a place stands out for fans of pet-themed titles against what that neighbourhood watches anyway.
- **The rate limit.** About 12 calls in 20 minutes, `rank` the strictest. Everything is cached, the area work is shared by every animal there, and the demo examples are precomputed.
- **Venue suitability.** Near Astoria, Qloo's list mixed a museum and a sculpture park with nightclubs. A keyword screen and the judgement of Namesake's AI each catch what the other misses.

## Accomplishments that I'm proud of

- The generic-versus-local toggle answers "would this work the same without Qloo?" on the result screen itself.
- Provenance everywhere: what Qloo returned is never blended with how Namesake read it.
- A listing generator held to the record by code, not by the model's good intentions: a sentence with a content word the facts don't contain is sent back, and the volunteer edits and approves the rest. And a name screen built from published research rather than taste.
- Honest scope: the tool claims what the evidence supports and records what a real trial would need.

## What I learned

- Qloo is most useful here as a check on the ideas of Namesake's AI and a source of comparisons, not as an oracle: order within a call and lift against a baseline carry the signal.
- An agent earns its place where answers are ambiguous: choosing between candidates, judging venues, deciding what to try next.
- In this domain the riskiest thing an AI writer can do is be warm and wrong.

## What's next for Namesake

- **Run the trial.** Randomise generic against local listings at intake, with time to adoption as the outcome and 30- and 90-day returns as safety checks. About 190 adoptions would detect a 50% faster rate; a network of rescues could get there.
- **Test recognition cheaply first:** show residents the locally popular titles and measure whether they recognise them.
- **Pet-owner places:** pet-supply brands as venue signals gave a list with less overlap with the baseline and a pet shop; it needs screening before it is useful.
- **Paste straight into shelter software**, since the description field there is where listings enter every adoption site.

## Built with

python, fastapi, pydantic-ai, qloo, sqlite, jinja, leaflet, openstreetmap, docker, caddy, uv

---

Taste data from the Qloo API. Namesake is not affiliated with or endorsed by Qloo. The animals and the shelter are fictional, and the photos are AI-generated.
