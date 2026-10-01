"""Everything members click: the request panel, the four forms, and the buttons on each ticket post.

Flow: panel button -> form (modal) -> the bot opens a forum post in the requests forum, pinging the role
that handles that kind of ticket -> staff press Claim / Done on the post -> the requester gets a DM at each
step, and the post's tags (Open / Claimed / Done / Cancelled) keep the forum list readable at a glance.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

import discord
from discord import ui

import bank
import recipes as recipe_mod
from recipes import Recipes
from store import ACTIVE, CANCELLED, CLAIMED, DONE, OPEN, Settings, Store, Ticket

log = logging.getLogger("castle.ui")

# Set by bot.py at startup.
store: Store = None  # type: ignore[assignment]
recipes: Recipes = None  # type: ignore[assignment]


def init(s: Store, r: Recipes) -> None:
    global store, recipes
    store, recipes = s, r


# ---------------------------------------------------------------- ticket kinds

@dataclass(frozen=True)
class Kind:
    name: str           # "Crafting"
    emoji: str
    role: str           # which Settings attribute holds the role that handles it
    tag: str            # forum tag name
    claim: str = "Claim"
    done: str = "Mark done"
    done_word: str = "done"
    staff_word: str = "staff"
    claimed_word: str = "Claimed"
    denied_word: str = "Cancelled"


KINDS: dict[str, Kind] = {
    "craft": Kind("Crafting", "🔨", "crafter_role", "Crafting", done="Crafted & delivered",
                  done_word="crafted and delivered", staff_word="crafter"),
    "gather": Kind("Gathering", "🌿", "gatherer_role", "Gathering", done="Gathered & delivered",
                   done_word="gathered and delivered", staff_word="gatherer"),
    "donate": Kind("Bank donation", "📦", "banker_role", "Bank Donation", done="Received",
                   done_word="received (thank you!)", staff_word="banker"),
    "bank": Kind("Bank request", "🏦", "banker_role", "Bank Request", claim="Approve", done="Handed over",
                 done_word="handed over", staff_word="banker", claimed_word="Approved", denied_word="Denied"),
}
STATUS_TAGS = {OPEN: "Open", CLAIMED: "Claimed", DONE: "Done", CANCELLED: "Cancelled"}
TAG_EMOJI = {"Crafting": "🔨", "Gathering": "🌿", "Bank Donation": "📦", "Bank Request": "🏦",
             "Open": "🟡", "Claimed": "🔵", "Done": "✅", "Cancelled": "⚪"}
COLORS = {OPEN: 0xF1C40F, CLAIMED: 0x3498DB, DONE: 0x2ECC71, CANCELLED: 0x95A5A6}

NEEDED_BY = ["ASAP", "Before next raid", "This week", "No rush"]
PURPOSES = {
    "self": "For myself",
    "craft": "For a crafting request",
    "guild_raid": "Guild: raid consumables",
    "guild_equip": "Guild: equipment",
    "other": "Other (explain in the post)",
}
OFFICER_PURPOSES = ("guild_raid", "guild_equip")


# ---------------------------------------------------------------- permissions

def _has(member: discord.abc.User, role_id: int | None) -> bool:
    return bool(role_id) and isinstance(member, discord.Member) and member.get_role(role_id) is not None


def is_officer(member: discord.abc.User, s: Settings) -> bool:
    if isinstance(member, discord.Member) and member.guild_permissions.manage_guild:
        return True
    return _has(member, s.officer_role)


def is_staff(member: discord.abc.User, s: Settings, kind: str) -> bool:
    return is_officer(member, s) or _has(member, getattr(s, KINDS[kind].role))


# ---------------------------------------------------------------- how a ticket looks

def _clip(s: str, n: int) -> str:
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1] + "…"


def _clip_lines(s: str, n: int) -> str:
    """Like _clip but keeps line breaks, dropping whole lines that don't fit."""
    out = ""
    for line in s.split("\n"):
        if len(out) + len(line) + 1 > n - 2:
            return out + "\n…"
        out += ("\n" if out else "") + line
    return out


def _span(hours: int) -> str:
    if hours % 24 == 0:
        return "a day" if hours == 24 else f"{hours // 24} days"
    return "an hour" if hours == 1 else f"{hours} hours"


