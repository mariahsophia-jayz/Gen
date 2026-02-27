import discord
from discord.ext import commands
from discord import app_commands
import json
import os
import time
import re
import asyncio
import aiohttp

# ── Config ────────────────────────────────────────────────────
OWNER_IDS = [1380042914922758224, 1451233341327147059]  # yocryptfez, icezz___
COOLDOWN_SECONDS = 30
LOW_STOCK_THRESHOLD = 5
STOCK_FILE = "stock.txt"
PERMITTED_FILE = "permitted.json"
HISTORY_FILE = "history.json"
TOKEN = os.environ.get("DISCORD_TOKEN")

# ── Colors ────────────────────────────────────────────────────
PURPLE      = 0x9B59B6
GOLD        = 0xF1C40F
RED         = 0xE74C3C
GREEN       = 0x2ECC71
DARK_PURPLE = 0x6C3483
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
    history.append({"user_id": user_id, "username": username, "email": email, "sent_by": sent_by, "timestamp": time.time()})
    save_history(history)


# ══════════════════════════════════════════════════════════════
#  AUTH & EMBEDS
# ══════════════════════════════════════════════════════════════

def is_owner_id(uid: int) -> bool:
    return uid in OWNER_IDS

def is_owner(i: discord.Interaction) -> bool:
    return i.user.id in OWNER_IDS

def error_embed(title: str, desc: str) -> discord.Embed:
    e = discord.Embed(title=f"╳  {title}", description=f"> {desc}", color=RED)
    e.set_footer(text="⚡ MC Account Bot")
    return e

def success_embed(title: str, desc: str) -> discord.Embed:
    e = discord.Embed(title=f"✦  {title}", description=f"> {desc}", color=GREEN)
    e.set_footer(text="⚡ MC Account Bot")
    return e

def stock_embed(count: int) -> discord.Embed:
    color = GOLD if count > 0 else RED
    status = "🟢  Online" if count > 0 else "🔴  Empty"
    e = discord.Embed(title="◈  Stock Status", color=color)
    e.add_field(name="Available Accounts", value=f"```{count}```", inline=True)
    e.add_field(name="Status", value=f"```{status}```", inline=True)
    e.set_footer(text="⚡ MC Account Bot")
    e.timestamp = discord.utils.utcnow()
    return e

def account_embed(accounts: list, user, sent_by=None) -> discord.Embed:
    is_gift = sent_by is not None
    title = "╔══ 🎁  YOU GOT AN ACCOUNT! ══╗" if is_gift else "╔══ 🎮  MINECRAFT ACCOUNT ══╗"
    color = GOLD if is_gift else PURPLE
    e = discord.Embed(title=title, description="```" + "─" * 32 + "```", color=color)
    for i, account in enumerate(accounts, 1):
        email, password = (account.split(":", 1) if ":" in account else (account, "N/A"))
        e.add_field(name=f"✦ Account #{i}", value=f"```yaml\nEmail   : {email}\nPassword: {password}```", inline=False)
    footer_user = sent_by if is_gift else user
    e.set_footer(text=f"⚡ {'Sent by ' + str(footer_user) if is_gift else 'Generated for ' + str(user)} • Keep this private!")
    e.timestamp = discord.utils.utcnow()
    return e


# ══════════════════════════════════════════════════════════════
#  LOW STOCK NOTIFIER & STATUS
# ══════════════════════════════════════════════════════════════

async def notify_low_stock(count: int):
    if count <= LOW_STOCK_THRESHOLD:
        for owner_id in OWNER_IDS:
            try:
                user = await bot.fetch_user(owner_id)
                e = discord.Embed(title="⚠️  Low Stock Alert", color=GOLD)
                e.description = f"```yaml\nStock is running low!\nOnly {count} account(s) remaining.```"
                e.set_footer(text="⚡ MC Account Bot • Restock soon!")
                await user.send(embed=e)
            except Exception:
                pass

async def update_status():
    await bot.wait_until_ready()
    while not bot.is_closed():
        count = len(load_stock())
        await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name=f"{count} accounts in stock"))
        await asyncio.sleep(60)


# ══════════════════════════════════════════════════════════════
#  CORE LOGIC
# ══════════════════════════════════════════════════════════════

