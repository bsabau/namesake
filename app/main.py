"""FastAPI app and routes.

Routes build view models (`app/views/`) and hand them to a UI (`app/ui/<name>/`)
or return them as JSON under `/api/`. Pages never call Qloo live: the location
profile comes from the cache and recordings, built ahead by
`scripts/build_profiles.py`.
"""

import json
import re
import uuid
import zlib
from datetime import UTC, datetime
from functools import cache
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ValidationError

from app.agent.pipeline import taken_names
from app.animals import Animal, Checks, load_roster
from app.config import get_settings
from app.custom_location import PREFIX as CUSTOM_PREFIX
from app.custom_location import check_location, clean, location_id
from app.limits import LimitReached
from app.listing import generic_name, missing_cautions
from app.locations import Location, load_locations
from app.profile import LocationProfile, build_profile, load_seeds
from app.qloo.cache import Cache
from app.qloo.exec import QlooClient
from app.runs import RUNS, limits_for, qloo_client, start_litter_run, start_run
from app.session import (
    ADDED_PREFIX,
    COOKIE,
    MAX_ANIMALS,
    MAX_PHOTO_BYTES,
    SESSIONS,
    TTL,
    Photo,
    Session,
    Sessions,
    photo_type,
)
from app.store import Approval, Store
from app.views.build import (
    added_photo_url,
    animal_card,
    build_add_animal_view,
    build_approved_view,
    build_result_view,
    build_start_view,
    build_working_view,
    copy_block,
    example_links,
)
from app.views.models import (
    LitterMateView,
    LocationForm,
    NoticeView,
    ResultView,
    StartView,
    WorkingView,
)

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


@app.middleware("http")
async def session_cookie(request: Request, call_next):
    """Give each visitor a random session ID; the cookie holds nothing else."""
    session_id = request.cookies.get(COOKIE) or ""
    fresh = not re.fullmatch(r"[\w-]{20,40}", session_id)
    if fresh:
        session_id = Sessions.new_id()
    request.state.session_id = session_id
    response = await call_next(request)
    if fresh:
        response.set_cookie(
            COOKIE,
            session_id,
            max_age=TTL,
            httponly=True,
            samesite="lax",
            secure=request.url.scheme == "https",
        )
    return response


def session_of(request: Request) -> Session | None:
    return SESSIONS.get(request.state.session_id)


def own_session(request: Request) -> Session:
    return SESSIONS.ensure(request.state.session_id)


def visitor(request: Request) -> str:
    # Behind a proxy, uvicorn's --proxy-headers sets this from X-Forwarded-For.
    return request.client.host if request.client else "unknown"


def notice(
    request: Request, ui: str, title: str, message: str, status: int, links=()
) -> HTMLResponse:
    view = NoticeView(title=title, message=message, links=list(links))
    response = render(request, ui, "notice.html", view)
    response.status_code = status
    return response


def find_animal(animal_id: str, session: Session | None = None) -> Animal:
    if animal_id.startswith(ADDED_PREFIX):
        animal = session.animals.get(animal_id) if session else None
        if animal is None:
            raise HTTPException(404, "that animal was added in another visit and has expired")
        return animal
    animal = load_roster(get_settings().animals_file).get(animal_id)
    if animal is None:
        raise HTTPException(404, f"no animal {animal_id!r}")
    return animal


def find_location(location_id: str | None) -> Location:
    settings = get_settings()
    locations = load_locations(settings.locations_file)
    if location_id is None:
        return locations[0]
    location = next((loc for loc in locations if loc.id == location_id), None)
    if location is None and location_id.startswith(CUSTOM_PREFIX):
        location = Store(settings.cache_db).get_location(location_id)
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


def ui_suffix(request: Request, ui: str | None) -> str:
    return f"&ui={ui}" if ui else ""


def start_view(
    location: str | None,
    session: Session | None = None,
    form: LocationForm | None = None,
    ui_query: str = "",
) -> StartView:
    settings = get_settings()
    store = Store(settings.cache_db)
    locations = load_locations(settings.locations_file)
    if location and location.startswith(CUSTOM_PREFIX):
        custom = store.get_location(location)
        if custom is not None:
            locations.append(custom)
    # An unknown or missing ?location= falls back to the first preset.
    selected = next((loc for loc in locations if loc.id == location), locations[0])
    ready = {
        (a, loc.id)
        for a in ("dog-02", "kitten-01")
        for loc in locations
        if store.get_listing(a, loc.id) is not None
    }
    added = [
        animal_card(a, added_photo_url(a, a.id in session.photos))
        for a in (session.animals.values() if session else [])
    ]
    view = build_start_view(
        load_roster(settings.animals_file),
        locations,
        selected.id,
        examples=example_links(ready, ui_query),
        added=added,
    )
    if form is not None:
        view.location_form = form
    return view


