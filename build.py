"""Pull the live CRM and write productivity.json: central desk and school team calling, visits and lead books.

Same rules as the Insights dashboards it replaces (Central Desk Productivity, School Teams Productivity):
- Central desk = enabled users with role 'GEMS Central Counsellor', minus System Managers. They are credited for leads they own
  (lead owner) or are assigned to (open ToDo).
- School team = enabled users with a CRM Territory User Permission, minus central counsellors and System Managers (campus
  managers included, as in Insights). They are credited for leads where they are the lead owner, once per campus they cover.
- Dial = outgoing call. Connect = status Completed with duration > 0. Talk time = all outgoing call durations.
- Duplicates and test leads ('test' in the lead name) are left out, as on the Business tab.
- School credit is per campus of the lead: a school counsellor is credited for a lead they own at a campus they cover. A school
  person covering several campuses has each call put under the campus of the lead dialled, so nothing is counted twice.
- Every total (team, campus, all campuses) counts each lead once.
- Visit booked = visit_attempts > 0, visit_done_on set, status Visit Scheduled / Visit Done, or converted; dated by the first
  GEMS Visit, else visit_done_on, else modified. Visit done = visit_done_on set, status Visit Done, or converted; dated by
  visit_done_on, else modified. Same rules as the Business tab (business.py).
- Untouched = status New, the number was never dialled and no call is linked to the lead.
CRM datetimes are stored in IST, so their date part is the IST date.

Env: CRM_TOKEN ("key:secret"), or FRAPPE_API_KEY + FRAPPE_API_SECRET.
"""
import json, os, re, sys, time, urllib.parse, urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone

HOST = "https://gemseducation.m.frappe.cloud"
TOKEN = (os.environ.get("CRM_TOKEN") or f"{os.environ['FRAPPE_API_KEY']}:{os.environ['FRAPPE_API_SECRET']}").strip()
IST = timezone(timedelta(hours=5, minutes=30))


def get(doctype, fields, filters=None):
    out, start = [], 0
    while True:
        q = {"fields": json.dumps(fields), "limit_start": start, "limit_page_length": 5000, "order_by": "name asc"}
        if filters: q["filters"] = json.dumps(filters)
        url = f"{HOST}/api/resource/{urllib.parse.quote(doctype)}?{urllib.parse.urlencode(q)}"
        for attempt in range(4):
            try:
                req = urllib.request.Request(url, headers={"Authorization": TOKEN if TOKEN.startswith("token ") else f"token {TOKEN}"})
                with urllib.request.urlopen(req, timeout=120) as r: page = json.load(r)["data"]
                break
            except Exception:
                if attempt == 3: raise
                time.sleep(5 * (attempt + 1))
        out += page
        if len(page) < 5000: return out
        start += 5000


day = lambda s: s[:10] if s else None

users = get("User", ["name", "full_name", "enabled", "roles.role"])
roles, full = defaultdict(set), {}
for u in users:
    if u["enabled"]: roles[u["name"]].add(u.get("role")); full[u["name"]] = u["full_name"] or u["name"]
first = lambda uid: full[uid].split(" ")[0]   # first word of the full name, as Insights shows it

central = sorted(u for u, r in roles.items() if "GEMS Central Counsellor" in r and "System Manager" not in r)
perms = get("User Permission", ["user", "for_value"], [["allow", "=", "CRM Territory"]])
school = sorted({(p["user"], p["for_value"]) for p in perms if p["user"] in roles
                 and not roles[p["user"]] & {"GEMS Central Counsellor", "System Manager"}})
campuses = sorted({c for _, c in school} | {p["for_value"] for p in perms})

# people: one row per central counsellor, and one per (school counsellor, campus)
people, pidx = [], {}
for u in central: pidx[("c", u)] = len(people); people.append({"n": first(u), "t": "c"})
for u, c in school: pidx[("s", u, c)] = len(people); people.append({"n": first(u), "t": "s", "c": campuses.index(c)})
school_of = defaultdict(list)          # user -> [(campus, person idx)]
for u, c in school: school_of[u].append((c, pidx[("s", u, c)]))
central_set = set(central)

# ---- leads (needed first: a call is placed under the campus of the lead dialled) ----
has_test = lambda *xs: "test" in " ".join(x for x in xs if x is not None).lower()
leads = [l for l in get("CRM Lead", ["name", "status", "lead_owner", "visit_attempts", "visit_done_on", "modified", "mobile_digits",
                                     "territory", "converted", "is_duplicate", "lead_name", "first_name", "last_name"])
         if not l["is_duplicate"] and not has_test(l["lead_name"], l["first_name"], l["last_name"])]
campus_of_number = {}
for l in sorted(leads, key=lambda l: l["modified"]):   # latest lead wins when a number has several
    if l["mobile_digits"] and l["territory"]: campus_of_number[l["mobile_digits"]] = l["territory"]

