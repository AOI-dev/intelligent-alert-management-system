# TrueConf bot

A first spike at a chat bot on TrueConf Server, using
[`python-trueconf-bot`](https://github.com/TrueConf/python-trueconf-bot) —
an aiogram-style wrapper around TrueConf Server's Chatbot API (requires
server 5.5+, TrueConf Enterprise, or TrueConf Server Free).

This **is** the "mandatory TrueConf channel" delivery adapter
`artifacts/happy-path.md` describes (steps 9-10), plus the original
echo/`/ping` bot. One process serves both.

## Incident delivery

`POST /v1/notify` is the channel endpoint the `notifications` dispatcher
calls as a plain webhook:

```json
{ "trueconf_id": "alice@trueconf.local", "text": "**[P1] ...**" }
```

Extra keys (rule, severity, metric, labels, …) are accepted and ignored —
`platform` sends alert context in the same payload for other webhook
consumers, and this adapter must not 422 on fields not addressed to it.

Why a webhook and not a second Kafka consumer: `notifications/` already
consumes `monitoring.notification-requests.v1`, dedups, and publishes
delivery outcomes. A consumer here would duplicate that and produce a
second, divergent record of what was delivered. Non-2xx is returned on
failure so the dispatcher records `notification.failed` rather than losing
the delivery silently.

The full chain: `platform` correlates → a `route` decision → `app/routing/`
resolves the on-call from `routing.json` and writes the message (Qwen, with
a heuristic fallback) → `NotificationRequest` on Kafka → `notifications`
POSTs it here → TrueConf direct message.

**Without `TRUECONF_BOT_TOKEN` the HTTP server still starts**, `/health`
reports the bot as unavailable and `/v1/notify` returns 503. Registering a
chat bot needs a human in the TrueConf Server control panel, so the rest of
the chain stays deployable and testable before that token exists.

Verified in this session against the built container: `/health` reports the
unconfigured state, a real `platform`-produced payload is accepted (503, not
422), and with the bot stubbed the endpoint returns 202 and calls
`create_personal_chat`/`send_message` with the right user and text. Delivery
against a *live* TrueConf Server is still unverified — that needs the token.

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
