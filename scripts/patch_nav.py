#!/usr/bin/env python3
"""
Run this from your repo root to patch nav links in all templates.
  python3 patch_nav.py
"""
import re, os

TEMPLATES_DIR = "app/templates"

NAV_REPLACEMENTS = {
    "index.html": {
        "old": '''      <div class="nav-links">
        <a href="/" class="active"><i data-lucide="users"></i> Players</a>
        <a href="/explore"><i data-lucide="compass"></i> Explore</a>
        <a href="/prizepicks"><i data-lucide="book"></i> PrizePicks</a>
      </div>''',
        "new": '''      <div class="nav-links">
        <a href="/" class="active"><i data-lucide="users"></i> Players</a>
        <a href="/explore"><i data-lucide="compass"></i> Explore</a>
        <a href="/prizepicks"><i data-lucide="list"></i> Player Props</a>
        <a href="/moneylines"><i data-lucide="trending-up"></i> Moneylines</a>
        <a href="/model-stats"><i data-lucide="bar-chart-3"></i> Model Stats</a>
      </div>'''
    },
    "explore.html": {
        "old": '''      <div class="nav-links">
        <a href="/"><i data-lucide="users"></i> Players</a>
        <a href="/explore" class="active"
          ><i data-lucide="compass"></i> Explore</a
        >
        <a href="/prizepicks"><i data-lucide="book"></i> PrizePicks</a>
      </div>''',
        "new": '''      <div class="nav-links">
        <a href="/"><i data-lucide="users"></i> Players</a>
        <a href="/explore" class="active"><i data-lucide="compass"></i> Explore</a>
        <a href="/prizepicks"><i data-lucide="list"></i> Player Props</a>
        <a href="/moneylines"><i data-lucide="trending-up"></i> Moneylines</a>
        <a href="/model-stats"><i data-lucide="bar-chart-3"></i> Model Stats</a>
      </div>'''
    },
    "player.html": {
        "old": '''      <div class="nav-links">
        <a href="/" class="active"> <i data-lucide="users"></i> Players </a>
        <a href="/explore"> <i data-lucide="compass"></i> Explore </a>
        <a href="/prizepicks"> <i data-lucide="book"></i> PrizePicks </a>
      </div>''',
        "new": '''      <div class="nav-links">
        <a href="/" class="active"> <i data-lucide="users"></i> Players </a>
        <a href="/explore"> <i data-lucide="compass"></i> Explore </a>
        <a href="/prizepicks"> <i data-lucide="list"></i> Player Props </a>
        <a href="/moneylines"> <i data-lucide="trending-up"></i> Moneylines </a>
        <a href="/model-stats"><i data-lucide="bar-chart-3"></i> Model Stats</a>
      </div>'''
    },
}


for fname, rep in NAV_REPLACEMENTS.items():
    path = os.path.join(TEMPLATES_DIR, fname)
    if not os.path.exists(path):
        print(f"  SKIP (not found): {path}")
        continue
    with open(path) as f:
        content = f.read()
    if rep["old"] in content:
        content = content.replace(rep["old"], rep["new"])
        with open(path, "w") as f:
            f.write(content)
        print(f"  PATCHED: {fname}")
    else:
        # Fallback: regex replace any nav-links block
        new_content = re.sub(
            r'<div class="nav-links">.*?</div>',
            rep["new"],
            content,
            flags=re.DOTALL,
            count=1
        )
        if new_content != content:
            with open(path, "w") as f:
                f.write(new_content)
            print(f"  PATCHED (regex): {fname}")
        else:
            print(f"  WARNING: Could not patch {fname} - check manually")

print("\nDone. Also:")
print("  1. Add moneylines.html and moneylines.css from outputs/")
print("  2. Add the /moneylines route from routes/players.py")