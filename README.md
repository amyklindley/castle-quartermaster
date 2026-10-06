# Castle Quartermaster

A Discord bot for the guild's crafting, gathering and guild bank requests. Members press a button, fill in
a short form, and the bot opens a post in the right forum (crafting & gathering, or the guild bank) and pings
the people who handle it. Staff
press **Claim** and **Done** on the post, and the requester gets a DM at each step. Forum tags
(Open / Claimed / Done / Cancelled) turn the channel into a live board anyone can watch or mute.

| Request | Form | Pings | Buttons |
|---|---|---|---|
| 🔨 Crafting | item, quantity, needed by, have the mats?, character | Castle Crafter | Claim → Crafted & delivered |
| 🌿 Gathering | item(s), quantity, needed by, what it's for, character | Castle Gatherer | Claim → Gathered & delivered |
| 📦 Bank donation | what you're donating, screenshot (optional), where you are in game, character | bank role | Received |
| 🏦 Bank request | what you're requesting, what it's for, where you are in game, character | bank role | Approve → Handed over, or Deny |

Every ticket can also be cancelled (by the requester or staff, with an optional reason), unclaimed, and reopened.

**No mats, no craft ticket.** If someone answers "No" to *Do you have the materials?*, no crafting ticket
is created. They get a private reply showing what the recipe needs, scaled to their quantity (from the
wiki's recipe list, the same data Mo Betta Crafts uses), and a button that opens a gathering request
already filled in with that shopping list. When the gathering post is marked done, it grows an
**Open the crafting request** button that re-opens the crafting form, pre-filled, with "Yes, I have the
mats". Nothing sits in the craft queue waiting on materials.

**Guild bank inventory.** When a banker marks a donation **Received** or a request **Handed over**, a small
form asks what actually moved (pre-filled from the ticket, one item per line) and the inventory updates.
`/bank add`, `/bank remove` and `/bank set` cover raid loot, consumables handed out and recounts. A live
**🏦 Guild Bank** board, grouped by category (weapons, armor, potions, crafting materials…), sits under the
bank forum's pinned post (or in a text channel from setup) and redraws itself on every change. Anyone can ask
`/bank show`, `/bank find <item>` (with the wiki's item icon and recent history) or `/bank history`.

Other touches:
- `/craft` and `/gather` open the same forms, but their item box autocompletes from the wiki's recipe list
  (craftable items for `/craft`, crafting materials for `/gather`). Typed item names are also corrected to the
  wiki's spelling when they match, so "iron rivet" is posted as "Iron Rivets".
- Crafting posts show the recipe (skill, trivial, station, ingredients for the quantity asked) when the item is a known recipe.
- "Needed by" is a dropdown (ASAP / Before next raid / This week / No rush), not free text.
- *What do you need it for?* has **Guild: raid consumables** and **Guild: equipment** choices, which only
  officers see, so a guild requisition is visibly different from someone buying mats.
- The form remembers each member's character name.
- Two crafters can't claim the same ticket; only the claimer (or an officer) can unclaim.
- Finished and cancelled posts are deleted a day after they close (the wait leaves time to reopen, or to press
  **Open the crafting request**); `delete_closed_after` in setup changes the wait, and 0 keeps posts forever.
  The ticket record and the bank ledger stay in the database either way. Open posts that Discord auto-archives
  after a quiet week are brought back so they stay visible.
- Donation screenshots are re-posted by the bot, so they don't expire.

## Setup

1. **Create the bot**: <https://discord.com/developers/applications> → **New Application** ("Castle Quartermaster") →
   **Bot** → **Reset Token**, copy it. No privileged intents needed. Copy the **Application ID** from
   General Information too.
2. **Send the server admin [ADMIN-SETUP.md](ADMIN-SETUP.md)** (the invite link in it already has the Application ID).
   They invite the bot, make the forum, and run `/tickets setup`.
3. **Run it** on the Google Cloud VM alongside Mo Betta Bot (SSH into the VM, then):
   ```
   curl -fsSL https://raw.githubusercontent.com/amyklindley/castle-quartermaster/main/deploy.sh -o deploy.sh && bash deploy.sh
   ```
   It asks for the token and the server id once. It installs to `/opt/castle-quartermaster` as its own service
   (`castle-quartermaster`), separate from Mo Betta. Logs: `sudo journalctl -u castle-quartermaster -f`. It's about the
   same size as Mo Betta, so the free e2-micro can run both.

To run it on this PC instead (for testing): `python -m venv .venv`, `.venv\Scripts\pip install -r requirements.txt`,
copy `.env.example` to `.env` and fill it in, then `run.bat`.

## Files

| File | What |
|---|---|
| `bot.py` | startup, `/craft`, `/gather`, `/tickets …`, `/bank …`, housekeeping |
| `bank.py` | bank line parsing, the live inventory board, history formatting |
| `ui.py` | the panel, the four forms, the ticket buttons, how posts look |
| `store.py` | SQLite (`tickets.db`): tickets, settings, bank ledger, remembered character names |
| `recipes.py` | wiki recipes and items: lookup, spelling, autocomplete, bank categories |
| `tests/` | offline tests with fake Discord objects: `.venv\Scripts\python -m pytest -q` |

## The data, and keeping it

Everything the bot knows (tickets, settings, the bank ledger) is in one file, `tickets.db`, next to `bot.py`.
Updates never touch it. Three layers keep it safe:

- **Daily copies**: the bot writes `backups/tickets-YYYY-MM-DD.db` once a day and keeps 60 days.
- **Before every update**: `deploy.sh` copies `tickets.db` to `backups/before-update-….db` first.
- **Off the server**: `/bank export` hands a banker two spreadsheets, the inventory and the full ledger. The
  ledger alone is enough to rebuild the bank, so saving one now and then covers even losing the whole VM.

To restore: stop the service, copy a backup over `tickets.db`, start the service.
