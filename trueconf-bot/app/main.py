"""TrueConf chat bot plus the incident-delivery adapter from
artifacts/happy-path.md steps 9-10.

Two things run in one process:

- the chat bot itself (echo/`/ping`), built on python-trueconf-bot -- an
  aiogram-style wrapper around TrueConf Server's Chatbot API;
- an HTTP endpoint, `POST /v1/notify`, which the notifications dispatcher
  calls as a plain webhook. That is the whole integration: `platform`
  resolves who to notify and writes the message, the dispatcher POSTs it
  here, and this turns it into a TrueConf direct message.

Why a webhook rather than a second Kafka consumer: notifications/ already
consumes monitoring.notification-requests.v1, retries, dedups and publishes
delivery outcomes. A Kafka consumer here would duplicate all of it and
produce a second, divergent record of what was delivered. The dispatcher's
`webhook_url` seam exists precisely so channels stay this thin.

Running without TRUECONF_BOT_TOKEN is a supported, visible state: the HTTP
server still starts, /health reports the bot as unavailable, and /v1/notify
returns 503. Registering a chat bot needs a human in the TrueConf Server
control panel, so the rest of the chain has to be deployable and testable
before that token exists.
"""
import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from trueconf import Bot, Dispatcher, F, Message, ParseMode, Router

logger = logging.getLogger(__name__)

TRUECONF_SERVER = os.environ.get("TRUECONF_SERVER", "")
TRUECONF_BOT_TOKEN = os.environ.get("TRUECONF_BOT_TOKEN", "")
# How to reach the server, which is not the library's default on this pilot.
# python-trueconf-bot defaults to https on 443; the deployed TrueConf Server
# publishes 443 but serves no TLS on it (`curl https://host:443/` fails to
# connect, `http://host:80/` answers 200) -- HTTPS is terminated by the
# separate trueconf-tls proxy on 8443 with a self-signed certificate. Left at
# the library defaults, every send fails at the transport before the token is
# ever checked, which looks exactly like a bad token.
TRUECONF_HTTPS = os.environ.get("TRUECONF_HTTPS", "false").lower() == "true"
TRUECONF_WEB_PORT = int(os.environ.get("TRUECONF_WEB_PORT", "80"))
# Only meaningful when TRUECONF_HTTPS is true: the proxy's certificate is
# self-signed, the same reason platform/flags.env sets TRUECONF_VERIFY_SSL.
TRUECONF_VERIFY_SSL = os.environ.get("TRUECONF_VERIFY_SSL", "false").lower() == "true"
# Fallback identity: an ordinary TrueConf account the adapter logs in as,
# used when no bot token is configured.
#
# A registered chat bot is the right way to do this, but it is not available
# on every server. This one runs 5.5.5, whose Chatbot API answers
# (/api/v4/server and /api/v4/endpoints/connects both 200), yet whose control
# panel ships no chat-bot section at all -- "chatbot" does not appear once in
# the admin-area or user-area bundles, only in the API docs. With no way to
# mint a token, token-only auth would leave delivery permanently unreachable
# on this deployment.
#
# The trade is real and worth stating: messages then arrive from a person's
# account rather than an identifiable bot, and that account's password lives
# in this stack's .env. Prefer TRUECONF_BOT_TOKEN wherever a bot can actually
# be registered; this is the pilot's way around a missing panel feature, not
# the better design.
TRUECONF_BOT_USERNAME = os.environ.get("TRUECONF_BOT_USERNAME", "")
TRUECONF_BOT_PASSWORD = os.environ.get("TRUECONF_BOT_PASSWORD", "")

router = Router()
dp = Dispatcher()
dp.include_router(router)

_TRANSPORT = {
    "https": TRUECONF_HTTPS,
    "web_port": TRUECONF_WEB_PORT,
    "verify_ssl": TRUECONF_VERIFY_SSL,
}

