"""A Discord bot that posts kills to a channel and answers !players.

Run it:
    pip install "oxrpy[async]" discord.py
    set OXFD_SERVER_KEY, DISCORD_TOKEN and KILL_FEED_CHANNEL_ID
    python discord_kill_feed.py

The bot needs the Message Content intent turned on in the Discord developer portal for !players.
"""

import asyncio
import os

import discord

from oxrpy import AsyncOxfordAPI

api = AsyncOxfordAPI(os.environ["OXFD_SERVER_KEY"])
CHANNEL_ID = int(os.environ["KILL_FEED_CHANNEL_ID"])


class Bot(discord.Client):
    async def setup_hook(self):
        # Runs the oxrpy handlers below alongside the bot.
        asyncio.create_task(api.run_forever())

    async def close(self):
        api.stop()
        await api.aclose()
        await super().close()


intents = discord.Intents.default()
intents.message_content = True
bot = Bot(intents=intents)


@api.on("Kill")
async def on_kill(kill):
    channel = bot.get_channel(CHANNEL_ID)
    if channel is None:
        return
    weapon = kill.get("Weapon") or "unknown weapon"
    headshot = " (headshot)" if kill.get("Headshot") else ""
    await channel.send(f"**{kill['KillerUsername']}** downed **{kill['VictimUsername']}** "
                       f"with {weapon}{headshot}")


@bot.event
async def on_message(message):
    if message.author.bot or message.content.strip() != "!players":
        return
    players = await api.get_players()
    if players is None:
        await message.channel.send("The server is offline.")
        return
    teams = {}
    for player in players:
        teams.setdefault(player.get("Team") or "Unknown", []).append(player["Username"])
    lines = [f"**{len(players)} players online**"]
    lines += [f"{team} ({len(names)}): {', '.join(sorted(names))}" for team, names in sorted(teams.items())]
    await message.channel.send("\n".join(lines)[:2000])


bot.run(os.environ["DISCORD_TOKEN"])
