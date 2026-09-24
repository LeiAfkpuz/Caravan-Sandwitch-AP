# Modding Caravan SandWitch — what we learned

> **Spoiler warning.** Internal names in this repo (gameplay tags, quest ids,
> location tables) spoil the plot, including the ending. Stop here if you have
> not finished the game.

Everything below was verified against the live retail build (Steam, **Unreal
Engine 5.4.3**) between July and September 2026. It is written for anyone
modding this game, not just for the Archipelago work — the Archipelago-specific
parts are marked as such.

## Getting a foothold

- **Engine: UE 5.4.3.** Read it off `Engine/Binaries/Win64/CrashReportClient.exe`
  (file version); the shipping exe carries no version resource.
- **No anti-cheat, no encryption.** Content ships as plain `pakchunk0-11`
  with **no IoStore** (`.utoc`/`.ucas`), so [repak](https://github.com/trumank/repak)
  or FModel opens everything directly.
- **Tooling: [UE4SS](https://github.com/UE4SS-RE/RE-UE4SS) experimental build**
  (supports UE 5.4–5.6). Drop `dwmapi.dll` + `ue4ss/` next to
  `CaravanSandWitch/Binaries/Win64/CaravanSandWitch-Win64-Shipping.exe`.
  Injects cleanly; no special config needed.
- **Dumps.** With UE4SS in place, `Ctrl+J` (object dump) and `Ctrl+Num9`
  (UHT headers) give you ~250 native `CSW_*` classes under
  `ue4ss/UHTHeaderDump/CaravanSandWitch/Public/`. Those headers are the map to
  everything else. (`game-mod-census/` in this repo is a mod that does the
  dumps unattended.)

## The one idea that explains the whole game

**The save is an append-only event log.** `UCSW_KnowledgeSubsystem` holds
`TArray<FString> History`, and essentially all world state is derived by
querying it (`IsProgressInHistory`, `IsRegexInHistory`, and a large family of
`CSW_*Request*` condition classes). Quest availability, NPC spawns, gates,
dialogue variants — all of it asks "is entry X in the history?"

Consequences worth knowing:

- Loading a save **replays the entire history from the beginning**, so a mod
  that watches `History` sees the player's whole playthrough on load, in order.
- Entries come in two shapes:
  - `PE:<GameplayTag>.<State>` — progress entries. Deterministic, stable
    across playthroughs. **These are the useful ones.**
  - `FE:<tag> (<random id>)` — flow-graph traversals. The suffix is random
    per run; filter them out.
- Observed states include `_Collected _Done _Discovered _Activated _Broken
  _Triggered _Unlocked _Deactivated _Pulled`. The set is **not closed**, and
  the devs' typos are load-bearing (`_Triggerd`, `Discoverd`). Match whole
  strings; never enumerate.
- You can write your own entries with `WriteRawEntryToHistory(FString)` — we
  use it to stamp a session id into the save.

The tag universe is registered in `CaravanSandWitch/Config/DefaultGameplayTags.ini`
inside pak0 (~4,168 tags: `World.*`, `Primary.*`, `Secondary.*`). Note the
registry is **not** a census of real objects — entries are built dynamically
under registered parents, and plenty of registered tags never fire.

## Player progression

`ECSW_PlayerUpgrade` is a bitmask on `ACSW_GameStateBase`:

| Bit | Upgrade | Bit | Upgrade |
|---:|---|---:|---|
| 1 | CharacterBreakJammer | 16 | CanUseVan |
| 2 | CharacterUseZipLine | 32 | GrappleCanGrab |
| 4 | AntennaDetectComputer | 64 | GrappleCanEnergize |
| 8 | AntennaDetectEnvironment | 128 | AntennaHack |

`UnlockUpgrade(int32)` / `LockUpgrade(int32)` / `HasPlayerUpgrade(int32)` are
all BlueprintCallable, so a Lua mod can grant or revoke abilities directly.
`DT_PlayerUpgrades` (in `Core/Characters/`) maps each upgrade to its inventory
item, van tool, scrap cost asset, and the progress entry it writes.

Real build costs, observed in play (common/uncommon/rare/epic):
Antenna **13/5/0/0**, Grapple **41/21/11/0**. Cable and zipline unconfirmed.

## Inventory and the scrap economy

`UCSW_InventorySubsystem` (a GameInstance subsystem):

```
FScrapAmount GetScrapAmount()
void AddScrapAmount(FScrapAmount, bool bNotify, bool bAllowDiscovery)
void RemoveScrapAmount(FScrapAmount, bool bNotify)
void AddItem(TSubclassOf<UCSWItem>, int32, bool, bool) / RemoveItem / ItemCount / ...
```

`FScrapAmount` is four ints (`CommonAmount`, `UncommonAmount`, `RareAmount`,
`EpicAmount`). **From UE4SS Lua you can pass a plain table** —
`inv:AddScrapAmount({CommonAmount=10, ...}, true, true)` works.

> ### Trap: `AddScrapAmount` is not a pickup signal
> We spent a long evening on this. The function fires constantly in the
> background — we logged **32 calls while standing still with zero pickups** —
> and it is also how the game restores your balance during a save load.
> Hooking it to suppress world pickups corrupts the real balance and can wipe
> a save's scraps on load.
>
> **What works instead:** ignore the call entirely and reconcile the *total*.
> Read `GetScrapAmount()` on a timer, compare against what you expect, and
> `RemoveScrapAmount(diff, false)` the excess. Gains you didn't authorise
> vanish; spending at a build station lowers the total legitimately; background
> chatter that nets to zero is invisible. See `game-mod/Scripts/main.lua`.

> ### Trap: parameter mutation in hooks
> Mutating a by-value struct param and calling `:set()` on it does **not**
> propagate to the game. Writing fields directly on the `:get()` proxy does.

## Objects in the world

World objects carry a `CSW_IdentityComponent` (it inherits `IdentityTags`, an
`FGameplayTagContainer`, from Flow's `UFlowComponent`). **That component, not
the actor or the interactable, is where the tag lives** — if you want to know
"what is this thing," read it there.

Collectibles are Blueprint actors named `BP_Actor_Collectible_*` —
`ScrapMetal_*`, `Sandwich`, `OrnementalFlower`, `Plushy`, `SandwitchClue_*`,
`MusicInstrument`, `AccessCard`, `Archives*`, and so on. Each carries a
`BP_PlayerInteractable_Component` plus the identity component.

> ### Trap: `NotifyOnNewObject` during world-partition streaming
> Registering for component construction notifications crashed the game with a
> native access violation (half-constructed objects; Lua `pcall` cannot catch
> those). Use a **periodic `FindAllOf` sweep** instead — it only ever returns
> fully constructed objects. `game-mod-census/` does this and is stable.

## Other useful bits

- **Saves** live in `%LOCALAPPDATA%/CaravanSandWitch/Saved/SaveGames/SaveSlot_NN/`
  and are compressed/encrypted — *not* plain GVAS. Reading state at runtime via
  the subsystems is far easier than parsing them.
- **No death or damage**, and an "unstuck" feature that teleports the van back
  to the hub without writing any history — a safe primitive if you ever want
  to fence the player out of an area (`CSW_PawnTeleportSubsystem`).
- Audio is FMOD; there are `OnlineSubsystemGOG`, `StoveSDK` and Interhaptics
  plugins in the build.
- The game ships its own cheat blueprints (`Core/Cheats/`), including
  `BP_Actor_Cheat_UnlockUpgrade` — handy for confirming intended call patterns.

## Archipelago-specific layer

Only relevant if you care about the randomizer itself.

- `game-mod/` — the `APCaravan` UE4SS Lua mod: exports history, delivers items,
  enforces the scrap economy, binds a save to a seed.
- `apworld/caravan_sandwitch/` — the Archipelago world and its client.
- Game ↔ client talk through JSONL/JSON files in
  `%LOCALAPPDATA%/CaravanSandWitch/Saved/Archipelago/`:

  | File | Direction | Purpose |
  |---|---|---|
  | `ap_checks.jsonl` | mod → client | every history entry, plus a marker per launch |
  | `ap_state.json` | client → mod | desired state (seed, permits, scrap totals) |
  | `ap_applied.json` | mod-local | what has actually been granted (idempotency) |
  | `ap_heartbeat.txt` | mod → client | liveness; the client ignores the ledger unless this is fresh |

  `ap_checks.jsonl` is **cumulative across launches**, which is why both the
  session marker and the heartbeat exist: without them a client that connects
  while the game is closed will happily replay someone's entire playthrough.
