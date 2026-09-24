"""Caravan SandWitch bridge client.

Reads the APCaravan UE4SS mod's history export, maps entries to locations
(direct tags, count-based pools, goal), and maintains a desired-state file
the mod applies in-game.

Bridge dir: %LOCALAPPDATA%/CaravanSandWitch/Saved/Archipelago/
  ap_checks.jsonl (mod -> client): {"index":N,"entry":"PE:<tag>.<state>"}
  ap_state.json   (client -> mod): desired state, idempotent:
      {"seed": str, "slot": str,
       "permits": {"antenna": 0-2, "grapple": 0-2, "van": 0-1,
                   "zipline": 0-1, "jammer": 0-1},
       "scraps": {"common": total, "uncommon": total,
                  "rare": total, "epic": total}}
The mod applies scraps as deltas vs its own ap_applied.json and treats
permits as the authoritative gate set. Full-state (not line-based) so
reconnects and out-of-order delivery are inherently safe.
"""

import asyncio
import json
import os
import re

import Utils
from CommonClient import (
    CommonContext, get_base_parser, gui_enabled, logger, server_loop,
)
from NetUtils import ClientStatus

from .locations import LOCATIONS

GAME = "Caravan SandWitch"
ITEM_BASE = 7_680_000
GOAL_ENTRY = "Primary.100SaveNefle.EndSelfDestruct.Common_Done"

BRIDGE_DIR = os.path.join(
    os.environ.get("LOCALAPPDATA", "."), "CaravanSandWitch", "Saved",
    "Archipelago")
CHECKS_FILE = os.path.join(BRIDGE_DIR, "ap_checks.jsonl")
STATE_FILE = os.path.join(BRIDGE_DIR, "ap_state.json")
HEARTBEAT_FILE = os.path.join(BRIDGE_DIR, "ap_heartbeat.txt")
HEARTBEAT_MAX_AGE = 10  # seconds; mod rewrites it every ~2s while running


def _game_is_live() -> bool:
    """True only while the mod's heartbeat is fresh (game actually running).
    Guards against replaying the previous session's ledger lines when the
    client connects before the game is launched."""
    try:
        with open(HEARTBEAT_FILE, encoding="utf-8") as f:
            ts = int(f.read().strip() or "0")
    except (OSError, ValueError):
        return False
    import time
    return (time.time() - ts) < HEARTBEAT_MAX_AGE

# item id offset -> (state key, amount per copy)
PERMIT_ITEMS = {0: "antenna", 1: "grapple", 2: "van", 3: "zipline",
                4: "jammer"}
SCRAP_ITEMS = {10: ("common", 10), 11: ("uncommon", 5), 12: ("rare", 3),
               13: ("epic", 1)}

TAG_TO_ID = {}
POOL_PATTERNS = {
    "mallow":   re.compile(r"(?i)mallow|flower"),
    "plush":    re.compile(r"(?i)plush"),
    "sandwich": re.compile(r"(?i)sandwich"),
    "snack":    re.compile(r"(?i)snack"),
    "teto":     re.compile(r"(?i)teto"),
    "clue":     re.compile(r"(?i)clue"),
}
POOL_SLOT_IDS = {}  # pool -> [location ids in # order]
for key, name, lid, ch, kind, cat in LOCATIONS:
    if kind == "pool":
        pool = key.split(":")[1].split("#")[0]
        POOL_SLOT_IDS.setdefault(pool, []).append(lid)
    else:
        TAG_TO_ID[key] = lid


class CSWContext(CommonContext):
    game = GAME
    items_handling = 0b111

    def __init__(self, server_address, password):
        super().__init__(server_address, password)
        # Session anchoring: ap_checks.jsonl is a cumulative ledger across every
        # game launch. Only entries after the most recent {"session":"start"}
        # marker belong to the currently-running game (and its loaded save), so
        # we anchor to that marker and never replay older sessions.
        self.session_ts = None      # ts of the marker we're anchored to
        self.processed_upto = 0     # line index processed so far
        self.pool_seen = {p: set() for p in POOL_SLOT_IDS}
        self.goal_sent = False
        self._seed = ""

    async def server_auth(self, password_requested: bool = False):
        if password_requested and not self.password:
            await super().server_auth(password_requested)
        await self.get_username()
        await self.send_connect()

    def on_package(self, cmd, args):
        super().on_package(cmd, args)
        # Read seed straight from the RoomInfo packet rather than relying on a
        # base-class attribute name (frozen lib, can't verify). RoomInfo always
        # carries seed_name and always precedes Connected.
        if cmd == "RoomInfo":
            self._seed = args.get("seed_name", "") or ""
        if cmd in ("RoomInfo", "Connected", "ReceivedItems"):
            self.write_state()

    def write_state(self):
        permits = {v: 0 for v in PERMIT_ITEMS.values()}
        scraps = {v[0]: 0 for v in SCRAP_ITEMS.values()}
        for net_item in self.items_received:
            off = net_item.item - ITEM_BASE
            if off in PERMIT_ITEMS:
                permits[PERMIT_ITEMS[off]] += 1
            elif off in SCRAP_ITEMS:
                key, amount = SCRAP_ITEMS[off]
                scraps[key] += amount
        seed = self._seed or getattr(self, "seed_name", "") or ""
        state = {"seed": seed, "slot": self.auth or "",
                 "permits": permits, "scraps": scraps}
        os.makedirs(BRIDGE_DIR, exist_ok=True)
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f)
        os.replace(tmp, STATE_FILE)

    def map_entry(self, entry: str):
        """Return location ids for one history entry (0..1 ids)."""
        if not entry.startswith("PE:"):
            return []
        body = entry[3:]
        identity = body.rsplit(".", 1)[0]
        if body == GOAL_ENTRY:
            self.goal_sent = True  # flag; StatusUpdate sent by watcher
        if identity in TAG_TO_ID:
            return [TAG_TO_ID[identity]]
        for pool, pat in POOL_PATTERNS.items():
            if pool in POOL_SLOT_IDS and pat.search(identity):
                if identity not in self.pool_seen[pool]:
                    self.pool_seen[pool].add(identity)
                    n = len(self.pool_seen[pool])
                    slots = POOL_SLOT_IDS[pool]
                    if n <= len(slots):
                        return [slots[n - 1]]
                return []
        return []


