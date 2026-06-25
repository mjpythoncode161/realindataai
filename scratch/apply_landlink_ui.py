import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
roots = [
    ROOT / "accounts/templates",
    ROOT / "bookings/templates",
    ROOT / "tally/templates",
]

replacements = [
    ("card card-outline card-maroon", "card card-outline card-primary ll-card"),
    ('class="table table-striped table-bordered"', 'class="table table-sm table-striped table-bordered table-hover ll-table mb-0"'),
    ('class="table table-bordered table-striped"', 'class="table table-sm table-bordered table-striped table-hover ll-table mb-0"'),
    ('class="table table-bordered"', 'class="table table-sm table-bordered table-striped table-hover ll-table mb-0"'),
    ('class="table table-hover table-striped"', 'class="table table-sm table-hover table-striped table-bordered ll-table mb-0"'),
    ('<section class="content-header">', '<section class="content-header py-2">'),
    ('<div class="content-header">', '<div class="content-header py-2">'),
    ('<section class="content">', '<section class="content pt-0">'),
]

skip = {
    "base.html", "landing.html", "landing_base.html", "login.html",
    "signup.html", "trial_expired.html", "pending_approval.html",
}

dt_css = re.compile(
    r'<link rel="stylesheet" href="\{% static \'assets/plugins/datatables-bs4/css/dataTables\.bootstrap4\.min\.css\' %\}" />\s*'
    r'<link rel="stylesheet" href="\{% static \'assets/plugins/datatables-responsive/css/responsive\.bootstrap4\.min\.css\' %\}" />\s*',
    re.MULTILINE,
)

for root in roots:
    if not root.exists():
        continue
    for path in root.rglob("*.html"):
        if path.name in skip or "website" in path.parts or "includes" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        orig = text
        for old, new in replacements:
            text = text.replace(old, new)
        text = dt_css.sub("", text)
        if text != orig:
            path.write_text(text, encoding="utf-8")
            print("updated", path.relative_to(ROOT))

print("done")