def title(t: Ticket) -> str:
    k, f = KINDS[t.kind], t.fields
    if t.kind in ("craft", "gather"):
        what = f"{f.get('quantity', '')}x {f.get('item', '')}" if f.get("quantity") else f.get("item", "")
    elif t.kind == "donate":
        what = f"Donation: {f.get('what', '')}"
    else:
        what = f"Request: {f.get('what', '')}"
    return _clip(f"{k.emoji} {what} · {t.character}", 100)


def status_line(t: Ticket) -> str:
    k = KINDS[t.kind]
    who = f" by <@{t.claimer_id}>" if t.claimer_id else ""
    if t.status == OPEN:
        return f"🟡 Open, waiting for a {k.staff_word}"
    if t.status == CLAIMED:
        return f"🔵 {k.claimed_word}{who}"
    if t.status == DONE:
        return f"✅ Done{who}"
    denied = t.claimer_id and t.claimer_id != t.requester_id
    word = k.denied_word if denied else "Cancelled"
    return f"⚪ {word}" + (f": {t.close_reason}" if t.close_reason else "")


def embed(t: Ticket) -> discord.Embed:
    k, f = KINDS[t.kind], t.fields
    e = discord.Embed(title=f"{k.emoji} {k.name} #{t.id}", color=COLORS.get(t.status, 0x95A5A6),
                      timestamp=datetime.fromtimestamp(t.created_at, tz=timezone.utc))
    if t.kind in ("craft", "gather"):
        e.add_field(name="Item" if t.kind == "craft" else "Item(s)", value=_clip(f.get("item", "?"), 1000), inline=False)
        e.add_field(name="Quantity", value=f.get("quantity", "?"))
        e.add_field(name="Needed by", value=f.get("needed_by", "?"))
        if t.kind == "craft":
            e.add_field(name="Has the mats", value="Yes")
        else:
            e.add_field(name="For", value=PURPOSES.get(f.get("purpose", ""), f.get("purpose", "?")))
            fc = f.get("for_craft")
            if fc:
                e.add_field(name="Gathering for a craft", value=f"{fc.get('quantity', '')}x {fc.get('item', '')}", inline=False)
        if f.get("raw"):
            e.add_field(name="⛏️ What to actually gather", value=_clip(f["raw"], 1000), inline=False)
        if f.get("buy"):
            e.add_field(name="🛒 Sold by vendors (buy these, don't farm them)", value=_clip_lines(f["buy"], 1000), inline=False)
        if f.get("crafted_first"):
            e.add_field(name="🧵 Crafted along the way", value=_clip(f["crafted_first"], 1000), inline=False)
        if f.get("recipe"):
            e.add_field(name=f"📖 Recipe: {f.get('recipe_name', '')}", value=_clip(f["recipe"], 1000), inline=False)
    elif t.kind == "donate":
        e.add_field(name="Donating", value=_clip(f.get("what", "?"), 1000), inline=False)
    else:
        e.add_field(name="Requesting", value=_clip(f.get("what", "?"), 1000), inline=False)
        if f.get("why"):
            e.add_field(name="What it's for", value=_clip(f["why"], 1000), inline=False)
    e.add_field(name="Character", value=t.character or "?")
    e.add_field(name="Requested by", value=f"<@{t.requester_id}>")
    e.add_field(name="Status", value=status_line(t), inline=False)
    return e


def forum_tags(forum: discord.ForumChannel, t: Ticket) -> list[discord.ForumTag]:
    wanted = {KINDS[t.kind].tag.lower(), STATUS_TAGS[t.status].lower()}
    return [tag for tag in forum.available_tags if tag.name.lower() in wanted]


# ---------------------------------------------------------------- form building blocks

def _text(label: str, *, default: str | None = None, placeholder: str | None = None, max_length: int = 100,
          paragraph: bool = False, required: bool = True, description: str | None = None) -> tuple[ui.Label, ui.TextInput]:
    box = ui.TextInput(style=discord.TextStyle.paragraph if paragraph else discord.TextStyle.short,
                       default=default or None, placeholder=placeholder, max_length=max_length, required=required)
    return ui.Label(text=label, description=description, component=box), box


def _choice(label: str, options: dict[str, str], *, default: str | None = None,
            description: str | None = None) -> tuple[ui.Label, ui.Select]:
    sel = ui.Select(options=[discord.SelectOption(label=v, value=k, default=k == default) for k, v in options.items()])
    return ui.Label(text=label, description=description, component=sel), sel


