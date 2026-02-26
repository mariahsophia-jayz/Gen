import discord
from discord.ext import commands
from discord import app_commands
import json
import os
import time
import re
import asyncio
import aiohttp
from datetime import datetime, timezone

# ── Config ────────────────────────────────────────────────────
OWNER_IDS = [1380042914922758224, 1451233341327147059]  # yocryptfez, icezz___
COOLDOWN_SECONDS = 30
LOW_STOCK_THRESHOLD = 5
STOCK_FILE = "stock.txt"
PERMITTED_FILE = "permitted.json"
HISTORY_FILE = "history.json"
TOKEN = os.environ.get("DISCORD_TOKEN")
# ─────────────────────────────────────────────────────────────

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree
cooldowns: dict[int, float] = {}


# ══════════════════════════════════════════════════════════════
#  DURATION PARSER
# ══════════════════════════════════════════════════════════════

def parse_duration(s: str):
    units = {
        's': 1, 'sec': 1, 'secs': 1, 'second': 1, 'seconds': 1,
        'm': 60, 'min': 60, 'mins': 60, 'minute': 60, 'minutes': 60,
        'h': 3600, 'hr': 3600, 'hrs': 3600, 'hour': 3600, 'hours': 3600,
        'd': 86400, 'day': 86400, 'days': 86400,
        'w': 604800, 'week': 604800, 'weeks': 604800,
        'y': 31536000, 'year': 31536000, 'years': 31536000,
    }
    match = re.fullmatch(r'(\d+)\s*([a-zA-Z]+)', s.strip())
    if not match:
        return None
    amount, unit = int(match.group(1)), match.group(2).lower()
    return amount * units[unit] if unit in units else None


def fmt_duration(seconds: int) -> str:
    for limit, label in [(31536000, 'year'), (604800, 'week'), (86400, 'day'),
                         (3600, 'hour'), (60, 'minute'), (1, 'second')]:
        if seconds >= limit:
            v = seconds // limit
            return f"{v} {label}{'s' if v != 1 else ''}"
    return f"{seconds} seconds"


# ══════════════════════════════════════════════════════════════
#  FILE HELPERS
# ══════════════════════════════════════════════════════════════

def load_permitted() -> dict:
    if not os.path.exists(PERMITTED_FILE):
        return {}
    with open(PERMITTED_FILE, "r") as f:
        return json.load(f)


def save_permitted(data: dict):
    with open(PERMITTED_FILE, "w") as f:
        json.dump(data, f, indent=2)


def is_permitted(user_id: int) -> bool:
    data = load_permitted()
    uid = str(user_id)
    if uid not in data:
        return False
    entry = data[uid]
    if isinstance(entry, dict) and entry.get("expires"):
        if time.time() > entry["expires"]:
            data.pop(uid)
            save_permitted(data)
            return False
    return True


def add_permitted(user_id: int, username: str, expires: float = None):
    data = load_permitted()
    data[str(user_id)] = {"username": username, "expires": expires}
    save_permitted(data)


def remove_permitted(user_id: int):
    data = load_permitted()
    data.pop(str(user_id), None)
    save_permitted(data)


def load_stock() -> list:
    if not os.path.exists(STOCK_FILE):
        return []
    with open(STOCK_FILE, "r") as f:
        return [line.strip() for line in f if line.strip()]


def save_stock(lines: list):
    with open(STOCK_FILE, "w") as f:
        f.write("\n".join(lines) + ("\n" if lines else ""))


def load_history() -> list:
    if not os.path.exists(HISTORY_FILE):
        return []
    with open(HISTORY_FILE, "r") as f:
        return json.load(f)


def save_history(data: list):
    with open(HISTORY_FILE, "w") as f:
        json.dump(data, f, indent=2)


def log_history(user_id: int, username: str, email: str, sent_by: str = None):
    history = load_history()
    history.append({
        "user_id": user_id,
        "username": username,
        "email": email,
        "sent_by": sent_by,
        "timestamp": time.time()
    })
    save_history(history)


# ══════════════════════════════════════════════════════════════
#  AUTH & EMBEDS
# ══════════════════════════════════════════════════════════════

