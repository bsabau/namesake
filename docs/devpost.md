# Devpost submission text

What was submitted on Devpost on 24 October 2026, with the same day's corrections after Codex, muse and DeepSeek Flash checked it against the evidence, kept here so the repository and the submission say the same thing. On 27 October the "How to try it" section and the two sentences on what the model chooses were added, after Qloo Support said on Discord (26 October) that judges have no Qloo keys of their own, need working access with clear testing instructions, and may judge from the submission materials alone. Same claim rules as the README: no "adopted faster", no "saves lives", no "matching".

**Project name:** Namesake

**Elevator pitch:** Namesake's AI drafts shelter-animal listings from recorded facts only, plus screened names and a plan to get each animal seen, using Qloo taste data near the shelter, beside a generic version.

**Demo:** https://namesake.bogdansabau.eu
**Code:** https://github.com/bsabau/namesake (MIT)
**Began:** October 3, 2026 (the first Qloo probes; the code from 15 October)
**Created by (solo):** I chose the problem, read the research behind the design, made the product and design decisions, and directed the AI coding agents (Claude Code building, Codex and other models reviewing), checking and merging every change. I also run the deployment.

**Gallery** (five images at 1800 × 1200, taken from the live demo on 24 October; the README's screenshots in `docs/img/` show the same result pages, though not the start page):

1. The same dog in Park Slope and Astoria: each area gets its own names, each labelled with the Qloo title it comes from.
2. Places to ask, each with Qloo's rank and why Namesake's AI picked it; the map compares pet-title fans with fans of top local shows.
3. The result: name options labelled with their Qloo titles, a Generic / Local toggle, and a listing written only from recorded facts.
4. How Namesake made this: what Qloo returned, kept apart from what Namesake's AI did with it and what code checked.
5. Start: pick a shelter area and an animal, add your own, or open one of five finished stories. Photos are AI-generated.

**Built with:** python, fastapi, pydantic-ai, qloo, sqlite, jinja, javascript, leaflet, openstreetmap, carto, docker, caddy, uv, github-actions, muse-spark, claude, deepseek, opencode, claude-code, codex

---

## How to try it

Nothing to install, sign up for or pay: the demo runs on my Qloo key and my model accounts, with the everyday usage caps raised far above their defaults for judging. Open https://namesake.bogdansabau.eu.

1. **Read a finished story** (instant). The start page links five precomputed results: the brindle dog in Park Slope (the one in the gallery) and the same dog in Astoria, where the names change with the area; the shy black cat in both; and the border collie-type mix with a bite on record, which the listing states. Each one's own step log is under "How Namesake made this".
2. **Run one live** (about a minute). The twelve animals already have saved results in the four preset areas, Park Slope, Astoria, Austin and Barcelona, so to watch the AI work, add an animal of your own in one of them: the area's Qloo work is saved and shared, and the page streams the listing run, with the lookalike titles the AI looks up in Qloo and the checks on its answer. Refine on any result is a live run too.
3. **Type a new shelter area** (a few minutes, since Qloo calls are spaced 2 seconds apart), then pick an animal and start the run. This is the full run: the page streams Qloo's lists for the area, the titles the AI proposes and looks up in Qloo, the places found, and the checks on its answer. A name Qloo can't settle shows its candidates as buttons, or asks for the city or state when they can't be told apart; an area with too little data is refused with a message.
4. **On the result**, switch between the Generic and the Local, with Qloo versions, open "How Namesake made this" and "Everything Qloo returned, and how Namesake read it" to see what Qloo returned apart from how Namesake read it, type a Refine request such as "other names", then expand "Edit and approve", or follow "Print a flyer".
5. An animal you add is kept for 7 days after your last visit, in a workspace tied to your browser, with no account. The same result data is also served as JSON at `/api/start` and `/api/results/dog-02@park-slope`.

## Inspiration

US shelters and rescues took in about 5.8 million dogs and cats in 2025, and volunteers write a listing for every animal, usually in a hurry, and AI bio writers are already everywhere. None of them has evidence that it helps, and one is known for inventing backstories.

So before writing any code, I read the research. No controlled study shows that a name speeds up adoption. The clearest risk is overselling: adopters who found a dog harder than expected had about ten times the odds of returning it. The largest associations, though only observational, are with being seen: in person, and through foster carers' own networks. And nobody had tested whether local taste data helps at all.

That set the goal: listings that stick to the facts, carefully screened names, and Qloo used for what it can plausibly do, which is finding the pet-themed titles people near a shelter tend to like, and the places their fans favour.

## What it does

A volunteer picks an animal and the shelter's area. In about a minute for an area it already knows (a few minutes for a new one), Namesake's AI produces:

- **a listing written only from the shelter's recorded facts**, with a bite history always stated (one of the five finished examples has one)
- **name options from Qloo taste data**: pet-themed shows, films and books that Qloo ranks or lists near the shelter, shows the area watches anyway, and titles with a lookalike animal that Namesake's AI finds in Qloo, each name labelled with what Qloo returned and screened for villains, violent or tragic characters (famous animals that die in their story among them), aggression and weapon words, words that put an animal down, real people and references coded to a race, religion or political identity
- **a plan to get the animal seen**: local places that fans of those titles favour, with listed national chains, theme parks and places mapped more than 5 km from the shelter left out, on a map, plus foster networks, outings (or a quiet meeting when the record says busy places are hard) and timing

A Generic / Local toggle shows the listing with and without Qloo, so you can see exactly what Qloo adds; when Qloo's data for the area doesn't back a name's title, the button says With Qloo instead of Local. Qloo's data is behind the local names, the places to ask and the map: without Qloo, Namesake still writes the generic listing, but with no local names, no places and no taste layer on the map. A Why drawer keeps what Qloo returned separate from how the app read it. Refine, edit, approve, copy, or print a flyer.

## How we built it

Two PydanticAI agents do the open-ended work. One finds pet-themed titles popular in the area, settles which *Bluey* is meant, ranks them and asks Qloo for places their fans go. The other writes the listing and the names. The model chooses the Qloo calls: which titles of its own to try, which title and which of TV shows, films or books to search the area's lists with, which of Qloo's candidates an ambiguous name means, which places suit an adoption event, and which lookalike titles to check for each animal. It reads each answer and adapts. Code sends the kept titles with the strongest Qloo evidence as the venue signals and fixes the kinds of place asked for, and a title the model proposes is kept only with Qloo's evidence for the area whenever any title has it (otherwise the AI's own stay, and the page says so). Plain code makes the fixed Qloo calls and checks everything the agents return: every title and place must be one Qloo returned, every bio sentence must trace to the recorded facts, and every name must pass the screen. A draft that fails gets one repair round, then falls back to a template.