def generic_seed(animal: Animal) -> int:
    roster = load_roster(get_settings().animals_file)
    ids = [a.id for a in roster.animals]
    return ids.index(animal.id) if animal.id in ids else zlib.crc32(animal.id.encode())


def litter_view(animal: Animal, location: Location, store: Store) -> list[LitterMateView]:
    if animal.litter is None:
        return []
    roster = load_roster(get_settings().animals_file)
    mates = []
    for a in roster.animals:
        if a.litter != animal.litter:
            continue
        saved = store.get_listing(a.id, location.id)
        name = saved.draft.names[0].name if saved and saved.draft else ""
        mates.append(
            LitterMateView(
                name=name,
                url=f"/result?animal={a.id}&location={location.id}",
                current=a.id == animal.id,
            )
        )
    return mates


def result_view(animal_id: str, location_id: str | None, session: Session | None) -> ResultView:
    location = find_location(location_id)
    animal = find_animal(animal_id, session)
    store = Store(get_settings().cache_db)
    key = f"{animal.id}@{location.id}"
    listing = session.listings.get(key) if session else None
    refined = session.requests.get(key) if session and listing else None
    if listing is None and not animal.id.startswith(ADDED_PREFIX):
        listing = store.get_listing(animal.id, location.id)
    own = {o.name.lower() for o in listing.draft.names} if listing and listing.draft else set()
    taken = taken_names(animal, location, store, set()) | own
    added = animal.id.startswith(ADDED_PREFIX)
    return build_result_view(
        animal,
        location,
        location_profile(location, animal.species),
        listing,
        generic=generic_name(generic_seed(animal), taken),
        refined=refined,
        litter=litter_view(animal, location, store),
        image_url=added_photo_url(animal, animal.id in session.photos) if added else None,
    )


def find_run(run_id: str):
    run = RUNS.get(run_id)
    if run is None:
        raise HTTPException(404, "no such run; runs are kept until the server restarts")
    return run


def working_view(run, ui_query: str = "") -> WorkingView:
    session = SESSIONS.get(run.session_id) if run.session_id else None
    animal = find_animal(run.animal_id, session)
    image_url = None
    if animal.id.startswith(ADDED_PREFIX):
        image_url = added_photo_url(animal, animal.id in session.photos)
    return build_working_view(run, animal, find_location(run.location_id), ui_query, image_url)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def start(request: Request, location: str | None = None, ui: str | None = None) -> HTMLResponse:
    chosen = pick_ui(ui)
    view = start_view(location, session_of(request), ui_query=ui_suffix(request, ui))
    return render(request, chosen, "start.html", view)


@app.get("/result", response_class=HTMLResponse)
def result(
    request: Request, animal: str, location: str | None = None, ui: str | None = None
) -> HTMLResponse:
    view = result_view(animal, location, session_of(request))
    return render(request, pick_ui(ui), "result.html", view)


@app.get("/api/start")
def api_start(request: Request, location: str | None = None) -> StartView:
    return start_view(location, session_of(request))


@app.get("/api/results/{result_id}")
def api_result(request: Request, result_id: str) -> ResultView:
    animal_id, _, location_id = result_id.partition("@")
    if not location_id:
        raise HTTPException(404, "a result id looks like <animal>@<location>")
    return result_view(animal_id, location_id, session_of(request))


def run_redirect(run, ui: str | None) -> RedirectResponse:
    suffix = f"?ui={pick_ui(ui)}" if ui else ""
    return RedirectResponse(f"/runs/{run.id}{suffix}", status_code=303)


def limit_notice(request: Request, ui: str | None, exc: LimitReached) -> HTMLResponse:
    return notice(
        request,
        pick_ui(ui),
        "Not right now",
        str(exc),
        429,
        [("Back to the start", "/" + (f"?ui={ui}" if ui else ""))],
    )


@app.post("/runs", response_model=None)
async def create_run(
    request: Request,
    animal: str = Form(...),
    location: str = Form(...),
    ui: str | None = Form(None),
) -> Response:
    settings = get_settings()
    place = find_location(location)
    litter = next(
        (lit for lit in load_roster(settings.animals_file).litters if lit.id == animal), None
    )
    try:
        if litter is not None:
            run = await start_litter_run(litter, place, settings, visitor=visitor(request))
        else:
            session = session_of(request)
            chosen = find_animal(animal, session)
            run = await start_run(
                chosen, place, settings, visitor=visitor(request), session=session
            )
    except LimitReached as exc:
        return limit_notice(request, ui, exc)
    return run_redirect(run, ui)


REFINE_MAX = 200