def is_owner_id(uid: int) -> bool:
    return uid in OWNER_IDS


def is_owner(i: discord.Interaction) -> bool:
    return i.user.id in OWNER_IDS


def error_embed(title: str, desc: str) -> discord.Embed:
    return discord.Embed(title=f"❌ {title}", description=desc, color=0xED4245)


def success_embed(title: str, desc: str) -> discord.Embed:
    return discord.Embed(title=f"✅ {title}", description=desc, color=0x57F287)


# ══════════════════════════════════════════════════════════════
#  LOW STOCK NOTIFIER
# ══════════════════════════════════════════════════════════════

async def notify_low_stock(count: int):
    if count <= LOW_STOCK_THRESHOLD:
        for owner_id in OWNER_IDS:
            try:
                user = await bot.fetch_user(owner_id)
                embed = discord.Embed(
                    title="⚠️ Low Stock Alert",
                    description=f"Stock is running low! Only **{count}** account(s) remaining.",
                    color=0xFEE75C
                )
                await user.send(embed=embed)
            except Exception:
                pass


# ══════════════════════════════════════════════════════════════
#  STATUS UPDATER
# ══════════════════════════════════════════════════════════════

async def update_status():
    await bot.wait_until_ready()
    while not bot.is_closed():
        count = len(load_stock())
        await bot.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name=f"{count} accounts in stock"
            )
        )
        await asyncio.sleep(60)


# ══════════════════════════════════════════════════════════════
#  CORE GENERATE LOGIC
# ══════════════════════════════════════════════════════════════

async def do_generate(user):
    now = time.time()
    last = cooldowns.get(user.id, 0)
    remaining = COOLDOWN_SECONDS - (now - last)
    if remaining > 0:
        return "cooldown", int(remaining) + 1, None

    stock = load_stock()
    if not stock:
        return "empty", None, None

    account = stock.pop(0)
    save_stock(stock)
    cooldowns[user.id] = now

    email, password = (account.split(":", 1) if ":" in account else (account, "N/A"))

    embed = discord.Embed(title="🎮 Minecraft Account", color=0x5865F2)
    embed.add_field(name="📧 Email / Username", value=f"`{email}`", inline=False)
    embed.add_field(name="🔑 Password", value=f"`{password}`", inline=False)
    embed.add_field(name="📦 Remaining Stock", value=f"{len(stock)} account(s)", inline=False)
    embed.set_footer(text=f"Generated for {user}")
    embed.timestamp = discord.utils.utcnow()

    log_history(user.id, str(user), email)
    await notify_low_stock(len(stock))

    return "ok", stock, embed


async def do_sendaccount(target, sender):
    stock = load_stock()
    if not stock:
        return "empty", None, None

    account = stock.pop(0)
    save_stock(stock)

    email, password = (account.split(":", 1) if ":" in account else (account, "N/A"))

    embed = discord.Embed(title="🎮 You received a Minecraft Account!", color=0x5865F2)
    embed.add_field(name="📧 Email / Username", value=f"`{email}`", inline=False)
    embed.add_field(name="🔑 Password", value=f"`{password}`", inline=False)
    embed.add_field(name="📦 Remaining Stock", value=f"{len(stock)} account(s)", inline=False)
    embed.set_footer(text=f"Sent by {sender}")
    embed.timestamp = discord.utils.utcnow()

    log_history(target.id, str(target), email, sent_by=str(sender))
    await notify_low_stock(len(stock))

    return "ok", stock, embed


# ══════════════════════════════════════════════════════════════
#  SLASH COMMANDS
# ══════════════════════════════════════════════════════════════

# ── /genaccess ────────────────────────────────────────────────

