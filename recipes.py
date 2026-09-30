"""Wiki data: recipes (from Mo Betta Crafts) and items (from Mo Betta Quests), both scraped from the community wiki.

Recipes: when someone asks for "20 Iron Rivets", the ticket shows the recipe (skill, station, ingredients
scaled to the quantity), and a "no mats" request pre-fills the gathering form with that shopping list.
Items: consistent spelling for whatever people type, autocomplete, and a category for the bank inventory.
If a file can't be downloaded or an item isn't known, everything simply carries on with the typed text.
"""
from __future__ import annotations

import difflib
import json
import logging
import math
import re
import time
import urllib.request
from pathlib import Path

SOURCES = {
    "recipes.json": "https://raw.githubusercontent.com/amyklindley/mo-betta-crafts/main/recipes.json",
    "items.json": "https://raw.githubusercontent.com/amyklindley/mo-betta-quests/main/items.json",
}
DATA = Path(__file__).resolve().parent / "data"
CACHE = DATA / "recipes.json"  # items.json sits next to it
MAX_AGE = 24 * 3600

CATEGORIES = ["⚔️ Weapons", "🛡️ Armor", "💍 Jewelry", "🎒 Bags", "🧪 Potions", "🍖 Food & Drink",
              "📜 Spells & Scrolls", "🪨 Crafting materials", "📦 Other"]

log = logging.getLogger("castle.recipes")


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", s.lower().replace("'", "")).strip()


class Recipes:
    def __init__(self, cache: Path = CACHE) -> None:
        self.cache = cache
        self.by_name: dict[str, list[dict]] = {}
        self.materials: dict[str, str] = {}  # norm(name) -> wiki spelling, for everything recipes use
        self.items: dict[str, dict] = {}     # norm(name) -> wiki item record

    def load(self, recipes: list[dict]) -> None:
        by_name: dict[str, list[dict]] = {}
        materials: dict[str, str] = {}
        for r in recipes:
            if not r.get("salvage"):
                by_name.setdefault(norm(r["name"]), []).append(r)
            for ing in r.get("ingredients", []):
                if not ing.get("tool"):
                    materials.setdefault(norm(ing["name"]), ing["name"])
        self.by_name, self.materials = by_name, materials

    def load_items(self, items: list[dict]) -> None:
        self.items = {norm(it["name"]): it for it in items if it.get("name")}

    def refresh(self) -> None:
        """Download fresh copies of any file that's missing or a day old, then load whatever we have."""
        for name, url in SOURCES.items():
            path = self.cache.parent / name
            try:
                if not path.exists() or time.time() - path.stat().st_mtime > MAX_AGE:
                    path.parent.mkdir(exist_ok=True)
                    with urllib.request.urlopen(url, timeout=60) as resp:
                        body = resp.read()
                    json.loads(body)  # don't replace a good cache with a broken download
                    path.write_bytes(body)
            except Exception as e:  # network trouble just means we keep yesterday's copy
                log.warning("%s download failed: %s", name, e)
        try:
            self.load(json.loads(self.cache.read_text("utf-8"))["recipes"])
            log.info("recipes loaded: %d names", len(self.by_name))
        except (OSError, ValueError, KeyError) as e:
            log.warning("no recipes available: %s", e)
        try:
            self.load_items(json.loads((self.cache.parent / "items.json").read_text("utf-8"))["items"])
            log.info("items loaded: %d", len(self.items))
        except (OSError, ValueError, KeyError) as e:
            log.warning("no item list available: %s", e)

    # ---------------------------------------------------------------- items (bank, spelling)

    def item_name(self, text: str) -> str:
        """The wiki's spelling of an item name if we know it (allowing a plural 's'), else the text as typed."""
        text = " ".join(text.split())
        q = norm(text)
        for key in (q, q[:-1] if q.endswith("s") else None, q[:-2] if q.endswith("es") else None):
            if not key:
                continue
            if key in self.items:
                return self.items[key]["name"]
            if key in self.materials:
                return self.materials[key]
            if key in self.by_name:
                return self.by_name[key][0]["name"]
        return text

    def item_choices(self, query: str, limit: int = 25) -> list[str]:
        keys = rank(query, list(self.items) + [k for k in self.materials if k not in self.items], limit)
        return [self.items[k]["name"] if k in self.items else self.materials[k] for k in keys]

    def icon(self, name: str) -> str | None:
        it = self.items.get(norm(name))
        return (it.get("image") or None) if it else None

    def category(self, name: str) -> str:
        """Which bank section an item belongs in, from its wiki slot, recipe skill or role in recipes."""
        q = norm(name)
        it = self.items.get(q)
        slot = (it or {}).get("slot", "").upper()
        if any(s in slot for s in ("PRIMARY", "SECONDARY", "RANGE", "AMMO")):
            return "⚔️ Weapons"
        if any(s in slot for s in ("BAG", "BACKPACK", "BELT")):
            return "🎒 Bags"
        if any(s in slot for s in ("NECK", "FINGER", "EAR")):
            return "💍 Jewelry"
        if slot:
            return "🛡️ Armor"
        skills = {r.get("skill", "") for r in self.by_name.get(q, [])}
        words = set(q.split())
        if q.startswith(("spell ", "scroll", "tome ", "song ", "enchant ")) or "Enchanting" in skills:
            return "📜 Spells & Scrolls"
        if skills & {"Alchemy", "Poison Making"} or words & {"potion", "elixir", "tonic", "salve", "poison", "philter"}:
            return "🧪 Potions"
        if skills & {"Cooking", "Brewing", "Baking"} or words & {"ale", "wine", "whiskey", "mead", "water", "bread",
                                                                 "stew", "pie", "rations", "meat", "milk", "cheese"}:
            return "🍖 Food & Drink"
        if q in self.materials:
            return "🪨 Crafting materials"
        return "📦 Other"

    def find(self, item: str) -> dict | None:
        """The recipe for an item name, allowing small typos and a trailing plural 's'."""
        q = norm(item)
        if not q or not self.by_name:
            return None
        for key in (q, q[:-1] if q.endswith("s") else None, q[:-2] if q.endswith("es") else None):
            if key and key in self.by_name:
                return self.by_name[key][0]
        close = difflib.get_close_matches(q, self.by_name.keys(), n=1, cutoff=0.88)
        return self.by_name[close[0]][0] if close else None

    # ---------------------------------------------------------------- autocomplete for /craft and /gather

    def craft_choices(self, query: str, limit: int = 25) -> list[tuple[str, str]]:
        """(label, wiki name) pairs for craftable items matching what's been typed so far."""
        keys = rank(query, self.by_name.keys(), limit)
        out = []
        for k in keys:
            r = self.by_name[k][0]
            skills = sorted({x.get("skill", "") for x in self.by_name[k]} - {""})
            out.append((f"{r['name']} ({', '.join(skills)})" if skills else r["name"], r["name"]))
        return out

    def material_choices(self, query: str, limit: int = 25) -> list[str]:
        """Wiki names of crafting materials matching what's been typed so far."""
        return [self.materials[k] for k in rank(query, self.materials.keys(), limit)]