async def core_generate(user, amount: int):
    now = time.time()
    last = cooldowns.get(user.id, 0)
    remaining = COOLDOWN_SECONDS - (now - last)
    if remaining > 0:
        return "cooldown", int(remaining) + 1, None, None

    stock = load_stock()
    if not stock:
        return "empty", None, None, None
    if amount > len(stock):
        return "notenough", len(stock), None, None

    accounts = stock[:amount]
    save_stock(stock[amount:])
    cooldowns[user.id] = now

    for acc in accounts:
        email = acc.split(":", 1)[0] if ":" in acc else acc
        log_history(user.id, str(user), email)

    embed = account_embed(accounts, user)
    embed.add_field(name="📦 Stock Remaining", value=f"```{len(stock) - amount} accounts left```", inline=False)
    await notify_low_stock(len(stock) - amount)
    return "ok", accounts, embed, len(stock) - amount


async def core_sendaccount(target, sender, amount: int):
    stock = load_stock()
    if not stock:
        return "empty", None, None
    if amount > len(stock):
        return "notenough", len(stock), None

    accounts = stock[:amount]
    save_stock(stock[amount:])

    for acc in accounts:
        email = acc.split(":", 1)[0] if ":" in acc else acc
        log_history(target.id, str(target), email, sent_by=str(sender))

    embed = account_embed(accounts, target, sent_by=sender)
    embed.add_field(name="📦 Stock Remaining", value=f"```{len(stock) - amount} accounts left```", inline=False)
    await notify_low_stock(len(stock) - amount)
    return "ok", accounts, embed


# ══════════════════════════════════════════════════════════════
#  SLASH COMMANDS
# ══════════════════════════════════════════════════════════════

@tree.command(name="genaccess", description="Grant a user permission to use /generate")
@app_commands.describe(user="The user to grant access to", duration="Duration e.g. 1h, 7d, 2w, 1y (blank = permanent)")
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
            return await interaction.response.send_message(embed=error_embed("Invalid Duration", "Use formats like `30s`, `5m`, `2h`, `7d`, `2w`, `1y`"), ephemeral=True)
        expires = time.time() + secs
        duration_text = fmt_duration(secs)
    add_permitted(user.id, str(user), expires)
    e = discord.Embed(title="✦  Access Granted", color=GOLD)
    e.add_field(name="User", value=user.mention, inline=True)
    e.add_field(name="Duration", value=f"`{duration_text}`", inline=True)
    e.add_field(name="Granted by", value=interaction.user.mention, inline=True)
    if expires:
        e.add_field(name="Expires", value=f"<t:{int(expires)}:R>", inline=False)
    e.set_footer(text="⚡ MC Account Bot")
    e.timestamp = discord.utils.utcnow()
    await interaction.response.send_message(embed=e)
    try:
        dm = discord.Embed(title="✦  You Got Generator Access!", color=GOLD)
        dm.description = f"```yaml\nYou can now generate Minecraft accounts!\nDuration: {duration_text}```"
        if expires:
            dm.add_field(name="⏳ Expires", value=f"<t:{int(expires)}:R>", inline=False)
        dm.set_footer(text=f"⚡ Granted by {interaction.user} • MC Account Bot")
        dm.timestamp = discord.utils.utcnow()
        await user.send(embed=dm)
    except Exception:
        pass


@tree.command(name="revokeaccess", description="Remove a user's permission to use /generate")
@app_commands.describe(user="The user to revoke access from")
async def revokeaccess(interaction: discord.Interaction, user: discord.Member):
    if not is_owner(interaction):
        return await interaction.response.send_message(embed=error_embed("No Permission", "Only owners can revoke access."), ephemeral=True)
    if not is_permitted(user.id):
        return await interaction.response.send_message(embed=error_embed("Not Permitted", f"{user.mention} doesn't have access."), ephemeral=True)
    remove_permitted(user.id)
    await interaction.response.send_message(embed=success_embed("Access Revoked", f"{user.mention}'s access has been removed."))