def _character_box(user_id: int, default: str = "") -> tuple[ui.Label, ui.TextInput]:
    return _text("Your character name", default=default or store.character(user_id), max_length=40,
                 placeholder="Who should we trade or mail in game?")


# ---------------------------------------------------------------- the four forms

class CraftForm(ui.Modal):
    def __init__(self, user_id: int, *, item: str = "", quantity: str = "1", needed_by: str | None = None,
                 has_mats: str | None = None, character: str = "") -> None:
        super().__init__(title="Crafting request")
        lbl, self.item = _text("Item", default=item, placeholder="e.g. Iron Rivets")
        self.add_item(lbl)
        lbl, self.quantity = _text("Quantity", default=quantity, max_length=20)
        self.add_item(lbl)
        lbl, self.needed_by = _choice("When do you need it by?", {n: n for n in NEEDED_BY}, default=needed_by)
        self.add_item(lbl)
        lbl, self.mats = _choice("Do you have the materials?",
                                 {"yes": "Yes, I have all the mats", "no": "No, I need them gathered"}, default=has_mats,
                                 description="No mats? We'll help you open a gathering request instead.")
        self.add_item(lbl)
        lbl, self.character = _character_box(user_id, character)
        self.add_item(lbl)

    async def on_submit(self, i: discord.Interaction) -> None:
        character = self.character.value.strip()
        store.remember_character(i.user.id, character)
        fields = {"item": self.item.value.strip(), "quantity": self.quantity.value.strip(),
                  "needed_by": self.needed_by.values[0]}
        recipe = recipes.find(fields["item"])
        if recipe:
            fields["item"] = recipe["name"]  # "iron rivet" -> the wiki's "Iron Rivets"
        qty = recipe_mod.parse_quantity(fields["quantity"])
        if self.mats.values[0] == "no":
            await send_to_gathering(i, fields, character, recipe, qty)
            return
        if recipe:
            fields["recipe_name"] = recipe["name"]
            fields["recipe"] = recipe_mod.summary(recipe, qty)
        await open_ticket(i, "craft", fields, character)


class GatherForm(ui.Modal):
    def __init__(self, user_id: int, officer: bool, *, item: str = "", quantity: str = "", needed_by: str | None = None,
                 purpose: str | None = None, for_craft: dict | None = None, character: str = "") -> None:
        super().__init__(title="Gathering request")
        self.for_craft = for_craft
        lbl, self.item = _text("What do you need gathered?", default=item, paragraph=True, max_length=1000,
                               placeholder="e.g. Copper Ore")
        self.add_item(lbl)
        lbl, self.quantity = _text("Quantity", default=quantity, max_length=20)
        self.add_item(lbl)
        lbl, self.needed_by = _choice("When do you need it by?", {n: n for n in NEEDED_BY}, default=needed_by)
        self.add_item(lbl)
        purposes = {k: v for k, v in PURPOSES.items() if officer or k not in OFFICER_PURPOSES}
        lbl, self.purpose = _choice("What do you need it for?", purposes, default=purpose,
                                    description=None if officer else "Guild requisitions are opened by officers.")
        self.add_item(lbl)
        lbl, self.character = _character_box(user_id, character)
        self.add_item(lbl)

    async def on_submit(self, i: discord.Interaction) -> None:
        character = self.character.value.strip()
        store.remember_character(i.user.id, character)
        item = self.item.value.strip()
        fields = {"item": recipes.materials.get(recipe_mod.norm(item), item), "quantity": self.quantity.value.strip(),
                  "needed_by": self.needed_by.values[0], "purpose": self.purpose.values[0]}
        if self.for_craft:
            fields["for_craft"] = self.for_craft
            top = recipes.find(self.for_craft.get("item", ""))
            if top:
                b = recipes.breakdown(top, recipe_mod.parse_quantity(self.for_craft.get("quantity", "")))
                if b.made:
                    fields["crafted_first"] = b.made_line()
        else:
            # someone asked for a thing that is itself crafted (canvas, bars): show what it's made from
            made = recipes.find(item) if "\n" not in item else None
            if made:
                b = recipes.breakdown(made, recipe_mod.parse_quantity(fields["quantity"]))
                fields["raw"] = f"{made['name']} is crafted ({made.get('skill', '?')}). Raw materials: " + ", ".join(b.raw_lines())
                if b.made:
                    fields["crafted_first"] = b.made_line()
        bought = []
        for name, _ in bank.parse_lines(item, recipes):
            sellers = recipes.vendors(name)
            if sellers:
                bought.append(f"**{name}**: {', '.join(sellers)}")
        if bought:
            fields["buy"] = "\n".join(bought)
        await open_ticket(i, "gather", fields, character)


