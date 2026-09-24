# Data files

> **Spoilers.** Everything here contains the game's internal quest and location
> names, including the ending.

**Source** — hand-authored or captured; edit these, then regenerate.

| File | What it is |
|---|---|
| `curation_worksheet.tsv` | Every candidate location, with the owner's `include` Y/N marks. The human decision layer. |
| `sphere_overrides.tsv` | Manual reachability corrections ("X is obtainable without Y"). Highest precedence; survives re-exports. |
| `full_playthrough_history.jsonl` | A complete playthrough's event log, as exported by the mod. The raw material everything else came from. |
| `ap_census.jsonl` | Runtime sweep of world objects: class, identity tag, world position. ~6 MB. Useful well beyond Archipelago — it's the basis for any map or tracker. |

**Derived** — regenerate rather than hand-edit.

| File | Produced by |
|---|---|
| `locations_v1.tsv` | `tools/build_location_table.py` (from the worksheet). IDs are **append-only**; never renumber a published one. |
| `sphere1_observed.tsv`, `sphere2_observed.tsv` | Exported from a playtest: what was reachable with a given item set. |
| `sphere1_unmapped.txt`, `sphere2_unmapped.txt` | Events the game logged that no location covers yet — the curation backlog. |
| `progress_tags.txt`, `world_tags.txt` | Tag names lifted from the game's `DefaultGameplayTags.ini` (pak0). Note this registry is *not* a census: tags are built dynamically, and many registered tags never fire. |
| `census_unreached.txt` | Census objects the owner's playthrough never triggered. |

## How logic gets built

The chapter column in `locations_v1.tsv` records *when the original
playthrough first touched* a location — not when it first became reachable.
Using it as logic was wrong in both directions, so spheres are instead
**measured**: play with a known item set, export what was reachable, feed it
back. `sphere_overrides.tsv` patches whatever the measurement misses, because
an export can only see where the player actually went.

```bash
python tools/gen_locations_py.py            # data/ -> apworld locations.py
powershell -File tools/gentest.ps1 -Runs 3  # package, install, generate, verify
```
