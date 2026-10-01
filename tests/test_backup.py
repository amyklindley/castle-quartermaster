"""The bank must not be lost: daily database backups and a CSV export."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bank  # noqa: E402
from recipes import Recipes  # noqa: E402
from store import Store  # noqa: E402

GUILD, BOB = 1, 1002


def test_daily_backup_is_a_complete_copy(tmp_path):
    s = Store(tmp_path / "t.db")
    s.bank_change(GUILD, "Spider Silk", 12, BOB, note="raid")
    s.create(GUILD, "donate", 5, "Moirin", {"what": "silk"})
    saved = s.backup(tmp_path / "backups")
    assert saved is not None and saved.exists()
    assert s.backup(tmp_path / "backups") is None  # once a day
    s.bank_change(GUILD, "Spider Silk", -12, BOB)  # later damage doesn't touch the copy
    copy = Store(saved)
    assert copy.bank_stock(GUILD) == [("Spider Silk", 12)]
    assert copy.get(1).character == "Moirin"


def test_old_backups_are_pruned(tmp_path):
    folder = tmp_path / "backups"
    folder.mkdir()
    for d in range(1, 10):
        (folder / f"tickets-2020-01-0{d}.db").write_bytes(b"x")
    Store(tmp_path / "t.db").backup(folder, keep=3)
    names = sorted(p.name for p in folder.iterdir())
    assert len(names) == 3 and names[0] == "tickets-2020-01-08.db" and names[1] == "tickets-2020-01-09.db"


def test_export_csv(tmp_path):
    s = Store(tmp_path / "t.db")
    s.bank_change(GUILD, "Spider Silk", 12, BOB, note="raid, with a comma")
    s.bank_change(GUILD, "Spider Silk", -2, BOB, ticket_id=7)
    s.bank_change(GUILD, "Coal", 1, BOB)
    inv, led = bank.export_csv(s, Recipes(cache=tmp_path / "r.json"), GUILD)
    assert inv.splitlines() == ["item,quantity,section", "Coal,1,Other", "Spider Silk,10,Other"]
    rows = led.splitlines()
    assert rows[0] == "id,when_utc,item,change,by_user_id,ticket,note" and len(rows) == 4
    assert rows[1].endswith('Spider Silk,12,1002,,"raid, with a comma"') and ",-2,1002,7," in rows[2]
