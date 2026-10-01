"""Offline tests: storage, recipe math, what each post looks like, and the button flows driven with fake
Discord objects (no token or server needed).  Run:  python -m pytest -q
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import recipes as recipe_mod  # noqa: E402
import ui  # noqa: E402
from recipes import Recipes  # noqa: E402
from store import CANCELLED, CLAIMED, DONE, OPEN, Settings, Store  # noqa: E402

GUILD, FORUM, THREAD = 1, 10, 500
CRAFTER, GATHERER, BANKER, OFFICER = 101, 102, 103, 104
ALICE, BOB, CAROL = 1001, 1002, 1003  # requester, crafter, random member

RIVETS = {"name": "Iron Rivets", "skill": "Blacksmithing", "trivial": 45, "station": "Forge", "makes": 4,
          "ingredients": [{"qty": 1, "name": "Iron Bar", "tool": False}, {"qty": 2, "name": "Coal", "tool": False},
                          {"qty": 1, "name": "Smithing Hammer", "tool": True}]}


@pytest.fixture()
def env(tmp_path):
    s = Store(tmp_path / "t.db")
    r = Recipes(cache=tmp_path / "recipes.json")
    r.load([RIVETS])
    ui.init(s, r)
    s.save_settings(Settings(GUILD, FORUM, CRAFTER, GATHERER, BANKER, OFFICER))
    return s


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------- fakes

class FakeMember(discord.Member):
    """Just enough of a Member: roles and guild permissions."""

    def __init__(self, uid: int, roles=(), manage_guild=False):  # noqa: D401 - no super().__init__ on purpose
        self._uid, self._roles_ids, self._mg = uid, set(roles), manage_guild

    id = property(lambda self: self._uid)
    mention = property(lambda self: f"<@{self._uid}>")
    display_name = property(lambda self: f"user{self._uid}")
    guild_permissions = property(lambda self: discord.Permissions(manage_guild=self._mg))

    def get_role(self, rid):
        return object() if rid in self._roles_ids else None


def fake_thread(archived=False):
    th = MagicMock(spec=discord.Thread)
    th.id, th.archived, th.jump_url, th.mention = THREAD, archived, "https://discord/x", f"<#{THREAD}>"
    th.parent = MagicMock(spec=discord.ForumChannel)
    th.parent.available_tags = [SimpleNamespace(name=n) for n in
                                ["Crafting", "Gathering", "Bank Donation", "Bank Request", "Open", "Claimed", "Done", "Cancelled"]]
    th.send, th.edit = AsyncMock(), AsyncMock()
    return th


def interaction(user, channel=None):
    i = MagicMock()
    i.user, i.guild_id, i.channel = user, GUILD, channel
    i.channel_id = channel.id if channel is not None else None
    done = {"v": False}
    i.response.is_done = lambda: done["v"]

    async def mark(*a, **k):
        done["v"] = True
    for name in ("send_message", "edit_message", "send_modal", "defer"):
        setattr(i.response, name, AsyncMock(side_effect=mark))
    i.followup.send = AsyncMock()
    i.edit_original_response = AsyncMock()
    user_obj = MagicMock()
    user_obj.send = AsyncMock()
    i.client.get_user = lambda uid: user_obj
    i.dm_target = user_obj
    return i


def make_ticket(s: Store, kind="craft", **fields):
    base = {"item": "Iron Rivets", "quantity": "20", "needed_by": "This week"} if kind in ("craft", "gather") else {"what": "Silk"}
    t = s.create(GUILD, kind, ALICE, "Moirin", base | fields)
    s.attach_thread(t.id, THREAD + t.id - 1, THREAD + t.id - 1)  # first ticket gets THREAD
    return s.get(t.id)


def labels(view):
    return [c.label for c in view.children]


# ---------------------------------------------------------------- store

def test_status_lifecycle(env):
    t = make_ticket(env)
    assert t.status == OPEN and t.active
    t = env.set_status(t.id, CLAIMED, claimer_id=BOB)
    assert t.claimer_id == BOB
    t = env.set_status(t.id, OPEN)
    assert t.claimer_id is None
    env.set_status(t.id, CLAIMED, claimer_id=BOB)
    t = env.set_status(t.id, DONE)
    assert t.status == DONE and t.claimer_id == BOB and t.closed_at and not t.active
    assert env.mine(GUILD, ALICE) == []


def test_character_memory(env):
    assert env.character(ALICE) == ""
    env.remember_character(ALICE, "Moirin")
    env.remember_character(ALICE, "Denvan")
    assert env.character(ALICE) == "Denvan"


# ---------------------------------------------------------------- recipes

def test_recipe_lookup_and_scaling(env):
    r = ui.recipes
    assert r.find("iron rivets")["name"] == "Iron Rivets"
    assert r.find("Iron Rivet")["name"] == "Iron Rivets"  # plural/singular slack
    assert r.find("Iron Rivts") is not None               # small typo
    assert r.find("Mithril Crown") is None
    # 20 rivets at 4 per combine = 5 combines; the hammer is a tool, needed once
    assert recipe_mod.shopping_list(RIVETS, 20) == ["5 x Iron Bar", "10 x Coal", "Smithing Hammer (tool)"]
    assert recipe_mod.shopping_list(RIVETS, 1) == ["1 x Iron Bar", "2 x Coal", "Smithing Hammer (tool)"]
    assert "5 combines" in recipe_mod.summary(RIVETS, 20)
    assert recipe_mod.parse_quantity("1,200") == 1200 and recipe_mod.parse_quantity("a stack") is None


def test_autocomplete(env):
    r = ui.recipes
    assert r.craft_choices("riv") == [("Iron Rivets (Blacksmithing)", "Iron Rivets")]
    assert r.craft_choices("") == []
    assert r.material_choices("co") == ["Coal"]
    assert "Smithing Hammer" not in r.material_choices("hammer")  # tools aren't gathered


def test_gather_item_uses_wiki_spelling(env):
    i, forum = forum_interaction(FakeMember(ALICE))
    f = ui.GatherForm(ALICE, officer=False)
    fill(f.item, "iron bar"); fill(f.quantity, "5"); fill(f.character, "Moirin")
    choose(f.needed_by, "ASAP"); choose(f.purpose, "self")
    submit(f, i)
    assert env.by_thread(777).fields["item"] == "Iron Bar"


def test_real_recipe_file_loads():
    real = Path(r"C:\Users\Arcti\Projects\mobetta-bot\data\recipes.json")
    if not real.exists():
        pytest.skip("no local copy of recipes.json")
    r = Recipes(cache=real)
    import json
    r.load(json.loads(real.read_text("utf-8"))["recipes"])
    assert len(r.by_name) > 500 and len(r.materials) > 100
    for q in ("pot", "silk", "bronze", "ale"):
        choices = r.craft_choices(q)
        assert 0 < len(choices) <= 25 and all(len(label) <= 100 for label, _ in choices), q
        assert len(r.material_choices(q)) <= 25


# ---------------------------------------------------------------- rendering

def test_titles_and_embeds(env):
    t = make_ticket(env)
    assert ui.title(t) == "🔨 20x Iron Rivets · Moirin"
    long = make_ticket(env, "bank", what="x" * 300)
    assert len(ui.title(long)) <= 100
    e = ui.embed(t)
    assert e.title == f"🔨 Crafting #{t.id}"
    assert any(f.name == "Status" and "Open" in f.value for f in e.fields)
    assert len(e) < 6000


def test_controls_per_status(env):
    t = make_ticket(env)
    assert labels(ui.Controls(t)) == ["Claim", "Cancel"]
    t = env.set_status(t.id, CLAIMED, claimer_id=BOB)
    assert labels(ui.Controls(t)) == ["Crafted & delivered", "Unclaim", "Cancel"]
    t = env.set_status(t.id, DONE)
    assert labels(ui.Controls(t)) == ["Reopen"]
    d = make_ticket(env, "donate")
    assert labels(ui.Controls(d)) == ["Received", "Cancel"]
    b = make_ticket(env, "bank")
    assert labels(ui.Controls(b)) == ["Approve", "Cancel / Deny"]
    g = make_ticket(env, "gather", for_craft={"item": "Iron Rivets", "quantity": "20", "needed_by": "ASAP"})
    g = env.set_status(g.id, DONE, claimer_id=BOB)
    assert labels(ui.Controls(g)) == ["Open the crafting request", "Reopen"]
    # the persistent instance registered at startup carries every button with a stable id
    assert {c.custom_id for c in ui.Controls().children} == {
        "castle:claim", "castle:done", "castle:unclaim", "castle:cancel", "castle:reopen", "castle:recraft"}
    for view in (ui.Controls(), ui.Controls(t), ui.Panel()):
        view.to_components()  # serialises without complaint


def test_forms_fit_discord_limits(env):
    member = FakeMember(ALICE)
    forms = [ui.CraftForm(ALICE), ui.GatherForm(ALICE, officer=False), ui.GatherForm(ALICE, officer=True),
             ui.DonateForm(ALICE), ui.BankRequestForm(ALICE), ui.ReasonForm("Cancel your request?", staff=False)]
    for f in forms:
        payload = f.to_dict()
        assert len(payload["components"]) <= 5, f.title
        for c in payload["components"]:
            assert len(c.get("label", "")) <= 45 and len(c.get("description") or "") <= 100
    # guild requisition choices only for officers
    assert "guild_raid" not in [o.value for o in ui.GatherForm(ALICE, officer=False).purpose.options]
    assert "guild_raid" in [o.value for o in ui.GatherForm(ALICE, officer=True).purpose.options]
    assert member.id == ALICE


def test_character_prefill(env):
    env.remember_character(ALICE, "Moirin")
    assert ui.CraftForm(ALICE).character.default == "Moirin"


# ---------------------------------------------------------------- permissions

def test_permissions(env):
    s = env.settings(GUILD)
    crafter, rando, officer, admin = (FakeMember(BOB, [CRAFTER]), FakeMember(CAROL), FakeMember(9, [OFFICER]),
                                      FakeMember(8, manage_guild=True))
    assert ui.is_staff(crafter, s, "craft") and not ui.is_staff(crafter, s, "gather")
    assert not ui.is_staff(rando, s, "craft")
    assert ui.is_staff(officer, s, "bank") and ui.is_staff(admin, s, "gather")


# ---------------------------------------------------------------- button flows

def press(view, name, i):
    return run(getattr(view, name).callback(i))


def test_claim_then_done_flow(env):
    t = make_ticket(env)
    th = fake_thread()
    view = ui.Controls()

    i = interaction(FakeMember(CAROL), th)
    press(view, "claim", i)
    assert "Only the crafters" in i.response.send_message.call_args.args[0]
    assert env.get(t.id).status == OPEN

    i = interaction(FakeMember(BOB, [CRAFTER]), th)
    press(view, "claim", i)
    assert env.get(t.id).status == CLAIMED and env.get(t.id).claimer_id == BOB
    assert labels(i.response.edit_message.call_args.kwargs["view"]) == ["Crafted & delivered", "Unclaim", "Cancel"]
    assert "claimed by user1002" in i.dm_target.send.call_args.args[0]
    th.edit.assert_awaited_with(archived=False, applied_tags=[th.parent.available_tags[0], th.parent.available_tags[5]])

    i2 = interaction(FakeMember(CAROL, [CRAFTER]), th)
    press(view, "claim", i2)
    assert "got to it first" in i2.response.send_message.call_args.args[0]

    i = interaction(FakeMember(BOB, [CRAFTER]), th)
    press(view, "done", i)
    t = env.get(t.id)
    assert t.status == DONE and t.claimer_id == BOB
    assert th.edit.call_args.kwargs["archived"] is True


def test_dm_closed_falls_back_to_ping(env):
    make_ticket(env)
    th = fake_thread()
    i = interaction(FakeMember(BOB, [CRAFTER]), th)
    i.dm_target.send.side_effect = discord.Forbidden(MagicMock(status=403), "no DMs")
    press(ui.Controls(), "claim", i)
    assert f"<@{ALICE}>" in th.send.call_args.args[0]


def test_claim_on_archived_post_unarchives_first(env):
    make_ticket(env)
    th = fake_thread(archived=True)
    i = interaction(FakeMember(BOB, [CRAFTER]), th)
    press(ui.Controls(), "claim", i)
    i.response.defer.assert_awaited()
    assert th.edit.await_args_list[0].kwargs == {"archived": False}
    i.edit_original_response.assert_awaited()
    i.response.edit_message.assert_not_awaited()


def test_cancel_by_requester_and_deny_by_banker(env):
    t = make_ticket(env)
    th = fake_thread()
    i = interaction(FakeMember(CAROL), th)
    press(ui.Controls(), "cancel", i)
    assert "Only the person who asked" in i.response.send_message.call_args.args[0]

    i = interaction(FakeMember(ALICE), th)
    press(ui.Controls(), "cancel", i)
    form = i.response.send_modal.call_args.args[0]
    assert form.title == "Cancel your request?"
    run(ui.cancel_ticket(i, ""))
    assert env.get(t.id).status == CANCELLED
    assert "Cancelled" in ui.status_line(env.get(t.id))
    i.dm_target.send.assert_not_awaited()  # no DM about your own action

    b = env.create(GUILD, "bank", ALICE, "Moirin", {"what": "Epic sword"})
    env.attach_thread(b.id, THREAD + 1, THREAD + 1)
    th2 = fake_thread()
    th2.id = THREAD + 1
    i = interaction(FakeMember(BOB, [BANKER]), th2)
    press(ui.Controls(), "cancel", i)
    assert i.response.send_modal.call_args.args[0].title == "Deny this request?"
    run(ui.cancel_ticket(i, "Save it for raid"))
    b = env.get(b.id)
    assert b.status == CANCELLED and ui.status_line(b) == "⚪ Denied: Save it for raid"
    assert "denied by user1002: Save it for raid" in i.dm_target.send.call_args.args[0]


def test_unclaim_rules(env):
    t = make_ticket(env)
    env.set_status(t.id, CLAIMED, claimer_id=BOB)
    th = fake_thread()
    i = interaction(FakeMember(CAROL, [CRAFTER]), th)
    press(ui.Controls(), "unclaim", i)
    assert "Only whoever claimed it" in i.response.send_message.call_args.args[0]
    i = interaction(FakeMember(BOB, [CRAFTER]), th)
    press(ui.Controls(), "unclaim", i)
    assert env.get(t.id).status == OPEN and env.get(t.id).claimer_id is None


# ---------------------------------------------------------------- forms -> tickets

def submit(form, i):
    return run(form.on_submit(i))


def fill(box, value):
    box._value = value


def choose(sel, value):
    sel._values = [value]


def test_craft_without_mats_redirects_to_gathering(env):
    member = FakeMember(ALICE)
    i = interaction(member)
    f = ui.CraftForm(ALICE)
    fill(f.item, "Iron Rivets"); fill(f.quantity, "20"); fill(f.character, "Moirin")
    choose(f.needed_by, "ASAP"); choose(f.mats, "no")
    submit(f, i)
    text = i.response.send_message.call_args.args[0]
    assert "5 x Iron Bar" in text and "Smithing Hammer (tool)" in text
    assert env.active(GUILD) == []  # no craft ticket left sitting around
    view = i.response.send_message.call_args.kwargs["view"]
    i2 = interaction(member)
    run(view.go.callback(i2))
    g = i2.response.send_modal.call_args.args[0]
    assert g.item.default == "10 x Coal\n5 x Iron Bar"  # tools left off the gathering list
    assert g.for_craft == {"item": "Iron Rivets", "quantity": "20", "needed_by": "ASAP"}
    assert [o.value for o in g.purpose.options if o.default] == ["craft"]


def forum_interaction(user):
    i = interaction(user)
    forum = MagicMock(spec=discord.ForumChannel)
    forum.available_tags = [SimpleNamespace(name="Crafting"), SimpleNamespace(name="Open")]
    posted = SimpleNamespace(thread=SimpleNamespace(id=777, mention="<#777>"), message=SimpleNamespace(id=777))
    forum.create_thread = AsyncMock(return_value=posted)
    role = MagicMock()
    role.mention = f"<@&{CRAFTER}>"
    i.guild.get_channel = lambda cid: forum if cid == FORUM else None
    i.guild.get_role = lambda rid: role
    return i, forum


def test_craft_with_mats_opens_post(env):
    i, forum = forum_interaction(FakeMember(ALICE))
    f = ui.CraftForm(ALICE)
    fill(f.item, "iron rivets"); fill(f.quantity, "8"); fill(f.character, "Moirin")
    choose(f.needed_by, "No rush"); choose(f.mats, "yes")
    submit(f, i)
    kw = forum.create_thread.call_args.kwargs
    assert kw["name"] == "🔨 8x Iron Rivets · Moirin"  # wiki spelling
    assert kw["content"].startswith(f"<@&{CRAFTER}> New crafting request")
    assert [t.name for t in kw["applied_tags"]] == ["Crafting", "Open"]
    t = env.by_thread(777)
    assert t.fields["recipe_name"] == "Iron Rivets" and "2 combines" in t.fields["recipe"]
    assert "Posted: <#777>" in i.followup.send.call_args.args[0]
    assert env.character(ALICE) == "Moirin"


def test_failed_post_leaves_no_ticket(env):
    i, forum = forum_interaction(FakeMember(ALICE))
    forum.create_thread.side_effect = discord.HTTPException(MagicMock(status=400), "boom")
    run(ui.open_ticket(i, "bank", {"what": "Sword"}, "Moirin"))
    assert env.active(GUILD) == []
    assert "your answers are below" in i.followup.send.call_args.args[0]


def test_not_set_up(tmp_path):
    s = Store(tmp_path / "t.db")
    ui.init(s, Recipes(cache=tmp_path / "r.json"))
    i = interaction(FakeMember(ALICE))
    run(ui.Panel().craft.callback(i))
    assert "/tickets setup" in i.response.send_message.call_args.args[0]
    i.response.send_modal.assert_not_awaited()
