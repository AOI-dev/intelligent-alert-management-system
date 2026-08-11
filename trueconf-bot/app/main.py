"""TrueConf chat bot, built on python-trueconf-bot (an aiogram-style wrapper
around TrueConf Server's Chatbot API):
https://github.com/TrueConf/python-trueconf-bot

This is a first spike, not the "mandatory TrueConf channel" delivery
adapter from artifacts/happy-path.md step 9-10 yet. It proves the bot
account/library round-trip works: register it as a chat bot in the TrueConf
Server control panel, run this, and message it.

notify() below is the piece that adapter needs -- a proactive send, not a
reply to an incoming message -- confirmed against the installed library
(1.4.2) by inspecting Bot.send_message/Bot.create_personal_chat directly,
since the published README quickstart only documents the reply path
(msg.answer()). Wiring an actual Kafka consumer for
monitoring.notification-requests.v1 and a producer for
monitoring.notification-results.v1, mirroring notifications/app/main.py,
is the remaining deferred step -- notify() is ready for it, but nothing
calls it yet.
"""
import os

from trueconf import Bot, Dispatcher, F, Message, ParseMode, Router

TRUECONF_SERVER = os.environ["TRUECONF_SERVER"]
TRUECONF_BOT_TOKEN = os.environ["TRUECONF_BOT_TOKEN"]

router = Router()
dp = Dispatcher()
dp.include_router(router)

bot = Bot(server=TRUECONF_SERVER, token=TRUECONF_BOT_TOKEN, dispatcher=dp)


@router.message(F.text == "/ping")
async def ping(msg: Message) -> None:
    await msg.answer("pong")


@router.message(F.text)
async def echo(msg: Message) -> None:
    await msg.answer(f"You said: **{msg.text}**", parse_mode=ParseMode.MARKDOWN)


async def notify(user_id: str, text: str) -> None:
    """Proactively message a TrueConf user -- the call an incident-delivery
    adapter would make. Not wired to anything yet; see module docstring.
    """
    chat = await bot.create_personal_chat(user_id)
    await bot.send_message(chat.chat_id, text, parse_mode=ParseMode.MARKDOWN)


async def main() -> None:
    await bot.run()


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
