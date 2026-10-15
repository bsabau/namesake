# Namesake

Accurate adoption listings for shelter animals, with names and a plan to get them seen,
drawn from local taste data.

A volunteer picks an animal and the shelter's neighbourhood. From the facts the volunteer
recorded, an agent writes a plain, accurate listing and offers name options. It also builds an
exposure plan, using [Qloo](https://www.qloo.com/) taste data to find pet-themed shows,
films, books and brands that are strong near the shelter, and the venues their fans favour.
A generic version sits beside the local one so Qloo's contribution is visible. The local
layer is an experiment, and the app records what is needed to test it.

Built for the Qloo Agentic Hackathon.

> Work in progress. Sections marked TODO are filled in as the milestones land.

## The problem

TODO

## How it uses Qloo

TODO: which workflows, and why.

## From request to result

TODO

## Run it locally

Needs Python 3.12 with [uv](https://docs.astral.sh/uv/), and Node 22.19+ with the Qloo
harness (`npm install -g @qloo/qloo-harness@0.1.26`).

```sh
cp .env.example .env      # then fill in the values
uv sync
uv run uvicorn app.main:app --reload
```

Picking an animal starts an agent run, shown live on a Working page: the agent proposes
pet-themed titles, settles ambiguous names, ranks them for the area, picks venues, then
writes name options, a bio from the recorded facts and a hook. Plain code checks every
answer; failures fall back to the fixed lookup and the templated listing, and say so.

Qloo calls are cached in `var/` and spaced a few seconds apart; set `ALLOW_LIVE_QLOO=false`
to use only the cache. To fill the cache for the preset locations without the agent:

```sh
uv run python scripts/build_profiles.py --live
uv run python scripts/run_agent.py dog-02 park-slope   # one agent run from the terminal
```

Open http://localhost:8000. Add `?ui=<name>` to try another interface from `app/ui/`, and
`/api/start` or `/api/results/dog-02@park-slope` for the same data as JSON.

Tests and lint:

```sh
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

## Run it with Docker

```sh
docker build -t namesake .
docker run --rm -p 8000:8000 --env-file .env namesake
```

## Known limitations

TODO

## Credits

Taste data from the Qloo API. This project is not affiliated with or endorsed by Qloo.

The animals and the shelter are fictional; the photos are AI-generated. Map tiles ©
OpenStreetMap contributors.

## Licence

[MIT](LICENSE)
