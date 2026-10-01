#!/usr/bin/env python3
"""Castle Quartermaster: the guild's crafting, gathering and guild bank requests, as forum posts.

Setup (once):
  1. https://discord.com/developers/applications -> New Application -> Bot -> Reset Token, copy it.
  2. Put it in a file named .env next to this script:   DISCORD_TOKEN=xxxxx   GUILD_ID=<server id>
  3. A server admin opens the invite link (see ADMIN-SETUP.md) and runs /tickets setup.
  4. python bot.py
"""
from __future__ import annotations

import asyncio
import io
import logging
import os
from pathlib import Path

import discord
from discord import app_commands

import bank
import ui
from recipes import Recipes
from store import CANCELLED, Store

HERE = Path(__file__).resolve().parent
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("castle")

# What the bot needs inside the requests forum. Manage Channels only matters for creating the tags.
NEEDED = {
    "view_channel": "View Channel",
    "send_messages": "Send Messages (create posts)",
    "send_messages_in_threads": "Send Messages in Threads",
    "manage_threads": "Manage Threads (pin the panel, tag and close posts)",
    "embed_links": "Embed Links",
    "attach_files": "Attach Files (donation screenshots)",
    "read_message_history": "Read Message History",
}


def load_env() -> None:
    p = HERE / ".env"
    if p.exists():
        for line in p.read_text("utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"'))


store = Store()
recipes = Recipes()
ui.init(store, recipes)

intents = discord.Intents.none()
intents.guilds = True  # channels, roles and threads; no message content, no member list
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)
tickets = app_commands.Group(name="tickets", description="Crafting, gathering and guild bank requests", guild_only=True)


async def housekeeping() -> None:
    """Every few hours: refresh the recipe list, and bring back any open ticket Discord archived for being
    quiet a week, so open requests stay at the top of the forum instead of sinking out of view."""
    await client.wait_until_ready()
    while not client.is_closed():
        await asyncio.to_thread(recipes.refresh)
        try:
            saved = store.backup(HERE / "backups")
            if saved:
                log.info("daily backup written: %s", saved.name)
        except Exception as e:  # a failed backup must never stop the bot, but it should be loud in the log
            log.error("BACKUP FAILED: %s", e)
        for guild in client.guilds:
            for t in store.active(guild.id):
                thread = guild.get_thread(t.thread_id)
                if thread is not None:
                    continue  # get_thread only knows unarchived threads
                try:
                    thread = await guild.fetch_channel(t.thread_id)
                    if isinstance(thread, discord.Thread) and thread.archived:
                        await thread.edit(archived=False)
                except discord.NotFound:
                    log.warning("ticket #%d's post was deleted; closing it", t.id)
                    store.set_status(t.id, CANCELLED, reason="post deleted")
                except discord.HTTPException as e:
                    log.warning("couldn't check ticket #%d: %s", t.id, e)
        await asyncio.sleep(6 * 3600)


@client.event
async def setup_hook() -> None:
    # Buttons keep working after a restart: these two views answer clicks on every panel and ticket post.
    client.add_view(ui.Panel())
    client.add_view(ui.BankPanel())
    client.add_view(ui.Controls())
    tree.add_command(tickets)
    tree.add_command(bank_cmds)
    ids = guild_ids()
    if ids:
        # Commands registered per server show up instantly (global ones can lag), so register them only
        # in the servers listed in GUILD_ID and clear any old global copies.
        for gid in ids:
            tree.copy_global_to(guild=discord.Object(id=gid))
        tree.clear_commands(guild=None)
        await tree.sync()
        for gid in ids:
            await sync_guild(gid)
    else:
        await tree.sync()
    client.loop.create_task(housekeeping())


def guild_ids() -> list[int]:
    """GUILD_ID from .env: one server id, or several separated by commas (e.g. a test server and the real one)."""
    return [int(x) for x in os.environ.get("GUILD_ID", "").replace(" ", "").split(",") if x.isdigit()]


async def sync_guild(gid: int) -> None:
    try:
        await tree.sync(guild=discord.Object(id=gid))
    except discord.Forbidden:
        log.info("not in server %s yet; its commands will register when the bot is invited", gid)


@client.event
async def on_guild_join(guild: discord.Guild) -> None:
    log.info("joined %s (%s)", guild.name, guild.id)
    if guild.id in guild_ids():
        await sync_guild(guild.id)
    else:
        log.warning("%s isn't in GUILD_ID in .env, so /craft, /gather and /tickets won't show up there. "
                    "Add its id (comma-separated) and restart.", guild.id)