@tree.command(name="genaccess", description="Grant a user permission to use /generate")
@app_commands.describe(user="The user to grant access to", duration="Duration e.g. 1h, 7d, 2w, 1y (leave blank for permanent)")
async def genaccess(interaction: discord.Interaction, user: discord.Member, duration: str = None):
    if not is_owner(interaction):
        return await interaction.response.send_message(embed=error_embed("No Permission", "Only owners can grant access."), ephemeral=True)
    if user.id in OWNER_IDS:
        return await interaction.response.send_message(embed=error_embed("Already Authorized", "That user is already an owner."), ephemeral=True)

    expires = None
    duration_text = "Permanent"

    if duration:
        secs = parse_duration(duration)
        if not secs:
            return await interaction.response.send_message(
                embed=error_embed("Invalid Duration", "Use formats like `30s`, `5m`, `2h`, `7d`, `2w`, `1y`"),
                ephemeral=True
            )
        expires = time.time() + secs
        duration_text = fmt_duration(secs)

    add_permitted(user.id, str(user), expires)
    desc = f"{user.mention} can now use `/generate`.\nDuration: **{duration_text}**\nGranted by {interaction.user.mention}"
    if expires:
        desc += f"\nExpires: <t:{int(expires)}:R>"

    await interaction.response.send_message(embed=success_embed("Access Granted", desc))

    # DM the user
    try:
        dm = discord.Embed(title="✅ Generator Access Granted", color=0x57F287)
        dm.description = f"You have been granted access to generate Minecraft accounts.\nDuration: **{duration_text}**"
        if expires:
            dm.add_field(name="Expires", value=f"<t:{int(expires)}:R>", inline=False)
        dm.set_footer(text=f"Granted by {interaction.user}")
        await user.send(embed=dm)
    except Exception:
        pass


# ── /revokeaccess ─────────────────────────────────────────────

@tree.command(name="revokeaccess", description="Remove a user's permission to use /generate")
@app_commands.describe(user="The user to revoke access from")
async def revokeaccess(interaction: discord.Interaction, user: discord.Member):
    if not is_owner(interaction):
        return await interaction.response.send_message(embed=error_embed("No Permission", "Only owners can revoke access."), ephemeral=True)
    if not is_permitted(user.id):
        return await interaction.response.send_message(embed=error_embed("Not Permitted", f"{user.mention} doesn't have access."), ephemeral=True)
    remove_permitted(user.id)
    await interaction.response.send_message(embed=success_embed("Access Revoked", f"{user.mention}'s access has been removed."))


# ── /listaccess ───────────────────────────────────────────────

@tree.command(name="listaccess", description="List all users with granted /generate access")
async def listaccess(interaction: discord.Interaction):
    if not is_owner(interaction):
        return await interaction.response.send_message(embed=error_embed("No Permission", "Only owners can view this."), ephemeral=True)
    data = load_permitted()
    if not data:
        return await interaction.response.send_message(
            embed=discord.Embed(title="📋 Permitted Users", description="No users granted access yet.", color=0x5865F2),
            ephemeral=True
        )
    lines = []
    for uid, entry in data.items():
        uname = entry.get("username", uid) if isinstance(entry, dict) else entry
        exp = entry.get("expires") if isinstance(entry, dict) else None
        exp_text = f" — expires <t:{int(exp)}:R>" if exp else " — Permanent"
        lines.append(f"<@{uid}> (`{uname}`){exp_text}")
    embed = discord.Embed(title="📋 Permitted Users", description="\n".join(lines), color=0x5865F2)
    embed.set_footer(text=f"{len(data)} user(s) with access")
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ── /addstock ─────────────────────────────────────────────────

@tree.command(name="addstock", description="Upload a .txt file to add Minecraft accounts to stock")
@app_commands.describe(file="A .txt file with one account per line (email:password)")
async def addstock(interaction: discord.Interaction, file: discord.Attachment):
    if not is_owner(interaction):
        return await interaction.response.send_message(embed=error_embed("No Permission", "Only owners can add stock."), ephemeral=True)
    if not file.filename.endswith(".txt"):
        return await interaction.response.send_message(embed=error_embed("Invalid File", "Please attach a `.txt` file."), ephemeral=True)
    await interaction.response.defer()
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(file.url) as resp:
                text = await resp.text()
        new_accounts = [l.strip() for l in text.splitlines() if l.strip()]
        if not new_accounts:
            return await interaction.followup.send(embed=error_embed("Empty File", "The file had no valid accounts."))
        existing = load_stock()
        merged = existing + new_accounts
        save_stock(merged)
        await interaction.followup.send(embed=success_embed("Stock Updated", f"Added **{len(new_accounts)}** account(s).\nTotal stock: **{len(merged)}**"))
    except Exception as e:
        await interaction.followup.send(embed=error_embed("Error", f"Could not read the file: {e}"))


