"""Recipe lookup for crafting tickets, from the same wiki-scraped recipes.json Mo Betta Crafts publishes.

When someone asks for "20 Iron Rivets", the ticket shows the recipe (skill, station, ingredients scaled to
the quantity), and a "no mats" request pre-fills the gathering form with that shopping list. If the file
can't be downloaded or the item isn't a known recipe, tickets simply go without it.
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

SOURCE = "https://raw.githubusercontent.com/amyklindley/mo-betta-crafts/main/recipes.json"
CACHE = Path(__file__).resolve().parent / "data" / "recipes.json"
MAX_AGE = 24 * 3600

log = logging.getLogger("castle.recipes")


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", s.lower().replace("'", "")).strip()


class Recipes:
    def __init__(self, cache: Path = CACHE) -> None:
        self.cache = cache
        self.by_name: dict[str, list[dict]] = {}

    def load(self, recipes: list[dict]) -> None:
        by_name: dict[str, list[dict]] = {}
        for r in recipes:
            if not r.get("salvage"):
                by_name.setdefault(norm(r["name"]), []).append(r)
        self.by_name = by_name

    def refresh(self) -> None:
        """Download a fresh copy if the cached one is missing or a day old, then load whatever we have."""
        try:
            stale = not self.cache.exists() or time.time() - self.cache.stat().st_mtime > MAX_AGE
            if stale:
                self.cache.parent.mkdir(exist_ok=True)
                with urllib.request.urlopen(SOURCE, timeout=30) as resp:
                    body = resp.read()
                json.loads(body)  # don't replace a good cache with a broken download
                self.cache.write_bytes(body)
        except Exception as e:  # network trouble just means we keep yesterday's copy
            log.warning("recipes download failed: %s", e)
        try:
            self.load(json.loads(self.cache.read_text("utf-8"))["recipes"])
            log.info("recipes loaded: %d names", len(self.by_name))
        except (OSError, ValueError, KeyError) as e:
            log.warning("no recipes available: %s", e)

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
