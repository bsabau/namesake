"""FastAPI app and routes."""

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.animals import load_roster
from app.config import get_settings
from app.locations import load_locations

HERE = Path(__file__).resolve().parent

app = FastAPI(title="Namesake")
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
templates = Jinja2Templates(directory=HERE / "templates")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def start(request: Request, location: str | None = None) -> HTMLResponse:
    settings = get_settings()
    locations = load_locations(settings.locations_file)
    # An unknown or missing ?location= falls back to the first preset.
    selected = next((loc for loc in locations if loc.id == location), locations[0])
    context = {
        "roster": load_roster(settings.animals_file),
        "locations": locations,
        "selected": selected,
        "map_points": {loc.id: loc.model_dump() for loc in locations},
    }
    return templates.TemplateResponse(request, "start.html", context)
