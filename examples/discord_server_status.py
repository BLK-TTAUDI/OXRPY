"""A Discord bot that posts when your server goes offline, comes back or restarts, and shows
the player count as its status.

Run it:
    pip install "oxrpy[async]" discord.py
    set OXFD_SERVER_KEY, DISCORD_TOKEN and STATUS_CHANNEL_ID
    python discord_server_status.py
"""

import asyncio
import os

import discord

from oxrpy import AsyncOxfordAPI

api = AsyncOxfordAPI(os.environ["OXFD_SERVER_KEY"])
CHANNEL_ID = int(os.environ["STATUS_CHANNEL_ID"])


class Bot(discord.Client):
    async def setup_hook(self):
        asyncio.create_task(api.run_forever())


bot = Bot(intents=discord.Intents.default())


async def post(text):
    channel = bot.get_channel(CHANNEL_ID)
    if channel is not None:
        await channel.send(text)


@api.on("ServerOnline")
async def on_online(data):
    await post(f"🟢 **{data['Server']['Name']}** is back online")


@api.on("ServerOffline")
async def on_offline(data):
    await post("🔴 The server is offline")


@api.on("ServerRestart")
async def on_restart(data):
    await post("🔄 The server restarted")


last_count = None


@api.on("poll")
async def on_poll(data):
    """After every request: keep the bot's status showing the player count."""
    global last_count
    server = data.get("Server") or {}
    count = f"{server.get('CurrentPlayers', 0)}/{server.get('MaxPlayers', '?')}" if data.online else "offline"
    if count != last_count and bot.is_ready():
        last_count = count
        await bot.change_presence(activity=discord.Game(f"Oxford RP: {count}"))


bot.run(os.environ["DISCORD_TOKEN"])
