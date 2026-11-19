#!/usr/bin/env python3
"""
process_export.py — convert a claude.ai data export into readable Markdown.

Prereq: the user requested an export (claude.ai → Settings → Privacy → Export data),
clicked the emailed link to get the JSON manifest, and then opened every
export_url in the manifest in their signed-in browser. That leaves zips like
conversations-000.zip (possibly -001, -002, …), projects-000.zip, and
light_metadata-000.zip in the downloads dir. The links are browser-session
bound; the user downloads them, not the agent.

Usage:
    python3 process_export.py [downloads_dir] [output_dir]

Produces:
    <output_dir>/*.md                     one file per conversation
    <output_dir>/COMBINED-1p-history.md   all conversations in one doc (for Projects)
    <output_dir>/GLOBAL-INSTRUCTIONS.txt  paste into Desktop → Settings → General →
                                          Instructions for Claude (every chat)
"""
import json, os, sys, zipfile, re, glob, shutil, unicodedata

downloads = os.path.expanduser(sys.argv[1] if len(sys.argv) > 1 else "~/Downloads")
out = os.path.expanduser(sys.argv[2] if len(sys.argv) > 2 else "~/claude_export_md")
work = os.path.expanduser("~/.claude_export_tmp")
shutil.rmtree(work, ignore_errors=True)          # start clean; avoid stale parts
os.makedirs(out, exist_ok=True); os.makedirs(work, exist_ok=True)

# Every part of every category (e.g. conversations-000.zip, conversations-001.zip).
zips = sorted(
    p for cat in ("conversations", "projects", "light_metadata")
    for p in glob.glob(os.path.join(downloads, f"{cat}-*.zip"))
)
if not zips:
    print("No export zips found in", downloads,
          "- open each export_url from the manifest in your browser first."); sys.exit(0)

for p in zips:
    name = os.path.basename(p)
    # guard: ensure it is a real zip, not a saved 403/Cloudflare HTML page
    with open(p, "rb") as fh:
        if fh.read(2) != b"PK":
            print(f"!! {name} is not a valid zip (likely an auth/Cloudflare page). "
                  f"Re-open its link in the signed-in browser."); continue
    dest = os.path.join(work, name[:-4])          # each part gets its own folder
    with zipfile.ZipFile(p) as zf: zf.extractall(dest)
    print("extracted", name)

conv_files = sorted(
    os.path.join(root, f)
    for root, _, files in os.walk(work)
    for f in files if "conversation" in f.lower() and f.endswith(".json")
)
if not conv_files:
    print("No conversations JSON found. Download every conversations-*.zip "
          "listed in the manifest."); sys.exit(0)

convs, seen = [], set()
for cf in conv_files:
    with open(cf, encoding="utf-8") as fh:
        data = json.load(fh)
    for c in (data if isinstance(data, list) else data.get("conversations", [data])):
        key = c.get("uuid") or id(c)
        if key in seen: continue                 # de-duplicate across parts
        seen.add(key); convs.append(c)
convs.sort(key=lambda c: c.get("created_at", ""))
print(f"found {len(convs)} conversations across {len(conv_files)} file(s)")

def slug(s):
    # ASCII-only file names: on Linux with a non-UTF-8 locale (e.g. LANG=C in a
    # container) the OS can't encode names like "café.md". Accents fold to
    # their base letter; other non-ASCII characters (emoji, CJK) are dropped.
    s = unicodedata.normalize("NFKD", s or "untitled").encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9\s-]", "", s.lower()).strip()
    return re.sub(r"\s+", "-", s)[:60].strip("-") or "untitled"

def msg_text(m):
    t = m.get("text")
    if not t and isinstance(m.get("content"), list):
        t = "".join(b.get("text", "") for b in m["content"] if isinstance(b, dict))
    return t or ""

combined = ["# Claude 1P Conversation History (Consolidated)", "",
            f"_{len(convs)} past conversations exported from claude.ai. "
            f"Use as background/reference context._", "", "## Table of Contents", ""]
bodies = []
used_names = set()
for i, c in enumerate(convs, 1):
    name = c.get("name") or c.get("title") or c.get("uuid", "untitled")
    created = c.get("created_at", "")
    msgs = c.get("chat_messages") or c.get("messages") or []
    # per-file
    lines = [f"# {name}", f"_created: {created}_", ""]
    for m in msgs:
        lines += [f"## {m.get('sender') or m.get('role') or '?'}", msg_text(m), ""]
    base = f"{slug(created[:10])}-{slug(name)}"
    fname, n = f"{base}.md", 2
    while fname in used_names:                   # same date + title: don't overwrite
        fname, n = f"{base}-{n}.md", n + 1
    used_names.add(fname)
    with open(os.path.join(out, fname), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    # combined
    combined.append(f"{i}. [{name}](#conv-{i})")
    body = [f'<a id="conv-{i}"></a>', f"## {i}. {name}", f"_created: {created}_", ""]
    for m in msgs:
        body += [f"### {m.get('sender') or m.get('role') or '?'}", msg_text(m), ""]
    bodies.append("\n".join(body))

doc = "\n".join(combined) + "\n\n---\n\n" + "\n\n---\n\n".join(bodies) + "\n"
combined_path = os.path.join(out, "COMBINED-1p-history.md")
with open(combined_path, "w", encoding="utf-8") as fh:
    fh.write(doc)

# Paste-ready brief for Claude Desktop → Settings → General → Instructions for
# Claude. Those instructions apply to every chat, but they are a
# typed brief, not a file store — so point Claude at the full history on disk
# and list the topics, instead of pasting whole transcripts.
topics = []
for c in convs:
    name = c.get("name") or c.get("title") or "untitled"
    summ = " ".join((c.get("summary") or "").split())
    summ = (summ[:140] + "…") if len(summ) > 140 else summ
    topics.append(f"- {c.get('created_at', '')[:10]} — {name}" + (f": {summ}" if summ else ""))
brief = "\n".join([
    "## My past Claude conversation history",
    f"My earlier Claude conversations ({len(convs)}) are saved on this computer at:",
    f"  {combined_path}",
    f"(individual conversations: {out}/*.md)",
    "When my request relates to past work, or I mention something we discussed "
    "before, read that file first and use it as background. Don't repeat it back "
    "unless I ask.",
    "",
    "Topics covered:",
    *topics,
]) + "\n"
with open(os.path.join(out, "GLOBAL-INSTRUCTIONS.txt"), "w", encoding="utf-8") as fh:
    fh.write(brief)

print(f"wrote {len(convs)} .md files + COMBINED-1p-history.md + GLOBAL-INSTRUCTIONS.txt to {out}")
