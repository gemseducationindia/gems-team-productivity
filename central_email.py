"""Daily central admissions desk stats email, from the live CRM. Same counting rules as the productivity dashboard (build.py).

Usage: python3 central_email.py [YYYY-MM-DD] [--send] [--force]   (--send skips if that day's email was already sent; --force sends anyway)   (date defaults to today IST; without --send it only writes central.html)
- Calls: every CRM Call Log, incoming + outgoing, started 09:00-19:00 IST that day. Incoming calls count for the receiver.
- Incoming calls / outbound dials and incoming / outbound talk time are shown separately, plus the totals.
- Connect = status Completed with duration > 0. Talk time = call durations. Unique dials = distinct numbers.
- Visits booked / done: the dashboard's central desk visit rules (build.py), for that day.
Env: CRM_TOKEN or FRAPPE_API_KEY + FRAPPE_API_SECRET; TT_TO, TT_CC (comma-separated).
Sent Mon-Sat by .github/workflows/central-email.yml (started at 7:30 pm IST by a Claude scheduled task, backup schedule 7:45 pm IST); recipients come from the TT_TO / TT_CC secrets.
"""
import json, os, subprocess, sys, tempfile, urllib.parse, urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone, date

HOST = "https://gemseducation.m.frappe.cloud"
TOKEN = (os.environ.get("CRM_TOKEN") or f"{os.environ['FRAPPE_API_KEY']}:{os.environ['FRAPPE_API_SECRET']}").strip()
AUTH = TOKEN if TOKEN.startswith("token ") else f"token {TOKEN}"
IST = timezone(timedelta(hours=5, minutes=30))
args = [a for a in sys.argv[1:] if not a.startswith("--")]
DAY = date.fromisoformat(args[0]) if args else datetime.now(IST).date()
D = DAY.isoformat()
BUILD = os.environ.get("BUILD_PY", os.path.join(os.path.dirname(os.path.abspath(__file__)), "build.py"))

# dashboard data (people, visits) so the numbers tally with the productivity report
tmp = os.path.join(tempfile.mkdtemp(), "p.json")
subprocess.run([sys.executable, BUILD, tmp], check=True, stdout=subprocess.DEVNULL)
P = json.load(open(tmp))

def get(doctype, fields, filters):
    q = {"fields": json.dumps(fields), "filters": json.dumps(filters), "limit_page_length": 0}
    req = urllib.request.Request(f"{HOST}/api/resource/{urllib.parse.quote(doctype)}?{urllib.parse.urlencode(q)}", headers={"Authorization": AUTH})
    with urllib.request.urlopen(req, timeout=120) as r: return json.load(r)["data"]

users = get("User", ["name", "full_name", "enabled", "roles.role"], [["enabled", "=", 1]])
roles, full = defaultdict(set), {}
for u in users: roles[u["name"]].add(u.get("role")); full[u["name"]] = u["full_name"] or u["name"]
central = sorted(u for u, r in roles.items() if "GEMS Central Counsellor" in r and "System Manager" not in r)
pid = {u: i for i, p in enumerate(P["people"]) if p["t"] == "c" for u in central if p["n"] == full[u].split(" ")[0]}

calls = get("CRM Call Log", ["type", "caller", "receiver", "from", "to", "status", "duration"],
            [["start_time", ">=", f"{D} 09:00:00"], ["start_time", "<", f"{D} 19:00:00"]])
S = lambda: {"dials": 0, "conn": 0, "tt": 0, "nums": set(), "in": 0, "out": 0, "tt_in": 0, "tt_out": 0}
st = defaultdict(S)
for c in calls:
    out = c["type"] == "Outgoing"
    who, num = (c["caller"], c["to"]) if out else (c["receiver"], c["from"] or c["caller"])
    if who not in central: continue
    du = int(c["duration"] or 0)
    for k in (who, "team"):
        a = st[k]; a["dials"] += 1; a["tt"] += du; a["conn"] += 1 if c["status"] == "Completed" and du > 0 else 0
        d = "out" if out else "in"; a[d] += 1; a["tt_" + d] += du
        a["nums"].add((num or "")[-10:])

vb, vd = defaultdict(set), defaultdict(set)
for i, (sched, done, owners) in enumerate(P["cvis"]):
    for o in owners:
        u = next((u for u, p in pid.items() if p == o), None)
        if not u: continue
        for k in (u, "team"):
            if sched == D: vb[k].add(i)
            if done == D: vd[k].add(i)

def hm(sec):
    m = round(sec / 60)
    return f"{m // 60}h {m % 60:02d}m" if m >= 60 else f"{m}m"
