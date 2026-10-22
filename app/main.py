"""FastAPI app and routes.

Routes build view models (`app/views/`) and hand them to a UI (`app/ui/<name>/`)
or return them as JSON under `/api/`. Pages never call Qloo live: the location
profile comes from the cache and recordings, built ahead by
`scripts/build_profiles.py`.
"""

import hashlib
import json
import logging
import mimetypes
import re
import uuid
import zlib
from datetime import UTC, datetime
from functools import cache
from pathlib import Path
from urllib.parse import urlencode, urlsplit

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import HTMLResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.formparsers import MultiPartParser

from app.agent.checks import reference_key, same_reference
from app.agent.pipeline import taken_names, taken_references
from app.animals import Animal, Checks, load_roster
from app.config import get_settings
from app.custom_location import INVALID, clean, location_id
from app.custom_location import PREFIX as CUSTOM_PREFIX
from app.limits import LimitReached
from app.listing import generic_name, missing_cautions, stage_for
from app.locations import Location, load_locations
from app.places import (
    MAX_PIN_KM,
    PIN_DECIMALS,
    Allowance,
    LookupFailed,
    Places,
    Throttled,
    distance_km,
    places_for,
)
from app.profile import LocationProfile, build_profile, load_seeds
from app.qloo.cache import Cache
from app.qloo.exec import QlooClient
from app.runs import (
    FAR_PIN,
    RUNS,
    start_area_run,
    start_litter_run,
    start_run,
    visit_names,
)
from app.session import (
    ADDED_PREFIX,
    COOKIE,
    MAX_ANIMALS,
    MAX_PHOTO_BYTES,
    PHOTO_BUDGET,
    SECURE_COOKIE,
    SESSIONS,
    Photo,
    Session,
    drop_listings,
    photo_type,
)
from app.store import Approval, Store
from app.views.build import (
    EXAMPLES,
    added_photo_url,
    animal_card,
    area_check_view,
    build_add_animal_view,
    build_approved_view,
    build_flyer_view,
    build_result_view,
    build_start_view,
    build_working_view,
    copy_block,
    example_links,
)
from app.views.models import (
    TYPED_AREA,
    LitterMateView,
    LocationForm,
    NameOptionView,
    NoticeView,
    PlaceOption,
    PlacesView,
    ResultView,
    StartView,
    WorkingView,
)
from app.workspace import TTL as WORKSPACE_TTL

HERE = Path(__file__).resolve().parent
UI_ROOT = HERE / "ui"
UIS = sorted(p.name for p in UI_ROOT.iterdir() if (p / "templates").is_dir())

# The warm and story UIs serve their own fonts. A slim Linux image has no mime.types file,
# so without this the files go out as application/octet-stream.
mimetypes.add_type("font/woff2", ".woff2")
mimetypes.add_type("font/woff", ".woff")

# The app's own log lines (each agent run's model usage, a model handing a run on, a model
# skipped for a bad setting) go to the server log, to watch the cost (decision 25).
# Uvicorn configures only its own loggers, so the app's get a handler.
_app_log = logging.getLogger("app")
_app_log.setLevel(logging.INFO)
if not _app_log.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    _app_log.addHandler(_handler)

# No interactive API docs: their pages load scripts from a CDN and inline, which the
# Content-Security-Policy below refuses, so they would be blank. /openapi.json stays.
app = FastAPI(title="Namesake", docs_url=None, redoc_url=None)
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


def places() -> Places:
    return places_for(get_settings().geocoder_url)


def pick_ui(requested: str | None) -> str:
    ui = requested or get_settings().ui
    if ui not in UIS:
        raise HTTPException(404, f"no UI named {ui!r}; available: {', '.join(UIS)}")
    return ui


@cache
def static_version(ui: str) -> str:
    """A short hash of a UI's static files. Links carry it, so a deploy that changes a
    script or stylesheet gives it a new URL and no browser keeps running the old one."""
    digest = hashlib.sha256()
    for path in sorted((UI_ROOT / ui / "static").rglob("*")):
        if path.is_file():
            digest.update(path.name.encode() + path.read_bytes())
    return digest.hexdigest()[:10]


def render(request: Request, ui: str, template: str, view, **extra) -> HTMLResponse:
    def ui_static(path: str) -> str:
        return f"/ui/{ui}/static/{path}?v={static_version(ui)}"

    # Links keep the chosen UI only when it was asked for explicitly.
    ui_query = f"&ui={ui}" if request.query_params.get("ui") else ""
    context = {"view": view, "ui": ui, "ui_static": ui_static, "ui_query": ui_query, **extra}
    return templates_for(ui).TemplateResponse(request, template, context)


