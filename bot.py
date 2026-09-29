#!/usr/bin/env python3
"""Castle Tickets: crafting, gathering and guild bank requests as forum posts.

Setup (once):
  1. https://discord.com/developers/applications -> New Application -> Bot -> Reset Token, copy it.
  2. Put it in a file named .env next to this script:   DISCORD_TOKEN=xxxxx   GUILD_ID=<server id>
  3. A server admin opens the invite link (see ADMIN-SETUP.md) and runs /tickets setup.
  4. python bot.py
"""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

import discord
from discord import app_commands

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
    client.add_view(ui.Controls())
    tree.add_command(tickets)
    guild_id = os.environ.get("GUILD_ID")
    if guild_id:
        g = discord.Object(id=int(guild_id))
        tree.copy_global_to(guild=g)
        tree.clear_commands(guild=None)
        await tree.sync(guild=g)
        await tree.sync()  # clears any old global copies
    else:
        await tree.sync()
    client.loop.create_task(housekeeping())


@client.event
async def on_ready() -> None:
    log.info("ready as %s in %d server(s)", client.user, len(client.guilds))


# ---------------------------------------------------------------- /tickets setup

async def ensure_tags(forum: discord.ForumChannel) -> list[str]:
    """Create any missing Crafting/Gathering/... and Open/Claimed/... tags. Returns the ones we couldn't create."""
    have = {t.name.lower() for t in forum.available_tags}
    wanted = [k.tag for k in ui.KINDS.values()] + list(ui.STATUS_TAGS.values())
    failed = []
    for name in wanted:
        if name.lower() in have:
            continue
        try:
            await forum.create_tag(name=name, emoji=discord.PartialEmoji(name=ui.TAG_EMOJI[name]), moderated=True)
        except discord.HTTPException:
            failed.append(name)
    return failed


async def post_panel(forum: discord.ForumChannel, old_thread_id: int | None) -> tuple[discord.Thread, list[str]]:
    """Put the button panel in a pinned, locked post at the top of the forum (reusing the old one if it's there)."""
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
            await msg.edit(content=ui.PANEL_TEXT, view=ui.Panel())
        except discord.HTTPException:
            thread = None
    if not isinstance(thread, discord.Thread) or thread.parent_id != forum.id:
        posted = await forum.create_thread(name=ui.PANEL_TITLE, content=ui.PANEL_TEXT, view=ui.Panel())
        thread = posted.thread
    try:
        await thread.edit(pinned=True, locked=True, archived=False)
    except discord.HTTPException:
        problems.append("couldn't pin and lock the panel post (the bot needs Manage Threads)")
    return thread, problems


@tickets.command(name="setup", description="Admins: choose the requests forum and the roles that handle each kind")
@app_commands.describe(
    forum="Forum channel where requests get posted (the panel goes at the top)",
    crafter="Role pinged for crafting requests, e.g. Castle Crafter",
    gatherer="Role pinged for gathering requests, e.g. Castle Gatherer",
    banker="Role that handles bank donations and requests",
    officer="Role that can act on any ticket and open guild requisitions (optional)",
)
@app_commands.default_permissions(manage_guild=True)
async def setup(i: discord.Interaction, forum: discord.ForumChannel, crafter: discord.Role, gatherer: discord.Role,
                banker: discord.Role, officer: discord.Role | None = None) -> None:
    await i.response.defer(ephemeral=True, thinking=True)
    me = forum.guild.me
    perms = forum.permissions_for(me)
    missing = [label for attr, label in NEEDED.items() if not getattr(perms, attr)]
    if missing:
        await i.followup.send("I'm missing these permissions in " + forum.mention + ":\n"
                              + "\n".join(f"• {m}" for m in missing)
                              + "\n\nGive the bot's role those in the forum's permission settings, then run this again.",
                              ephemeral=True)
        return

    s = store.settings(i.guild_id)
    s.forum_id, s.crafter_role, s.gatherer_role, s.banker_role = forum.id, crafter.id, gatherer.id, banker.id
    s.officer_role = officer.id if officer else None

    notes = []
    failed_tags = await ensure_tags(forum)
    if failed_tags:
        notes.append("Couldn't create the forum tags " + ", ".join(failed_tags) + ". Either create them by hand "
                     "(Edit Channel → Tags), or let the bot's role *Manage Channel* on this forum and run setup again. "
                     "Tickets work without them; the tags just make the list easy to filter.")
    thread, problems = await post_panel(forum, s.panel_thread_id)
    s.panel_thread_id = thread.id
    store.save_settings(s)
    notes += problems

    unpingable = [r.mention for r in (crafter, gatherer, banker)
                  if not r.mentionable and not perms.mention_everyone]
    if unpingable:
        notes.append("I can't ping " + ", ".join(unpingable) + ". Turn on *Allow anyone to @mention this role* "
                     "in each role's settings, or give the bot *Mention All Roles*.")

    await i.followup.send(
        f"All set. Requests go to {forum.mention}; the panel is here: {thread.mention}\n"
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
