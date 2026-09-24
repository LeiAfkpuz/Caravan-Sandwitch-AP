"""Build the location-curation worksheet: union of everything ever checked
(history) and everything found in the world (census), one row per identity
tag, with enough context to decide include/exclude at a glance.

Output: data/curation_worksheet.tsv  (open in Excel/Sheets)

Chapter assignment fixes the max-number-seen bug: a chapter only becomes
"current" once it shows sustained activity (its entry is corroborated by
more same-chapter entries shortly after), so stray early availability pings
(e.g. 070BuyCable firing during ch.030) no longer poison the windows.
"""

import json
import os
import re
from collections import defaultdict

HISTORY = ["data/full_playthrough_history.jsonl"]
LIVE = os.path.join(os.environ.get("LOCALAPPDATA", ""), "CaravanSandWitch",
                    "Saved", "Archipelago", "ap_checks.jsonl")
CENSUS = "data/ap_census.jsonl"

CATEGORY_RULES = [
    ("scrap",      r"(?i)scrap"),
    ("sitspot",    r"(?i)sitspot"),
    ("vanjump",    r"(?i)vanjump|jump"),
    ("jammer",     r"(?i)jammer"),
    ("door/gate",  r"(?i)door|gate|lever|button"),
    ("collectible",r"(?i)collect|plush|flower|mallow|radio|teto|clue"),
    ("ambient",    r"(?i)ambiant|ambient|music|selftalk|dialogue"),
    ("energy",     r"(?i)energy|generator|plug|relay"),
    ("shop",       r"(?i)vanshop|buy"),
]

def categorize(tag):
    for cat, pat in CATEGORY_RULES:
        if re.search(pat, tag):
            return cat
    return ""

def load_history_entries():
    """Ordered unique PE entries across all sessions."""
    entries, seen = [], set()
    for path in HISTORY + [LIVE]:
        try:
            fh = open(path, encoding="utf-8")
        except OSError:
            continue
        for line in fh:
            try:
                e = json.loads(line).get("entry", "")
            except json.JSONDecodeError:
                continue
            if e.startswith("PE:") and e not in seen:
                seen.add(e)
                entries.append(e[3:])
    return entries

def assign_chapters(entries):
    """Debounced chapter windows: chapter N starts at the first of its
    entries that is corroborated by >=2 more chapter-N entries within the
    next 15 history entries."""
    def chap(e):
        m = re.match(r"Primary\.(\d+)", e)
        return int(m.group(1)) if m else None

    cur, out = 0, {}
    for i, e in enumerate(entries):
        c = chap(e)
        if c and c > cur:
            ahead = sum(1 for x in entries[i + 1:i + 16] if chap(x) == c)
            if ahead >= 2:
                cur = c
        tag = e.rsplit(".", 1)[0]
        out.setdefault(tag, {"chapter": cur, "states": set()})
        out[tag]["states"].add(e.rsplit(".", 1)[1])
    return out

def load_census():
    tags = {}
    try:
        fh = open(CENSUS, encoding="utf-8")
    except OSError:
        return tags
    for line in fh:
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        t = r.get("tag", "nil")
        if t and t not in ("nil", "None") and not t.startswith("UScriptStruct"):
            if t not in tags:
                tags[t] = (r.get("x", 0), r.get("y", 0), r.get("z", 0))
    return tags

def main():
    entries = load_history_entries()
    hist = assign_chapters(entries)
    census = load_census()

    all_tags = sorted(set(hist) | set(census))
    rows = []
    for t in all_tags:
        h = hist.get(t)
        pos = census.get(t)
        src = "both" if (h and pos) else ("history" if h else "census")
        ns = t.split(".")[0]
        cat = categorize(t)
        include = "N" if cat == "ambient" or ns in ("Developers",) else ""
        rows.append({
            "tag": t, "namespace": ns, "source": src,
            "chapter": h["chapter"] if h else "",
            "states": "|".join(sorted(h["states"])) if h else "",
            "category": cat, "include": include,
            "x": f"{pos[0]:.0f}" if pos else "",
            "y": f"{pos[1]:.0f}" if pos else "",
            "z": f"{pos[2]:.0f}" if pos else "",
        })

    cols = ["include", "namespace", "category", "chapter", "source",
            "states", "tag", "x", "y", "z"]
    with open("data/curation_worksheet.tsv", "w", encoding="utf-8") as f:
        f.write("\t".join(cols) + "\n")
        for r in rows:
            f.write("\t".join(str(r[c]) for c in cols) + "\n")

    from collections import Counter
    print(f"rows: {len(rows)}")
    print("by source:", dict(Counter(r["source"] for r in rows)))
    print("by category:", dict(Counter(r["category"] or "(none)" for r in rows).most_common()))
    print("pre-marked exclude:", sum(1 for r in rows if r["include"] == "N"))

if __name__ == "__main__":
    main()