class DonateForm(ui.Modal):
    def __init__(self, user_id: int) -> None:
        super().__init__(title="Guild bank donation")
        lbl, self.what = _text("What are you donating?", paragraph=True, max_length=1000,
                               placeholder="e.g. 3 stacks of Silk, 12 Minor Healing Potions")
        self.add_item(lbl)
        self.screenshot = ui.FileUpload(required=True, min_values=1, max_values=5)
        self.add_item(ui.Label(text="Screenshot of what you're donating", component=self.screenshot,
                               description="So we know how much bank space it needs."))
        lbl, self.character = _character_box(user_id)
        self.add_item(lbl)

    async def on_submit(self, i: discord.Interaction) -> None:
        character = self.character.value.strip()
        store.remember_character(i.user.id, character)
        await i.response.defer(ephemeral=True, thinking=True)
        files = []
        for a in self.screenshot.values:
            try:
                files.append(await a.to_file())
            except discord.HTTPException as e:
                log.warning("screenshot download failed: %s", e)
        await open_ticket(i, "donate", {"what": self.what.value.strip()}, character, files=files)


class BankRequestForm(ui.Modal):
    def __init__(self, user_id: int) -> None:
        super().__init__(title="Guild bank request")
        lbl, self.what = _text("What are you requesting?", paragraph=True, max_length=1000)
        self.add_item(lbl)
        lbl, self.why = _text("What's it for?", paragraph=True, max_length=500, required=False,
                              placeholder="Optional, but it helps the bankers say yes faster")
        self.add_item(lbl)
        lbl, self.character = _character_box(user_id)
        self.add_item(lbl)

    async def on_submit(self, i: discord.Interaction) -> None:
        character = self.character.value.strip()
        store.remember_character(i.user.id, character)
        fields = {"what": self.what.value.strip()}
        if self.why.value.strip():
            fields["why"] = self.why.value.strip()
        await open_ticket(i, "bank", fields, character)


class ReasonForm(ui.Modal):
    """Cancelling (or denying) goes through this, which also stops a stray click from closing a ticket."""

    def __init__(self, heading: str, staff: bool) -> None:
        super().__init__(title=heading)
        lbl, self.reason = _text("Reason", paragraph=True, max_length=300, required=False,
                                 placeholder="Optional, shown on the post and in the DM" if staff else "Optional")
        self.add_item(lbl)

    async def on_submit(self, i: discord.Interaction) -> None:
        await cancel_ticket(i, self.reason.value.strip())


# ---------------------------------------------------------------- "no mats" hand-off

class ToGathering(ui.View):
    def __init__(self, user_id: int, officer: bool, fields: dict, character: str, item: str, quantity: str) -> None:
        super().__init__(timeout=15 * 60)
        self.args = dict(user_id=user_id, officer=officer, item=item, quantity=quantity,
                         needed_by=fields["needed_by"], purpose="craft", character=character,
                         for_craft={k: fields[k] for k in ("item", "quantity", "needed_by")})

    @ui.button(label="Open a gathering request", emoji="🌿", style=discord.ButtonStyle.primary)
    async def go(self, i: discord.Interaction, _: ui.Button) -> None:
        a = dict(self.args)
        await i.response.send_modal(GatherForm(a.pop("user_id"), a.pop("officer"), **a))


