# TrueConf bot

A first spike at a chat bot on TrueConf Server, using
[`python-trueconf-bot`](https://github.com/TrueConf/python-trueconf-bot) —
an aiogram-style wrapper around TrueConf Server's Chatbot API (requires
server 5.5+, TrueConf Enterprise, or TrueConf Server Free).

This is **not yet** the "mandatory TrueConf channel" delivery adapter
`artifacts/happy-path.md` describes (step 9-10) — it's a working
echo/`/ping` bot, plus a `notify()` helper for proactively messaging a
user, ready for that adapter to call once it exists.

Dependencies are managed with `uv` (`pyproject.toml` + `uv.lock`), and the
package installs and imports cleanly — verified in this session: `uv sync`
pulled `python-trueconf-bot==1.4.2` for real, `Bot`/`Dispatcher`/`Router`
construct against the actual installed library (not just the README
quickstart), and `Bot.send_message`/`Bot.create_personal_chat` — the
proactive-send API `notify()` uses — were confirmed by inspecting the
installed library's real signatures, not guessed. The Docker image builds
and a container gets as far as a real network handshake attempt against
the configured server before failing (expected, since that test used a
fake host) — so everything up to "the TrueConf server actually responds"
is verified.

One thing this *didn't* verify: an actual conversation with a real,
reachable TrueConf Server (needs a live server + a real bot token from its
control panel, neither available in this sandbox). Test that before
trusting message delivery itself.

## Setup

1. In the TrueConf Server control panel: find the Chat bots section (not
   the same as API -> OAuth2, which `platform/app/identity/` uses for
   end-user login) and register a new bot to get its token.
2. `cp .env.example .env`, fill in `TRUECONF_BOT_TOKEN`.
3. Confirm `TRUECONF_SERVER` in `flags.env` matches the deployed server's
   address (same convention as `platform/flags.env`'s `TRUECONF_BASE_URL`
   — TrueConf Server isn't on any Docker network here, see
   `trueconf/README.md`).

## Run (local, dev)

```sh
uv sync
export TRUECONF_SERVER=... TRUECONF_BOT_TOKEN=...
uv run python -m app.main
```

## Run (container)

```sh
set -a; . flags.env; . .env; set +a
docker compose up -d --build
docker compose logs -f bot
```

Message the bot from any TrueConf client: `/ping` replies `pong`, anything
else gets echoed back.

## Deploy

```sh
scripts/deploy.sh trueconf-bot trueconf-bot
```

No health-check URL — this stack has no HTTP server (the bot library owns
its own connection loop), so `deploy.sh`'s health probe is skipped; check
`docker compose logs` instead.

## Next steps

- Test against a real, reachable TrueConf Server with a real bot token —
  the one thing this session couldn't do (see caveat above).
- Wire a Kafka consumer for `monitoring.notification-requests.v1` and a
  producer for `monitoring.notification-results.v1`, mirroring
  `notifications/app/main.py`, calling `notify()` for delivery — that
  turns this from a spike into the actual mandatory-channel adapter.
- Resolve `target_id -> TrueConf user id` once routing exists (see
  `notifications/README.md`'s note on the same open question) — `notify()`
  takes a TrueConf `user_id`, not an arbitrary `target_id`.