It's FastAPI and Jinja, Leaflet for the map, SQLite caching every Qloo answer, and one Docker image on a VM. AI agents built and reviewed it under my direction: one wrote the code, and two or three other models reviewed every change before it merged.

## Challenges we ran into

Most of them came from the data. Qloo's pet tags left almost nothing when used as filters, but worked well as signals. Names were ambiguous: 6 of 10 titles came back with several candidates, and a bare "Portland" resolves without saying which one. Popular isn't the same as pet-loving: 9 of the 15 venues Qloo returned near Park Slope for two pet-themed shows also came back for *Yellowstone*, so every place is now compared with what the neighbourhood watches anyway. Name screening was subtler than expected: famous animals that die in their story, and reality shows whose "characters" are real people.

## Accomplishments that we're proud of

- The Generic / Local toggle answers "would this work the same without Qloo?" on the result screen itself.
- What Qloo returned is never blended with the app's interpretation of it.
- The listing is held to the record by code, not by the model's good intentions.
- The claims stay within the evidence, and the app records what a real trial would need.

## What we learned

Read the evidence first; it changed what I built. Qloo's signal is in order and comparison, not raw scores, which saturate near 1.0. Always check what the API actually heard, because Qloo quietly ignores parameters it doesn't recognise. An agent earns its place where the answers are ambiguous; everywhere else, plain code is cheaper and safer. And in this domain, the riskiest thing an AI writer can do is be warm and wrong.

## What's next for Namesake

- **Run the trial:** randomise generic against local listings at intake and measure days to adoption, with returns as a safety check. About 190 adoptions would detect a 50% faster rate, more with several shelters, so it needs a network of rescues rather than one shelter.
- **A cheap test before the trial:** ask people who live near a shelter whether they recognise the titles Qloo picked for their area. If they don't, local names can't help, and the big trial isn't worth running.
- **Paste straight into shelter software**, where listings go out to the adoption sites.

---

Taste data from the Qloo API. Namesake is not affiliated with or endorsed by Qloo. The animals and the shelter are fictional, and the photos are AI-generated.