@app.post("/refine", response_model=None)
async def refine(
    request: Request,
    animal: str = Form(...),
    location: str = Form(...),
    text: str = Form(""),
    ui: str | None = Form(None),
) -> Response:
    """A new listing for this visitor only, following one follow-up request."""
    asked = " ".join(text.split())
    if not 3 <= len(asked) <= REFINE_MAX:
        raise HTTPException(400, f"a refine request is 3 to {REFINE_MAX} characters")
    session = own_session(request)
    chosen, place = find_animal(animal, session), find_location(location)
    try:
        run = await start_run(
            chosen, place, get_settings(), visitor=visitor(request), session=session, request=asked
        )
    except LimitReached as exc:
        return limit_notice(request, ui, exc)
    return run_redirect(run, ui)


@app.post("/refine/reset")
def refine_reset(
    request: Request,
    animal: str = Form(...),
    location: str = Form(...),
    ui: str | None = Form(None),
) -> RedirectResponse:
    session = session_of(request)
    key = f"{animal}@{location}"
    if session is not None and key in session.requests:
        session.listings.pop(key, None)
        session.requests.pop(key, None)
    return RedirectResponse(
        f"/result?animal={animal}&location={location}{ui_suffix(request, ui)}", status_code=303
    )


TEXT_MAX = 3000


@app.post("/approve", response_class=HTMLResponse)
def approve(
    request: Request,
    animal: str = Form(...),
    location: str = Form(...),
    variant: str = Form(...),
    text: str = Form(...),
    local_name: str | None = Form(None),
    ui: str | None = Form(None),
) -> HTMLResponse:
    """Record the approval (never the text) and show the copy-ready listing."""
    chosen_ui = pick_ui(ui)
    session = session_of(request)
    view = result_view(animal, location, session)
    version = next((v for v in view.listing.versions if v.variant == variant and v.available), None)
    if version is None:
        raise HTTPException(400, "that version is not available for this animal")
    edited = "\n\n".join(" ".join(p.split()) for p in text.strip().split("\n\n") if p.strip())
    if not edited or len(edited) > TEXT_MAX:
        raise HTTPException(400, f"the listing text is 1 to {TEXT_MAX} characters")

    hook = None
    if variant == "local":
        option = next((o for o in view.name.options if o.name == local_name), None)
        if option is None:
            raise HTTPException(400, "pick one of the name options")
        name, hook = option.name, option.hook
        source = f"Qloo, {option.badge.lower()}: {option.title}"
    else:
        name, source = version.name, "a fixed list of common pet names, not Qloo"

    missing = missing_cautions(find_animal(animal, session), edited)
    if missing:
        view.approve_error = (
            "Not approved: the edit dropped or reworded what the shelter recorded as a "
            "caution. Keep these words: " + "; ".join(f"“{m}”" for m in missing) + "."
        )
        view.edited_text = edited
        # Keep what the volunteer picked, so only the text needs fixing.
        for v in view.listing.versions:
            v.selected = v.variant == variant
            if v.variant == "local":
                v.name, v.hook = name if variant == "local" else v.name, hook or v.hook
                v.copy_text = copy_block(v.name, v.hook, view.listing.text)
        view.chosen_name = name if variant == "local" else view.name.value
        return render(request, chosen_ui, "result.html", view)

    approval = Approval(
        id=uuid.uuid4().hex[:10],
        animal_id="added" if animal.startswith(ADDED_PREFIX) else animal,
        location_id=view.location.id,
        variant=variant,
        name=name,
        name_source=source,
        edited=" ".join(edited.split()) != " ".join(view.listing.text.split()),
        approved_at=datetime.now(UTC).isoformat(),
    )
    Store(get_settings().cache_db).record_approval(approval)
    approved = build_approved_view(
        approval.id,
        view,
        version.label,
        copy_block(name, hook, edited),
        name,
        source,
        approval.edited,
        f"/result?animal={animal}&location={location}{ui_suffix(request, ui)}",
    )
    return render(request, chosen_ui, "approved.html", approved)