# Uploads up to this size stay in memory: Starlette spools larger ones to disk, so the
# limit is raised past the largest request accepted, and larger requests are refused
# before they are read. A photo reaches disk only in its workspace (decision 34), never
# as a temporary file.
MAX_UPLOAD_REQUEST = MAX_PHOTO_BYTES + 64 * 1024
MultiPartParser.spool_max_size = MAX_UPLOAD_REQUEST


# Animals added per visitor per minute: a few to fix a mistake, too few to fill memory.
ADD_ALLOWANCE = Allowance(per_minute=5)
# Photos per visitor per hour. The photo budget now counts every workspace on disk and
# empties only as workspaces end, so one visitor must not fill it in minutes for a week
# (review of the workspace PR): at 6 an hour, 64 MB takes a single address 4 hours.
PHOTO_ALLOWANCE = Allowance(per_minute=6, window=3600)

# Any other request body (a form, a refine line, an edited listing of up to 3000
# characters) is far smaller; a larger one is refused before it is read (19 October audit:
# the form parser read any size into memory before the length checks ran).
MAX_FORM_REQUEST = 64 * 1024


@app.middleware("http")
async def upload_size(request: Request, call_next):
    length = request.headers.get("content-length")
    if request.headers.get("content-type", "").startswith("multipart/"):
        if length is None:
            return Response("A content length is required.", status_code=411)
        if not length.isdigit() or int(length) > MAX_UPLOAD_REQUEST:
            return Response("The upload is too large: photos are up to 3 MB.", status_code=413)
    elif request.method in ("POST", "PUT", "PATCH"):
        if length is None and request.headers.get("transfer-encoding"):
            return Response("A content length is required.", status_code=411)
        if length is not None and (not length.isdigit() or int(length) > MAX_FORM_REQUEST):
            return Response("The request is too large.", status_code=413)
    return await call_next(request)


def cross_site(request: Request) -> bool:
    """A request another site's page sent: by the browser's Sec-Fetch-Site, or, from a
    browser that sends none, by an Origin naming another host. "same-site" counts as
    another site: every form is on this one host."""
    site = request.headers.get("sec-fetch-site")
    if site is not None:
        return site not in ("same-origin", "none")
    origin = request.headers.get("origin")
    if not origin:
        return False
    hosts = {request.headers.get("host"), request.headers.get("x-forwarded-host")}
    return urlsplit(origin).netloc not in hosts


@app.middleware("http")
async def same_site_posts(request: Request, call_next):
    """Almost every POST starts live work or records something, so one sent by another
    site's page (which could spend a judge's run allowance) is refused (19 October
    audit). `POST /flyer` records nothing, but another site has no business printing a
    flyer on this one's pages either."""
    if request.method == "POST" and cross_site(request):
        return Response("Requests from other sites are refused.", status_code=403)
    return await call_next(request)


# The pages load scripts and styles only from here and Leaflet's pinned copy on unpkg,
# map tiles from CARTO and OpenStreetMap, and talk only to this server (19 October audit:
# only HSTS was set). No skin uses an inline script or style attribute.
CONTENT_SECURITY_POLICY = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self' https://unpkg.com",
        "style-src 'self' https://unpkg.com",
        "img-src 'self' data: blob: https://*.basemaps.cartocdn.com "
        "https://tile.openstreetmap.org https://unpkg.com",
        "font-src 'self'",
        "connect-src 'self'",
        "frame-ancestors 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "object-src 'none'",
    ]
)
SECURITY_HEADERS = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "X-Frame-Options": "DENY",
}


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    for name, value in SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    return response


@app.exception_handler(StarletteHTTPException)
async def page_not_found(request: Request, exc: StarletteHTTPException):
    """A missing page, for a browser, as the skin's notice with a way back (19 October
    audit: a judge who mistyped a link saw raw JSON). The API and files keep their JSON."""
    wants_page = "text/html" in request.headers.get("accept", "")
    api_or_file = request.url.path.startswith(("/api/", "/static/", "/ui/", "/photos/"))
    if exc.status_code == 404 and wants_page and not api_or_file:
        ui = request.query_params.get("ui")
        ui = ui if ui in UIS else None  # an unknown skin is itself a 404: use the default
        return notice(
            request,
            pick_ui(ui),
            "Not found",
            str(exc.detail) if exc.detail and exc.detail != "Not Found" else "No such page.",
            404,
            [("Back to the start", "/" + (f"?ui={ui}" if ui else ""))],
        )
    return await http_exception_handler(request, exc)


def cookie_name(request: Request) -> str:
    return SECURE_COOKIE if request.url.scheme == "https" else COOKIE


