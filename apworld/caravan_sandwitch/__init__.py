"""Archipelago world for Caravan SandWitch — v1.

Locations: frozen table in locations.py (from the owner's full-playthrough
history + world census). Items: build-permit upgrades (progressive chains),
scrap bundles (story currency), van skins, snack filler.

Design notes (see repo docs/ARCHITECTURE.md and memory):
- Story/chapters stay vanilla; chapters are regions, gated by the items the
  vanilla story needs at that point (build permits + scrap costs).
- Build-permit model: receiving an upgrade item allows the vanilla build;
  the game-side mod vetoes build interactions until permitted.
- Scrap costs are placeholder estimates until read from the game's cost
  assets at runtime (TUNE_* constants below).
"""

from dataclasses import dataclass

from BaseClasses import Item, ItemClassification, Location, Region
from Options import PerGameCommonOptions
from worlds.AutoWorld import World
from worlds.generic.Rules import set_rule

from .locations import LOCATIONS, SPHERE1_IDS, SPHERE2_IDS

GAME = "Caravan SandWitch"
ITEM_BASE = 7_680_000

PROG_ANTENNA = "Progressive Antenna"
PROG_GRAPPLE = "Progressive Grapple"
VAN_KEYS = "Van Keys"
ZIPLINE = "Zipline"
JAMMER_DESTROYER = "Jammer Destroyer"
VICTORY = "Victory"

SCRAP_BUNDLES = {
    "Common Scraps x10":  (ITEM_BASE + 10, 20),
    "Uncommon Scraps x5": (ITEM_BASE + 11, 12),
    "Rare Scraps x3":     (ITEM_BASE + 12, 8),
    "Epic Scrap":         (ITEM_BASE + 13, 4),
}
SKINS = {f"Van Skin {c}": ITEM_BASE + 20 + i for i, c in enumerate("ABCDE")}
FILLER = "Snack"

ITEMS = {
    PROG_ANTENNA: ITEM_BASE + 0,
    PROG_GRAPPLE: ITEM_BASE + 1,
    VAN_KEYS: ITEM_BASE + 2,
    ZIPLINE: ITEM_BASE + 3,
    JAMMER_DESTROYER: ITEM_BASE + 4,
    **{n: i for n, (i, _) in SCRAP_BUNDLES.items()},
    **SKINS,
    FILLER: ITEM_BASE + 30,
}
PROGRESSION = {PROG_ANTENNA, PROG_GRAPPLE, VAN_KEYS, ZIPLINE, JAMMER_DESTROYER,
               *SCRAP_BUNDLES}

# Placeholder cumulative scrap-bundle requirements per chapter entrance,
# expressed as counts of "Common Scraps x10" (TUNE with real DA_ScrapAmount
# values once read at runtime).
# Real build costs observed in playtest (c/u/r/e):
#   Antenna (ch030) = 13/5/0/0        (Sept 9)
#   Grapple (ch040) = 41/21/11/0      (Sept 18)
#   PowerCable, Zipline (ch070)       = still unobserved (byte-scan hints only)
# Bundles: Common x10, Uncommon x5, Rare x3, Epic x1. Thresholds are the
# CUMULATIVE cost of every paid build needed to enter that chapter, rounded
# up to whole bundles. Cumulative through Grapple = 54/26/11 -> 6c/6u/4r.
TUNE_BUNDLES_BY_CHAPTER = {
    40: {"Common Scraps x10": 2, "Uncommon Scraps x5": 1},
    50: {"Common Scraps x10": 6, "Uncommon Scraps x5": 6, "Rare Scraps x3": 4},
    60: {"Common Scraps x10": 6, "Uncommon Scraps x5": 6, "Rare Scraps x3": 4},
    70: {"Common Scraps x10": 9, "Uncommon Scraps x5": 9, "Rare Scraps x3": 6,
         "Epic Scrap": 1},  # estimate until cable/zipline costs observed
}

# What each chapter's story needs before it can start (build permits etc.).
CHAPTER_ITEM_REQS = {
    20: [(VAN_KEYS, 1)],
    30: [(VAN_KEYS, 1)],
    # 040 is the chapter you ACQUIRE the grapple in: entering it needs only the
    # antenna (built at 030). Grapple gates 050 onward.
    40: [(VAN_KEYS, 1), (PROG_ANTENNA, 1)],
    50: [(VAN_KEYS, 1), (PROG_ANTENNA, 1), (PROG_GRAPPLE, 1),
         (JAMMER_DESTROYER, 1)],
    60: [(VAN_KEYS, 1), (PROG_ANTENNA, 2), (PROG_GRAPPLE, 1),
         (JAMMER_DESTROYER, 1)],
    70: [(VAN_KEYS, 1), (PROG_ANTENNA, 2), (PROG_GRAPPLE, 2),
         (JAMMER_DESTROYER, 1), (ZIPLINE, 1)],
    80: [(VAN_KEYS, 1), (PROG_ANTENNA, 2), (PROG_GRAPPLE, 2),
         (JAMMER_DESTROYER, 1), (ZIPLINE, 1)],
    90: [(VAN_KEYS, 1), (PROG_ANTENNA, 2), (PROG_GRAPPLE, 2),
         (JAMMER_DESTROYER, 1), (ZIPLINE, 1)],
    100: [(VAN_KEYS, 1), (PROG_ANTENNA, 2), (PROG_GRAPPLE, 2),
          (JAMMER_DESTROYER, 1), (ZIPLINE, 1)],
}

