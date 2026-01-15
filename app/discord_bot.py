import discord
from config import DISCORD_TOKEN, DISCORD_CHANNEL_ID

intents = discord.Intents.default()
client = discord.Client(intents=intents)

async def notify(msg):
    channel = client.get_channel(DISCORD_CHANNEL_ID)
    await channel.send(msg)

@client.event
async def on_ready():
    print("Discord bot ready")

client.run(DISCORD_TOKEN)