@client.event
async def on_ready() -> None:
    log.info("ready as %s in %d server(s): %s", client.user, len(client.guilds),
             ", ".join(f"{g.name} ({g.id})" for g in client.guilds))


# ---------------------------------------------------------------- /tickets setup

async def ensure_tags(forum: discord.ForumChannel, kinds: tuple[str, ...]) -> list[str]:
    """Create any missing kind tags (Crafting, Gathering, ...) and status tags (Open, Claimed, ...) on a forum.
    Returns the ones we couldn't create."""
    have = {t.name.lower() for t in forum.available_tags}
    wanted = [ui.KINDS[k].tag for k in kinds] + list(ui.STATUS_TAGS.values())
    failed = []
    for name in wanted:
        if name.lower() in have:
            continue
        try:
            await forum.create_tag(name=name, emoji=discord.PartialEmoji(name=ui.TAG_EMOJI[name]), moderated=True)
        except discord.HTTPException:
            failed.append(name)
    return failed


async def post_panel(forum: discord.ForumChannel, old_thread_id: int | None, title: str, text: str,
                     view: discord.ui.View) -> tuple[discord.Thread, list[str]]:
    """Put a button panel in a pinned post at the top of a forum (reusing the old one if it's there).
    Not locked: Discord lets only moderators press buttons in a locked post."""
    problems = []
    thread = forum.guild.get_thread(old_thread_id) if old_thread_id else None
    if thread is None and old_thread_id:
        try:
            thread = await forum.guild.fetch_channel(old_thread_id)
        except discord.HTTPException:
            thread = None
    if isinstance(thread, discord.Thread) and thread.parent_id == forum.id:
        try:
            msg = await thread.fetch_message(thread.id)  # a forum post's first message shares the post's id
            await msg.edit(content=text, view=view)
        except discord.HTTPException:
            thread = None
    if not isinstance(thread, discord.Thread) or thread.parent_id != forum.id:
        posted = await forum.create_thread(name=title, content=text, view=view)
        thread = posted.thread
    try:
        await thread.edit(pinned=True, locked=False, archived=False)
    except discord.HTTPException:
        problems.append(f"couldn't pin the panel post in {forum.mention} (the bot needs Manage Threads)")
    return thread, problems


def missing_perms(forum: discord.ForumChannel) -> list[str]:
    perms = forum.permissions_for(forum.guild.me)
    return [label for attr, label in NEEDED.items() if not getattr(perms, attr)]


