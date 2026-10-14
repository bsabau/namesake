"""Make web-sized copies of the animal photos for the app to serve.

    uv run python scripts/make_web_photos.py

Reads data/animals/*.jpg and writes app/static/animals/<id>.jpg, at most
800 pixels on the long side and under 150 KB. Safe to re-run.
"""

import io
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "data" / "animals"
TARGET = ROOT / "app" / "static" / "animals"
MAX_SIDE = 800
MAX_BYTES = 150 * 1024


def shrink(path: Path) -> bytes:
    with Image.open(path) as img:
        img = img.convert("RGB")
        img.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
        # Step the quality down until the file fits.
        for quality in range(85, 40, -5):
            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=quality, optimize=True, progressive=True)
            if buf.tell() <= MAX_BYTES:
                return buf.getvalue()
    raise ValueError(f"{path.name} does not fit in {MAX_BYTES} bytes")


def main() -> None:
    TARGET.mkdir(parents=True, exist_ok=True)
    for path in sorted(SOURCE.glob("*.jpg")):
        data = shrink(path)
        (TARGET / path.name).write_bytes(data)
        print(f"{path.name}: {path.stat().st_size // 1024} KB -> {len(data) // 1024} KB")


if __name__ == "__main__":
    main()