# ---- calls: per person per day ----
calls = get("CRM Call Log", ["caller", "to", "status", "duration", "start_time"], [["type", "=", "Outgoing"]])
# a lead with any call linked to it (incoming too) is not untouched, as in Insights
linked = {c["reference_docname"] for c in get("CRM Call Log", ["reference_docname"], [["reference_doctype", "=", "CRM Lead"], ["reference_docname", "is", "set"]])}
dialled = set()
agg = defaultdict(lambda: [0, 0, 0, set()])   # (date, person) -> dials, connects, talk seconds, numbers dialled
num_id = {}                                    # number -> anonymous id, so per-lead averages can count distinct numbers
for c in calls:
    dialled.add((c["to"] or "")[-10:])   # RIGHT(to, 10), as in Insights
    d, who = day(c["start_time"]), c["caller"]
    if not d or not who: continue
    mine = school_of.get(who, [])
    if len(mine) > 1:   # covers several campuses: the campus of the lead dialled, else the first one
        at = campus_of_number.get((c["to"] or "")[-10:])
        mine = [x for x in mine if x[0] == at] or mine[:1]
    targets = ([pidx[("c", who)]] if who in central_set else []) + [p for _, p in mine]
    for p in targets:
        a = agg[(d, p)]; a[0] += 1; a[1] += 1 if c["status"] == "Completed" and (c["duration"] or 0) > 0 else 0; a[2] += int(c["duration"] or 0)
        a[3].add(num_id.setdefault((c["to"] or "")[-10:], len(num_id)))
days = sorted([d, p, v[0], v[1], v[2], sorted(v[3])] for (d, p), v in agg.items())

# ---- leads, owners and visits ----
todos = get("ToDo", ["reference_name", "allocated_to"], [["reference_type", "=", "CRM Lead"], ["status", "=", "Open"]])
open_owners = defaultdict(set)
for t in todos:
    if t["allocated_to"]: open_owners[t["reference_name"]].add(t["allocated_to"])
first_visit = {}
for v in get("GEMS Visit", ["enquiry", "creation"]):
    if v["enquiry"] and (v["enquiry"] not in first_visit or v["creation"] < first_visit[v["enquiry"]]): first_visit[v["enquiry"]] = v["creation"]

STATUS = ["New", "Contacted", "Visit Scheduled", "Visit Done", "Lost", "Junk"]
status_of = lambda s: STATUS.index(s) if s in STATUS else len(STATUS)   # anything else = "Other"
cbook, sbook, cvis, svis = [], [], [], []
for l in leads:
    name, owner, todo = l["name"], l["lead_owner"], open_owners.get(l["name"], set())
    booked = bool((l["visit_attempts"] or 0) > 0 or l["visit_done_on"] or l["status"] in ("Visit Scheduled", "Visit Done") or l["converted"])
    sched = day(first_visit.get(name) or l["visit_done_on"] or l["modified"]) if booked else None
    done = day(l["visit_done_on"] or l["modified"]) if (l["visit_done_on"] or l["status"] == "Visit Done" or l["converted"]) else None
    untouched = l["status"] == "New" and not (l["mobile_digits"] and l["mobile_digits"] in dialled) and name not in linked
    shared = len(todo) >= 2
    flags = (1 if shared else 0) | (2 if untouched else 0) | (4 if booked else 0) | (8 if done else 0)
    # central desk: owner or open assignee who is a central counsellor
    cown = sorted(pidx[("c", u)] for u in ({owner} | todo) if u in central_set)
    if cown:
        team_only = all(u in central_set for u in todo)
        cbook.append([status_of(l["status"]), cown, flags | (16 if team_only else 0)])
        if booked: cvis.append([sched, done, cown])
    # school team: lead owner, at the lead's campus if they cover it
    for c, p in school_of.get(owner, []):
        if c != l["territory"]: continue
        team = {u for u, cc in school if cc == c}
        team_only = all(u in team for u in todo)
        sbook.append([status_of(l["status"]), [p], flags | (16 if team_only else 0)])
        if booked: svis.append([sched, done, [p]])

now = datetime.now(IST)
out = {"generated": now.strftime("%Y-%m-%dT%H:%M"), "today": now.strftime("%Y-%m-%d"), "status": STATUS + ["Other"],
       "campuses": campuses, "people": people, "days": days, "cbook": cbook, "sbook": sbook, "cvis": cvis, "svis": svis}
json.dump(out, open(sys.argv[1] if len(sys.argv) > 1 else "productivity.json", "w"), separators=(",", ":"))
print(f"{len(central)} central, {len(school)} school rows, {len(calls)} outgoing calls, {len(cbook)} central / {len(sbook)} school book leads")
