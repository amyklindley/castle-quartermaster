"""Finished and cancelled posts are deleted after a while; the ticket record and bank ledger stay."""
from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import test_tickets  # noqa: E402
import ui  # noqa: E402
from store import CANCELLED, CLAIMED, DONE  # noqa: E402
from test_tickets import ALICE, BOB, CRAFTER, GUILD, FakeMember, fake_thread, interaction, press, run  # noqa: E402

env = pytest.fixture()(test_tickets.env.__wrapped__)


def ticket(env, thread_id, status=None, closed_hours_ago=None):
    t = env.create(GUILD, "craft", ALICE, "Moirin", {"item": "Iron Rivets", "quantity": "1", "needed_by": "ASAP"})
    env.attach_thread(t.id, thread_id, thread_id)
    if status:
        env.set_status(t.id, status, claimer_id=BOB)
    if closed_hours_ago is not None:
        env.db.execute("UPDATE tickets SET closed_at = ? WHERE id = ?", (time.time() - closed_hours_ago * 3600, t.id))
        env.db.commit()
    return t.id


def test_only_long_closed_posts_are_due(env):
    old_done = ticket(env, 1, DONE, 30)
    old_cancel = ticket(env, 2, CANCELLED, 25)
    ticket(env, 3, DONE, 2)          # closed recently
    ticket(env, 4, CLAIMED)          # still being worked
    ticket(env, 5)                   # open
    due = env.closed_before(GUILD, time.time() - 24 * 3600)
    assert sorted(t.id for t in due) == [old_done, old_cancel]


def test_cleanup_deletes_posts_and_keeps_records(env, monkeypatch):
    import bot
    monkeypatch.setattr(bot, "store", env)
    old = ticket(env, 1, DONE, 30)
    vanished = ticket(env, 2, DONE, 30)     # someone already deleted this post by hand
    stuck = ticket(env, 3, DONE, 30)        # Discord refuses
    fresh = ticket(env, 4, DONE, 1)
    env.bank_change(GUILD, "Spider Silk", 5, BOB, ticket_id=old)

    threads = {1: MagicMock(delete=AsyncMock()), 4: MagicMock(delete=AsyncMock()),
               3: MagicMock(delete=AsyncMock(side_effect=discord.HTTPException(MagicMock(status=500), "boom")))}
    guild = MagicMock(id=GUILD)
    guild.get_thread = lambda tid: threads.get(tid)
    guild.fetch_channel = AsyncMock(side_effect=discord.NotFound(MagicMock(status=404), "gone"))

    assert run(bot.cleanup_closed(guild)) == 2
    threads[1].delete.assert_awaited_once()
    threads[4].delete.assert_not_awaited()
    assert env.get(old).thread_id is None and env.get(old).status == DONE   # record kept, post gone
    assert env.get(vanished).thread_id is None
    assert env.get(stuck).thread_id == 3                                    # retried next hour
    assert env.get(fresh).thread_id == 4
    assert env.bank_stock(GUILD) == [("Spider Silk", 5)]                    # the bank never forgets


def test_zero_hours_keeps_everything(env, monkeypatch):
    import bot
    monkeypatch.setattr(bot, "store", env)
    s = env.settings(GUILD)
    s.cleanup_hours = 0
    env.save_settings(s)
    ticket(env, 1, DONE, 300)
    guild = MagicMock(id=GUILD)
    assert run(bot.cleanup_closed(guild)) == 0
    assert env.settings(GUILD).cleanup_after == 0


def test_closing_note_says_when_it_goes(env):
    ticket(env, 500, CLAIMED)
    th = fake_thread()
    i = interaction(FakeMember(BOB, [CRAFTER]), th)
    press(ui.Controls(), "done", i)
    assert "tidies itself away in about a day" in th.send.call_args.args[0]
    assert ui._span(1) == "an hour" and ui._span(6) == "6 hours" and ui._span(72) == "3 days"