def _find_session_anchor(lines):
    """Return (ts, line_index) of the last {"session":"start"} marker, or
    (None, len(lines)) if none — fail-safe skips everything unanchored."""
    for i in range(len(lines) - 1, -1, -1):
        line = lines[i]
        if '"session"' not in line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("session") == "start":
            return obj.get("ts"), i
    return None, len(lines)


async def watch_checks(ctx: CSWContext):
    announced_waiting = False
    while not ctx.exit_event.is_set():
        try:
            if not _game_is_live():
                # Game not running: touch nothing (offsets included), so when
                # it launches we anchor to ITS new session marker, not stale lines.
                if not announced_waiting:
                    logger.info("Waiting for Caravan SandWitch to launch...")
                    announced_waiting = True
                await asyncio.sleep(2)
                continue
            if announced_waiting:
                logger.info("Game detected — bridging checks.")
                announced_waiting = False
            if ctx.server and ctx.slot and os.path.exists(CHECKS_FILE):
                with open(CHECKS_FILE, encoding="utf-8") as f:
                    lines = f.readlines()

                anchor_ts, anchor_idx = _find_session_anchor(lines)
                # New game launch (or first read): re-anchor to this session's
                # marker and forget prior sessions' progress. A loaded save
                # re-exports its full history after the marker, so resume is
                # covered; a fresh New Game simply grows from here.
                if anchor_ts != ctx.session_ts:
                    ctx.session_ts = anchor_ts
                    ctx.processed_upto = anchor_idx + 1
                    ctx.pool_seen = {p: set() for p in POOL_SLOT_IDS}
                    ctx.goal_sent = False

                new = lines[ctx.processed_upto:]
                to_send = set()
                for line in new:
                    try:
                        entry = json.loads(line).get("entry", "")
                    except (json.JSONDecodeError, AttributeError):
                        continue
                    for lid in ctx.map_entry(entry):
                        if lid not in ctx.checked_locations:
                            to_send.add(lid)
                # Only advance past these lines once their checks are actually
                # sent. If the send raises (e.g. socket dropped mid-batch), the
                # lines stay pending and are retried after reconnect.
                if to_send:
                    await ctx.send_msgs([{"cmd": "LocationChecks",
                                          "locations": sorted(to_send)}])
                ctx.processed_upto = len(lines)
                if ctx.goal_sent and not ctx.finished_game:
                    await ctx.send_msgs([{"cmd": "StatusUpdate",
                                          "status": ClientStatus.CLIENT_GOAL}])
                    ctx.finished_game = True
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 - the watcher must never die
            # Was: `except OSError` only. A websocket-closed error during a
            # brief server drop killed this task silently while the client
            # itself reconnected fine -> checks silently stopped (Sept 18).
            logger.warning("check watcher: %s: %s (will retry)",
                           type(e).__name__, e)
        await asyncio.sleep(2)


def launch_client(*args) -> None:
    async def main(args):
        ctx = CSWContext(args.connect, args.password)
        ctx.server_task = asyncio.create_task(server_loop(ctx), name="server loop")
        watcher = asyncio.create_task(watch_checks(ctx), name="check watcher")
        if gui_enabled:
            ctx.run_gui()
        ctx.run_cli()
        await ctx.exit_event.wait()
        watcher.cancel()
        await ctx.shutdown()

    parser = get_base_parser(description="Caravan SandWitch Archipelago client")
    args = parser.parse_args(args)
    Utils.init_logging("CSWClient", exception_logger="Client")
    import colorama
    colorama.just_fix_windows_console()
    asyncio.run(main(args))
    colorama.deinit()
