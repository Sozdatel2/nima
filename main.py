import os

import nextcord
from nextcord.ext import commands
from dotenv import load_dotenv

load_dotenv()

intents = nextcord.Intents.all()
bot = commands.Bot(command_prefix="ni.", intents=intents)


@bot.event
async def on_ready():
    print(f"Бот запущен как {bot.user} (id: {bot.user.id})")


def load_cogs():
    for filename in os.listdir("./cogs"):
        if filename.endswith(".py") and not filename.startswith("_"):
            bot.load_extension(f"cogs.{filename[:-3]}")
            print(f"Загружен ког: {filename}")


if __name__ == "__main__":
    load_cogs()
    bot.run(os.getenv("TOKEN"))