async def send_to_gathering(i: discord.Interaction, fields: dict, character: str, recipe: dict | None,
                            qty: int | None) -> None:
    s = store.settings(i.guild_id)
    if recipe:
        b = recipes.breakdown(recipe, qty)
        item, quantity = "\n".join(b.raw_lines()), "see list"
        needs = (f"\n\nHere's what **{fields['quantity']}x {recipe['name']}** takes ({recipe.get('skill', '')}):\n"
                 + "\n".join(f"• {x}" for x in recipe_mod.shopping_list(recipe, qty)))
        if b.made:
            needs += ("\n\nSome of that is crafted too, so the gathering request asks for the raw materials:\n"
                      + "\n".join(f"• {x}" for x in b.raw_lines()))
        shops = [f"• **{n}**: {recipes.vendors(n, limit=1)[0]}" for n, _ in b.raw if recipes.vendors(n, limit=1)]
        if shops:
            needs += "\n\n🛒 You can buy these from a vendor yourself:\n" + "\n".join(shops[:8])
    else:
        item, quantity, needs = f"Materials for {fields['item']}", fields["quantity"], ""
    await i.response.send_message(
        "**No mats yet? No problem.** Crafting requests need the materials in hand, so let's get them "
        f"gathered first.{needs}\n\nThe button below opens a gathering request that's already filled in. "
        "When the gathering's done, the post gets a button to send the crafting request.",
        view=ToGathering(i.user.id, is_officer(i.user, s), fields, character, item, quantity), ephemeral=True)


# ---------------------------------------------------------------- panel (persistent)

async def ready(i: discord.Interaction) -> Settings | None:
    """The server's settings, or None (after telling the member) if nobody has run /tickets setup yet."""
    s = store.settings(i.guild_id)
    if not s.forum_id:
        await i.response.send_message("Requests aren't set up yet. An admin needs to run `/tickets setup`.",
                                      ephemeral=True)
        return None
    return s


class Panel(ui.View):
    """Crafting and gathering buttons, pinned at the top of the requests forum."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @ui.button(label="Crafting", emoji="🔨", style=discord.ButtonStyle.primary, custom_id="castle:new:craft")
    async def craft(self, i: discord.Interaction, _: ui.Button) -> None:
        if await ready(i):
            await i.response.send_modal(CraftForm(i.user.id))

    @ui.button(label="Gathering", emoji="🌿", style=discord.ButtonStyle.primary, custom_id="castle:new:gather")
    async def gather(self, i: discord.Interaction, _: ui.Button) -> None:
        if s := await ready(i):
            await i.response.send_modal(GatherForm(i.user.id, is_officer(i.user, s)))


class BankPanel(ui.View):
    """Donation and request buttons, pinned at the top of the bank forum (the inventory board sits under them)."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @ui.button(label="Bank donation", emoji="📦", style=discord.ButtonStyle.primary, custom_id="castle:new:donate")
    async def donate(self, i: discord.Interaction, _: ui.Button) -> None:
        if await ready(i):
            await i.response.send_modal(DonateForm(i.user.id))

    @ui.button(label="Bank request", emoji="🏦", style=discord.ButtonStyle.primary, custom_id="castle:new:bank")
    async def bank(self, i: discord.Interaction, _: ui.Button) -> None:
        if await ready(i):
            await i.response.send_modal(BankRequestForm(i.user.id))


PANEL_TITLE = "📋 Start a request here"
PANEL_TEXT = (
    "**Crafting & gathering requests.** Pick a button and fill in the form; the bot opens a post here and pings "
    "the right people.\n\n"
    "🔨 **Crafting**: you have the mats and need something made. No mats? The form will help you get them gathered first.\n"
    "🌿 **Gathering**: you need materials farmed.\n\n"
    "**Tip:** type `/craft` or `/gather` instead, and the item box searches the wiki's recipe list as you type.\n\n"
    "You'll get a DM when someone picks up your request and when it's done. `/tickets mine` lists your open requests."
)
BANK_PANEL_TITLE = "🏦 Guild Bank"
BANK_PANEL_TEXT = (
    "**Guild bank.** Pick a button and fill in the form; the bot opens a post here and pings the bankers.\n\n"
    "📦 **Bank donation**: you're giving something to the guild bank. Include a screenshot so we can plan the space.\n"
    "🏦 **Bank request**: you'd like something from the bank. Say what it's for and a banker will approve or deny it.\n\n"
    "What's in stock is right below this and updates itself. `/bank find <item>` checks one thing; "
    "`/bank history` shows recent movements."
)


# ---------------------------------------------------------------- ticket buttons (persistent)

