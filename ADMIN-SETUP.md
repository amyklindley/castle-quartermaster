# Castle Quartermaster: setup for a server admin

About 10 minutes. You need the **Manage Server** permission. The bot is already written and running;
this just lets it into the server and tells it where to post.

## 1. Invite the bot

Open this link, pick the guild's server, and press **Authorize**:

```
https://discord.com/oauth2/authorize?client_id=1554547394249621584&scope=bot%20applications.commands&permissions=328565115904
```

It asks for: View Channels, Send Messages, Send Messages in Threads, Create Public Threads, Manage Threads,
Embed Links, Attach Files, Read Message History, Use Application Commands. There's no admin, no kicking or
banning, and no reading of messages. *Manage Threads* is how it pins the panel and tags/closes its own posts.

## 2. Make the forums

1. Create two **Forum** channels: one for crafting and gathering, e.g. `#castle-requests`, and one for the guild
   bank, e.g. `#guild-bank`. (One forum for everything also works; then skip `bank_forum` below.) For each:
2. Edit Channel → **Permissions**:
   - **@everyone**: turn **off** *Create Posts* and leave *Send Messages in Posts* **on**. Members can
     talk in any ticket, but new tickets only come from the bot's forms, so they all have the same fields.
   - Add the **Castle Quartermaster** role and turn **on** *Create Posts*, *Send Messages in Posts*, *Manage Threads*,
     *Embed Links*, *Attach Files*.
   - Optional: also give the Castle Quartermaster role **Manage Channel** *on this forum only*. That lets it create the
     8 forum tags for you (Crafting, Gathering, Bank Donation, Bank Request, Open, Claimed, Done, Cancelled).
     If you'd rather not, create those tags yourself under Edit Channel → Tags. The names have to match.
     Tickets still work without tags; the tags just make the list easy to filter.

## 3. Make the roles pingable

For **@Castle Crafter**, **@Castle Gatherer** and whichever role handles the guild bank: Server Settings → Roles →
the role → turn on **Allow anyone to @mention this role**. That lets the bot ping them when a ticket comes in.

## 4. Run setup

In any channel, type:

```
/tickets setup forum:#castle-requests crafter:@Castle Crafter gatherer:@Castle Gatherer banker:@<bank role> bank_forum:#guild-bank officer:@<officer role>
```

- **banker**: who handles bank donations and requests (it can be the officer role).
- **bank_forum** (optional): the forum for donations and bank requests. It gets its own pinned **🏦 Guild Bank**
  post with the two bank buttons and the live inventory board right under them.
- **bank_channel** (optional): a plain text channel for the inventory board instead, if you'd rather it not sit
  in the bank forum (the bot needs Send Messages and Embed Links there).
- **officer** (optional): can act on any ticket and open guild requisitions ("Guild: raid consumables / equipment")
  on gathering requests. Anyone with Manage Server counts as an officer automatically.

The bot checks its permissions, creates the tags, and pins a **📋 Start a request here** post with the crafting and
gathering buttons at the top of the requests forum, and a **🏦 Guild Bank** post with the bank buttons and inventory
at the top of the bank forum. If anything's missing, it tells you exactly what. Fix it and
run the same command again (it's safe to re-run any time, e.g. to change a role).

## Commands

| Command | Who | What |
|---|---|---|
| `/tickets setup` | Manage Server | Forum, roles, panel (see above) |
| `/craft <item>` | anyone | Opens the crafting form; the item box searches the wiki's recipes as you type |
| `/gather <item>` | anyone | Opens the gathering form; the item box searches crafting materials as you type |
| `/tickets mine` | anyone | Your open requests |
| `/bank show [category]`, `/bank find <item>`, `/bank history [item]` | anyone | What's in the bank |
| `/bank add`, `/bank remove`, `/bank set`, `/bank board` | bank role / officers | Change the inventory by hand, redraw the board |
| `/bank export` | bank role / officers | Download the inventory and full history as spreadsheets (a backup you hold) |
| `/tickets queue [kind]` | anyone | Everything open, optionally just one kind |

Only admins see `/tickets setup` by default. You can change who sees what under Server Settings →
Integrations → Castle Quartermaster.