# ── /generate ─────────────────────────────────────────────────

@tree.command(name="generate", description="Generate a Minecraft account from stock")
async def generate(interaction: discord.Interaction):
    if not is_owner(interaction):
        return await interaction.response.send_message(embed=error_embed("No Permission", "Only owners can generate accounts."), ephemeral=True)
    status, data, embed = await do_generate(interaction.user)
    if status == "cooldown":
        return await interaction.response.send_message(embed=error_embed("⏳ Cooldown", f"Please wait **{data}s** before generating again."), ephemeral=True)
    if status == "empty":
        return await interaction.response.send_message(embed=error_embed("Out of Stock", "There are no accounts available right now."), ephemeral=True)
    try:
        await interaction.user.send(embed=embed)
        await interaction.response.send_message(embed=success_embed("Account Sent!", "Your Minecraft account has been sent to your DMs! 📬"), ephemeral=True)
    except discord.Forbidden:
        await interaction.response.send_message(content="⚠️ Couldn't DM you, so here it is (only you can see this):", embed=embed, ephemeral=True)


# ── /stock ────────────────────────────────────────────────────

@tree.command(name="stock", description="Check how many accounts are in stock")
async def stock_cmd(interaction: discord.Interaction):
    if not is_owner(interaction):
        return await interaction.response.send_message(embed=error_embed("No Permission", "Only owners can check stock."), ephemeral=True)
    count = len(load_stock())
    color = 0x57F287 if count > 0 else 0xED4245
    embed = discord.Embed(title="📦 Stock Status", description=f"There are **{count}** account(s) available." if count > 0 else "Stock is **empty**.", color=color)
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ── /checkstock ───────────────────────────────────────────────

@tree.command(name="checkstock", description="Publicly check how many accounts are in stock")
async def checkstock(interaction: discord.Interaction):
    count = len(load_stock())
    color = 0x57F287 if count > 0 else 0xED4245
    embed = discord.Embed(title="📦 Stock Status", description=f"There are **{count}** account(s) available." if count > 0 else "Stock is currently **empty**.", color=color)
    await interaction.response.send_message(embed=embed)


# ── /sendaccount ──────────────────────────────────────────────

@tree.command(name="sendaccount", description="Send a Minecraft account to a user via DM")
@app_commands.describe(user="The user to send an account to")
async def sendaccount(interaction: discord.Interaction, user: discord.Member):
    if not is_owner(interaction):
        return await interaction.response.send_message(embed=error_embed("No Permission", "Only owners can send accounts."), ephemeral=True)
    status, stock, embed = await do_sendaccount(user, interaction.user)
    if status == "empty":
        return await interaction.response.send_message(embed=error_embed("Out of Stock", "There are no accounts available right now."), ephemeral=True)
    try:
        await user.send(embed=embed)
    except discord.Forbidden:
        return await interaction.response.send_message(embed=error_embed("DM Failed", f"Couldn't DM {user.mention}. They may have DMs disabled."), ephemeral=True)
    await interaction.response.send_message(
        content=f"{user.mention}",
        embed=success_embed("Account Sent!", f"{user.mention} has been sent a Minecraft account via DM.\nSent by {interaction.user.mention}")
    )


# ── /clearstock ───────────────────────────────────────────────

@tree.command(name="clearstock", description="Clear all accounts from stock")
async def clearstock(interaction: discord.Interaction):
    if not is_owner(interaction):
        return await interaction.response.send_message(embed=error_embed("No Permission", "Only owners can clear stock."), ephemeral=True)
    count = len(load_stock())
    if count == 0:
        return await interaction.response.send_message(embed=error_embed("Already Empty", "Stock is already empty."), ephemeral=True)
    save_stock([])
    await interaction.response.send_message(embed=success_embed("Stock Cleared", f"Deleted **{count}** account(s) from stock."))


