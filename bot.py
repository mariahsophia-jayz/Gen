import discord
from discord.ext import commands
from discord import app_commands
import json
import os
import time
import aiohttp

# ── Config ────────────────────────────────────────────────────
OWNER_IDS = [1380042914922758224, 1451233341327147059]  # yocryptfez, icezz___
COOLDOWN_SECONDS = 30
STOCK_FILE = "stock.txt"
PERMITTED_FILE = "permitted.json"
TOKEN = os.environ.get("DISCORD_TOKEN")  # Set in Railway environment variables
# ─────────────────────────────────────────────────────────────

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

cooldowns: dict[int, float] = {}


# ── Helpers ───────────────────────────────────────────────────

def is_owner(interaction: discord.Interaction) -> bool:
    return interaction.user.id in OWNER_IDS


def is_authorized(interaction: discord.Interaction) -> bool:
    """Owners OR users granted via /genaccess"""
    if interaction.user.id in OWNER_IDS:
        return True
    return is_permitted(interaction.user.id)


def load_permitted() -> dict:
    if not os.path.exists(PERMITTED_FILE):
        return {}
    with open(PERMITTED_FILE, "r") as f:
        return json.load(f)


def save_permitted(data: dict):
    with open(PERMITTED_FILE, "w") as f:
        json.dump(data, f, indent=2)


def is_permitted(user_id: int) -> bool:
    return str(user_id) in load_permitted()


def add_permitted(user_id: int, username: str):
    data = load_permitted()
    data[str(user_id)] = username
    save_permitted(data)


def remove_permitted(user_id: int):
    data = load_permitted()
    data.pop(str(user_id), None)
    save_permitted(data)


def load_stock() -> list:
    if not os.path.exists(STOCK_FILE):
        return []
    with open(STOCK_FILE, "r") as f:
        return [line.strip() for line in f.readlines() if line.strip()]


def save_stock(lines: list):
    with open(STOCK_FILE, "w") as f:
        f.write("\n".join(lines) + ("\n" if lines else ""))


def error_embed(title: str, desc: str) -> discord.Embed:
    return discord.Embed(title=f"❌ {title}", description=desc, color=0xED4245)


def success_embed(title: str, desc: str) -> discord.Embed:
    return discord.Embed(title=f"✅ {title}", description=desc, color=0x57F287)


# ── /genaccess ────────────────────────────────────────────────

@tree.command(name="genaccess", description="Grant a user permission to use /generate")
@app_commands.describe(user="The user to grant access to")
async def genaccess(interaction: discord.Interaction, user: discord.Member):
    if not is_owner(interaction):
        return await interaction.response.send_message(
            embed=error_embed("No Permission", "Only owners can grant access."),
            ephemeral=True
        )
    if user.id in OWNER_IDS:
        return await interaction.response.send_message(
            embed=error_embed("Already Authorized", "That user is already an owner."),
            ephemeral=True
        )
    if is_permitted(user.id):
        return await interaction.response.send_message(
            embed=error_embed("Already Permitted", f"{user.mention} already has access."),
            ephemeral=True
        )
    add_permitted(user.id, str(user))
    await interaction.response.send_message(
        embed=success_embed(
            "Access Granted",
            f"{user.mention} can now use `/generate`.\nGranted by {interaction.user.mention}"
        )
    )


# ── /revokeaccess ─────────────────────────────────────────────

@tree.command(name="revokeaccess", description="Remove a user's permission to use /generate")
@app_commands.describe(user="The user to revoke access from")
async def revokeaccess(interaction: discord.Interaction, user: discord.Member):
    if not is_owner(interaction):
        return await interaction.response.send_message(
            embed=error_embed("No Permission", "Only owners can revoke access."),
            ephemeral=True
        )
    if not is_permitted(user.id):
        return await interaction.response.send_message(
            embed=error_embed("Not Permitted", f"{user.mention} doesn't have granted access."),
            ephemeral=True
        )
    remove_permitted(user.id)
    await interaction.response.send_message(
        embed=success_embed("Access Revoked", f"{user.mention}'s access has been removed.")
    )


# ── /listaccess ───────────────────────────────────────────────

@tree.command(name="listaccess", description="List all users with granted /generate access")
async def listaccess(interaction: discord.Interaction):
    if not is_owner(interaction):
        return await interaction.response.send_message(
            embed=error_embed("No Permission", "Only owners can view this."),
            ephemeral=True
        )
    data = load_permitted()
    if not data:
        return await interaction.response.send_message(
            embed=discord.Embed(title="📋 Permitted Users", description="No users granted access yet.", color=0x5865F2),
            ephemeral=True
        )
    user_list = "\n".join([f"<@{uid}> (`{uname}`)" for uid, uname in data.items()])
    embed = discord.Embed(title="📋 Permitted Users", description=user_list, color=0x5865F2)
    embed.set_footer(text=f"{len(data)} user(s) with access")
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ── /addstock ─────────────────────────────────────────────────

