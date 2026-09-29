# Castle Tickets: setup for a server admin

About 10 minutes. You need the **Manage Server** permission. The bot is already written and running;
this just lets it into the server and tells it where to post.

## 1. Invite the bot

Open this link, pick the guild's server, and press **Authorize**:

```
https://discord.com/oauth2/authorize?client_id=<CLIENT_ID>&scope=bot%20applications.commands&permissions=328565115904
```

It asks for: View Channels, Send Messages, Send Messages in Threads, Create Public Threads, Manage Threads,
Embed Links, Attach Files, Read Message History, Use Application Commands. There's no admin, no kicking or
banning, and no reading of messages. *Manage Threads* is how it pins the panel and tags/closes its own posts.

## 2. Make the requests forum

1. Create a **Forum** channel, e.g. `#castle-requests`.
2. Edit Channel → **Permissions**:
   - **@everyone**: turn **off** *Create Posts* and leave *Send Messages in Posts* **on**. Members can
     talk in any ticket, but new tickets only come from the bot's forms, so they all have the same fields.
   - Add the **Castle Tickets** role and turn **on** *Create Posts*, *Send Messages in Posts*, *Manage Threads*,
     *Embed Links*, *Attach Files*.
   - Optional: also give the Castle Tickets role **Manage Channel** *on this forum only*. That lets it create the
     8 forum tags for you (Crafting, Gathering, Bank Donation, Bank Request, Open, Claimed, Done, Cancelled).
     If you'd rather not, create those tags yourself under Edit Channel → Tags. The names have to match.
     Tickets still work without tags; the tags just make the list easy to filter.

## 3. Make the roles pingable

For **@Castle Crafter**, **@Castle Gatherer** and whichever role handles the guild bank: Server Settings → Roles →
the role → turn on **Allow anyone to @mention this role**. That lets the bot ping them when a ticket comes in.

## 4. Run setup

In any channel, type:

```
/tickets setup forum:#castle-requests crafter:@Castle Crafter gatherer:@Castle Gatherer banker:@<bank role> officer:@<officer role>
```

- **banker**: who handles bank donations and requests (it can be the officer role).
- **officer** (optional): can act on any ticket and open guild requisitions ("Guild: raid consumables / equipment")
  on gathering requests. Anyone with Manage Server counts as an officer automatically.

The bot checks its permissions, creates the tags, and posts a pinned, locked **📋 Start a request here** post at
the top of the forum with the four buttons. If anything's missing, it tells you exactly what. Fix it and
run the same command again (it's safe to re-run any time, e.g. to change a role).

## Commands

| Command | Who | What |
|---|---|---|
| `/tickets setup` | Manage Server | Forum, roles, panel (see above) |
| `/tickets mine` | anyone | Your open requests |
| `/tickets queue [kind]` | anyone | Everything open, optionally just one kind |

Only admins see `/tickets setup` by default. You can change who sees what under Server Settings →
Integrations → Castle Tickets.
