# Namesake

Adoption listings for shelter animals, tuned to what people near the shelter love.

A volunteer picks an animal and the shelter's neighbourhood. An agent proposes cultural
references that fit the animal, checks each one against [Qloo](https://www.qloo.com/) taste
data for that area, and writes a name, a short bio and a promotion plan from the ones that
hold up. The same listing is shown in a generic version so the difference is visible.

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

The animals and the shelter are fictional; the photos are AI-generated. Map tiles ©
OpenStreetMap contributors.

## Licence

[MIT](LICENSE)
