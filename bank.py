"""The guild bank inventory: a ledger of what went in and out, and a live board that shows what's there.

Bankers record what actually landed when they mark a donation Received, and what left when they mark a
request Handed over; /bank add and /bank remove cover everything else (raids, corrections, a recount).
The board is one message the bot keeps edited: in the bank channel if setup named one, otherwise
under the request panel. Anyone can also ask /bank show or /bank find.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

import discord

from recipes import CATEGORIES, Recipes
from store import Settings, Store

log = logging.getLogger("castle.bank")

LINE = re.compile(r"""^\s*(?:(?P<q1>\d[\d,]*)\s*[x×]?\s+)?(?P<name>.+?)\s*(?:[x×]\s*(?P<q2>\d[\d,]*)|\(\s*(?P<q3>\d[\d,]*)\s*\)|[-–:]\s*(?P<q4>\d[\d,]*))?\s*$""", re.I)


def parse_lines(text: str, wiki: Recipes | None = None) -> list[tuple[str, int]]:
    """Turn what a banker typed into (item, quantity) pairs, one per line or comma.

    Accepts "12 Spider Silk", "12x Spider Silk", "Spider Silk x12", "Spider Silk (12)", "Spider Silk - 12"
    and plain "Spider Silk" (one). Item names get the wiki's spelling when known.
    """
    out: dict[str, int] = {}
    for raw in re.split(r"[\n,;]+", text):
        raw = raw.strip(" \t-•*")
        if not raw:
            continue
        m = LINE.match(raw)
        if not m:
            continue
        qty = next((g for g in (m["q1"], m["q2"], m["q3"], m["q4"]) if g), "1")
        name = m["name"].strip(" -:")
        if not name:
            continue
        if wiki:
            name = wiki.item_name(name)
        out[name] = out.get(name, 0) + int(qty.replace(",", ""))
    return list(out.items())


def format_lines(pairs: list[tuple[str, int]]) -> str:
    return "\n".join(f"{q} {n}" for n, q in pairs)


# ---------------------------------------------------------------- the board

def board_embeds(stock: list[tuple[str, int]], wiki: Recipes) -> list[discord.Embed]:
    """The inventory as embeds, one field per category, split over more embeds if it gets long."""
    by_cat: dict[str, list[str]] = {}
    for item, n in stock:
        by_cat.setdefault(wiki.category(item), []).append(f"{item} **×{n:,}**")
    total = sum(n for _, n in stock)
    head = discord.Embed(title="🏦 Guild Bank", color=0xD9AB3F,
                         description=(f"{len(stock)} kinds of item, {total:,} in all · updated <t:{int(datetime.now(timezone.utc).timestamp())}:R>"
                                      if stock else "Empty. Donations welcome: press **Bank donation** on the request panel."))
    head.set_footer(text="/bank find <item> · /bank show <category> · want something? Bank request on the panel")
    embeds = [head]
    for cat in CATEGORIES:
        lines = by_cat.get(cat)
        if not lines:
            continue
        chunks, cur = [], ""
        for line in lines:
            if len(cur) + len(line) + 1 > 1000:
                chunks.append(cur)
                cur = ""
            cur += ("\n" if cur else "") + line
        chunks.append(cur)
        for k, chunk in enumerate(chunks):
            name = cat if k == 0 else f"{cat} (cont.)"
            if len(embeds[-1].fields) >= 25 or len(embeds[-1]) + len(name) + len(chunk) > 5800:
                embeds.append(discord.Embed(color=0xD9AB3F))
            embeds[-1].add_field(name=name, value=chunk, inline=False)
    if len(embeds) > 10:
        embeds = embeds[:10]
        embeds[-1].set_footer(text="…and more. /bank find <item> searches everything.")
    return embeds


async def board_home(client: discord.Client, s: Settings) -> discord.abc.Messageable | None:
    """The channel the board lives in: the bank channel from setup, else the request panel's post."""
    target_id = s.bank_channel_id or s.panel_thread_id
    if not target_id:
        return None
    ch = client.get_channel(target_id)
    if ch is None:
        try:
            ch = await client.fetch_channel(target_id)
        except discord.HTTPException:
            return None
    if isinstance(ch, discord.Thread) and ch.archived:
        try:
            await ch.edit(archived=False)
        except discord.HTTPException:
            pass
    return ch if isinstance(ch, discord.abc.Messageable) else None


async def refresh_board(client: discord.Client, store: Store, wiki: Recipes, s: Settings) -> bool:
    """Redraw the live inventory message (creating it the first time). Returns whether it worked."""
    home = await board_home(client, s)
    if home is None:
        return False
    embeds = board_embeds(store.bank_stock(s.guild_id), wiki)
    try:
        if s.bank_message_id:
            try:
                msg = await home.fetch_message(s.bank_message_id)
                await msg.edit(embeds=embeds)
                return True
            except discord.NotFound:
                pass  # someone deleted it; post a fresh one
        msg = await home.send(embeds=embeds)
        s.bank_message_id = msg.id
        store.save_settings(s)
        return True
    except discord.HTTPException as e:
        log.warning("couldn't update the bank board: %s", e)
        return False


def history_lines(entries, wiki: Recipes | None = None) -> str:
    out = []
    for e in entries:
        sign = "+" if e.delta > 0 else "−"
        when = f"<t:{int(e.created_at)}:d>"
        why = f" · {e.note}" if e.note else ""
        out.append(f"{when} {sign}{abs(e.delta):,} {e.item} by <@{e.actor_id}>{why}")
    return "\n".join(out) if out else "Nothing recorded yet."