class Controls(ui.View):
    """The buttons under each ticket post. One persistent instance handles clicks on every post; each post
    shows only the buttons that make sense for its kind and status."""

    def __init__(self, t: Ticket | None = None) -> None:
        super().__init__(timeout=None)
        if t is not None:
            self._shape(t)

    def _shape(self, t: Ticket) -> None:
        k = KINDS[t.kind]
        self.claim.label, self.done.label = k.claim, k.done
        self.cancel.label = "Cancel / Deny" if t.kind == "bank" else "Cancel"
        if t.status == OPEN:
            keep = [self.done, self.cancel] if t.kind == "donate" else [self.claim, self.cancel]
        elif t.status == CLAIMED:
            keep = [self.done, self.unclaim, self.cancel]
        elif t.status == DONE and t.kind == "gather" and t.fields.get("for_craft"):
            keep = [self.recraft, self.reopen]
        else:
            keep = [self.reopen]
        for item in list(self.children):
            if item not in keep:
                self.remove_item(item)

    @ui.button(label="Claim", emoji="🙋", style=discord.ButtonStyle.success, custom_id="castle:claim")
    async def claim(self, i: discord.Interaction, _: ui.Button) -> None:
        t, s = await _ticket_for(i)
        if not t:
            return
        if not is_staff(i.user, s, t.kind):
            return await _deny(i, f"Only the {KINDS[t.kind].staff_word}s can take this one.")
        if t.status != OPEN:
            return await _deny(i, "Someone got to it first." if t.status == CLAIMED else "This isn't open any more.")
        t = store.set_status(t.id, CLAIMED, claimer_id=i.user.id)
        verb = "approved" if t.kind == "bank" else "claimed"
        await _apply(i, t, f"🔵 {i.user.mention} {verb} this.",
                     f"Your {KINDS[t.kind].name.lower()} request #{t.id} was {verb} by {i.user.display_name}.")

    @ui.button(label="Mark done", emoji="✅", style=discord.ButtonStyle.success, custom_id="castle:done")
    async def done(self, i: discord.Interaction, _: ui.Button) -> None:
        t, s = await _ticket_for(i)
        if not t:
            return
        if not is_staff(i.user, s, t.kind):
            return await _deny(i, f"Only the {KINDS[t.kind].staff_word}s can close this one.")
        if t.status not in ACTIVE:
            return await _deny(i, "This is already closed.")
        if t.kind in ("donate", "bank"):
            return await i.response.send_modal(BankLinesForm(t))  # record what moved, then close
        await finish_done(i, t)

    @ui.button(label="Unclaim", emoji="↩️", style=discord.ButtonStyle.secondary, custom_id="castle:unclaim")
    async def unclaim(self, i: discord.Interaction, _: ui.Button) -> None:
        t, s = await _ticket_for(i)
        if not t:
            return
        if t.status != CLAIMED:
            return await _deny(i, "This isn't claimed.")
        if i.user.id != t.claimer_id and not is_officer(i.user, s):
            return await _deny(i, "Only whoever claimed it (or an officer) can unclaim it.")
        t = store.set_status(t.id, OPEN)
        await _apply(i, t, f"↩️ {i.user.mention} unclaimed this, so it's open again.",
                     f"Your {KINDS[t.kind].name.lower()} request #{t.id} is back in the queue "
                     f"({i.user.display_name} had to let it go).")

    @ui.button(label="Cancel", emoji="✖️", style=discord.ButtonStyle.danger, custom_id="castle:cancel")
    async def cancel(self, i: discord.Interaction, _: ui.Button) -> None:
        t, s = await _ticket_for(i)
        if not t:
            return
        staff = is_staff(i.user, s, t.kind)
        if i.user.id != t.requester_id and not staff:
            return await _deny(i, "Only the person who asked (or staff) can cancel this.")
        if t.status not in ACTIVE:
            return await _deny(i, "This is already closed.")
        own = i.user.id == t.requester_id
        heading = "Cancel your request?" if own else ("Deny this request?" if t.kind == "bank" else "Cancel this request?")
        await i.response.send_modal(ReasonForm(heading, staff=not own))

    @ui.button(label="Open the crafting request", emoji="🔨", style=discord.ButtonStyle.primary, custom_id="castle:recraft")
    async def recraft(self, i: discord.Interaction, _: ui.Button) -> None:
        t, s = await _ticket_for(i)
        if not t:
            return
        fc = t.fields.get("for_craft")
        if not fc:
            return await _deny(i, "This gathering request wasn't for a craft.")
        if i.user.id != t.requester_id:
            return await _deny(i, "Only the person who asked can send the crafting request.")
        await i.response.send_modal(CraftForm(i.user.id, item=fc.get("item", ""), quantity=fc.get("quantity", "1"),
                                              needed_by=fc.get("needed_by"), has_mats="yes", character=t.character))

    @ui.button(label="Reopen", emoji="🔄", style=discord.ButtonStyle.secondary, custom_id="castle:reopen")
    async def reopen(self, i: discord.Interaction, _: ui.Button) -> None:
        t, s = await _ticket_for(i)
        if not t:
            return
        if i.user.id != t.requester_id and not is_staff(i.user, s, t.kind):
            return await _deny(i, "Only the person who asked (or staff) can reopen this.")
        if t.status in ACTIVE:
            return await _deny(i, "This is already open.")
        t = store.set_status(t.id, OPEN)
        await _apply(i, t, f"🟡 {i.user.mention} reopened this.",
                     f"Your {KINDS[t.kind].name.lower()} request #{t.id} was reopened by {i.user.display_name}.")


