-- APCensus: passive world census for Caravan SandWitch (UE4SS Lua).
-- Logs every CSW interactable/placeable as world-partition streaming loads
-- it near the player. No interaction needed — just drive around the map.
-- Output: %LOCALAPPDATA%/CaravanSandWitch/Saved/Archipelago/ap_census.jsonl
--
-- EXPLORATORY: property names for the identity tag are best-guess; the
-- first session's output tells us which guess is right. Everything is
-- pcall-guarded so a wrong guess logs less detail, never crashes.

local BRIDGE_DIR = os.getenv("LOCALAPPDATA") .. "\\CaravanSandWitch\\Saved\\Archipelago"
os.execute('mkdir "' .. BRIDGE_DIR .. '" 2>nul')
local OUT = BRIDGE_DIR .. "\\ap_census.jsonl"

local seen = {}
local count = 0

local function Log(msg) print("[APCensus] " .. msg .. "\n") end

local function Append(line)
    local f = io.open(OUT, "a")
    if f then f:write(line .. "\n") f:close() end
end

local function TryTag(obj)
    -- Try common spots for a gameplay-tag identity on the object or its owner.
    local candidates = { "IdentityTags", "AddedIdentityTags", "IdentityTag", "Tag", "ProgressEntry" }
    for _, prop in ipairs(candidates) do
        local ok, val = pcall(function() return obj[prop] end)
        if ok and val then
            local ok2, s = pcall(function()
                if val.GameplayTags then                -- FGameplayTagContainer
                    local t = val.GameplayTags
                    if #t > 0 then return t[1].TagName:ToString() end
                elseif val.TagName then                  -- FGameplayTag
                    return val.TagName:ToString()
                end
                return tostring(val)
            end)
            if ok2 and s and s ~= "" and s ~= "None" then return prop, s end
        end
    end
    return nil, nil
end

local function Record(obj, kind)
    local ok, err = pcall(function()
        if not obj:IsValid() then return end
        local full = obj:GetFullName()
        if seen[full] then return end
        seen[full] = true

        local tagProp, tag = TryTag(obj)
        if not tag then
            local okO, owner = pcall(function() return obj:GetOwner() end)
            if okO and owner and owner:IsValid() then
                tagProp, tag = TryTag(owner)
            end
        end

        local x, y, z = 0, 0, 0
        pcall(function()
            local actor = obj.GetOwner and obj:GetOwner() or obj
            local loc = actor:K2_GetActorLocation()
            x, y, z = loc.X, loc.Y, loc.Z
        end)

        count = count + 1
        Append(string.format(
            '{"kind":"%s","name":"%s","tagProp":"%s","tag":"%s","x":%.0f,"y":%.0f,"z":%.0f}',
            kind, full, tostring(tagProp), tostring(tag), x, y, z))
        if count % 50 == 0 then Log(count .. " objects recorded") end
    end)
    if not err == nil then Log("record error: " .. tostring(err)) end
end

-- Sweep-only design: NotifyOnNewObject fired during actor construction and
-- caused a native access violation (crash, July 11 2026). FindAllOf in a
-- periodic sweep only ever sees fully-constructed objects. A 10s interval
-- vs streaming range means negligible risk of missing cells while driving.
LoopAsync(10000, function()
    ExecuteInGameThread(function()
        pcall(function()
            local a = FindAllOf("CSW_InteractableComponent") or {}
            for _, o in ipairs(a) do Record(o, "interactable") end
            local b = FindAllOf("CSW_Placeable") or {}
            for _, o in ipairs(b) do Record(o, "placeable") end
            local c = FindAllOf("CSW_IdentityComponent") or {}
            for _, o in ipairs(c) do Record(o, "identity") end
        end)
    end)
    return false
end)

Log("armed — drive around; streamed-in objects are recorded to ap_census.jsonl")