pct = lambda a, b: f"{a / b * 100:.0f}%" if b else "–"
avg = lambda a, b: f"{a / b:.1f}" if b else "–"
ROWS = [("Incoming calls", lambda a, k: str(a["in"])),
        ("Outbound dials", lambda a, k: str(a["out"])),
        ("Total calls", lambda a, k: str(a["dials"])),
        ("Connect %", lambda a, k: pct(a["conn"], a["dials"])),
        ("Incoming talk time", lambda a, k: hm(a["tt_in"])),
        ("Outbound talk time", lambda a, k: hm(a["tt_out"])),
        ("Total talk time", lambda a, k: hm(a["tt"])),
        ("Unique leads", lambda a, k: str(len(a["nums"]))),
        ("Visits booked", lambda a, k: str(len(vb[k]))),
        ("Visits done", lambda a, k: str(len(vd[k])))]
rows = sorted(central, key=lambda u: -st[u]["tt"]) + ["team"]
name = lambda k: "Central team" if k == "team" else full[k]
cell = 'padding:9px 10px;border-bottom:1px solid #e5e7eb;text-align:right;white-space:nowrap'
head = ('<tr style="background:#1b2a5c;color:#ffffff">'
        '<th style="padding:9px 10px;text-align:left;font-weight:600">Counsellor</th>'
        + "".join(f'<th style="padding:9px 10px;text-align:right;font-weight:600;vertical-align:bottom">{label}</th>' for label, _ in ROWS) + "</tr>")
def tr(k):
    bold = k == "team"
    bg = "#f3f4f6" if bold else "#ffffff"
    w = "font-weight:700;" if bold else ""
    return (f'<tr style="background:{bg}"><td style="padding:9px 10px;border-bottom:1px solid #e5e7eb;text-align:left;white-space:nowrap;{w}">{name(k)}</td>'
            + "".join(f'<td style="{cell};{w}">{fn(st[k], k)}</td>' for _, fn in ROWS) + "</tr>")
table = f'<table style="border-collapse:collapse;font-size:13px;width:100%;max-width:1100px">{head}{"".join(tr(k) for k in rows)}</table>'

t = st["team"]
dtext = f"{DAY.day} {DAY.strftime('%B %Y')}"
summary = (f"Between 9 am and 7 pm the team handled <b>{t['dials']} calls</b> (<b>{t['in']}</b> incoming, <b>{t['out']}</b> outbound dials) across <b>{len(t['nums'])} unique leads</b>, "
           f"connected on <b>{pct(t['conn'], t['dials'])}</b> of them and logged <b>{hm(t['tt'])}</b> of talk time "
           f"(<b>{hm(t['tt_in'])}</b> incoming, <b>{hm(t['tt_out'])}</b> outbound). "
           f"<b>{len(vb['team'])}</b> visit{'s were' if len(vb['team']) != 1 else ' was'} booked and <b>{len(vd['team'])}</b> completed during the day.")
html = f"""<div style="font-family:Segoe UI,Arial,sans-serif;color:#111827;font-size:14px;line-height:1.55">
<p>Dear Team,</p>
<p>Please find below the central admissions team's calling and visit summary for <b>{DAY.strftime('%A')}, {dtext}</b>.</p>
<p>{summary}</p>
<p style="margin-bottom:6px"><b>Counsellor-wise summary</b></p>
{table}
<p>The detailed view, including school teams, is available on the <a href="https://gemseducationindia.github.io/gems-team-productivity/" style="color:#1b2a5c">team productivity dashboard</a>.</p>
<p>Best regards,<br>Admissions Desk<br><span style="color:#6b7280">GEMS Education India</span></p></div>"""
out = os.path.join(tempfile.gettempdir(), "central.html")
open(out, "w").write(html); print("wrote", out, "for", D)

if "--send" in sys.argv:
    to = os.environ.get("TT_TO", "")
    if not to: sys.exit("TT_TO is not set")
    subject = f"Central Admissions Team: Daily Summary, {DAY.day} {DAY.strftime('%b %Y')}"
    # send once a day at most: skip if today's email already exists in the CRM (another run or a manual send)
    if "--force" not in sys.argv and get("Communication", ["name"], [["subject", "=", subject], ["sent_or_received", "=", "Sent"]]):
        print("already sent today, skipping:", subject); sys.exit(0)
    data = urllib.parse.urlencode({"recipients": to, "cc": os.environ.get("TT_CC", ""), "subject": subject,
                                   "content": html, "send_email": 1, "sender": os.environ.get("TT_FROM", "admissiondesk@gemsedu.in")}).encode()
    req = urllib.request.Request(f"{HOST}/api/method/frappe.core.doctype.communication.email.make", data=data,
                                 headers={"Authorization": AUTH, "Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=120) as r: print("sent", json.load(r).get("message"))