async def finish_done(i: discord.Interaction, t: Ticket, extra: str = "") -> None:
    k = KINDS[t.kind]
    t = store.set_status(t.id, DONE, claimer_id=t.claimer_id or i.user.id)
    dm = f"Your {k.name.lower()} request #{t.id} was {k.done_word} by {i.user.display_name}."
    if t.fields.get("for_craft"):
        dm += " Your mats are in! Press **Open the crafting request** on the post when you have them."
    await _apply(i, t, f"✅ {i.user.mention} marked this {k.done_word}." + extra, dm + extra)


class BankLinesForm(ui.Modal):
    """Received / Handed over: the banker confirms what actually moved, and the inventory follows."""

    def __init__(self, t: Ticket) -> None:
        going_in = t.kind == "donate"
        super().__init__(title="What went into the bank?" if going_in else "What left the bank?")
        self.ticket = t
        lbl, self.lines = _text("Items, one per line", paragraph=True, max_length=1000, required=False,
                                default=bank.format_lines(bank.parse_lines(t.fields.get("what", ""), recipes)),
                                placeholder="12 Spider Silk\n3 Iron Bar",
                                description="Fix the list if it's off. Leave it empty to skip the inventory.")
        self.add_item(lbl)

    async def on_submit(self, i: discord.Interaction) -> None:
        t = store.get(self.ticket.id)
        if t is None or t.status not in ACTIVE:
            return await _deny(i, "This is already closed.")
        pairs = bank.parse_lines(self.lines.value, recipes)
        sign = 1 if t.kind == "donate" else -1
        why = f"{'donation' if sign > 0 else 'request'} #{t.id}"
        moved, short = [], []
        for item, qty in pairs:
            left = store.bank_change(i.guild_id, item, sign * qty, i.user.id, t.id, why)
            moved.append(f"{qty:,} {item}")
            if left < 0:
                short.append(f"{item} (bank now shows {left})")
        extra = ""
        if moved:
            extra = ("\n📦 Into the bank: " if sign > 0 else "\n📤 Out of the bank: ") + ", ".join(moved)
        if short:
            extra += "\n⚠️ More went out than was recorded for " + ", ".join(short) + ". A banker may want to `/bank set` it."
        await finish_done(i, t, extra)
        if moved:
            await bank.refresh_board(i.client, store, recipes, store.settings(i.guild_id))


async def _ticket_for(i: discord.Interaction) -> tuple[Ticket | None, Settings | None]:
    t = store.by_thread(i.channel_id)
    if t is None:
        await _deny(i, "I can't find the ticket for this post.")
        return None, None
    return t, store.settings(i.guild_id)


async def _deny(i: discord.Interaction, text: str) -> None:
    await i.response.send_message(text, ephemeral=True)


async def cancel_ticket(i: discord.Interaction, reason: str) -> None:
    t, s = await _ticket_for(i)
    if not t:
        return
    if t.status not in ACTIVE:
        return await _deny(i, "This is already closed.")
    own = i.user.id == t.requester_id
    t = store.set_status(t.id, CANCELLED, claimer_id=i.user.id, reason=reason)
    k = KINDS[t.kind]
    if own:
        note, dm = "⚪ Cancelled by the person who asked.", None
    else:
        word = "denied" if t.kind == "bank" else "cancelled"
        note = f"⚪ {i.user.mention} {word} this" + (f": {reason}" if reason else ".")
        dm = f"Your {k.name.lower()} request #{t.id} was {word} by {i.user.display_name}" + (f": {reason}" if reason else ".")
    await _apply(i, t, note, dm)


