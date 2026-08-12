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

The UI is in Russian and split into two nav groups: **УПРАВЛЕНИЕ**
(Сводка, Пользователи, Матрица ответственности, Системы, Маршрутизация,
Роли и права доступа, Политики SLA, Интеграции, Аудит) and **МОНИТОРИНГ**
(Инциденты, Алерты, События, Решения корреляции).

Only some of that is live. Сводка, Системы, Алерты, События, Решения
корреляции and Пользователи read the platform; the rest are Figma-macket
screens rendered from constants in `app.js` and marked as such at the top
of the page by `designBanner()` — they are honest placeholders, not
mock data pretending to be real. Every button on those screens carries
`data-protected` and answers with a toast rather than silently doing
nothing.

## API it talks to

- `GET /health`, `GET /v1/contours` — the only two calls that work logged
  out. They drive the sidebar connection dot, the platform-health card and
  the Системы page.
- `GET /v1/summary`, `GET /v1/alerts`, `GET /v1/events`, `GET /v1/decisions`
  — the live read-only views. A 401 on any of them drops Сводка into its
  macket state with the banner explaining why, rather than showing an
  error.
- `GET /v1/incidents` (+ `/{id}/ack`) — **always 501 today** on purpose;
  see `INCIDENTS_NOT_IMPLEMENTED` in `platform/app/main.py`. `renderOverview`
  therefore requests it outside its `Promise.all` and tolerates 501
  alongside 401/403, so the landing page degrades to an empty "Требуют
  внимания" card instead of an error screen. The Инциденты tab itself does
  surface the 501 — that page has nothing else to show.
- `GET /v1/auth/me`, `GET /v1/auth/login`, `POST /v1/auth/logout` — the
  account block in the top bar. With OAuth unconfigured (`health.auth !==
  'configured'`) the link says so instead of offering a login that cannot
  complete.
- `GET /v1/identities`, `POST /v1/identities/{id}/roles` — the Пользователи
  page. Role grants are real platform-only data (`identity_roles`); the AD
  columns are a local reference copy only — this never creates or touches a
  real Active Directory account, see `platform/README.md`'s note on the same
  endpoint and АР-07.

## Start (local or VM)

Requires the `platform` stack already running (this stack joins its
`platform_platform` network to reach `monitoring-platform:8100` by name).

```sh
cd frontend
set -a; . flags.env; set +a
docker compose up -d --build
```

Open `http://<host>:8091`.

On the VM, use **`https://161.104.107.172:8543`** instead — the same
frontend, served over TLS by `trueconf-tls/`'s nginx. TrueConf login only
completes from there: the OAuth2 state cookie is `SameSite=Lax`, and
browsers treat `http://…:8091` and the `https://…:8443` callback as
cross-site (same host, different scheme), so the cookie never comes back.
See `trueconf-tls/README.md`, "The callback has to live on the TrueConf
origin". Everything else works on either.

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

- `public/` — the static site, self-contained: no bundler, no external JS
  or fonts fetched at runtime.
  - `index.html` — the shell only. It renders nothing itself; it supplies
    the twelve elements `app.js` resolves by id (`sidebar`, `nav-eyebrow`,
    `main-nav`, `connection-dot`, `connection-label`, `theme-button`,
    `menu-button`, `global-search`, `account-meta`, `auth-link`, `content`,
    `toast-region`) plus the `theme-color` meta tag that `applyTheme()`
    writes to. Removing any of them breaks `bootstrap()` outright, so the
    two files have to change together.
  - `app.js` — every view, rendered client-side into `#content`.
  - `app.css` — light/dark tokens on `:root` / `:root[data-theme="dark"]`;
    the theme choice persists in `localStorage` under `spokukha-theme` and
    is applied by an inline script in `index.html` before first paint to
    avoid a light flash.
  - `assets/` — the logo, used by the brand mark, the favicon and the
    logged-out screen.
- `nginx.conf.template` — nginx substitutes `${PLATFORM_UPSTREAM}` into
  this at container start (built into `nginx:alpine`'s entrypoint; see the
  comment in `Dockerfile`).

**Keep all four under `public/` in git.** `scripts/deploy.sh` rsyncs
without `--delete`, so anything that exists only on the VM survives
deploys invisibly until a same-named file in the repo overwrites it — which
is exactly how the original `index.html` was lost once already.
