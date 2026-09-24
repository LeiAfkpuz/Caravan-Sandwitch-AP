# Caravan SandWitch — Archipelago

Work-in-progress [Archipelago](https://archipelago.gg) multiworld support for
**Caravan SandWitch** (Unreal Engine 5.4.3, Steam), built on
[UE4SS](https://github.com/UE4SS-RE/RE-UE4SS).

> ### ⚠️ Spoilers
> This repository contains the game's internal quest and location names,
> including the ending. **Do not browse it if you have not finished the game.**

> ### ⚠️ Not ready to play
> Undergoing its first full playtest. Expect rough edges, and expect location
> IDs to keep changing until a 1.0 — seeds generated today will not stay
> compatible.

If you are here to **mod the game rather than play the randomizer**, go
straight to [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). It documents the
engine version, how the save/event system works, the useful subsystem calls,
and three traps that cost us real debugging time. It is written to be useful
independently of Archipelago.

## What works today

| Area | Status |
|---|---|
| Checks sent from gameplay | ✅ verified in game |
| Items (scraps) delivered into the save | ✅ verified in game |
| World scraps suppressed so scraps come only from the multiworld | ✅ verified in game |
| Save bound to its seed (refuses mismatched saves) | ✅ verified in game |
| World generates and fills | ✅ 622 locations, 13 progression items |
| Logic (region/sphere accuracy) | 🚧 being derived from playtesting |
| Upgrade gating (story still grants upgrades on schedule) | ❌ not implemented |
| In-game "item received" notifications | ❌ not implemented |

Currently the multiworld gates progress through the **scrap economy**: world
scraps are removed on pickup, so the only spendable scrap comes from
Archipelago items, and paid builds cannot happen until it arrives.

## Layout

```
game-mod/          APCaravan — the UE4SS Lua mod (checks, delivery, suppression)
game-mod-census/   APCensus — optional mod that inventories world objects
apworld/           the Archipelago world + its client (packaged .apworld)
data/              location tables, observed spheres, manual corrections
docs/              ARCHITECTURE.md — how the game works internally
tools/             generators and a generate-and-verify script
```

## Install (for development)

1. Install the **experimental** UE4SS build into
   `steamapps/common/CaravanSandwitch/CaravanSandWitch/Binaries/Win64/`
   (`dwmapi.dll` + `ue4ss/` beside the shipping exe).
2. Copy `game-mod/` to `ue4ss/Mods/APCaravan/` and add `APCaravan : 1` to
   `ue4ss/Mods/mods.txt`.
3. Copy `apworld/caravan_sandwitch.apworld` into your Archipelago
   `custom_worlds/` folder. The client appears in the Archipelago Launcher as
   **Caravan SandWitch Client**.

The mod is inert until an Archipelago session is active — with no
`ap_state.json` present it only observes, and gameplay is unmodified.

## Working on the logic

Sphere data is empirical: play with no items, export what was reachable, and
feed it back as logic.

```bash
python tools/gen_locations_py.py          # rebuild locations.py from data/
powershell -File tools/gentest.ps1 -Runs 3   # package, install, generate, verify
```

`data/sphere_overrides.tsv` is the manual correction table — it takes
precedence over observed data, so hand corrections survive future exports.

## Credits

Built by [LeiAfkpuz](https://github.com/LeiAfkpuz) with Claude (Anthropic).
Caravan SandWitch is by Studio Plane Toast / Dear Villagers; this project is an
unofficial fan modification and is not affiliated with or endorsed by them.