async def _apply(i: discord.Interaction, t: Ticket, note: str, dm: str | None) -> None:
    """After a status change: redraw the post, log a line in it, DM the requester, retag and (un)archive."""
    thread = i.channel
    if not isinstance(thread, discord.Thread):
        await i.response.edit_message(embed=embed(t), view=Controls(t))
        return
    if thread.archived:
        # Discord archives quiet posts after a week, and closed ones are archived on purpose; an archived
        # post's messages can't be edited until it's reopened.
        await i.response.defer()
        try:
            await thread.edit(archived=False)
        except discord.HTTPException as e:
            log.warning("couldn't unarchive ticket #%d: %s", t.id, e)
        await i.edit_original_response(embed=embed(t), view=Controls(t))
    else:
        await i.response.edit_message(embed=embed(t), view=Controls(t))
    reached = True
    if dm and i.user.id != t.requester_id:
        reached = await _dm(i.client, t.requester_id, f"{dm}\n{thread.jump_url}")
    ping = f" <@{t.requester_id}>" if not reached else ""
    hours = store.settings(t.guild_id).cleanup_after
    if not t.active and hours:
        note += f"\n🧹 This post tidies itself away in about {_span(hours)}."
    try:
        await thread.send(note + ping, allowed_mentions=discord.AllowedMentions(users=[discord.Object(t.requester_id)]))
    except discord.HTTPException as e:
        log.warning("couldn't post in ticket #%d: %s", t.id, e)
    await sync_thread(thread, t)


async def sync_thread(thread: discord.Thread, t: Ticket) -> None:
    kwargs: dict = {"archived": not t.active}
    if isinstance(thread.parent, discord.ForumChannel):
        kwargs["applied_tags"] = forum_tags(thread.parent, t)
    try:
        await thread.edit(**kwargs)
    except discord.HTTPException as e:
        log.warning("couldn't update post for ticket #%d: %s", t.id, e)


async def _dm(client: discord.Client, user_id: int, text: str) -> bool:
    try:
        user = client.get_user(user_id) or await client.fetch_user(user_id)
        await user.send(text)
        return True
    except discord.HTTPException:
        return False  # DMs closed; the thread message pings them instead


# ---------------------------------------------------------------- opening a ticket

async def open_ticket(i: discord.Interaction, kind: str, fields: dict, character: str,
                      files: list[discord.File] | None = None) -> None:
    async def say(text: str) -> None:
        if i.response.is_done():
            await i.followup.send(text, ephemeral=True)
        else:
            await i.response.send_message(text, ephemeral=True)

    s = store.settings(i.guild_id)
    forum_id = s.forum_for(kind)
    forum = i.guild.get_channel(forum_id) if (i.guild and forum_id) else None
    if not isinstance(forum, discord.ForumChannel):
        return await say("Requests aren't set up yet (or the requests forum was deleted). Ask an admin to run `/tickets setup`.")
    if not i.response.is_done():
        await i.response.defer(ephemeral=True, thinking=True)

    t = store.create(i.guild_id, kind, i.user.id, character, fields)
    role_id = getattr(s, KINDS[kind].role)
    role = i.guild.get_role(role_id) if role_id else None
    k = KINDS[kind]
    content = f"{role.mention + ' ' if role else ''}New {k.name.lower()} request from {i.user.mention}"
    kwargs: dict = {"files": files} if files else {}
    try:
        posted = await forum.create_thread(
            name=title(t), content=content, embed=embed(t), view=Controls(t), applied_tags=forum_tags(forum, t),
            auto_archive_duration=10080,
            allowed_mentions=discord.AllowedMentions(everyone=False, users=[i.user], roles=[role] if role else False),
            **kwargs)
    except discord.HTTPException as e:
        store.delete(t.id)
        log.error("couldn't open %s ticket: %s", kind, e)
        return await say(f"Sorry, I couldn't post that ({e.text or e}). Tell an officer; your answers are below so "
                         f"you don't lose them:\n>>> {chr(10).join(f'{k2}: {v}' for k2, v in fields.items())}")
    store.attach_thread(t.id, posted.thread.id, posted.message.id)
    await say(f"Posted: {posted.thread.mention}. You'll get a DM when someone picks it up.")
