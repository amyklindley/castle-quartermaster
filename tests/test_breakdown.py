"""Breaking a craft down through crafted ingredients until only raw materials are left."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

import test_tickets  # noqa: E402
import ui  # noqa: E402
from test_tickets import ALICE, RIVETS, FakeMember, choose, fill, forum_interaction, interaction, run, submit  # noqa: E402

env = pytest.fixture()(test_tickets.env.__wrapped__)  # same store + settings setup as the ticket tests

CANVAS = {"name": "Leather Canvas", "skill": "Leatherworking", "makes": 1,
          "ingredients": [{"qty": 6, "name": "Leather Scraps", "tool": False}, {"qty": 1, "name": "Awl", "tool": True}]}
THREAD = {"name": "Sinew Thread", "skill": "Tailoring", "makes": 4, "ingredients": [{"qty": 1, "name": "Sinew", "tool": False}]}
PACK = {"name": "Leatherback Pack", "skill": "Leatherworking", "makes": 1,
        "ingredients": [{"qty": 2, "name": "Leather Canvas", "tool": False}, {"qty": 3, "name": "Sinew Thread", "tool": False},
                        {"qty": 1, "name": "Brass Buckle", "tool": False}]}


def test_breakdown_goes_down_to_raw_materials(env):
    r = ui.recipes
    r.load([RIVETS, CANVAS, THREAD, PACK])
    b = r.breakdown(PACK, 3)
    # 6 canvas -> 36 scraps; 9 thread at 4 per combine -> 3 combines -> 3 sinew; buckles aren't craftable
    assert b.raw == [("Brass Buckle", 3), ("Leather Scraps", 36), ("Sinew", 3)]
    assert b.made == [("Leather Canvas", 6, "Leatherworking"), ("Sinew Thread", 9, "Tailoring")]
    assert b.tools == ["Awl"]
    flat = r.breakdown(RIVETS, 20)
    assert flat.raw == [("Coal", 10), ("Iron Bar", 5)] and flat.made == []


def test_breakdown_survives_a_recipe_loop(env):
    a = {"name": "A", "makes": 1, "ingredients": [{"qty": 1, "name": "B", "tool": False}]}
    b = {"name": "B", "makes": 1, "ingredients": [{"qty": 1, "name": "A", "tool": False}, {"qty": 1, "name": "Ore", "tool": False}]}
    ui.recipes.load([a, b])
    assert ("Ore", 1) in ui.recipes.breakdown(a, 1).raw


def test_no_mats_asks_for_raw_materials(env):
    ui.recipes.load([CANVAS, THREAD, PACK])
    i = interaction(FakeMember(ALICE))
    f = ui.CraftForm(ALICE)
    fill(f.item, "leatherback pack"); fill(f.quantity, "1"); fill(f.character, "Moirin")
    choose(f.needed_by, "ASAP"); choose(f.mats, "no")
    submit(f, i)
    text = i.response.send_message.call_args.args[0]
    assert "2 x Leather Canvas" in text and "12 x Leather Scraps" in text
    view = i.response.send_message.call_args.kwargs["view"]
    i2 = interaction(FakeMember(ALICE))
    run(view.go.callback(i2))
    g = i2.response.send_modal.call_args.args[0]
    assert g.item.default == "1 x Brass Buckle\n12 x Leather Scraps\n1 x Sinew"
    # submitting it notes what gets crafted on the way
    i3, forum = forum_interaction(FakeMember(ALICE))
    fill(g.item, g.item.default); fill(g.quantity, "see list"); fill(g.character, "Moirin")
    choose(g.needed_by, "ASAP"); choose(g.purpose, "craft")
    submit(g, i3)
    assert env.by_thread(777).fields["crafted_first"] == "2 x Leather Canvas (Leatherworking), 3 x Sinew Thread (Tailoring)"


def test_gathering_a_crafted_item_shows_its_raw_materials(env):
    ui.recipes.load([CANVAS])
    i, forum = forum_interaction(FakeMember(ALICE))
    f = ui.GatherForm(ALICE, officer=False)
    fill(f.item, "leather canvas"); fill(f.quantity, "4"); fill(f.character, "Moirin")
    choose(f.needed_by, "ASAP"); choose(f.purpose, "self")
    submit(f, i)
    t = env.by_thread(777)
    assert t.fields["raw"] == "Leather Canvas is crafted (Leatherworking). Raw materials: 24 x Leather Scraps"
    assert any(fl.name.startswith("⛏️") for fl in ui.embed(t).fields)