@tree.command(name="addstock", description="Upload a .txt file to add Minecraft accounts to stock")
@app_commands.describe(file="A .txt file with one account per line (email:password)")
async def addstock(interaction: discord.Interaction, file: discord.Attachment):
    if not is_owner(interaction):
        return await interaction.response.send_message(
            embed=error_embed("No Permission", "Only owners can add stock."),
            ephemeral=True
        )
    if not file.filename.endswith(".txt"):
        return await interaction.response.send_message(
            embed=error_embed("Invalid File", "Please attach a `.txt` file."),
            ephemeral=True
        )
    await interaction.response.defer(ephemeral=True)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(file.url) as resp:
                text = await resp.text()
        new_accounts = [line.strip() for line in text.splitlines() if line.strip()]
        if not new_accounts:
            return await interaction.followup.send(embed=error_embed("Empty File", "The file had no valid accounts."))
        existing = load_stock()
        merged = existing + new_accounts
        save_stock(merged)
        await interaction.followup.send(
            embed=success_embed("Stock Updated", f"Added **{len(new_accounts)}** account(s).\nTotal stock: **{len(merged)}**")
        )
    except Exception as e:
        await interaction.followup.send(embed=error_embed("Error", f"Could not read the file: {e}"))


# ── /generate ─────────────────────────────────────────────────

@tree.command(name="generate", description="Generate a Minecraft account from stock")
async def generate(interaction: discord.Interaction):
    if not is_owner(interaction):
        return await interaction.response.send_message(
            embed=error_embed("No Permission", "Only owners can generate accounts."),
            ephemeral=True
        )
    now = time.time()
    last_used = cooldowns.get(interaction.user.id, 0)
    remaining = COOLDOWN_SECONDS - (now - last_used)
    if remaining > 0:
        return await interaction.response.send_message(
            embed=error_embed("⏳ Cooldown", f"Please wait **{int(remaining) + 1}s** before generating again."),
            ephemeral=True
        )
    stock = load_stock()
    if not stock:
        return await interaction.response.send_message(
            embed=error_embed("Out of Stock", "There are no accounts available right now."),
            ephemeral=True
        )
    account = stock.pop(0)
    save_stock(stock)
    cooldowns[interaction.user.id] = now
    if ":" in account:
        parts = account.split(":", 1)
        email, password = parts[0], parts[1]
    else:
        email, password = account, "N/A"
    embed = discord.Embed(title="🎮 Minecraft Account", color=0x5865F2)
    embed.add_field(name="📧 Email / Username", value=f"`{email}`", inline=False)
    embed.add_field(name="🔑 Password", value=f"`{password}`", inline=False)
    embed.add_field(name="📦 Remaining Stock", value=f"{len(stock)} account(s)", inline=False)
    embed.set_footer(text=f"Generated for {interaction.user}")
    embed.timestamp = discord.utils.utcnow()
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ── /stock ────────────────────────────────────────────────────

@tree.command(name="stock", description="Check how many accounts are in stock")
async def stock_cmd(interaction: discord.Interaction):
    if not is_owner(interaction):
        return await interaction.response.send_message(
            embed=error_embed("No Permission", "Only owners can check stock."),
            ephemeral=True
        )
    count = len(load_stock())
    color = 0x57F287 if count > 0 else 0xED4245
    embed = discord.Embed(
        title="📦 Stock Status",
        description=f"There are **{count}** account(s) available." if count > 0 else "Stock is **empty**.",
        color=color
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ── Bot ready ─────────────────────────────────────────────────

@bot.event
async def on_ready():
    await tree.sync()

# ── /sendaccount ──────────────────────────────────────────────

@tree.command(name="sendaccount", description="Send a Minecraft account to a user via DM")
@app_commands.describe(user="The user to send an account to")
async def sendaccount(interaction: discord.Interaction, user: discord.Member):
    if not is_owner(interaction):
        return await interaction.response.send_message(
            embed=error_embed("No Permission", "Only owners can send accounts."),
            ephemeral=True
        )

    stock = load_stock()
    if not stock:
        return await interaction.response.send_message(
            embed=error_embed("Out of Stock", "There are no accounts available right now."),
            ephemeral=True
        )

    account = stock.pop(0)
    save_stock(stock)

    if ":" in account:
        parts = account.split(":", 1)
        email, password = parts[0], parts[1]
    else:
        email, password = account, "N/A"

    # DM embed
    dm_embed = discord.Embed(title="🎮 You received a Minecraft Account!", color=0x5865F2)
    dm_embed.add_field(name="📧 Email / Username", value=f"`{email}`", inline=False)
    dm_embed.add_field(name="🔑 Password", value=f"`{password}`", inline=False)
    dm_embed.add_field(name="📦 Remaining Stock", value=f"{len(stock)} account(s)", inline=False)
    dm_embed.set_footer(text=f"Sent by {interaction.user}")
    dm_embed.timestamp = discord.utils.utcnow()

    try:
        await user.send(embed=dm_embed)
    except discord.Forbidden:
        # Give back the account if DM failed
        stock.insert(0, account)
        save_stock(stock)
        return await interaction.response.send_message(
            embed=error_embed("DM Failed", f"Couldn't DM {user.mention}. They may have DMs disabled."),
            ephemeral=True
        )

    # Ping in channel
    await interaction.response.send_message(
        content=f"{user.mention}",
        embed=success_embed(
            "Account Sent!",
            f"{user.mention} has been sent a Minecraft account via DM.\nSent by {interaction.user.mention}"
        )
    )


# ── Bot ready ─────────────────────────────────────────────────

@bot.event
async def on_ready():
    await tree.sync()
    print(f"Logged in as {bot.user} | Slash commands synced.")


bot.run(TOKEN)
