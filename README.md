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

Open http://localhost:8000.

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
