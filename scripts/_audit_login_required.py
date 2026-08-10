"""List @app.route handlers that lack @login_required on the next decorator."""
import re
from pathlib import Path

text = Path("app.py").read_text(encoding="utf-8")
export_text = Path("export_routes.py").read_text(encoding="utf-8")

route_re = re.compile(
    r"@app\.route\([^\)]+\)\s*\n((?:@[^\n]+\s*\n)*?)def (\w+)\(",
    re.MULTILINE,
)

unprotected = []
for source, label in [(text, "app.py"), (export_text, "export_routes.py")]:
    for m in route_re.finditer(source):
        decorators = m.group(1)
        name = m.group(2)
        if "login_required" not in decorators:
            # allow public routes
            public = {
                "index", "login", "logout", "about", "contact", "events",
                "verify_transcript", "api_stats", "download_file",
            }
            if name not in public and not name.startswith("static"):
                unprotected.append((label, name))

print("=== ROUTES WITHOUT @login_required ===")
for label, name in unprotected:
    print(f"  {label}: {name}")
print(f"Total: {len(unprotected)}")
