"""One-shot audit: url_for endpoints vs Flask view_functions."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import app

endpoints = set(app.view_functions.keys())
pattern = re.compile(r"url_for\(['\"]([^'\"]+)['\"]")

url_for_refs = {}
for p in Path("templates").rglob("*.html"):
    text = p.read_text(encoding="utf-8", errors="ignore")
    for m in pattern.finditer(text):
        ep = m.group(1)
        url_for_refs.setdefault(ep, []).append(str(p).replace("\\", "/"))

missing = {
    ep: files
    for ep, files in sorted(url_for_refs.items())
    if ep not in endpoints and ep != "static"
}

print("=== MISSING ENDPOINTS (BuildError risk) ===")
for ep, files in missing.items():
    print(f"  {ep}: {len(files)} refs, first={files[0]}")

print(f"\nTotal endpoints: {len(endpoints)}")
print(f"Unique url_for endpoints: {len(url_for_refs)}")
print(f"Missing: {len(missing)}")