@tree.command(name="listaccess", description="List all users with granted access")
async def listaccess(interaction: discord.Interaction):
    if not is_owner(interaction):
        return await interaction.response.send_message(embed=error_embed("No Permission", "Only owners can view this."), ephemeral=True)
    data = load_permitted()
    if not data:
        e = discord.Embed(title="◈  Permitted Users", description="> No users granted access yet.", color=PURPLE)
        e.set_footer(text="⚡ MC Account Bot")
        return await interaction.response.send_message(embed=e, ephemeral=True)
    lines = []
    for uid, entry in data.items():
        uname = entry.get("username", uid) if isinstance(entry, dict) else entry
        exp = entry.get("expires") if isinstance(entry, dict) else None
        exp_text = f" — expires <t:{int(exp)}:R>" if exp else " — Permanent"
        lines.append(f"<@{uid}> (`{uname}`){exp_text}")
    e = discord.Embed(title="◈  Permitted Users", description="\n".join(lines), color=PURPLE)
    e.set_footer(text=f"⚡ {len(data)} user(s) with access • MC Account Bot")
    e.timestamp = discord.utils.utcnow()
    await interaction.response.send_message(embed=e, ephemeral=True)


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
        e = discord.Embed(title="✦  Stock Updated", color=GOLD)
        e.add_field(name="Added", value=f"```{len(new_accounts)} accounts```", inline=True)
        e.add_field(name="Total Stock", value=f"```{len(merged)} accounts```", inline=True)
        e.set_footer(text=f"⚡ MC Account Bot • Uploaded by {interaction.user}")
        e.timestamp = discord.utils.utcnow()
        await interaction.followup.send(embed=e)
    except Exception as ex:
        await interaction.followup.send(embed=error_embed("Error", f"Could not read the file: {ex}"))


@tree.command(name="generate", description="Generate a Minecraft account from stock")
@app_commands.describe(amount="How many accounts to generate (default 1, max 10)")
async def generate(interaction: discord.Interaction, amount: int = 1):
    if not is_owner(interaction) and not is_permitted(interaction.user.id):
        return await interaction.response.send_message(embed=error_embed("No Permission", "You don't have access to generate accounts."), ephemeral=True)
    if amount < 1 or amount > 10:
        return await interaction.response.send_message(embed=error_embed("Invalid Amount", "Amount must be between 1 and 10."), ephemeral=True)
    status, data, embed, remaining = await core_generate(interaction.user, amount)
    if status == "cooldown":
        return await interaction.response.send_message(embed=error_embed("⏳ Cooldown", f"Please wait **{data}s** before generating again."), ephemeral=True)
    if status == "empty":
        return await interaction.response.send_message(embed=error_embed("Out of Stock", "There are no accounts available right now."), ephemeral=True)
    if status == "notenough":
        return await interaction.response.send_message(embed=error_embed("Not Enough Stock", f"Only **{data}** account(s) available."), ephemeral=True)
    try:
        await interaction.user.send(embed=embed)
        sent = discord.Embed(title="✦  Account(s) Sent!", description=f"> **{amount}** account(s) slid into your DMs 📬", color=GOLD)
        sent.set_footer(text="⚡ MC Account Bot • Check your DMs!")
        await interaction.response.send_message(embed=sent, ephemeral=True)
    except discord.Forbidden:
        await interaction.response.send_message(content="⚠️ Couldn't DM you, here it is:", embed=embed, ephemeral=True)


@tree.command(name="sendaccount", description="Send a Minecraft account to a user via DM")
@app_commands.describe(user="The user to send an account to", amount="How many accounts to send (default 1, max 10)")
async def sendaccount(interaction: discord.Interaction, user: discord.Member, amount: int = 1):
    if not is_owner(interaction):
        return await interaction.response.send_message(embed=error_embed("No Permission", "Only owners can send accounts."), ephemeral=True)
    if amount < 1 or amount > 10:
        return await interaction.response.send_message(embed=error_embed("Invalid Amount", "Amount must be between 1 and 10."), ephemeral=True)
    status, accounts, embed = await core_sendaccount(user, interaction.user, amount)
    if status == "empty":
        return await interaction.response.send_message(embed=error_embed("Out of Stock", "There are no accounts available right now."), ephemeral=True)
    if status == "notenough":
        return await interaction.response.send_message(embed=error_embed("Not Enough Stock", f"Only **{accounts}** account(s) available."), ephemeral=True)
    try:
        await user.send(embed=embed)
    except discord.Forbidden:
        return await interaction.response.send_message(embed=error_embed("DM Failed", f"Couldn't DM {user.mention}. They may have DMs disabled."), ephemeral=True)
    confirm = discord.Embed(title="✦  Account(s) Sent!", color=PURPLE)
    confirm.add_field(name="Sent by", value=interaction.user.mention, inline=True)
    confirm.add_field(name="Recipient", value=user.mention, inline=True)
    confirm.add_field(name="Amount", value=f"`{amount}`", inline=True)
    confirm.set_footer(text="⚡ MC Account Bot")
    confirm.timestamp = discord.utils.utcnow()
    await interaction.response.send_message(content=f"{user.mention}", embed=confirm)