def rank(query: str, keys, limit: int) -> list[str]:
    """Normalised names best-first: exact, then starts-with, then contains every word, then near misses.
    An empty query lists nothing (Discord shows the box's hint instead)."""
    q = norm(query)
    if not q:
        return []
    keys = list(keys)
    words = q.split()
    exact = [k for k in keys if k == q]
    prefix = sorted((k for k in keys if k.startswith(q) and k != q), key=lambda k: (len(k), k))
    contains = sorted((k for k in keys if all(w in k for w in words) and k != q and not k.startswith(q)),
                      key=lambda k: (len(k), k))
    out = exact + prefix + contains
    if not out:  # only guess at typos when nothing actually matched
        out = difflib.get_close_matches(q, keys, n=limit, cutoff=0.8)
    return out[:limit]


def parse_quantity(text: str) -> int | None:
    m = re.search(r"\d+", text.replace(",", ""))
    return int(m.group()) if m else None


def shopping_list(recipe: dict, quantity: int | None) -> list[str]:
    """Ingredient lines scaled to how many the person wants. Tools are needed once, not per combine."""
    makes = max(int(recipe.get("makes") or 1), 1)
    combines = math.ceil((quantity or makes) / makes)
    out = []
    for ing in recipe.get("ingredients", []):
        if ing.get("tool"):
            out.append(f"{ing['name']} (tool)")
        else:
            out.append(f"{ing.get('qty', 1) * combines} x {ing['name']}")
    return out


def summary(recipe: dict, quantity: int | None) -> str:
    """Two short lines for a ticket embed."""
    makes = max(int(recipe.get("makes") or 1), 1)
    combines = math.ceil((quantity or makes) / makes)
    head = f"{recipe.get('skill', '?')}"
    if recipe.get("trivial"):
        head += f" (trivial {recipe['trivial']})"
    if recipe.get("station"):
        head += f" at a {recipe['station']}"
    per = f"{combines} combine{'s' if combines != 1 else ''}" + (f", makes {makes} each" if makes > 1 else "")
    return f"{head} · {per}\n" + ", ".join(shopping_list(recipe, quantity))