# Per-location extra requirements by census category.
CATEGORY_REQS = {
    "jammer": [(JAMMER_DESTROYER, 1)],
    "door/gate": [(PROG_GRAPPLE, 1)],
    "energy": [(PROG_GRAPPLE, 2)],
}

# Every gate chapter gets a region even if no location's chapter column is
# that value (the chapter heuristic never assigned 40, but Sphere 2 lives in
# the Chapter 40 region and CHAPTER_ITEM_REQS/TUNE_* key on it).
CHAPTERS = sorted({loc[3] for loc in LOCATIONS} | set(range(10, 101, 10)))


@dataclass
class CSWOptions(PerGameCommonOptions):
    pass


class CSWItem(Item):
    game = GAME


class CSWLocation(Location):
    game = GAME


class CaravanSandWitchWorld(World):
    """Cozy post-apocalyptic exploration: drive your van across Cigalo,
    upgrade it, and find out what happened to your sister."""
    game = GAME
    options_dataclass = CSWOptions
    options: CSWOptions

    item_name_to_id = ITEMS
    location_name_to_id = {name: lid for _, name, lid, _, _, _ in LOCATIONS}
    topology_present = True

    def create_item(self, name: str) -> CSWItem:
        cls = (ItemClassification.progression if name in PROGRESSION
               else ItemClassification.filler)
        return CSWItem(name, cls, ITEMS[name], self.player)

    def create_items(self) -> None:
        pool = [
            self.create_item(PROG_ANTENNA), self.create_item(PROG_ANTENNA),
            self.create_item(PROG_GRAPPLE), self.create_item(PROG_GRAPPLE),
            self.create_item(VAN_KEYS), self.create_item(ZIPLINE),
            self.create_item(JAMMER_DESTROYER),
        ]
        for name, (_, count) in SCRAP_BUNDLES.items():
            pool += [self.create_item(name) for _ in range(count)]
        pool += [self.create_item(name) for name in SKINS]
        fill = len(LOCATIONS) - len(pool)
        pool += [self.create_item(FILLER) for _ in range(fill)]
        self.multiworld.itempool += pool

    def create_regions(self) -> None:
        menu = Region("Menu", self.player, self.multiworld)
        self.multiworld.regions.append(menu)

        chapter_regions = {}
        for ch in CHAPTERS:
            r = Region(f"Chapter {ch}", self.player, self.multiworld)
            chapter_regions[ch] = r
            self.multiworld.regions.append(r)

        prev = menu
        for ch in CHAPTERS:
            reqs = CHAPTER_ITEM_REQS.get(ch, [])
            bundles = TUNE_BUNDLES_BY_CHAPTER.get(ch, 0)
            rule = self._make_rule(reqs, bundles)
            prev.connect(chapter_regions[ch], f"Enter Chapter {ch}", rule)
            prev = chapter_regions[ch]

        start = chapter_regions[CHAPTERS[0]]
        for key, name, lid, ch, kind, category in LOCATIONS:
            # Empirical override: locations the owner reached with NO items in
            # a fresh playtest live in the start region with no category
            # requirement, regardless of the chapter their original
            # playthrough happened to first touch them in.
            itemless = lid in SPHERE1_IDS
            antenna_only = lid in SPHERE2_IDS
            if itemless:
                region = start
                extra = None
            elif antenna_only:
                # Empirical Sphere 2: reached with Antenna + Van (+ Jammer
                # Destroyer, vanilla-granted in that run), before the Grapple.
                # Chapter 40's entrance carries the Van/Antenna/cost gate.
                region = chapter_regions[40]
                extra = CATEGORY_REQS.get(category) if category == "jammer" else None
            else:
                region = chapter_regions.get(ch) or start
                extra = CATEGORY_REQS.get(category)
            loc = CSWLocation(self.player, name, lid, region)
            if extra:
                loc.access_rule = self._make_rule(extra, {})
            region.locations.append(loc)

        finale = chapter_regions[CHAPTERS[-1]]
        ending = CSWLocation(self.player, "Ending", None, finale)
        ending.place_locked_item(
            CSWItem(VICTORY, ItemClassification.progression, None, self.player))
        finale.locations.append(ending)
        self.multiworld.completion_condition[self.player] = (
            lambda state: state.has(VICTORY, self.player))

    def _make_rule(self, reqs, bundles):
        def rule(state, reqs=tuple(reqs), bundles=tuple((bundles or {}).items())):
            for item, count in reqs:
                if not state.has(item, self.player, count):
                    return False
            for item, count in bundles:
                if not state.has(item, self.player, count):
                    return False
            return True
        return rule

    def set_rules(self) -> None:
        pass  # all rules are set in create_regions

    def get_filler_item_name(self) -> str:
        return FILLER

    def fill_slot_data(self):
        return {"table_version": 1}


try:
    from worlds.LauncherComponents import (
        Component, Type, components, launch_subprocess)

    def _launch_client(*args) -> None:
        from .CSWClient import launch_client
        launch_client(*args)

    components.append(Component(
        "Caravan SandWitch Client",
        component_type=Type.CLIENT,
        func=lambda *args: launch_subprocess(
            _launch_client, name="Caravan SandWitch Client", args=args),
        game_name=GAME,
        supports_uri=True,
    ))
except Exception:
    pass