@tree.command(name="stock", description="Check how many accounts are in stock")
async def stock_cmd(interaction: discord.Interaction):
    await interaction.response.send_message(embed=stock_embed(len(load_stock())))


@tree.command(name="checkstock", description="Publicly check how many accounts are in stock")
async def checkstock(interaction: discord.Interaction):
    await interaction.response.send_message(embed=stock_embed(len(load_stock())))


@tree.command(name="clearstock", description="Clear all accounts from stock")
async def clearstock(interaction: discord.Interaction):
    if not is_owner(interaction):
        return await interaction.response.send_message(embed=error_embed("No Permission", "Only owners can clear stock."), ephemeral=True)
    count = len(load_stock())
    if count == 0:
        return await interaction.response.send_message(embed=error_embed("Already Empty", "Stock is already empty."), ephemeral=True)
    save_stock([])
    await interaction.response.send_message(embed=success_embed("Stock Cleared", f"Deleted **{count}** account(s) from stock."))


@tree.command(name="removestock", description="Remove a specific number of accounts from stock")
@app_commands.describe(amount="How many accounts to remove")
async def removestock(interaction: discord.Interaction, amount: int):
    if not is_owner(interaction):
        return await interaction.response.send_message(embed=error_embed("No Permission", "Only owners can remove stock."), ephemeral=True)
    stock = load_stock()
    if amount < 1:
        return await interaction.response.send_message(embed=error_embed("Invalid Amount", "Amount must be greater than 0."), ephemeral=True)
    if amount > len(stock):
        return await interaction.response.send_message(embed=error_embed("Too Many", f"Only **{len(stock)}** account(s) in stock."), ephemeral=True)
    save_stock(stock[amount:])
    await interaction.response.send_message(embed=success_embed("Stock Removed", f"Removed **{amount}** account(s). Remaining: **{len(stock) - amount}**"))


@tree.command(name="history", description="View recent account generation history")
async def history(interaction: discord.Interaction):
    if not is_owner(interaction):
        return await interaction.response.send_message(embed=error_embed("No Permission", "Only owners can view history."), ephemeral=True)
    data = load_history()
    if not data:
        e = discord.Embed(title="◈  History", description="> No accounts have been generated yet.", color=DARK_PURPLE)
        e.set_footer(text="⚡ MC Account Bot")
        return await interaction.response.send_message(embed=e, ephemeral=True)
    recent = data[-10:][::-1]
    lines = []
    for entry in recent:
        ts = int(entry.get("timestamp", 0))
        sent_by = f" *(sent by {entry['sent_by']})*" if entry.get("sent_by") else ""
        lines.append(f"<t:{ts}:R> — <@{entry['user_id']}>{sent_by}\n`{entry['email']}`")
    e = discord.Embed(title="◈  Generation History", description="\n\n".join(lines), color=DARK_PURPLE)
    e.set_footer(text=f"⚡ Total generated: {len(data)} • MC Account Bot")
    e.timestamp = discord.utils.utcnow()
    await interaction.response.send_message(embed=e, ephemeral=True)