bot: Bot | None = None
auth_mode = "unavailable: no TRUECONF_BOT_TOKEN and no TRUECONF_BOT_USERNAME/PASSWORD"
if TRUECONF_SERVER and TRUECONF_BOT_TOKEN:
    bot = Bot(server=TRUECONF_SERVER, token=TRUECONF_BOT_TOKEN, dispatcher=dp, **_TRANSPORT)
    auth_mode = "token"
elif TRUECONF_SERVER and TRUECONF_BOT_USERNAME and TRUECONF_BOT_PASSWORD:
    bot = Bot.from_credentials(
        server=TRUECONF_SERVER,
        username=TRUECONF_BOT_USERNAME,
        password=TRUECONF_BOT_PASSWORD,
        dispatcher=dp,
        **_TRANSPORT,
    )
    auth_mode = f"credentials ({TRUECONF_BOT_USERNAME})"
else:
    logger.warning(
        "No TrueConf credentials configured (TRUECONF_BOT_TOKEN, or "
        "TRUECONF_BOT_USERNAME + TRUECONF_BOT_PASSWORD); HTTP API will start "
        "but /v1/notify will answer 503"
    )


@router.message(F.text == "/ping")
async def ping(msg: Message) -> None:
    await msg.answer("pong")


@router.message(F.text)
async def echo(msg: Message) -> None:
    await msg.answer(f"You said: **{msg.text}**", parse_mode=ParseMode.MARKDOWN)


async def notify(user_id: str, text: str) -> None:
    """Proactively message a TrueConf user -- a send, not a reply."""
    if bot is None:
        raise RuntimeError("bot is not configured")
    chat = await bot.create_personal_chat(user_id)
    await bot.send_message(chat.chat_id, text, parse_mode=ParseMode.MARKDOWN)


class NotifyRequest(BaseModel):
    """The subset of NotificationRequest.payload this channel needs.

    `extra` is allowed and ignored: platform's routing service sends alert
    context (rule, severity, metric, labels, ...) in the same payload for
    other webhook consumers, and this adapter must not 422 on fields that
    were never addressed to it.
    """

    model_config = {"extra": "allow"}

    trueconf_id: str = Field(min_length=1)
    text: str = Field(min_length=1)


@asynccontextmanager
async def lifespan(api: FastAPI):
    task: asyncio.Task | None = None
    if bot is not None:
        # The bot's own receive loop, so /ping and echo keep working
        # alongside the HTTP channel. Failures here must not stop the HTTP
        # server: outbound notification is the job that matters, and it
        # goes through notify() rather than through this loop.
        task = asyncio.create_task(bot.run())
    try:
        yield
    finally:
        if task is not None:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass


api = FastAPI(title="trueconf-bot", lifespan=lifespan)


@api.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "server": TRUECONF_SERVER or "unset",
        # Reported because a wrong transport fails identically to a wrong
        # token from the caller's side, and this is the cheapest way to tell
        # the two apart without reading container env.
        "transport": f"{'https' if TRUECONF_HTTPS else 'http'}://{TRUECONF_SERVER}:{TRUECONF_WEB_PORT}",
        "bot": "configured" if bot is not None else auth_mode,
        # Which identity messages are sent as. Never the password itself --
        # only whether a token or an account is doing the sending, and which
        # account, both of which are already visible to every recipient.
        "auth": auth_mode,
    }


@api.post("/v1/notify", status_code=202)
async def notify_endpoint(request: NotifyRequest) -> dict:
    """Deliver one incident notification to a TrueConf user.

    Returns 5xx on failure on purpose: the dispatcher turns a non-2xx into
    a `notification.failed` result, so a delivery that did not happen is
    recorded as such rather than being lost.
    """
    if bot is None:
        raise HTTPException(status_code=503, detail="bot not configured: TRUECONF_BOT_TOKEN is unset")
    try:
        await notify(request.trueconf_id, request.text)
    except Exception as error:
        logger.exception("TrueConf delivery to %s failed", request.trueconf_id)
        raise HTTPException(status_code=502, detail=f"TrueConf delivery failed: {error}") from error
    return {"delivered_to": request.trueconf_id}