@app.middleware("http")
async def session_cookie(request: Request, call_next):
    """Find the visitor's session. Only IDs the server made are used: an unknown ID is
    ignored, and a new session always gets a new ID. The cookie holds nothing but its
    random ID; the workspace link (/workspace/{id}) is the one way to adopt an existing
    one (decision 34)."""
    presented = request.cookies.get(cookie_name(request), "")
    known = SESSIONS.get(presented) if re.fullmatch(r"[\w-]{20,40}", presented) else None
    request.state.session_id = known.id if known else None
    request.state.new_session_id = None
    response = await call_next(request)
    # A page or answer built for one visitor's session (their pin, added animals) is
    # never kept by a cache on the way.
    session_bound = known or request.state.new_session_id
    shared_file = request.url.path.startswith(("/static/", "/ui/"))
    if session_bound and not shared_file and "cache-control" not in response.headers:
        response.headers["Cache-Control"] = "private, no-store"
    # Set when a session is made, and renewed on each visit, as long as the workspace.
    cookie_id = request.state.new_session_id or (known.id if known else None)
    if cookie_id and not shared_file:
        response.set_cookie(
            cookie_name(request),
            cookie_id,
            max_age=WORKSPACE_TTL,
            httponly=True,
            samesite="lax",
            secure=request.url.scheme == "https",
        )
    return response


def session_of(request: Request) -> Session | None:
    return SESSIONS.get(request.state.session_id)


def own_session(request: Request) -> Session:
    """The visitor's session, created under a new server-made ID if they have none."""
    session = session_of(request)
    if session is None:
        session = SESSIONS.create()
        request.state.session_id = request.state.new_session_id = session.id
    return session


def visitor(request: Request) -> str:
    # Behind a proxy, uvicorn's --proxy-headers sets this from X-Forwarded-For.
    return request.client.host if request.client else "unknown"


def notice(
    request: Request, ui: str, title: str, message: str, status: int, links=(), **action
) -> HTMLResponse:
    """`action_url` and `action_label` add one button that posts, to confirm a step."""
    view = NoticeView(title=title, message=message, links=list(links), **action)
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


def replay_client(settings) -> QlooClient:
    """The cache and recordings only: never a live call."""
    return QlooClient(
        Cache(settings.cache_db), mode="replay", recordings=settings.qloo_recordings, env={}
    )


def location_profile(location: Location, species: str) -> LocationProfile:
    settings = get_settings()
    saved = Store(settings.cache_db).get_profile(location.id, species)
    if saved is not None:
        return saved
    # No agent run yet: the fixed lookup, in replay only, so a page never spends
    # quota. A missing profile shows as notes.
    return build_profile(
        replay_client(settings), location, load_seeds(settings.seeds_file), species=species
    )


def ui_suffix(request: Request, ui: str | None) -> str:
    return f"&ui={ui}" if ui else ""


def start_view(
    location: str | None,
    session: Session | None = None,
    form: LocationForm | None = None,
    ui_query: str = "",
    select_none: bool = False,
) -> StartView:
    """`select_none` when the typed area is chosen (`form.typed`), so no preset is."""
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
        for a in {animal for animal, _, _ in EXAMPLES}
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
        "" if select_none else selected.id,
        examples=example_links(ready, ui_query),
        added=added,
        pins=session.pins if session else None,
        # Relative: the visitor copies or bookmarks it as the browser shows it.
        workspace_link=f"/workspace/{session.id}" if session else "",
    )
    if form is not None:
        view.location_form = form
    # The search on the map needs place lookups; without them it would be a dead field.
    view.location_form.map_search = places().enabled
    if form is not None and form.typed:
        # The typed area is the choice, shown in the bar as typed; the panel opens on it.
        view.shelter = view.shelter.model_copy(
            update={"name": form.value or view.shelter.name, "chosen": bool(form.value),
                    "open": True}
        )  # fmt: skip
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
    visit = visit_names(session, animal.id, location.id, store)
    taken = taken_names(animal, location, store, visit) | own
    added = animal.id.startswith(ADDED_PREFIX)
    view = build_result_view(
        animal,
        location,
        location_profile(location, animal.species),
        listing,
        generic=generic_name(generic_seed(animal), taken),
        refined=refined,
        litter=litter_view(animal, location, store),
        image_url=added_photo_url(animal, animal.id in session.photos) if added else None,
        pin=session.pins.get(location.id) if session else None,
    )
    litter = next(
        (
            lit
            for lit in load_roster(get_settings().animals_file).litters
            if animal.id in lit.members
        ),
        None,
    )
    query = urlencode({"animal": animal.id, "location": location.id})
    available = {v.variant for v in view.listing.versions if v.available}
    if "generic" in available:
        view.flyer_generic_url = f"/flyer?{query}&variant=generic"
    if "local" in available:
        view.flyer_local_url = f"/flyer?{query}&variant=local"
        for option in view.name.options:
            option.flyer_url = f"{view.flyer_local_url}&{urlencode({'name': option.name})}"
    if view.write_label and litter is not None:
        # A litter is named as a set: the button runs the litter, whose members already
        # named keep their names (decision 13).
        view.write_label, view.write_animal = "Name the litter with Namesake's AI", litter.id
    return view