@tree.command(name="restock", description="Put back recently generated accounts into stock")
@app_commands.describe(minutes="How many minutes back to restock (1-10, default 5)", amount="Max accounts to restock (1-10, default 10)")
async def restock(interaction: discord.Interaction, minutes: int = 5, amount: int = 10):
    if not is_owner(interaction):
        return await interaction.response.send_message(embed=error_embed("No Permission", "Only owners can restock."), ephemeral=True)
    if minutes < 1 or minutes > 10:
        return await interaction.response.send_message(embed=error_embed("Invalid Time", "Minutes must be between 1 and 10."), ephemeral=True)
    if amount < 1 or amount > 10:
        return await interaction.response.send_message(embed=error_embed("Invalid Amount", "Amount must be between 1 and 10."), ephemeral=True)

    history = load_history()
    if not history:
        return await interaction.response.send_message(embed=error_embed("No History", "No accounts have been generated yet."), ephemeral=True)

    cutoff = time.time() - (minutes * 60)
    recent = [e for e in history if e.get("timestamp", 0) >= cutoff]

    if not recent:
        return await interaction.response.send_message(
            embed=error_embed("None Found", f"No accounts were generated in the last **{minutes}** minute(s)."),
            ephemeral=True
        )

    # Take up to `amount` most recent ones
    to_restock = recent[-amount:]
    emails_restocked = [e["email"] for e in to_restock]

    # Add back to stock
    current_stock = load_stock()
    save_stock(emails_restocked + current_stock)

    # Remove from history
    restocked_timestamps = {e["timestamp"] for e in to_restock}
    updated_history = [e for e in history if e.get("timestamp") not in restocked_timestamps]
    save_history(updated_history)

    e = discord.Embed(title="✦  Restock Complete", color=GOLD)
    e.add_field(name="Restocked", value=f"```{len(emails_restocked)} account(s)```", inline=True)
    e.add_field(name="Time Window", value=f"```Last {minutes} min(s)```", inline=True)
    e.add_field(name="New Stock Total", value=f"```{len(current_stock) + len(emails_restocked)} accounts```", inline=True)
    e.set_footer(text=f"⚡ Restocked by {interaction.user} • MC Account Bot")
    e.timestamp = discord.utils.utcnow()
    await interaction.response.send_message(embed=e)

# ══════════════════════════════════════════════════════════════
#  PREFIX COMMANDS
# ══════════════════════════════════════════════════════════════

@bot.command(name="gen")
async def prefix_gen(ctx: commands.Context, amount: int = 1):
    if not is_owner_id(ctx.author.id) and not is_permitted(ctx.author.id):
        return await ctx.send(embed=error_embed("No Permission", "You don't have access to generate accounts."))
    if amount < 1 or amount > 10:
        return await ctx.send(embed=error_embed("Invalid Amount", "Amount must be between 1 and 10."))
    status, data, embed, remaining = await core_generate(ctx.author, amount)
    if status == "cooldown":
        return await ctx.send(embed=error_embed("⏳ Cooldown", f"Please wait **{data}s** before generating again."))
    if status == "empty":
        return await ctx.send(embed=error_embed("Out of Stock", "There are no accounts available right now."))
    if status == "notenough":
        return await ctx.send(embed=error_embed("Not Enough Stock", f"Only **{data}** account(s) available."))
    try:
        await ctx.author.send(embed=embed)
        sent = discord.Embed(title="✦  Account(s) Sent!", description=f"> **{amount}** account(s) slid into your DMs 📬", color=GOLD)
        sent.set_footer(text="⚡ MC Account Bot • Check your DMs!")
        await ctx.send(embed=sent)
    except discord.Forbidden:
        await ctx.send(content="⚠️ Couldn't DM you, here it is:", embed=embed)


@bot.command(name="stock")
async def prefix_stock(ctx: commands.Context):
    await ctx.send(embed=stock_embed(len(load_stock())))


@bot.command(name="sendaccount")
async def prefix_sendaccount(ctx: commands.Context, user: discord.Member = None, amount: int = 1):
    if not is_owner_id(ctx.author.id):
        return await ctx.send(embed=error_embed("No Permission", "Only owners can send accounts."))
    if not user:
        return await ctx.send(embed=error_embed("Missing User", "Usage: `!sendaccount @user <amount>`"))
    if amount < 1 or amount > 10:
        return await ctx.send(embed=error_embed("Invalid Amount", "Amount must be between 1 and 10."))
    status, accounts, embed = await core_sendaccount(user, ctx.author, amount)
    if status == "empty":
        return await ctx.send(embed=error_embed("Out of Stock", "There are no accounts available right now."))
    if status == "notenough":
        return await ctx.send(embed=error_embed("Not Enough Stock", f"Only **{accounts}** account(s) available."))
    try:
        await user.send(embed=embed)
    except discord.Forbidden:
        return await ctx.send(embed=error_embed("DM Failed", f"Couldn't DM {user.mention}. They may have DMs disabled."))
    confirm = discord.Embed(title="✦  Account(s) Sent!", color=PURPLE)
    confirm.add_field(name="Sent by", value=ctx.author.mention, inline=True)
    confirm.add_field(name="Recipient", value=user.mention, inline=True)
    confirm.add_field(name="Amount", value=f"`{amount}`", inline=True)
    confirm.set_footer(text="⚡ MC Account Bot")
    confirm.timestamp = discord.utils.utcnow()
    await ctx.send(content=f"{user.mention}", embed=confirm)


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
        e = discord.Embed(title="✦  Stock Updated", color=GOLD)
        e.add_field(name="Added", value=f"```{len(new_accounts)} accounts```", inline=True)
        e.add_field(name="Total Stock", value=f"```{len(merged)} accounts```", inline=True)
        e.set_footer(text=f"⚡ MC Account Bot • Uploaded by {ctx.author}")
        e.timestamp = discord.utils.utcnow()
        await ctx.send(embed=e)
    except Exception as ex:
        await ctx.send(embed=error_embed("Error", f"Could not read the file: {ex}"))


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
    save_stock(stock[amount:])
    await ctx.send(embed=success_embed("Stock Removed", f"Removed **{amount}** account(s). Remaining: **{len(stock) - amount}**"))


