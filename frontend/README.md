# frontend

A static dashboard (plain HTML/JS, no build step) for the events/alerts/
decisions the `platform` monolith projects, served by nginx and reverse-
proxying `/v1/*`, `/health`, `/metrics` straight through to it.

Reverse-proxied on purpose, not CORS'd: the browser only ever talks to
this one origin. That means the platform's TrueConf OAuth2 session cookie
(set during `/v1/auth/callback`, scoped to the request host — not the
port, so it's already shared across this container and `platform`'s own
published port on the same host) just works through the proxy with zero
changes to `platform`'s identity code — no `CORSMiddleware`, no
`SameSite`/`credentials` tuning needed there.

This replaces `platform/app/static/index.html` (the monolith's own bundled
landing page) as the primary way to look at the platform, but doesn't
remove it — that page is unaffected and still served directly by
`platform` at its own `/`.

## API it talks to

- `GET /v1/alerts`, `GET /v1/events`, `GET /v1/decisions` — the read-only
  tabs. Require an authenticated session (see below); a 401 shows a
  "log in" prompt instead of an empty table.
- `GET /v1/auth/me`, `GET /v1/auth/login`, `POST /v1/auth/logout` — the
  header's auth link.
- `GET /v1/identities`, `GET /v1/auth/roles`, `POST /v1/identities/{id}/roles`,
  `PUT /v1/identities/{id}/ad-link` — the Admin tab. Requires the `admin`
  role (a 403 shows a distinct "admin role required" message, not the same
  401 as being logged out). Role grants are real platform-only data
  (`identity_roles`); the AD fields on that same tab are explicitly labeled
  as a local reference copy only — this never creates or touches a real
  Active Directory account, see `platform/README.md`'s note on the same
  endpoint and АР-07. Doesn't auto-refresh like the other tabs, on purpose:
  refreshing mid-edit would clobber whatever you were typing.

## Start (local or VM)

Requires the `platform` stack already running (this stack joins its
`platform_platform` network to reach `monitoring-platform:8100` by name).

```sh
cd frontend
set -a; . flags.env; set +a
docker compose up -d --build
```

Open `http://<host>:8091`.

## Deploy

```sh
scripts/deploy.sh frontend frontend http://localhost:8091/health
```

## Configuration

- `flags.env` — `FRONTEND_PORT` (published port) and `PLATFORM_UPSTREAM`
  (platform's container-DNS `host:port`, only needs changing if
  `platform`'s own `container_name` or port changes).
- No secrets: this stack has none of its own, so there's no `.env`/
  `.env.example` here.

## Files

- `public/` — the static site (`index.html`, self-contained: no bundler,
  no external JS dependencies fetched at runtime).
- `nginx.conf.template` — nginx substitutes `${PLATFORM_UPSTREAM}` into
  this at container start (built into `nginx:alpine`'s entrypoint; see the
  comment in `Dockerfile`).
