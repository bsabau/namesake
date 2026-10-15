"""FastAPI app and routes.

Routes build view models (`app/views/`) and hand them to a UI (`app/ui/<name>/`)
or return them as JSON under `/api/`. Pages never call Qloo live: the location
profile comes from the cache and recordings, built ahead by
`scripts/build_profiles.py`.
"""

import json
from functools import cache
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from app.animals import Animal, load_roster
from app.config import get_settings
from app.locations import Location, load_locations
from app.profile import LocationProfile, build_profile, load_seeds
from app.qloo.cache import Cache
from app.qloo.exec import QlooClient
from app.runs import RUNS, start_run
from app.store import Store
from app.views.build import build_result_view, build_start_view, build_working_view
from app.views.models import ResultView, StartView, WorkingView

HERE = Path(__file__).resolve().parent
UI_ROOT = HERE / "ui"
UIS = sorted(p.name for p in UI_ROOT.iterdir() if (p / "templates").is_dir())

app = FastAPI(title="Namesake")
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
for _ui in UIS:
    app.mount(
        f"/ui/{_ui}/static", StaticFiles(directory=UI_ROOT / _ui / "static"), name=f"ui-{_ui}"
    )


def plain(value):
    """View models as plain data, for `|plain|tojson` in templates."""
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [plain(v) for v in value]
    return value


@cache
def templates_for(ui: str) -> Jinja2Templates:
    templates = Jinja2Templates(directory=UI_ROOT / ui / "templates")
    templates.env.filters["plain"] = plain
    return templates


def pick_ui(requested: str | None) -> str:
    ui = requested or get_settings().ui
    if ui not in UIS:
        raise HTTPException(404, f"no UI named {ui!r}; available: {', '.join(UIS)}")
    return ui


def render(request: Request, ui: str, template: str, view, **extra) -> HTMLResponse:
    def ui_static(path: str) -> str:
        return f"/ui/{ui}/static/{path}"

    # Links keep the chosen UI only when it was asked for explicitly.
    ui_query = f"&ui={ui}" if request.query_params.get("ui") else ""
    context = {"view": view, "ui": ui, "ui_static": ui_static, "ui_query": ui_query, **extra}
    return templates_for(ui).TemplateResponse(request, template, context)


def find_animal(animal_id: str) -> Animal:
    animal = load_roster(get_settings().animals_file).get(animal_id)
    if animal is None:
        raise HTTPException(404, f"no animal {animal_id!r}")
    return animal


def find_location(location_id: str | None) -> Location:
    locations = load_locations(get_settings().locations_file)
    if location_id is None:
        return locations[0]
    location = next((loc for loc in locations if loc.id == location_id), None)
    if location is None:
        raise HTTPException(404, f"no location {location_id!r}")
    return location


def location_profile(location: Location, species: str) -> LocationProfile:
    settings = get_settings()
    saved = Store(settings.cache_db).get_profile(location.id, species)
    if saved is not None:
        return saved
    # No agent run yet: the fixed lookup, in replay only, so a page never spends
    # quota. A missing profile shows as notes.
    qloo = QlooClient(
        Cache(settings.cache_db), mode="replay", recordings=settings.qloo_recordings, env={}
    )
    return build_profile(qloo, location, load_seeds(settings.seeds_file))


def start_view(location: str | None) -> StartView:
    settings = get_settings()
    locations = load_locations(settings.locations_file)
    # An unknown or missing ?location= falls back to the first preset.
    selected = next((loc for loc in locations if loc.id == location), locations[0])
    return build_start_view(load_roster(settings.animals_file), locations, selected.id)


def result_view(animal_id: str, location_id: str | None) -> ResultView:
    location = find_location(location_id)
    animal = find_animal(animal_id)
    listing = Store(get_settings().cache_db).get_listing(animal.id, location.id)
    return build_result_view(animal, location, location_profile(location, animal.species), listing)


def find_run(run_id: str):
    run = RUNS.get(run_id)
    if run is None:
        raise HTTPException(404, "no such run; runs are kept until the server restarts")
    return run


def working_view(run, ui_query: str = "") -> WorkingView:
    return build_working_view(
        run, find_animal(run.animal_id), find_location(run.location_id), ui_query
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def start(request: Request, location: str | None = None, ui: str | None = None) -> HTMLResponse:
    return render(request, pick_ui(ui), "start.html", start_view(location))


@app.get("/result", response_class=HTMLResponse)
def result(
    request: Request, animal: str, location: str | None = None, ui: str | None = None
) -> HTMLResponse:
    return render(request, pick_ui(ui), "result.html", result_view(animal, location))


@app.get("/api/start")
def api_start(location: str | None = None) -> StartView:
    return start_view(location)


@app.get("/api/results/{result_id}")
def api_result(result_id: str) -> ResultView:
    animal_id, _, location_id = result_id.partition("@")
    if not location_id:
        raise HTTPException(404, "a result id looks like <animal>@<location>")
    return result_view(animal_id, location_id)


@app.post("/runs")
async def create_run(
    animal: str = Form(...), location: str = Form(...), ui: str | None = Form(None)
) -> RedirectResponse:
    run = await start_run(find_animal(animal), find_location(location), get_settings())
    suffix = f"?ui={pick_ui(ui)}" if ui else ""
    return RedirectResponse(f"/runs/{run.id}{suffix}", status_code=303)


@app.get("/runs/{run_id}", response_class=HTMLResponse)
def working(request: Request, run_id: str, ui: str | None = None) -> HTMLResponse:
    chosen = pick_ui(ui)
    view = working_view(find_run(run_id), f"&ui={chosen}" if ui else "")
    return render(request, chosen, "working.html", view)


@app.get("/api/runs/{run_id}")
def api_run(run_id: str) -> WorkingView:
    return working_view(find_run(run_id))


@app.get("/api/runs/{run_id}/events")
async def run_events(run_id: str) -> StreamingResponse:
    """The step log as server-sent events: one `step` per step, then `done`."""
    run = find_run(run_id)

    async def stream():
        async for step in run.log.follow():
            payload = json.dumps({"kind": step.kind, "text": step.text})
            yield f"event: step\ndata: {payload}\n\n"
        yield f"event: done\ndata: {json.dumps({'result_url': run.result_url})}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")