# ── /removestock ─────────────────────────────────────────────

@tree.command(name="removestock", description="Remove a specific number of accounts from stock")
@app_commands.describe(amount="How many accounts to remove")
async def removestock(interaction: discord.Interaction, amount: int):
    if not is_owner(interaction):
        return await interaction.response.send_message(embed=error_embed("No Permission", "Only owners can remove stock."), ephemeral=True)
    stock = load_stock()
    if amount <= 0:
        return await interaction.response.send_message(embed=error_embed("Invalid Amount", "Amount must be greater than 0."), ephemeral=True)
    if amount > len(stock):
        return await interaction.response.send_message(embed=error_embed("Too Many", f"Only **{len(stock)}** account(s) in stock."), ephemeral=True)
    stock = stock[amount:]
    save_stock(stock)
    await interaction.response.send_message(embed=success_embed("Stock Removed", f"Removed **{amount}** account(s).\nRemaining: **{len(stock)}**"))


# ── /history ──────────────────────────────────────────────────

@tree.command(name="history", description="View recent account generation history")
async def history(interaction: discord.Interaction):
    if not is_owner(interaction):
        return await interaction.response.send_message(embed=error_embed("No Permission", "Only owners can view history."), ephemeral=True)
    data = load_history()
    if not data:
        return await interaction.response.send_message(
            embed=discord.Embed(title="📜 History", description="No accounts have been generated yet.", color=0x5865F2),
            ephemeral=True
        )
    recent = data[-10:][::-1]
    lines = []
    for entry in recent:
        ts = int(entry.get("timestamp", 0))
        sent_by = f" (sent by {entry['sent_by']})" if entry.get("sent_by") else ""
        lines.append(f"<t:{ts}:R> — <@{entry['user_id']}>{sent_by}\n`{entry['email']}`")
    embed = discord.Embed(title="📜 Generation History (Last 10)", description="\n\n".join(lines), color=0x5865F2)
    embed.set_footer(text=f"Total generated: {len(data)}")
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ══════════════════════════════════════════════════════════════
#  PREFIX COMMANDS
# ══════════════════════════════════════════════════════════════

@bot.command(name="gen")
async def prefix_gen(ctx: commands.Context):
    if not is_owner_id(ctx.author.id):
        return await ctx.send(embed=error_embed("No Permission", "Only owners can generate accounts."))
    status, data, embed = await do_generate(ctx.author)
    if status == "cooldown":
        return await ctx.send(embed=error_embed("⏳ Cooldown", f"Please wait **{data}s** before generating again."))
    if status == "empty":
        return await ctx.send(embed=error_embed("Out of Stock", "There are no accounts available right now."))
    try:
        await ctx.author.send(embed=embed)
        await ctx.send(embed=success_embed("Account Sent!", "Your Minecraft account has been sent to your DMs! 📬"))
    except discord.Forbidden:
        await ctx.send(content="⚠️ Couldn't DM you, here it is:", embed=embed)


@bot.command(name="stock")
async def prefix_stock(ctx: commands.Context):
    if not is_owner_id(ctx.author.id):
        return await ctx.send(embed=error_embed("No Permission", "Only owners can check stock."))
    count = len(load_stock())
    color = 0x57F287 if count > 0 else 0xED4245
    embed = discord.Embed(title="📦 Stock Status", description=f"There are **{count}** account(s) available." if count > 0 else "Stock is **empty**.", color=color)
    await ctx.send(embed=embed)


@bot.command(name="sendaccount")
async def prefix_sendaccount(ctx: commands.Context, user: discord.Member = None):
    if not is_owner_id(ctx.author.id):
        return await ctx.send(embed=error_embed("No Permission", "Only owners can send accounts."))
    if not user:
        return await ctx.send(embed=error_embed("Missing User", "Usage: `!sendaccount @user`"))
    status, stock, embed = await do_sendaccount(user, ctx.author)
    if status == "empty":
        return await ctx.send(embed=error_embed("Out of Stock", "There are no accounts available right now."))
    try:
        await user.send(embed=embed)
    except discord.Forbidden:
        return await ctx.send(embed=error_embed("DM Failed", f"Couldn't DM {user.mention}. They may have DMs disabled."))
    await ctx.send(content=f"{user.mention}", embed=success_embed("Account Sent!", f"{user.mention} has been sent a Minecraft account via DM.\nSent by {ctx.author.mention}"))


