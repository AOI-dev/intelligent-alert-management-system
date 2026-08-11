FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# python-trueconf-bot depends on python-magic (file-type sniffing for
# send_document/send_photo), which needs the libmagic1 shared library --
# not present in the slim base and not something pip/uv installs for you.
RUN apt-get update && apt-get install -y --no-install-recommends libmagic1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY app ./app

CMD ["uv", "run", "--frozen", "--no-dev", "python", "-m", "app.main"]