def find_run(run_id: str, request: Request):
    """A run, if this visitor may see it: a run over an added animal or a refined
    listing belongs to the session that started it."""
    run = RUNS.get(run_id)
    if run is None or (run.session_id and run.session_id != request.state.session_id):
        raise HTTPException(404, "No such run: a run is kept for an hour after it finishes.")
    return run


def working_view(run, ui_query: str = "") -> WorkingView:
    session = SESSIONS.get(run.session_id) if run.session_id else None
    animal = find_animal(run.animal_id, session)
    image_url = None
    if animal.id.startswith(ADDED_PREFIX):
        image_url = added_photo_url(animal, animal.id in session.photos)
    place = run.place or find_location(run.location_id)
    view = build_working_view(run, animal, place, ui_query, image_url)
    if run.area_failed:
        view.area = area_check_view(run.area, ui_query)
    return view


@app.get("/robots.txt", response_class=Response)
def robots() -> Response:
    """Crawlers may read the pages, not start runs, walk the API or index a workspace."""
    return Response(
        "User-agent: *\nDisallow: /api/\nDisallow: /runs\nDisallow: /workspace/\n",
        media_type="text/plain",
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def start(
    request: Request,
    location: str | None = None,
    area: str | None = Query(None, max_length=200),
    ui: str | None = None,
) -> HTMLResponse:
    """With `area`, back from a typed area Qloo could not check: the area stays typed and
    chosen in the open panel, to change it."""
    chosen = pick_ui(ui)
    typed = " ".join((area or "").split())
    form = LocationForm(value=typed, typed=True) if typed else None
    view = start_view(
        location,
        session_of(request),
        form,
        ui_query=ui_suffix(request, ui),
        select_none=form is not None,
    )
    return render(request, chosen, "start.html", view)


@app.get("/result", response_class=HTMLResponse)
def result(
    request: Request, animal: str, location: str | None = None, ui: str | None = None
) -> HTMLResponse:
    view = result_view(animal, location, session_of(request))
    return render(request, pick_ui(ui), "result.html", view)


@app.get("/flyer", response_class=HTMLResponse)
def flyer(
    request: Request,
    animal: str,
    location: str | None = None,
    variant: str | None = None,
    name: str | None = Query(None, max_length=40),
    ui: str | None = None,
) -> HTMLResponse:
    """A printable page from the result: the flyer, then the volunteer's checklist of
    places to ask (decision 35), for the version and name chosen on the result page."""
    view = result_view(animal, location, session_of(request))
    chosen = pick_ui(ui)
    flyer_view = build_flyer_view(view, variant, f"&ui={chosen}" if ui else "", name)
    if flyer_view is None:
        raise HTTPException(404, "This animal has no listing to print here.")
    return render(request, chosen, "flyer.html", flyer_view)


@app.post("/flyer", response_class=HTMLResponse)
def flyer_approved(
    request: Request,
    animal: str = Form(...),
    location: str = Form(...),
    variant: str = Form(...),
    text: str = Form(...),
    name: str | None = Form(None, max_length=40),
    ui: str | None = Form(None),
) -> HTMLResponse:
    """The flyer with the text just approved, sent from the approval page. The text and
    the name are held to the approval's own checks (the recorded cautions, the name and
    what it refers to still free here) and kept nowhere."""
    session = session_of(request)
    view = result_view(animal, location, session)
    chosen = pick_ui(ui)
    if not any(v.variant == variant and v.available for v in view.listing.versions):
        raise HTTPException(400, "that version is not available for this animal")
    edited = listing_text(text)
    store = Store(get_settings().cache_db)
    checked_choice(view, animal, location, variant, session, store, name, name)
    if missing_cautions(find_animal(animal, session), edited):
        raise HTTPException(400, "the text drops what the shelter recorded as a caution")
    flyer_view = build_flyer_view(
        view, variant, f"&ui={chosen}" if ui else "", name, approved=edited
    )
    if flyer_view is None:
        raise HTTPException(400, "that version or name is not this animal's")
    return render(request, chosen, "flyer.html", flyer_view)


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
    area: str = Form("", max_length=200),
    pin_lat: str = Form(""),
    pin_lon: str = Form(""),
    ui: str | None = Form(None),
) -> Response:
    """An animal (or a litter) at a preset or saved area, or at the area typed in the
    panel (`location` is TYPED_AREA): one Qloo has not checked before is checked as the
    run's first step (decision 32). Qloo only ever gets the typed name, never the spot."""
    settings = get_settings()
    litter = next(
        (lit for lit in load_roster(settings.animals_file).litters if lit.id == animal), None
    )
    note = None
    if location == TYPED_AREA:
        typed = " ".join(area.split())
        cleaned = clean(typed)
        pin = pin_from(pin_lat, pin_lon)
        if cleaned is None:
            form = LocationForm(message=INVALID, value=typed, typed=True)
            if pin:
                form.pin_lat, form.pin_lon = str(pin[0]), str(pin[1])
            view = start_view(
                None, session_of(request), form, ui_suffix(request, ui), select_none=True
            )
            response = render(request, pick_ui(ui), "start.html", view)
            response.status_code = 400
            return response
        known = Store(settings.cache_db).get_location(location_id(cleaned))
        if known is None:
            # The spot, or an added animal, needs the visit's session.
            needs_session = pin is not None or animal.startswith(ADDED_PREFIX)
            session = own_session(request) if needs_session else session_of(request)
            chosen = None if litter is not None else find_animal(animal, session)
            try:
                run = await start_area_run(
                    cleaned,
                    animal,
                    settings,
                    animal=chosen,
                    litter=litter,
                    pin=pin,
                    keep_pin=lambda loc: keep_pin(session, loc, pin),
                    visitor=visitor(request),
                    session=session,
                )
            except LimitReached as exc:
                return limit_notice(request, ui, exc)
            return run_redirect(run, ui)
        if pin and not keep_pin(own_session(request), known, pin):
            note = FAR_PIN
        place = known
    else:
        place = find_location(location)
    try:
        if litter is not None:
            run = await start_litter_run(
                litter, place, settings, visitor=visitor(request), note=note
            )
        else:
            session = session_of(request)
            chosen = find_animal(animal, session)
            run = await start_run(
                chosen, place, settings, visitor=visitor(request), session=session, note=note
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
        SESSIONS.save(session)
    return RedirectResponse(
        f"/result?animal={animal}&location={location}{ui_suffix(request, ui)}", status_code=303
    )


TEXT_MAX = 3000


def checked_choice(
    view: ResultView,
    animal: str,
    location: str,
    variant: str,
    session: Session | None,
    store: Store,
    local_name: str | None,
    generic_name: str | None,
) -> tuple[str, str | None, str, NameOptionView | None]:
    """The name the volunteer chose, checked as of now: one of the local options, or the
    generic name they saw, and neither taken by another animal here since, nor (for a
    local name) what it refers to. Returns the name, its hook, where it came from and the
    option; refuses as `/approve` does. `/flyer` holds a print to the same checks."""
    hook = None
    option = None
    if variant == "local":
        option = next((o for o in view.name.options if o.name == local_name), None)
        if option is None:
            raise HTTPException(400, "pick one of the name options")
        name, hook = option.name, option.hook
        source = option.approved_source
    else:
        version = next(v for v in view.listing.versions if v.variant == variant)
        name, source = version.name, "a fixed list of common pet names, not Qloo"
        # The generic name is worked out afresh; approve only the one the volunteer saw.
        if not generic_name:
            raise HTTPException(400, "the generic name shown on the page is missing")
        if generic_name != name:
            raise HTTPException(409, f"{generic_name} is now used by another animal here")
    # Checked again now: another animal here may have been given the name since.
    taken = taken_names(
        find_animal(animal, session),
        find_location(location),
        store,
        visit_names(session, animal, view.location.id, store),
    )
    if name.lower() in taken:
        raise HTTPException(409, f"{name} is now used by another animal here")
    if option is not None and not animal.startswith(ADDED_PREFIX):
        # Nor what the name refers to (decision 26): another animal may have been named
        # after the same character since this listing was written.
        mine = reference_key(option.entity_id, option.character)
        refs = taken_references(find_animal(animal, session), find_location(location), store)
        shared = next((label for key, label in refs.items() if same_reference(key, mine)), None)
        if shared:
            raise HTTPException(
                409, f"{name} refers to {shared}, which another animal here is now named after"
            )
    return name, hook, source, option


def listing_text(text: str) -> str:
    """A listing as the volunteer sent it, with its paragraphs and spacing tidied."""
    # A browser sends a textarea's line breaks as CRLF (Flash, 22 October).
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    edited = "\n\n".join(" ".join(p.split()) for p in text.strip().split("\n\n") if p.strip())
    if not edited or len(edited) > TEXT_MAX:
        raise HTTPException(400, f"the listing text is 1 to {TEXT_MAX} characters")
    return edited


@app.post("/approve", response_class=HTMLResponse)
def approve(
    request: Request,
    animal: str = Form(...),
    location: str = Form(...),
    variant: str = Form(...),
    text: str = Form(...),
    local_name: str | None = Form(None),
    generic_name: str | None = Form(None),
    ui: str | None = Form(None),
) -> HTMLResponse:
    """Record the approval (never the text) and show the copy-ready listing."""
    chosen_ui = pick_ui(ui)
    session = session_of(request)
    store = Store(get_settings().cache_db)
    view = result_view(animal, location, session)
    version = next((v for v in view.listing.versions if v.variant == variant and v.available), None)
    if version is None:
        raise HTTPException(400, "that version is not available for this animal")
    edited = listing_text(text)

    name, hook, source, option = checked_choice(
        view, animal, location, variant, session, store, local_name, generic_name
    )

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
            if v.variant == "local" and variant == "local":
                v.name, v.hook, v.name_source = name, hook, option.header_source
                v.copy_text, v.choice = option.copy_text, option.version_choice
        view.chosen_name = name if variant == "local" else view.name.value
        # The flyer follows the restored choice, as the page does.
        picked = next((o for o in view.name.options if o.name == view.chosen_name), None)
        if picked is not None and picked.flyer_url:
            view.flyer_local_url = picked.flyer_url
        return render(request, chosen_ui, "result.html", view)

    approval = Approval(
        id=uuid.uuid4().hex[:10],
        animal_id=animal,
        location_id=view.location.id,
        variant=variant,
        name=name,
        name_source=source,
        edited=" ".join(edited.split()) != " ".join(view.listing.text.split()),
        approved_at=datetime.now(UTC).isoformat(),
    )
    store.record_approval(approval)
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
    approved.flyer_fields = {
        "animal": animal,
        "location": location,
        "variant": variant,
        "name": name,
        "text": edited,
        **({"ui": ui} if ui else {}),
    }
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
def new_animal(
    request: Request,
    location: str | None = None,
    area: str = Query("", max_length=200),
    edit: str | None = Query(None, max_length=40),
    ui: str | None = None,
):
    """The form for one animal, opened from the start page with its chosen area, which
    may be the typed one (its name in `area`). With `edit`, one of the visitor's own
    animals, filled in with its record."""
    location_id, typed = chosen_area(location, area)
    values = None
    if edit:
        session = session_of(request)
        animal = session.animals.get(edit) if session else None
        if animal is None:
            raise HTTPException(404, "That animal is not in your workspace.")
        values = animal_values(animal)
    view = build_add_animal_view(location_id, MAX_FACTS, values=values, area=typed, edit=edit or "")
    return render(request, pick_ui(ui), "add_animal.html", view)


def animal_values(animal: Animal) -> dict[str, str]:
    """An added animal's record as the form's fields, to edit it."""
    return {
        "species": animal.species, "sex": animal.sex or "", "age": animal.age,
        "look": animal.look, "temperament": animal.temperament,
        "facts": "\n".join(animal.facts), **animal.checks.model_dump(),
    }  # fmt: skip


@app.post("/animals/remove")
def remove_animal(
    request: Request,
    remove: str = Form(..., max_length=40),
    location: str | None = Form(None),
    area: str = Form("", max_length=200),
    ui: str | None = Form(None),
    confirm: str = Form("", max_length=3),
):
    """One of the visitor's own animals, gone from their workspace with its photo and
    listings, once they confirm: nothing brings it back. Sent from the start page's
    form, so its chosen area comes back."""
    session = session_of(request)
    if session is not None and remove in session.animals and confirm != "yes":
        animal = session.animals[remove]
        fields = {"remove": remove, "area": area, "confirm": "yes"}
        fields.update({"location": location} if location else {})
        fields.update({"ui": ui} if ui else {})
        return notice(
            request,
            pick_ui(ui),
            "Remove this animal?",
            f"The {animal.look} {animal.species}, its photo and every listing made for it "
            "leave your workspace for good.",
            200,
            [("Keep it", "/" + (f"?ui={pick_ui(ui)}" if ui else ""))],
            action_url="/animals/remove",
            action_label="Remove it",
            action_fields=fields,
        )
    if session is not None and remove in session.animals:
        SESSIONS.remove_animal(session, remove)
    location_id, typed = chosen_area(location, area)
    back = urlencode({"area": typed} if location_id == TYPED_AREA else {"location": location_id})
    return RedirectResponse(f"/?{back}{ui_suffix(request, ui)}", status_code=303)


def kept_workspace(workspace_id: str, renew: bool = True) -> Session:
    """A workspace the server made and still keeps; anything else is a 404."""
    valid = re.fullmatch(r"[\w-]{20,40}", workspace_id)
    known = SESSIONS.get(workspace_id, renew=renew) if valid else None
    if known is None:
        raise HTTPException(404, "This workspace has ended, or the link is not complete.")
    return known


@app.get("/workspace/{workspace_id}", response_class=HTMLResponse)
def workspace_link(request: Request, workspace_id: str, ui: str | None = None):
    """The workspace link asks before it opens anything, so a link alone never moves a
    visitor into a workspace and a page elsewhere cannot fix one on them (review of the
    workspace PR). Opening it is the POST below, behind the same-site check."""
    # Only looked at: the workspace is renewed when it is opened, not when it is asked about.
    known = kept_workspace(workspace_id, renew=False)
    current = session_of(request)
    if current is not None and current.id == known.id:
        return RedirectResponse("/" + (f"?ui={pick_ui(ui)}" if ui else ""), status_code=303)
    count = len(known.animals)
    holds = f"It holds {count} animal{'' if count == 1 else 's'}." if count else "It is empty."
    leaving = (
        " The workspace this browser has now stays open from its own link."
        if current is not None and current.animals
        else ""
    )
    chosen = pick_ui(ui)
    return notice(
        request,
        chosen,
        "Open this workspace?",
        f"{holds} Anyone with its link can open and change it, so open it only if it is "
        f"yours.{leaving}",
        200,
        [("Back to the start", "/" + (f"?ui={chosen}" if ui else ""))],
        action_url=f"/workspace/{known.id}",
        action_label="Open it in this browser",
        action_fields={"ui": chosen} if ui else {},
    )


@app.post("/workspace/{workspace_id}")
def open_workspace(
    request: Request, workspace_id: str, ui: str | None = Form(None)
) -> RedirectResponse:
    """Open the workspace in this browser, as the visitor confirmed."""
    known = kept_workspace(workspace_id)
    request.state.session_id = request.state.new_session_id = known.id
    return RedirectResponse("/" + (f"?ui={pick_ui(ui)}" if ui else ""), status_code=303)


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
    area: str = Form("", max_length=200),
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
    edit: str | None = Form(None, max_length=40),
    ui: str | None = Form(None),
):
    """Add one animal to the visitor's workspace, or with `edit` change one already
    there: its record is replaced, the listings made from the old one are dropped, and
    its photo is kept unless a new one is sent."""
    chosen_ui = pick_ui(ui)
    location_id, typed = chosen_area(location, area)
    session = own_session(request)
    if edit and edit not in session.animals:
        raise HTTPException(404, "That animal is not in your workspace.")
    entered = {
        "species": species, "sex": sex, "age": age, "look": look,
        "temperament": temperament, "facts": facts,
        "good_with_children": good_with_children, "good_with_dogs": good_with_dogs,
        "good_with_cats": good_with_cats, "house_trained": house_trained,
        "bite_history": bite_history,
    }  # fmt: skip

    def refuse(message: str, status: int = 400) -> HTMLResponse:
        # What was entered comes back, so only the fix is needed; a photo cannot be kept
        # in the form, so the message says to add it again.
        if photo is not None and photo.filename and "without one" not in message:
            message += " Add the photo again."
        view = build_add_animal_view(
            location_id, MAX_FACTS, error=message, values=entered, area=typed, edit=edit or ""
        )
        response = render(request, chosen_ui, "add_animal.html", view)
        response.status_code = status
        return response

    if not edit and len(session.animals) >= MAX_ANIMALS:
        return refuse(f"A workspace holds up to {MAX_ANIMALS} animals.")
    try:
        if species not in ("dog", "cat") or sex not in ("female", "male"):
            raise ValueError("pick a species and a sex")
        fact_lines = [_short(f, "Each fact") for f in facts.splitlines() if f.strip()]
        if len(fact_lines) > MAX_FACTS:
            raise ValueError(f"up to {MAX_FACTS} facts, one per line")
        age_text = _short(age, "The age")
        animal = Animal(
            id=edit or ADDED_PREFIX + uuid.uuid4().hex[:8],
            species=species,
            group=stage_for(species, age_text) or f"adult {species}",
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
        photo_kept = Photo(content_type=content_type, data=data)
    else:
        photo_kept = None
    # Only an animal actually added counts against the allowance, so refused attempts
    # never lock a visitor out of the corrected one (review of PR #46); an edit adds none.
    who = visitor(request)
    if not edit and not ADD_ALLOWANCE.take(who):
        return refuse(
            "Too many animals added from here in the last minute; try again shortly.", 429
        )
    if photo_kept is not None:
        if not PHOTO_ALLOWANCE.take(who):
            if not edit:
                ADD_ALLOWANCE.refund(who)
            return refuse(
                "Too many photos added from here in the last hour; save the animal without "
                "one, or try again later.",
                429,
            )
        previous = session.animals.get(animal.id)
        # The record first, so the workspace written with the photo names its animal.
        session.animals[animal.id] = animal
        if not SESSIONS.add_photo(session, animal.id, photo_kept, PHOTO_BUDGET):
            if previous is None:
                session.animals.pop(animal.id, None)
            else:
                session.animals[animal.id] = previous
            SESSIONS.save(session)
            PHOTO_ALLOWANCE.refund(who)
            if not edit:
                ADD_ALLOWANCE.refund(who)
            return refuse(
                "Namesake is holding too many photos right now; save the animal without "
                "one, or try again later."
            )
    if edit:
        # A new record: what was written from the old one no longer holds.
        drop_listings(session, edit)
    session.animals[animal.id] = animal
    SESSIONS.save(session)
    back = urlencode({"area": typed} if location_id == TYPED_AREA else {"location": location_id})
    return RedirectResponse(f"/?{back}{ui_suffix(request, ui)}#{animal.id}", status_code=303)


def chosen_area(location: str | None, area: str) -> tuple[str, str]:
    """The area chosen on the start page: a preset's or saved area's ID, or the typed
    area with its name (checked only when a run starts)."""
    if location == TYPED_AREA:
        return TYPED_AREA, " ".join(area.split())
    return find_location(location).id, ""


def place_lookup() -> Places:
    lookup = places()
    if not lookup.enabled:
        raise HTTPException(404, "place lookups are off here; type the area instead")
    return lookup


TOO_MANY_LOOKUPS = "too many place lookups; wait a minute, or type the area"
LOOKUP_FAILED = (
    "The map's place lookup did not answer just now. Pick the spot again, or type the area."
)


@app.get("/api/places")
def api_places(
    request: Request,
    q: str = Query("", max_length=200),
    lat: float | None = Query(None, ge=-90, le=90),
    lon: float | None = Query(None, ge=-180, le=180),
) -> PlacesView:
    """Area names matching what the visitor is typing in the location field, ranked near
    the area on the map when lat and lon are given."""
    near = (lat, lon) if lat is not None and lon is not None else None
    try:
        found = place_lookup().search(q, near, visitor=visitor(request))
    except Throttled:
        raise HTTPException(429, TOO_MANY_LOOKUPS) from None
    return PlacesView(places=[PlaceOption(**p.model_dump()) for p in found])


@app.get("/api/places/at")
def api_place_at(
    request: Request,
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
) -> PlacesView:
    """The areas a spot the visitor picked for the shelter lies in, most local first."""
    try:
        found = place_lookup().at(lat, lon, visitor=visitor(request))
    except Throttled:
        raise HTTPException(429, TOO_MANY_LOOKUPS) from None
    except LookupFailed:
        raise HTTPException(503, LOOKUP_FAILED) from None
    if not found:
        return PlacesView(
            message="No neighbourhood or city was found at that spot. Pick a spot in a town, "
            "or type the area."
        )
    return PlacesView(places=[PlaceOption(**p.model_dump()) for p in found])


def pin_from(latitude: str, longitude: str) -> tuple[float, float] | None:
    """The spot picked on the map, from the form, to about 10 m: plenty for a pin on an area
    map. None when absent or not a place on Earth."""
    try:
        lat, lon = float(latitude), float(longitude)
    except ValueError:
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return round(lat, PIN_DECIMALS), round(lon, PIN_DECIMALS)


def keep_pin(session: Session, location: Location, pin: tuple[float, float] | None) -> bool:
    """Remember the picked spot for this visit, if it lies in the area Qloo checked; False
    when a spot was given but is too far to show."""
    if not pin:
        return True
    if distance_km(pin, (location.latitude, location.longitude)) > MAX_PIN_KM:
        # The visitor picked again: an earlier pin for this area no longer stands.
        session.pins.pop(location.id, None)
        return False
    session.pins[location.id] = pin
    return True


@app.get("/runs/{run_id}", response_class=HTMLResponse)
def working(request: Request, run_id: str, ui: str | None = None) -> HTMLResponse:
    chosen = pick_ui(ui)
    view = working_view(find_run(run_id, request), f"&ui={chosen}" if ui else "")
    return render(request, chosen, "working.html", view)


@app.get("/api/runs/{run_id}")
def api_run(request: Request, run_id: str) -> WorkingView:
    return working_view(find_run(run_id, request))


@app.get("/api/runs/{run_id}/events")
async def run_events(request: Request, run_id: str) -> StreamingResponse:
    """The step log as server-sent events: one `step` per step (its kind, text and actor),
    then `done`."""
    run = find_run(run_id, request)

    async def stream():
        async for step in run.log.follow():
            payload = json.dumps({"kind": step.kind, "text": step.text, "actor": step.actor})
            yield f"event: step\ndata: {payload}\n\n"
        payload = {
            "result_url": run.result_url,
            "failed": run.failed,
            "error": run.error,
            # A typed area Qloo could not check: the page reloads to offer what it said.
            "area": run.area_failed,
        }
        yield f"event: done\ndata: {json.dumps(payload)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")
