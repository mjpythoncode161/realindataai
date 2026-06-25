import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
roots = [ROOT / "accounts/templates", ROOT / "bookings/templates", ROOT / "tally/templates"]
skip = {"base.html", "landing.html", "landing_base.html", "login.html", "signup.html", "trial_expired.html", "pending_approval.html"}

btn_style = re.compile(
    r'\s+style="background-color: #29577f[^"]*"',
    re.IGNORECASE,
)
h1_style = re.compile(r'<h1 style="color: #333; font-weight: 500;">', re.IGNORECASE)
empty_extra = re.compile(r"\{% block extra_head %\}\s*\{% endblock %\}\s*\n\s*\n", re.MULTILINE)

for root in roots:
    if not root.exists():
        continue
    for path in root.rglob("*.html"):
        if path.name in skip or "website" in path.parts or "includes" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        orig = text
        text = btn_style.sub("", text)
        text = h1_style.sub('<h1 class="m-0">', text)
        text = text.replace('class="btn btn-maroon-custom"', 'class="btn btn-sm btn-primary ll-btn-primary"')
        text = text.replace('class="btn btn-primary" style="background-color: #29577f; border: none;"', 'class="btn btn-sm btn-primary ll-btn-primary"')
        if text != orig:
            path.write_text(text, encoding="utf-8")
            print("cleaned", path.relative_to(ROOT))

print("done")
