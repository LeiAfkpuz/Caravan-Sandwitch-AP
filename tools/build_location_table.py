"""Resolve the curated worksheet into the frozen v1 location table.

Policy (agreed July 12, 2026):
  1. User's explicit Y/N always wins.
  2. Blank Primary/Secondary rows: include if a completion-ish state was
     observed (Common_Done, *_Collected, *_Broken, Upgrade_Unlocked, ...);
     exclude availability pings, checkpoints, and census-only ambient.
  3. Capped collectible pools (mallow/plush/sandwich/snack/teto/clue) become
     count-based locations: pool cap = number the user actually collected
     (the quest closes the pool at its requirement). Individual pool tags are
     replaced by "<Pool> #1..#cap".
  4. Blank World rows stay out of v1 (census-only, unverified) — revisit for
     v1.1 with the static parse.

Output: data/locations_v1.tsv (tag/pool, name, id, chapter, kind)
IDs are BASE+index over a sorted freeze; NEVER renumber — append only.
"""

import csv
import re
from collections import defaultdict

BASE_ID = 7_681_000
POOLS = {
    "mallow":   ("Mallow Flower", r"(?i)mallow|flower"),
    "plush":    ("Plushy",        r"(?i)plush"),
    "sandwich": ("Sandwich Clue", r"(?i)sandwich"),
    "snack":    ("Snack",         r"(?i)snack"),
    "teto":     ("Teto",          r"(?i)teto"),
    "clue":     ("Clue",          r"(?i)clue"),
}
GOOD_STATES = re.compile(
    r"Common_Done|_Collected|_Broken|_Activated|_Hacked|_Pulled|"
    r"Upgrade_Unlocked|_Discovered|_Triggered|_Triggerd"
)

def pool_of(tag):
    for key, (label, pat) in POOLS.items():
        if re.search(pat, tag):
            return key
    return None

def main():
    rows = list(csv.DictReader(
        open("data/curation_worksheet.tsv", encoding="utf-8"), delimiter="\t"))

    included = []           # (tag, chapter, kind, category)
    pool_counts = defaultdict(int)
    pool_chapter = {}

    for r in rows:
        tag, ns, inc, states = r["tag"], r["namespace"], r["include"], r["states"]
        chapter = r["chapter"] or "0"
        category = r.get("category", "")
        p = pool_of(tag)

        if p:
            # pool tags: count user-collected instances (states non-empty),
            # regardless of Y/blank; explicit N still excludes.
            if inc != "N" and states:
                pool_counts[p] += 1
                pool_chapter.setdefault(p, chapter)
            continue

        if inc == "Y":
            included.append((tag, chapter, "tag", category))
        elif inc == "N":
            continue
        elif ns in ("Primary", "Secondary") and states and GOOD_STATES.search(states):
            kind = "build" if "Upgrade_Unlocked" in states else "tag"
            included.append((tag, chapter, kind, category))
        # blank World / stateless rows: out of v1

    lines = []
    for tag, chapter, kind, category in sorted(included):
        lines.append((tag, tag, chapter, kind, category))
    for p, count in sorted(pool_counts.items()):
        label = POOLS[p][0]
        for i in range(1, count + 1):
            lines.append((f"POOL:{p}#{i}", f"{label} #{i}",
                          pool_chapter.get(p, "0"), "pool", "pool"))

    with open("data/locations_v1.tsv", "w", encoding="utf-8") as f:
        f.write("key\tname\tid\tchapter\tkind\tcategory\n")
        for i, (key, name, chapter, kind, category) in enumerate(lines):
            f.write(f"{key}\t{name}\t{BASE_ID + i}\t{chapter}\t{kind}\t{category}\n")

    from collections import Counter
    kinds = Counter(k for _, _, _, k, _ in lines)
    print(f"v1 locations: {len(lines)}  {dict(kinds)}")
    print("pool caps (from user's collected counts):", dict(pool_counts))

if __name__ == "__main__":
    main()