@tickets.command(name="setup", description="Admins: choose the request forums and the roles that handle each kind")
@app_commands.describe(
    forum="Forum for crafting and gathering requests (the panel goes at the top)",
    crafter="Role pinged for crafting requests, e.g. Castle Crafter",
    gatherer="Role pinged for gathering requests, e.g. Castle Gatherer",
    banker="Role that handles bank donations and requests",
    bank_forum="Forum for bank donations and requests, with the bank panel and inventory at the top (optional)",
    officer="Role that can act on any ticket and open guild requisitions (optional)",
    bank_channel="Text channel for the inventory board instead of the bank panel (optional)",
)
@app_commands.default_permissions(manage_guild=True)
async def setup(i: discord.Interaction, forum: discord.ForumChannel, crafter: discord.Role, gatherer: discord.Role,
                banker: discord.Role, bank_forum: discord.ForumChannel | None = None,
                officer: discord.Role | None = None, bank_channel: discord.TextChannel | None = None) -> None:
    await i.response.defer(ephemeral=True, thinking=True)
    for f in (forum, bank_forum):
        if f and (missing := missing_perms(f)):
            await i.followup.send("I'm missing these permissions in " + f.mention + ":\n"
                                  + "\n".join(f"• {m}" for m in missing)
                                  + "\n\nGive the bot's role those in the forum's permission settings, then run this again.",
                                  ephemeral=True)
            return

    s = store.settings(i.guild_id)
    s.forum_id, s.crafter_role, s.gatherer_role, s.banker_role = forum.id, crafter.id, gatherer.id, banker.id
    s.officer_role = officer.id if officer else None
    s.bank_forum_id = bank_forum.id if bank_forum and bank_forum.id != forum.id else None
    if bank_channel and bank_channel.id != s.bank_channel_id:
        s.bank_channel_id, s.bank_message_id = bank_channel.id, None  # the board moves; post a fresh one there
    if not bank_channel and s.bank_channel_id:
        s.bank_channel_id, s.bank_message_id = None, None

    notes = []
    plan = [(forum, ("craft", "gather") if s.bank_forum_id else tuple(ui.KINDS))]
    if s.bank_forum_id:
        plan.append((bank_forum, ("donate", "bank")))
    for f, kinds in plan:
        failed_tags = await ensure_tags(f, kinds)
        if failed_tags:
            notes.append(f"Couldn't create the tags {', '.join(failed_tags)} in {f.mention}. Either create them by hand "
                         "(Edit Channel → Tags), or let the bot's role *Manage Channel* on that forum and run setup again. "
                         "Tickets work without them; the tags just make the list easy to filter.")

    if s.bank_forum_id:
        thread, problems = await post_panel(forum, s.panel_thread_id, ui.PANEL_TITLE, ui.PANEL_TEXT, ui.Panel())
        notes += problems
        s.panel_thread_id = thread.id
        bank_thread, problems = await post_panel(bank_forum, s.bank_panel_thread_id, ui.BANK_PANEL_TITLE,
                                                 ui.BANK_PANEL_TEXT, ui.BankPanel())
        notes += problems
        if bank_thread.id != s.bank_panel_thread_id:
            s.bank_message_id = None if not s.bank_channel_id else s.bank_message_id
        s.bank_panel_thread_id = bank_thread.id
    else:
        # one forum for everything: both button sets on the same pinned post
        both = ui.Panel()
        for item in ui.BankPanel().children:
            both.add_item(item)
        text = ui.PANEL_TEXT.replace("**Crafting & gathering requests.**", "**Castle requests.**").replace(
            "🌿 **Gathering**: you need materials farmed.\n",
            "🌿 **Gathering**: you need materials farmed.\n"
            "📦 **Bank donation**: you're giving something to the guild bank. Include a screenshot so we can plan the space.\n"
            "🏦 **Bank request**: you'd like something from the guild bank.\n")
        thread, problems = await post_panel(forum, s.panel_thread_id, ui.PANEL_TITLE, text, both)
        notes += problems
        s.panel_thread_id = thread.id
        s.bank_panel_thread_id = None
    store.save_settings(s)
    if not await bank.refresh_board(client, store, recipes, s):
        notes.append("Couldn't post the bank inventory board" + (f" in {bank_channel.mention}" if bank_channel else "")
                     + ". Check the bot can send messages and embeds there, then run `/bank board`.")

    perms = forum.permissions_for(forum.guild.me)
    unpingable = [r.mention for r in (crafter, gatherer, banker)
                  if not r.mentionable and not perms.mention_everyone]
    if unpingable:
        notes.append("I can't ping " + ", ".join(unpingable) + ". Turn on *Allow anyone to @mention this role* "
                     "in each role's settings, or give the bot *Mention All Roles*.")

    where = f"Crafting and gathering go to {forum.mention}"
    where += f"; the bank lives in {bank_forum.mention}" if s.bank_forum_id else " along with the bank"
    await i.followup.send(
        f"All set. {where}.\n"
        f"🔨 Crafting → {crafter.mention} · 🌿 Gathering → {gatherer.mention} · 📦🏦 Bank → {banker.mention}"
        + (f" · Officers: {officer.mention}" if officer else "")
        + ("\n\n" + "\n".join(f"⚠️ {n}" for n in notes) if notes else ""),
        ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


# ---------------------------------------------------------------- /tickets mine, /tickets open

def ticket_lines(ts) -> str:
    return "\n".join(f"• <#{t.thread_id}> · {ui.status_line(t)}" for t in ts)


@tickets.command(name="mine", description="Your open requests")
async def mine(i: discord.Interaction) -> None:
    ts = store.mine(i.guild_id, i.user.id)
    text = ticket_lines(ts) if ts else "You don't have any open requests."
    await i.response.send_message(text[:2000], ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


@tickets.command(name="queue", description="Open requests waiting on someone")
@app_commands.describe(kind="Only one kind of request")
@app_commands.choices(kind=[app_commands.Choice(name=f"{k.emoji} {k.name}", value=key) for key, k in ui.KINDS.items()])
async def queue(i: discord.Interaction, kind: app_commands.Choice[str] | None = None) -> None:
    ts = store.active(i.guild_id, (kind.value,) if kind else None)
    if not ts:
        await i.response.send_message("Nothing open. 🎉", ephemeral=True)
        return
    text = ticket_lines(ts[:40]) + (f"\n…and {len(ts) - 40} more" if len(ts) > 40 else "")
    await i.response.send_message(text[:2000], ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


# ---------------------------------------------------------------- /craft, /gather (wiki autocomplete)

@tree.command(name="craft", description="Ask the crafters to make something; the item box searches the wiki's recipes")
@app_commands.guild_only()
@app_commands.describe(item="Start typing an item name", quantity="How many (you can change it on the form)")
async def craft_cmd(i: discord.Interaction, item: str, quantity: app_commands.Range[int, 1, 9999] = 1) -> None:
    if await ui.ready(i):
        await i.response.send_modal(ui.CraftForm(i.user.id, item=item, quantity=str(quantity)))


@craft_cmd.autocomplete("item")
async def craft_items(i: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    return [app_commands.Choice(name=label[:100], value=name[:100]) for label, name in recipes.craft_choices(current)]


@tree.command(name="gather", description="Ask the gatherers for materials; the item box searches the wiki's recipes")
@app_commands.guild_only()
@app_commands.describe(item="Start typing a material name", quantity="How many (you can change it on the form)")
async def gather_cmd(i: discord.Interaction, item: str, quantity: app_commands.Range[int, 1, 9999] | None = None) -> None:
    if s := await ui.ready(i):
        await i.response.send_modal(ui.GatherForm(i.user.id, ui.is_officer(i.user, s), item=item,
                                                  quantity=str(quantity) if quantity else ""))


@gather_cmd.autocomplete("item")
async def gather_items(i: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    return [app_commands.Choice(name=name[:100], value=name[:100]) for name in recipes.material_choices(current)]


# ---------------------------------------------------------------- /bank

bank_cmds = app_commands.Group(name="bank", description="What's in the guild bank", guild_only=True)
CATEGORY_CHOICES = [app_commands.Choice(name=c, value=c) for c in bank.CATEGORIES]


def _wiki_choices(i: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    names = store.bank_items_like(i.guild_id, current) if i.guild_id else []
    names += [n for n in recipes.item_choices(current) if n not in names]
    return [app_commands.Choice(name=n[:100], value=n[:100]) for n in names[:25]]


@bank_cmds.command(name="show", description="The bank inventory, optionally one category")
@app_commands.choices(category=CATEGORY_CHOICES)
async def bank_show(i: discord.Interaction, category: app_commands.Choice[str] | None = None) -> None:
    stock = store.bank_stock(i.guild_id)
    if category:
        stock = [(item, n) for item, n in stock if recipes.category(item) == category.value]
        if not stock:
            return await i.response.send_message(f"Nothing in {category.value} right now.", ephemeral=True)
    await i.response.send_message(embeds=bank.board_embeds(stock, recipes), ephemeral=True)


@bank_cmds.command(name="find", description="How many of an item the bank has, and its recent history")
@app_commands.describe(item="Start typing an item name")
async def bank_find(i: discord.Interaction, item: str) -> None:
    name = recipes.item_name(item)
    n = store.bank_count(i.guild_id, name)
    e = discord.Embed(title=name, color=0xD9AB3F, description=f"**{n:,}** in the bank" if n > 0 else "None in the bank right now.")
    e.add_field(name="Section", value=recipes.category(name))
    icon = recipes.icon(name)
    if icon:
        e.set_thumbnail(url=icon)
    hist = store.bank_history(i.guild_id, name, limit=6)
    if hist:
        e.add_field(name="Recent", value=bank.history_lines(hist)[:1024], inline=False)
    await i.response.send_message(embed=e, ephemeral=True)


@bank_find.autocomplete("item")
async def bank_find_ac(i: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    return _wiki_choices(i, current)


async def _bank_staff(i: discord.Interaction):
    s = store.settings(i.guild_id)
    if not ui.is_staff(i.user, s, "bank"):
        await i.response.send_message("Only bankers and officers can change the inventory.", ephemeral=True)
        return None
    return s


@bank_cmds.command(name="add", description="Bankers: record items going into the bank")
@app_commands.describe(item="Item name", quantity="How many", note="Why (optional), e.g. raid loot")
async def bank_add(i: discord.Interaction, item: str, quantity: app_commands.Range[int, 1, 1_000_000], note: str = "") -> None:
    if s := await _bank_staff(i):
        name = recipes.item_name(item)
        n = store.bank_change(i.guild_id, name, quantity, i.user.id, note=note)
        await i.response.send_message(f"📦 +{quantity:,} {name}. The bank now has **{n:,}**.", ephemeral=True)
        await bank.refresh_board(client, store, recipes, s)


@bank_cmds.command(name="remove", description="Bankers: record items leaving the bank")
@app_commands.describe(item="Item name", quantity="How many", note="Why (optional), e.g. raid consumables")
async def bank_remove(i: discord.Interaction, item: str, quantity: app_commands.Range[int, 1, 1_000_000], note: str = "") -> None:
    if s := await _bank_staff(i):
        name = recipes.item_name(item)
        n = store.bank_change(i.guild_id, name, -quantity, i.user.id, note=note)
        warn = " (that's more than was recorded; `/bank set` fixes the count)" if n < 0 else ""
        await i.response.send_message(f"📤 −{quantity:,} {name}. The bank now has **{max(n, 0):,}**{warn}.", ephemeral=True)
        await bank.refresh_board(client, store, recipes, s)


@bank_cmds.command(name="set", description="Bankers: set an item's count to what's actually there (after a recount)")
@app_commands.describe(item="Item name", quantity="How many are really in the bank", note="Why (optional)")
async def bank_set(i: discord.Interaction, item: str, quantity: app_commands.Range[int, 0, 1_000_000], note: str = "recount") -> None:
    if s := await _bank_staff(i):
        name = recipes.item_name(item)
        delta = quantity - store.bank_count(i.guild_id, name)
        if delta:
            store.bank_change(i.guild_id, name, delta, i.user.id, note=note)
        await i.response.send_message(f"🧮 {name} set to **{quantity:,}** ({delta:+,}).", ephemeral=True)
        await bank.refresh_board(client, store, recipes, s)


@bank_cmds.command(name="history", description="Recent bank movements, optionally for one item")
@app_commands.describe(item="Item name (optional)")
async def bank_history(i: discord.Interaction, item: str | None = None) -> None:
    name = recipes.item_name(item) if item else None
    text = bank.history_lines(store.bank_history(i.guild_id, name, limit=20))
    e = discord.Embed(title=f"🏦 History: {name}" if name else "🏦 Recent bank movements", description=text[:4000], color=0xD9AB3F)
    await i.response.send_message(embed=e, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


@bank_cmds.command(name="board", description="Bankers: redraw the live inventory board")
async def bank_board(i: discord.Interaction) -> None:
    if s := await _bank_staff(i):
        ok = await bank.refresh_board(client, store, recipes, s)
        await i.response.send_message("Board updated." if ok else "Couldn't post the board; check the bot can send "
                                      "messages and embeds in the bank channel (or run `/tickets setup`).", ephemeral=True)


@bank_cmds.command(name="export", description="Bankers: download the inventory and the full history as spreadsheets")
async def bank_export(i: discord.Interaction) -> None:
    if await _bank_staff(i):
        inv, led = bank.export_csv(store, recipes, i.guild_id)
        day = discord.utils.utcnow().strftime("%Y-%m-%d")
        files = [discord.File(io.BytesIO(inv.encode("utf-8-sig")), filename=f"bank-inventory-{day}.csv"),
                 discord.File(io.BytesIO(led.encode("utf-8-sig")), filename=f"bank-ledger-{day}.csv")]
        await i.response.send_message("Here's the bank as of now. The ledger has every movement ever recorded, so it's "
                                      "enough to rebuild the inventory. Keep a copy somewhere safe.", files=files, ephemeral=True)


for _cmd in (bank_add, bank_remove, bank_set, bank_history):
    _cmd.autocomplete("item")(bank_find_ac)


@tree.error
async def on_app_command_error(i: discord.Interaction, error: app_commands.AppCommandError) -> None:
    log.exception("command failed", exc_info=error)
    text = "Something went wrong there. The error is in the bot's log."
    if i.response.is_done():
        await i.followup.send(text, ephemeral=True)
    else:
        await i.response.send_message(text, ephemeral=True)


def main() -> None:
    load_env()
    token = os.environ.get("DISCORD_TOKEN")
    if not token:
        raise SystemExit("No DISCORD_TOKEN. Put it in a .env file next to bot.py (see README).")
    client.run(token, log_handler=None)


if __name__ == "__main__":
    main()