@app.get("/photos/{animal_id}")
def photo(request: Request, animal_id: str) -> Response:
    """An added animal's photo, served back to the visitor who added it, and no one else."""
    session = session_of(request)
    stored = session.photos.get(animal_id) if session else None
    if stored is None:
        raise HTTPException(404, "no such photo in this visit")
    return Response(
        stored.data,
        media_type=stored.content_type,
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


MAX_FACTS = 6
FIELD_MAX = 120


@app.get("/animals/new", response_class=HTMLResponse)
def new_animal(request: Request, location: str | None = None, ui: str | None = None):
    view = build_add_animal_view(find_location(location).id, MAX_FACTS)
    return render(request, pick_ui(ui), "add_animal.html", view)


def _short(value: str, label: str, required: bool = True) -> str:
    value = " ".join(value.split())
    if required and not value:
        raise ValueError(f"{label} is needed")
    if len(value) > FIELD_MAX:
        raise ValueError(f"{label} is at most {FIELD_MAX} characters")
    return value


@app.post("/animals", response_class=HTMLResponse)
async def add_animal(
    request: Request,
    location: str = Form(...),
    species: str = Form(...),
    sex: str = Form(...),
    age: str = Form(...),
    look: str = Form(...),
    temperament: str = Form(...),
    facts: str = Form(""),
    good_with_children: str = Form("unknown"),
    good_with_dogs: str = Form("unknown"),
    good_with_cats: str = Form("unknown"),
    house_trained: str = Form("unknown"),
    bite_history: str = Form("unknown"),
    photo: UploadFile | None = File(None),
    ui: str | None = Form(None),
):
    """Add one animal for this visit only: kept in memory, never stored."""
    chosen_ui = pick_ui(ui)
    place = find_location(location)
    session = own_session(request)

    def refuse(message: str) -> HTMLResponse:
        view = build_add_animal_view(place.id, MAX_FACTS, error=message)
        response = render(request, chosen_ui, "add_animal.html", view)
        response.status_code = 400
        return response

    if len(session.animals) >= MAX_ANIMALS:
        return refuse(f"One visit can add up to {MAX_ANIMALS} animals.")
    try:
        if species not in ("dog", "cat") or sex not in ("female", "male"):
            raise ValueError("pick a species and a sex")
        fact_lines = [_short(f, "Each fact") for f in facts.splitlines() if f.strip()]
        if len(fact_lines) > MAX_FACTS:
            raise ValueError(f"up to {MAX_FACTS} facts, one per line")
        age_text = _short(age, "The age")
        young = re.search(r"\b(week|month)s?\b", age_text) is not None
        animal = Animal(
            id=ADDED_PREFIX + uuid.uuid4().hex[:8],
            species=species,
            group=("puppy" if species == "dog" else "kitten") if young else f"adult {species}",
            sex=sex,
            age=age_text,
            look=_short(look, "The look"),
            temperament=_short(temperament, "The temperament"),
            facts=fact_lines,
            checks=Checks(
                good_with_children=good_with_children,
                good_with_dogs=good_with_dogs,
                good_with_cats=good_with_cats,
                house_trained=house_trained,
                bite_history=bite_history,
            ),
            image="",
        )
    except ValidationError:
        return refuse("Each yes/no question takes yes, no or unknown.")
    except ValueError as exc:
        return refuse(str(exc)[:1].upper() + str(exc)[1:] + ".")

    if photo is not None and photo.filename:
        data = await photo.read(MAX_PHOTO_BYTES + 1)
        if len(data) > MAX_PHOTO_BYTES:
            return refuse("The photo is larger than 3 MB.")
        content_type = photo_type(data)
        if content_type is None:
            return refuse("The photo must be a JPEG, PNG or WebP image.")
        session.photos[animal.id] = Photo(content_type=content_type, data=data)
    session.animals[animal.id] = animal
    return RedirectResponse(
        f"/?location={place.id}{ui_suffix(request, ui)}#{animal.id}", status_code=303
    )


@app.post("/locations", response_class=HTMLResponse)
def add_location(request: Request, text: str = Form(""), ui: str | None = Form(None)):
    """A typed shelter area: checked with Qloo once, then offered like a preset."""
    chosen_ui = pick_ui(ui)
    settings = get_settings()
    store = Store(settings.cache_db)
    typed = " ".join(text.split())

    def back(form: LocationForm, status: int) -> HTMLResponse:
        view = start_view(None, session_of(request), form, ui_suffix(request, ui))
        response = render(request, chosen_ui, "start.html", view)
        response.status_code = status
        return response

    cleaned = clean(typed)
    if cleaned is not None:
        known = store.get_location(location_id(cleaned))
        if known is not None:
            return RedirectResponse(
                f"/?location={known.id}{ui_suffix(request, ui)}", status_code=303
            )
    try:
        if cleaned is not None:
            limits_for(settings).charge(visitor(request), "location")
    except LimitReached as exc:
        return back(LocationForm(message=str(exc), value=typed), 429)

    checked = check_location(qloo_client(settings), typed, load_seeds(settings.seeds_file))
    if checked.status != "ok" or checked.location is None:
        status = 400 if checked.status in ("invalid", "thin", "needs_input") else 503
        form = LocationForm(message=checked.message, value=typed, candidates=checked.candidates)
        return back(form, status)
    store.put_location(checked.location)
    return RedirectResponse(
        f"/?location={checked.location.id}{ui_suffix(request, ui)}", status_code=303
    )


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
        payload = {"result_url": run.result_url, "failed": run.failed, "error": run.error}
        yield f"event: done\ndata: {json.dumps(payload)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")
