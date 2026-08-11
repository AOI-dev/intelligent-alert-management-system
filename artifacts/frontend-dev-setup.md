# Frontend dev setup

For picking up work on `frontend/` — the dashboard at `frontend/public/index.html`.
Written to be followed step by step, in order, by you or by an AI coding
assistant (Codex, Claude Code, Cursor, etc.) on your behalf — every step is
a command to run and what you should see happen.

**You do not need to run the full backend.** The real backend (`platform`,
Kafka, the database) is already deployed and running on the project's VM.
You only need to run the one small `frontend` container on your own
machine, pointed at that already-running backend. No Kafka, no database,
no Zabbix, nothing else to install.

## What you need first

- **Docker Desktop** (or Docker Engine + the `docker compose` command) —
  install it, make sure `docker compose version` works in a terminal.
- **Git**.
- **Access to the GitHub repo** — you'll be given either a collaborator
  invite or an SSH key for GitHub. If it's an SSH key, ask how to add it
  to `~/.ssh/` and to your GitHub account before step 1.

You do **not** need SSH access to the VM for any of this — that's only
needed later, if/when you're ready to publish your own changes for real
(see "Publishing your changes" at the end).

## 1. Clone the repo

```sh
git clone git@github.com:AOI-dev/intelligent-alert-management-system.git
cd intelligent-alert-management-system/frontend
```

(If cloning fails with a permission error, your GitHub access isn't set
up yet — stop here and get that sorted first.)

## 2. Point the frontend at the real backend

The frontend needs to know where the backend API is. Point it at the
deployed VM instead of something you'd have to run yourself:

```sh
export PLATFORM_UPSTREAM=161.104.107.172:8100
export FRONTEND_PORT=8091
```

## 3. Start it, in "live edit" mode

```sh
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
```

This does two things differently from a normal deploy: it builds the
image once, and it live-mounts the `public/` folder into the running
container — so editing `public/index.html` and refreshing your browser
shows the change immediately, with **no rebuild step**. (The plain
`docker compose up -d --build` without the `-f docker-compose.dev.yml`
part also works, but you'd need to re-run it after every edit — use the
two-file form above for actual development.)

## 4. Open it

Go to **http://localhost:8091** in a browser. You should see the
"Monitoring platform" dashboard: a header, a summary strip, and four tabs
(Alerts / Events / Decisions / Incidents).

Expected, not a bug:
- The tables show **"Not logged in"** until you actually log in (see
  below) — that's correct, not an error.
- The **Incidents** tab always shows "Not implemented yet (501)" — that's
  intentional too. That feature genuinely doesn't exist on the backend
  yet; the frontend is supposed to say so honestly rather than show a
  fake empty table.

### Logging in from here does work — a quick note on why

TrueConf's OAuth2 login always sends your browser back to one fixed
address (`161.104.107.172:8100`, the deployed backend) — that's a
security requirement of OAuth2 itself, not something this project chose.
The normal consequence would be that your login is only valid there, not
for `localhost:8091`. Clicking "Log in" here works anyway because the
backend hands the finished login back to whatever origin asked for it (via
a one-time code in the URL, picked up by the page automatically) instead
of only ever setting a cookie tied to that one fixed address — but only
for origins it's been told to trust, and `localhost:8091` is one of them.
If you ever see a normal cookie-only login fail from some *other* origin
(a different port, a teammate's machine), that's why: it has to be
explicitly allowlisted server-side (`AUTH_RETURN_TO_ALLOWLIST` in
`platform/flags.env`) — ask for that to be added rather than assuming your
setup is broken.

Ask for a TrueConf test login when you get to this point.

If step 4 doesn't show the page at all: check `docker compose logs web`
for errors, and confirm `curl http://161.104.107.172:8100/health` returns
something (if that fails, the backend itself is down — not something to
fix from your end, flag it back).

## 5. Where the actual code is

Everything is in **one file**: `frontend/public/index.html`. No build
step, no npm, no framework — plain HTML/CSS/JS. Inside it:

- `COLUMNS` (near the top of the `<script>`) — one entry per tab
  (`alerts`, `events`, `decisions`, `incidents`), each with the API
  endpoint it calls, its table headers, and a `row()` function that turns
  one API result into a row of cells. Adding a column to a tab means
  editing its `headers` array and its `row()` function together.
- `refresh()` — fetches the current tab's endpoint and renders the table;
  already handles "not logged in" (401) and "not implemented" (501)
  states.
- `refreshSummary()` — fills in the chip strip at the top from
  `/v1/summary`.
- `updateAuthLink()` — the login/logout link in the header.

The backend API it talks to (for reference, so you know what fields exist
to work with): `platform/README.md`'s "API" section, in the same repo.

## 6. Making a change

1. Edit `public/index.html`.
2. Refresh the browser tab at `http://localhost:8091` — the change is
   already there (see step 3's live-mount).
3. No commit/push needed just to preview — only when you're ready to
   share the change.

## Publishing your changes

This part **does** need VM access, which is why you'll be given a key
separately — ask for it when you're ready for this step, not before.

Once you have it (a private key, typically placed at `~/.ssh/id_ed25519`
or similar, plus a `Host vm` entry in `~/.ssh/config` pointing at the VM —
whoever gives you the key will tell you exactly where it goes):

```sh
git add public/index.html
git commit -m "describe what you changed"
git push origin <your-branch>
```

Then, from the repo root (not `frontend/`), deploying for real:

```sh
scripts/deploy.sh frontend frontend http://localhost:8091/health
```

That's the same script that deployed the backend — it syncs `frontend/`
to the VM, rebuilds the container there, and checks it came up healthy.
Ask before running this the first few times — it changes what's live for
everyone, unlike everything above it in this doc, which only ever
touches your own machine.
