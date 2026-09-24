-- APCaravan v2: Archipelago bridge mod for Caravan SandWitch (UE4SS Lua).
--
-- v1 (proven stable): poll CSW_KnowledgeSubsystem.History -> ap_checks.jsonl.
-- v2 adds (ALL gated on ap_state.json existing = an AP session is active;
-- without it the mod is a passive exporter and gameplay is 100% vanilla):
--   * ap_state.json (from CSWClient): desired {seed, slot, permits, scraps}
--   * scrap delivery: apply scraps deltas vs ap_applied.json via
--     CSW_InventorySubsystem:AddScrapAmount
--   * scrap pickup zeroing: pre-hook AddScrapAmount, zero world pickups
--     (check still fires via history; AP deliveries bypass via guard flag)
--   * seed binding: AP_SEED raw entry written into the save's history;
--     mismatched save vs state.seed -> refuse deliveries, loud log
--   * build-gate veto: TODO v2.1 (needs live hook discovery); interim
--     enforcement is economic (no free scraps -> can't afford builds)

local BRIDGE_DIR = os.getenv("LOCALAPPDATA") .. "\\CaravanSandWitch\\Saved\\Archipelago"
os.execute('mkdir "' .. BRIDGE_DIR .. '" 2>nul')

local CHECKS_FILE    = BRIDGE_DIR .. "\\ap_checks.jsonl"
local STATE_FILE     = BRIDGE_DIR .. "\\ap_state.json"
local APPLIED_FILE   = BRIDGE_DIR .. "\\ap_applied.json"
-- Liveness: rewritten every poll with os.time(). The client only processes
-- checks while this is fresh, so a client connecting with the game CLOSED
-- never replays the previous session's lines still sitting in the ledger.
local HEARTBEAT_FILE = BRIDGE_DIR .. "\\ap_heartbeat.txt"

local function WriteHeartbeat()
    local f = io.open(HEARTBEAT_FILE, "w")
    if f then f:write(tostring(os.time())) f:close() end
end

local SCRAP_KEYS = { "common", "uncommon", "rare", "epic" }

-- World-scrap suppression via REACTIVE BALANCE ENFORCEMENT (not call hooking).
-- Hooking AddScrapAmount failed: the game calls it constantly in the
-- background (32 idle fires, 0 pickups), so intercepting corrupts the balance.
-- Instead we let the game do whatever, then each poll read the real total with
-- GetScrapAmount() and silently RemoveScrapAmount() any gain that wasn't an AP
-- delivery. Baseline = the save's restored total (on settle); AP deliveries
-- raise the expected total; builds lower it (accepted); world pickups raise
-- the actual above expected -> clawed back. Net: scraps come only from AP.
local SUPPRESS_WORLD_SCRAPS = true

local historyIndex = 0
local stablePolls = 0        -- consecutive polls with no new history (save settled)
local DELIVER_AFTER_STABLE = 2
local pollBusy = false
local deliveringFromAP = false   -- reserved guard (unused by reactive model)
local expectedScrap = { common = 0, uncommon = 0, rare = 0, epic = 0 }
local scrapBaselined = false      -- expectedScrap seeded from the settled save
local seedRefused = false        -- save/seed mismatch latch
local seedMarkerWritten = false

local function Log(msg) print("[APCaravan] " .. msg .. "\n") end

local function AppendLine(path, line)
    local f = io.open(path, "a")
    if f then f:write(line .. "\n") f:close() end
end

local function ReadAll(path)
    local f = io.open(path, "r")
    if not f then return nil end
    local s = f:read("*a")
    f:close()
    return s
end

-- ---------- state / applied files ----------

local function ParseState(raw)
    -- Fixed schema, all keys unique file-wide: targeted extraction is safe.
    local function num(key)
        return tonumber(raw:match('"' .. key .. '"%s*:%s*(%-?%d+)')) or 0
    end
    local state = {
        seed = raw:match('"seed"%s*:%s*"([^"]*)"') or "",
        permits = { antenna = num("antenna"), grapple = num("grapple"),
                    van = num("van"), zipline = num("zipline"),
                    jammer = num("jammer") },
        scraps = {},
    }
    for _, k in ipairs(SCRAP_KEYS) do state.scraps[k] = num(k) end
    return state
end

local function ReadApplied()
    local raw = ReadAll(APPLIED_FILE)
    if not raw then
        return { seed = "", scraps = { common = 0, uncommon = 0, rare = 0, epic = 0 } }
    end
    local a = ParseState(raw)
    return { seed = a.seed, scraps = a.scraps }
end

local function WriteApplied(applied)
    local f = io.open(APPLIED_FILE, "w")
    if not f then return end
    f:write(string.format(
        '{"seed":"%s","scraps":{"common":%d,"uncommon":%d,"rare":%d,"epic":%d}}',
        applied.seed, applied.scraps.common, applied.scraps.uncommon,
        applied.scraps.rare, applied.scraps.epic))
    f:close()
end

-- ---------- v1: history export (+ seed marker scan) ----------

local savedSeedMarker = nil      -- AP_SEED value found in the save's history

local function ExportNewHistory()
    local ks = FindFirstOf("CSW_KnowledgeSubsystem")
    if not ks or not ks:IsValid() then return end
    local history = ks.History
    if not history then return end
    local n = #history
    if n < historyIndex then
        -- History shrank: a different save (or a New Game) was loaded within
        -- this session. Re-export from scratch, reset all per-save state, and
        -- emit a new session marker so the client re-anchors to this save.
        Log("history reset detected (" .. historyIndex .. " -> " .. n ..
            "): new save loaded this session")
        historyIndex = 0
        stablePolls = 0
        scrapBaselined = false
        savedSeedMarker = nil
        seedMarkerWritten = false
        seedRefused = false
        AppendLine(CHECKS_FILE, string.format('{"session":"start","ts":%d}', os.time()))
    end
    if n <= historyIndex then return end
    for i = historyIndex + 1, n do
        local entry = history[i]:ToString()
        local seed = entry:match("^AP_SEED:(.+)$")
        if seed then savedSeedMarker = seed end
        AppendLine(CHECKS_FILE, string.format('{"index":%d,"entry":"%s"}', i, entry))
    end
    historyIndex = n
end

-- ---------- v2: seed binding ----------

local bindingBlockedLogged = false
local function EnsureSeedBinding(state)
    -- Returns true when deliveries are allowed for this save+seed.
    if state.seed == "" then
        if not bindingBlockedLogged then
            Log("binding blocked: ap_state.json seed is EMPTY (client not sending seed)")
            bindingBlockedLogged = true
        end
        return false
    end
    if seedRefused then return false end
    if historyIndex == 0 then return false end -- no save loaded yet
    if savedSeedMarker then
        if savedSeedMarker ~= state.seed then
            seedRefused = true
            Log("!!! SAVE/SEED MISMATCH: save is bound to '" .. savedSeedMarker ..
                "', client session is '" .. state.seed ..
                "'. Deliveries DISABLED. Load the matching save or start a new one.")
            return false
        end
        return true
    end
    if not seedMarkerWritten then
        local ks = FindFirstOf("CSW_KnowledgeSubsystem")
        if ks and ks:IsValid() then
            local ok = pcall(function()
                ks:WriteRawEntryToHistory("AP_SEED:" .. state.seed)
            end)
            if ok then
                seedMarkerWritten = true
                savedSeedMarker = state.seed
                Log("save bound to seed '" .. state.seed .. "'")
                return true
            end
            Log("WriteRawEntryToHistory failed; retrying next poll")
        end
        return false
    end
    return true
end

-- ---------- v2: scrap delivery ----------

local function DeliverScraps(state, applied)
    -- Applied-state belongs to one seed. A different seed means a fresh
    -- multiworld: its scraps have never been paid to this save, so start the
    -- delivered-tally from zero rather than inheriting the old seed's.
    if applied.seed ~= "" and applied.seed ~= state.seed then
        Log("applied-state was for seed '" .. applied.seed ..
            "'; resetting tally for '" .. state.seed .. "'")
        applied.scraps = { common = 0, uncommon = 0, rare = 0, epic = 0 }
    end
    local delta = {}
    local any = false
    for _, k in ipairs(SCRAP_KEYS) do
        delta[k] = math.max(0, (state.scraps[k] or 0) - (applied.scraps[k] or 0))
        if delta[k] > 0 then any = true end
    end
    if not any then return end

    local inv = FindFirstOf("CSW_InventorySubsystem")
    if not inv or not inv:IsValid() then
        Log("delivery pending: CSW_InventorySubsystem not found yet")
        return
    end
    Log(string.format("attempting delivery c+%d u+%d r+%d e+%d",
        delta.common, delta.uncommon, delta.rare, delta.epic))

    deliveringFromAP = true
    local ok, err = pcall(function()
        inv:AddScrapAmount({
            CommonAmount = delta.common, UncommonAmount = delta.uncommon,
            RareAmount = delta.rare, EpicAmount = delta.epic,
        }, true, true)
    end)
    deliveringFromAP = false

    if ok then
        for _, k in ipairs(SCRAP_KEYS) do
            applied.scraps[k] = (applied.scraps[k] or 0) + delta[k]
            expectedScrap[k] = expectedScrap[k] + delta[k]  -- AP scraps are legit
        end
        applied.seed = state.seed
        WriteApplied(applied)
        Log(string.format("delivered scraps c+%d u+%d r+%d e+%d",
            delta.common, delta.uncommon, delta.rare, delta.epic))
    else
        Log("AddScrapAmount failed (will retry): " .. tostring(err))
    end
end

-- ---------- v2: reactive world-scrap suppression ----------

local function ReadScrap(inv)
    local okv, c, u, r, e = pcall(function()
        local a = inv:GetScrapAmount()
        return a.CommonAmount, a.UncommonAmount, a.RareAmount, a.EpicAmount
    end)
    if okv and c ~= nil then
        return { common = c, uncommon = u, rare = r, epic = e }
    end
    return nil
end

local BASELINE_AFTER_STABLE = 3  -- extra margin beyond delivery's gate
local function BaselineScrap(inv)
    if scrapBaselined then return end
    -- Only baseline once a save is actually LOADED (history has entries) and
    -- has settled. At the main menu the history is empty-and-stable, which
    -- looked "settled" and baselined an empty inventory -> the real save's
    -- scraps were then clawed back as "world gains" on load. Never again.
    if historyIndex == 0 then return end
    if stablePolls < BASELINE_AFTER_STABLE then return end
    local cur = ReadScrap(inv)
    if not cur then return end
    for _, k in ipairs(SCRAP_KEYS) do expectedScrap[k] = cur[k] end
    scrapBaselined = true
    Log(string.format("suppression baseline c=%d u=%d r=%d e=%d",
        expectedScrap.common, expectedScrap.uncommon,
        expectedScrap.rare, expectedScrap.epic))
end

local function EnforceScrap(inv)
    if not SUPPRESS_WORLD_SCRAPS or not scrapBaselined then return end
    local cur = ReadScrap(inv)
    if not cur then return end
    local remove, any = {}, false
    for _, k in ipairs(SCRAP_KEYS) do
        if cur[k] > expectedScrap[k] then
            remove[k] = cur[k] - expectedScrap[k]   -- world gain -> claw back
            any = true
        else
            remove[k] = 0
            expectedScrap[k] = cur[k]               -- spent (build) -> accept
        end
    end
    if any then
        local ok, err = pcall(function()
            inv:RemoveScrapAmount({
                CommonAmount = remove.common, UncommonAmount = remove.uncommon,
                RareAmount = remove.rare, EpicAmount = remove.epic,
            }, false)  -- silent
        end)
        if ok then
            Log(string.format("suppressed world scrap c-%d u-%d r-%d e-%d",
                remove.common, remove.uncommon, remove.rare, remove.epic))
        else
            Log("RemoveScrapAmount failed: " .. tostring(err))
        end
    end
end

-- ---------- main poll ----------

LoopAsync(2000, function()
    if pollBusy then return false end
    pollBusy = true
    ExecuteInGameThread(function()
        WriteHeartbeat()  -- "game is running and ticking"
        local ok, err = pcall(function()
            local before = historyIndex
            ExportNewHistory()
            -- Defer scrap delivery until the history has stopped growing for a
            -- couple polls: a save-load re-exports the whole history, and
            -- delivering mid-load gets clobbered when the save's own inventory
            -- finishes applying.
            if historyIndex == before then
                stablePolls = stablePolls + 1
            else
                stablePolls = 0
            end
            local raw = ReadAll(STATE_FILE)
            if raw and stablePolls >= DELIVER_AFTER_STABLE then
                local state = ParseState(raw)
                local inv = FindFirstOf("CSW_InventorySubsystem")
                if inv and inv:IsValid() then
                    BaselineScrap(inv)                    -- seed expected from settled save
                    if EnsureSeedBinding(state) then
                        DeliverScraps(state, ReadApplied())  -- raises expected
                    end
                    EnforceScrap(inv)                     -- claw back non-AP gains
                end
            end
        end)
        if not ok then Log("poll error: " .. tostring(err)) end
        pollBusy = false
    end)
    return false
end)

AppendLine(CHECKS_FILE, string.format('{"session":"start","ts":%d}', os.time()))
Log("v2 loaded; passive until ap_state.json exists")