@bot.command(name="addstock")
async def prefix_addstock(ctx: commands.Context):
    if not is_owner_id(ctx.author.id):
        return await ctx.send(embed=error_embed("No Permission", "Only owners can add stock."))
    if not ctx.message.attachments:
        return await ctx.send(embed=error_embed("No File", "Please attach a `.txt` file with your message."))
    attachment = ctx.message.attachments[0]
    if not attachment.filename.endswith(".txt"):
        return await ctx.send(embed=error_embed("Invalid File", "Please attach a `.txt` file."))
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(attachment.url) as resp:
                text = await resp.text()
        new_accounts = [l.strip() for l in text.splitlines() if l.strip()]
        if not new_accounts:
            return await ctx.send(embed=error_embed("Empty File", "The file had no valid accounts."))
        existing = load_stock()
        merged = existing + new_accounts
        save_stock(merged)
        await ctx.send(embed=success_embed("Stock Updated", f"Added **{len(new_accounts)}** account(s).\nTotal stock: **{len(merged)}**"))
    except Exception as e:
        await ctx.send(embed=error_embed("Error", f"Could not read the file: {e}"))


@bot.command(name="clearstock")
async def prefix_clearstock(ctx: commands.Context):
    if not is_owner_id(ctx.author.id):
        return await ctx.send(embed=error_embed("No Permission", "Only owners can clear stock."))
    count = len(load_stock())
    if count == 0:
        return await ctx.send(embed=error_embed("Already Empty", "Stock is already empty."))
    save_stock([])
    await ctx.send(embed=success_embed("Stock Cleared", f"Deleted **{count}** account(s) from stock."))


@bot.command(name="removestock")
async def prefix_removestock(ctx: commands.Context, amount: int = None):
    if not is_owner_id(ctx.author.id):
        return await ctx.send(embed=error_embed("No Permission", "Only owners can remove stock."))
    if not amount:
        return await ctx.send(embed=error_embed("Missing Amount", "Usage: `!removestock <number>`"))
    stock = load_stock()
    if amount > len(stock):
        return await ctx.send(embed=error_embed("Too Many", f"Only **{len(stock)}** account(s) in stock."))
    stock = stock[amount:]
    save_stock(stock)
    await ctx.send(embed=success_embed("Stock Removed", f"Removed **{amount}** account(s).\nRemaining: **{len(stock)}**"))


@bot.command(name="history")
async def prefix_history(ctx: commands.Context):
    if not is_owner_id(ctx.author.id):
        return await ctx.send(embed=error_embed("No Permission", "Only owners can view history."))
    data = load_history()
    if not data:
        return await ctx.send(embed=discord.Embed(title="📜 History", description="No accounts have been generated yet.", color=0x5865F2))
    recent = data[-10:][::-1]
    lines = []
    for entry in recent:
        ts = int(entry.get("timestamp", 0))
        sent_by = f" (sent by {entry['sent_by']})" if entry.get("sent_by") else ""
        lines.append(f"<t:{ts}:R> — <@{entry['user_id']}>{sent_by}\n`{entry['email']}`")
    embed = discord.Embed(title="📜 Generation History (Last 10)", description="\n\n".join(lines), color=0x5865F2)
    embed.set_footer(text=f"Total generated: {len(data)}")
    await ctx.send(embed=embed)


# ══════════════════════════════════════════════════════════════
#  BOT READY
# ══════════════════════════════════════════════════════════════

@bot.event
async def on_ready():
    await tree.sync()
    bot.loop.create_task(update_status())
    print(f"Logged in as {bot.user} | Slash commands synced.")


bot.run(TOKEN)
