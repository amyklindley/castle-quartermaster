"""Guild bank: line parsing, the ledger, the board, and the Received -> inventory flow."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bank  # noqa: E402
import ui  # noqa: E402
from store import DONE, Settings, Store  # noqa: E402
from test_tickets import ALICE, BANKER, BOB, GUILD, FakeMember, RIVETS, fake_thread, fill, interaction, press, run  # noqa: E402
from recipes import Recipes  # noqa: E402

SILK = {"name": "Spider Silk", "slot": "", "effect": ""}
SWORD = {"name": "Rusty Sword", "slot": "PRIMARY", "effect": ""}
POTION = {"name": "Minor Healing Potion", "slot": "", "effect": ""}


@pytest.fixture()
def env(tmp_path):
    s = Store(tmp_path / "t.db")
    r = Recipes(cache=tmp_path / "recipes.json")
    r.load([RIVETS])
    r.load_items([SILK, SWORD, POTION])
    ui.init(s, r)
    s.save_settings(Settings(GUILD, 10, 101, 102, BANKER, 104, panel_thread_id=900))
    return s


def test_parse_lines(env):
    w = ui.recipes
    assert bank.parse_lines("12 spider silk\n3x Iron Bar\nRusty Sword x2\nCoal (5)\nMinor healing potions - 4\nbread", w) == [
        ("Spider Silk", 12), ("Iron Bar", 3), ("Rusty Sword", 2), ("Coal", 5), ("Minor Healing Potion", 4), ("bread", 1)]
    assert bank.parse_lines("2 Coal, 2 Coal; 1,000 Iron Ore", w) == [("Coal", 4), ("Iron Ore", 1000)]
    assert bank.parse_lines("  \n- \n", w) == []
    assert bank.format_lines([("Spider Silk", 12), ("Coal", 1)]) == "12 Spider Silk\n1 Coal"


def test_categories(env):
    c = ui.recipes.category
    assert c("Rusty Sword") == "⚔️ Weapons"
    assert c("Spider Silk") == "📦 Other"          # in items.json, not used by our one test recipe
    assert c("Iron Bar") == "🪨 Crafting materials"
    assert c("Minor Healing Potion") == "🧪 Potions"
    assert c("Iron Rivets") == "📦 Other"          # Blacksmithing output, no slot: "other" is honest
    assert c("Spell: Gate") == "📜 Spells & Scrolls"


def test_ledger_and_board(env):
    assert env.bank_stock(GUILD) == []
    assert env.bank_change(GUILD, "Spider Silk", 12, BOB) == 12
    assert env.bank_change(GUILD, "Spider Silk", -4, BOB, note="raid") == 8
    env.bank_change(GUILD, "Rusty Sword", 1, BOB)
    env.bank_change(GUILD, "Coal", 5, BOB)
    env.bank_change(GUILD, "Coal", -5, BOB)  # gone entirely: not shown
    assert env.bank_stock(GUILD) == [("Rusty Sword", 1), ("Spider Silk", 8)]
    assert env.bank_items_like(GUILD, "silk") == ["Spider Silk"]
    assert [e.delta for e in env.bank_history(GUILD, "Spider Silk")] == [-4, 12]
    embeds = bank.board_embeds(env.bank_stock(GUILD), ui.recipes)
    assert embeds[0].title == "🏦 Guild Bank" and "2 kinds of item, 9 in all" in embeds[0].description
    names = [f.name for e in embeds for f in e.fields]
    assert names == ["⚔️ Weapons", "📦 Other"]
    assert "Spider Silk **×8**" in embeds[0].fields[1].value
    assert bank.board_embeds([], ui.recipes)[0].description.startswith("Empty")


def test_big_board_splits_cleanly(env):
    stock = [(f"Item number {n:04d} with a long name", n) for n in range(1, 400)]
    embeds = bank.board_embeds(stock, ui.recipes)
    assert 1 < len(embeds) <= 10
    for e in embeds:
        assert len(e) <= 6000 and len(e.fields) <= 25
        assert all(len(f.value) <= 1024 for f in e.fields)


def test_settings_migration(tmp_path):
    s = Store(tmp_path / "t.db")
    st = Settings(GUILD, 10, 101, 102, 103, bank_channel_id=555, bank_message_id=556)
    s.save_settings(st)
    assert s.settings(GUILD) == st
    # opening the same file again runs the migrations harmlessly
    assert Store(tmp_path / "t.db").settings(GUILD).bank_channel_id == 555


def test_received_records_the_donation(env, monkeypatch):
    t = env.create(GUILD, "donate", ALICE, "Moirin", {"what": "12 spider silk\n2 rusty swords"})
    env.attach_thread(t.id, 500, 500)
    th = fake_thread()
    refreshed = AsyncMock(return_value=True)
    monkeypatch.setattr(bank, "refresh_board", refreshed)

    i = interaction(FakeMember(BOB, [BANKER]), th)
    press(ui.Controls(), "done", i)
    form = i.response.send_modal.call_args.args[0]
    assert form.title == "What went into the bank?"
    assert form.lines.default == "12 Spider Silk\n2 Rusty Sword"

    fill(form.lines, "12 Spider Silk\n1 Rusty Sword")  # the banker corrects the count
    run(form.on_submit(i))
    assert env.get(t.id).status == DONE
    assert env.bank_stock(GUILD) == [("Rusty Sword", 1), ("Spider Silk", 12)]
    assert env.bank_history(GUILD)[0].ticket_id == t.id
    assert "Into the bank: 12 Spider Silk, 1 Rusty Sword" in th.send.call_args.args[0]
    refreshed.assert_awaited_once()


def test_handed_over_subtracts_and_warns(env, monkeypatch):
    env.bank_change(GUILD, "Spider Silk", 5, BOB)
    t = env.create(GUILD, "bank", ALICE, "Moirin", {"what": "10 spider silk"})
    env.attach_thread(t.id, 501, 501)
    th = fake_thread()
    th.id = 501
    monkeypatch.setattr(bank, "refresh_board", AsyncMock(return_value=True))
    i = interaction(FakeMember(BOB, [BANKER]), th)
    press(ui.Controls(), "done", i)
    form = i.response.send_modal.call_args.args[0]
    assert form.title == "What left the bank?"
    run(form.on_submit(i))
    assert env.bank_count(GUILD, "Spider Silk") == -5
    note = th.send.call_args.args[0]
    assert "Out of the bank: 10 Spider Silk" in note and "More went out than was recorded" in note


def test_empty_lines_skip_inventory(env, monkeypatch):
    t = env.create(GUILD, "donate", ALICE, "Moirin", {"what": "some stuff"})
    env.attach_thread(t.id, 502, 502)
    th = fake_thread()
    th.id = 502
    refreshed = AsyncMock()
    monkeypatch.setattr(bank, "refresh_board", refreshed)
    i = interaction(FakeMember(BOB, [BANKER]), th)
    press(ui.Controls(), "done", i)
    form = i.response.send_modal.call_args.args[0]
    fill(form.lines, "")
    run(form.on_submit(i))
    assert env.get(t.id).status == DONE and env.bank_stock(GUILD) == []
    refreshed.assert_not_awaited()


def test_refresh_board_creates_then_edits(env):
    client = MagicMock()
    home = MagicMock(spec=discord.TextChannel)
    sent = MagicMock(id=777)
    home.send = AsyncMock(return_value=sent)
    home.fetch_message = AsyncMock(return_value=sent)
    sent.edit = AsyncMock()
    client.get_channel = lambda cid: home if cid == 900 else None
    s = env.settings(GUILD)
    assert run(bank.refresh_board(client, env, ui.recipes, s)) is True
    assert env.settings(GUILD).bank_message_id == 777
    assert run(bank.refresh_board(client, env, ui.recipes, env.settings(GUILD))) is True
    home.send.assert_awaited_once()
    sent.edit.assert_awaited_once()


def test_bank_tickets_go_to_the_bank_forum(env):
    from test_tickets import forum_interaction
    s = env.settings(GUILD)
    s.bank_forum_id = 11
    env.save_settings(s)
    assert s.forum_for("donate") == 11 and s.forum_for("bank") == 11 and s.forum_for("craft") == 10
    i, forum = forum_interaction(FakeMember(ALICE))
    bank_forum = MagicMock(spec=discord.ForumChannel)
    bank_forum.available_tags = []
    posted = MagicMock(thread=MagicMock(id=778, mention="<#778>"), message=MagicMock(id=778))
    bank_forum.create_thread = AsyncMock(return_value=posted)
    i.guild.get_channel = lambda cid: {10: forum, 11: bank_forum}.get(cid)
    run(ui.open_ticket(i, "bank", {"what": "Sword"}, "Moirin"))
    bank_forum.create_thread.assert_awaited_once()
    forum.create_thread.assert_not_awaited()
    assert env.by_thread(778).kind == "bank"


def test_panels_split():
    assert [b.custom_id for b in ui.Panel().children] == ["castle:new:craft", "castle:new:gather"]
    assert [b.custom_id for b in ui.BankPanel().children] == ["castle:new:donate", "castle:new:bank"]
    both = ui.Panel()
    for item in ui.BankPanel().children:
        both.add_item(item)
    assert len(both.to_components()[0]["components"]) == 4


def test_donation_without_a_screenshot(env):
    from test_tickets import forum_interaction, submit
    i, forum = forum_interaction(FakeMember(ALICE))
    f = ui.DonateForm(ALICE)
    assert f.to_dict()["components"][1]["component"]["required"] is False
    fill(f.what, "3 Spider Silk"); fill(f.character, "Moirin")
    f.screenshot._values = []
    submit(f, i)
    assert "files" not in forum.create_thread.call_args.kwargs
    assert env.by_thread(777).kind == "donate"


def test_donation_carries_the_donor_location(env):
    from test_tickets import forum_interaction, submit
    ui.recipes.load_npcs([{"name": "A banker", "zone": "Night Harbor", "location": "", "sells": []},
                          {"name": "A guard", "zone": "Faelindral", "location": "", "sells": []}])
    z = ui.recipes.zone_name
    assert z("night harbor") == "Night Harbor"
    assert z("  night harbor,  by the bank ") == "Night Harbor, by the bank"
    assert z("Nite Harbor") == "Night Harbor"            # small typo
    assert z("my house") == "my house"                   # unknown places are left alone

    i, forum = forum_interaction(FakeMember(ALICE))
    f = ui.DonateForm(ALICE)
    assert len(f.to_dict()["components"]) == 4
    fill(f.what, "3 Spider Silk"); fill(f.location, "faelindral bank"); fill(f.character, "Moirin")
    f.screenshot._values = []
    submit(f, i)
    kw = forum.create_thread.call_args.kwargs
    assert kw["content"].endswith("· 📍 Faelindral bank")
    t = env.by_thread(777)
    assert t.fields["location"] == "Faelindral bank"
    assert any(fl.name == "📍 Donor is at" and fl.value == "Faelindral bank" for fl in ui.embed(t).fields)
