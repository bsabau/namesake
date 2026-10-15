"""The PydanticAI agents, their checks and the run pipeline."""

import os

# PydanticAI prints an observability banner on first run; keep logs clean.
os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")
