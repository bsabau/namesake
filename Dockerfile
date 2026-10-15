# One image: Python for the app, Node for the Qloo harness.

FROM node:22-bookworm-slim AS node

FROM python:3.12-slim-bookworm

# Node and npm, copied from the official image.
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
 && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
 && node -e 'const [a,b]=process.versions.node.split(".").map(Number); if (a<22||(a===22&&b<19)) { console.error("need Node 22.19+"); process.exit(1) }'

# The Qloo harness, pinned.
RUN npm install -g @qloo/qloo-harness@0.1.26 \
 && npm cache clean --force \
 && qloo --version

COPY --from=ghcr.io/astral-sh/uv:0.11.17 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Dependencies first so code changes don't reinstall them.
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev

COPY app ./app
COPY data ./data

RUN useradd --create-home namesake && chown -R namesake /app
USER namesake

ENV PATH="/app/.venv/bin:$PATH" \
    PORT=8000
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s \
  CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/health')"

# --proxy-headers trusts X-Forwarded-For only from FORWARDED_ALLOW_IPS (default 127.0.0.1),
# so per-visitor limits see the real client behind the host's proxy.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers"]
