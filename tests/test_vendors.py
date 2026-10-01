"""Vendor hints on gathering requests: bought materials name who sells them and where."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import test_tickets  # noqa: E402
import ui  # noqa: E402
from test_tickets import ALICE, FakeMember, choose, fill, forum_interaction, submit  # noqa: E402

env = pytest.fixture()(test_tickets.env.__wrapped__)

NPCS = [
    {"name": "A cloth armorer", "zone": "Night Harbor", "location": "Night Market. Shortfolk area", "sells": ["Light Thread"]},
    {"name": "Mira Gables", "zone": "Night Harbor", "location": "", "sells": ["Light Thread", "Rough Thread"]},
    {"name": "a gloom widow", "zone": "Blacktide Bay", "location": "", "sells": []},
]
ITEMS = [
    {"name": "Light Thread", "slot": "", "sold_by": ["Faelindral", "Night Harbor", "a cloth armorer", "Old Tam"]},
    {"name": "Spider Silk", "slot": "", "sold_by": []},
]


def load(r):
    r.load_items(ITEMS)
    r.load_npcs(NPCS + [{"name": "Somebody", "zone": "Faelindral", "location": "", "sells": []}])


def test_vendors(env):
    r = ui.recipes
    load(r)
    # merchant pages first, then names from the item page; zone headers ("Faelindral", "Night Harbor") dropped
    assert r.vendors("light thread") == ["A cloth armorer (Night Harbor: Night Market. Shortfolk area)",
                                         "Mira Gables (Night Harbor)", "Old Tam"]
    assert r.vendors("Light Thread", limit=1) == ["A cloth armorer (Night Harbor: Night Market. Shortfolk area)"]
    assert r.vendors("Spider Silk") == [] and r.vendors("Nonsense") == []


def test_gather_ticket_names_the_vendor(env):
    load(ui.recipes)
    i, forum = forum_interaction(FakeMember(ALICE))
    f = ui.GatherForm(ALICE, officer=False)
    fill(f.item, "8 x Spider Silk\n4 x Light Thread"); fill(f.quantity, "see list"); fill(f.character, "Moirin")
    choose(f.needed_by, "ASAP"); choose(f.purpose, "self")
    submit(f, i)
    t = env.by_thread(777)
    assert t.fields["buy"].startswith("**Light Thread**: A cloth armorer (Night Harbor")
    assert "Spider Silk" not in t.fields["buy"]
    field = next(fl for fl in ui.embed(t).fields if fl.name.startswith("🛒"))
    assert "Mira Gables" in field.value and len(field.value) <= 1024