@bot.command(name="history")
async def prefix_history(ctx: commands.Context):
    if not is_owner_id(ctx.author.id):
        return await ctx.send(embed=error_embed("No Permission", "Only owners can view history."))
    data = load_history()
    if not data:
        e = discord.Embed(title="◈  History", description="> No accounts have been generated yet.", color=DARK_PURPLE)
        e.set_footer(text="⚡ MC Account Bot")
        return await ctx.send(embed=e)
    recent = data[-10:][::-1]
    lines = []
    for entry in recent:
        ts = int(entry.get("timestamp", 0))
        sent_by = f" *(sent by {entry['sent_by']})*" if entry.get("sent_by") else ""
        lines.append(f"<t:{ts}:R> — <@{entry['user_id']}>{sent_by}\n`{entry['email']}`")
    e = discord.Embed(title="◈  Generation History", description="\n\n".join(lines), color=DARK_PURPLE)
    e.set_footer(text=f"⚡ Total generated: {len(data)} • MC Account Bot")
    e.timestamp = discord.utils.utcnow()
    await ctx.send(embed=e)





@bot.command(name="help")
async def prefix_help(ctx: commands.Context):
    owner = is_owner_id(ctx.author.id)
    permitted = is_permitted(ctx.author.id)
    e = discord.Embed(title="[MC ACCOUNT BOT]", color=PURPLE)
    e.description = "> Your Minecraft account generator bot"
    if owner:
        e.add_field(name="Owner Commands", value="\u200b", inline=False)
        e.add_field(name="Stock", value="`!addstock` - Add accounts\n`!clearstock` - Wipe stock\n`!removestock <n>` - Remove N accounts\n`!stock` - Check count\n`/restock <mins> <n>` - Restock recent", inline=False)
        e.add_field(name="Generate", value="`!gen <n>` - Generate to DMs\n`!sendaccount @user <n>` - Send to user\n`/generate <n>` - Slash version\n`/sendaccount @user <n>` - Slash version", inline=False)
        e.add_field(name="Access", value="`/genaccess @user <time>` - Grant access\n`/revokeaccess @user` - Remove access\n`/listaccess` - List users", inline=False)
        e.add_field(name="Logs", value="`!history` / `/history` - Last 10 generated", inline=False)
    elif permitted:
        e.add_field(name="Your Commands", value="\u200b", inline=False)
        e.add_field(name="Generate", value="`!gen <n>` - Generate accounts (sent to DMs)\n`/generate <n>` - Slash version", inline=False)
        e.add_field(name="Stock", value="`!stock` - Check how many accounts are available", inline=False)
    else:
        e.add_field(name="Commands", value="\u200b", inline=False)
        e.add_field(name="Stock", value="`!stock` / `/checkstock` - Check available accounts", inline=False)
        e.add_field(name="Want Access?", value="Ask an owner to grant you access via `/genaccess`", inline=False)
    e.set_footer(text="MC Account Bot | <n> is optional, default is 1")
    e.timestamp = discord.utils.utcnow()
    await ctx.send(embed=e)

# ══════════════════════════════════════════════════════════════
#  BOT READY
# ══════════════════════════════════════════════════════════════

@bot.event
async def on_ready():
    await tree.sync()
    bot.loop.create_task(update_status())
    print(f"Logged in as {bot.user} | Slash commands synced.")


bot.run(TOKEN)
