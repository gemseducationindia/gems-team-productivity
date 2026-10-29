"""Pull the live CRM and write business.json: the CFO business dashboard (leads, visits, new admissions, capacity, revenue).

Same rules as the Insights Business Dashboard it replaces (frj4ta3uje + driqlh66ug, base query br59hj57ib):
- Leads: not duplicate, campus set (not the India root), no 'test' in the lead name. Dated by creation; grade = grade applied
  ('Not set' when blank).
- Visit booked = visit_attempts > 0, visit_done_on set, status Visit Scheduled / Visit Done, or converted; dated by the first
  GEMS Visit (created on, or its visit date if earlier), else visit_done_on, else modified. Visit done = visit_done_on set, status Visit Done, or converted; dated by
  visit_done_on, else modified.
- New admission = deal Blocking Fee Paid or Enrolled, not duplicate, no 'test' in name / student / lead name / lost notes.
  Dated by blocking_fee_paid_on, else enrolled_on, else creation. Normal / RTE from admission_type (blank = Normal).
- Revenue = published amount of the deal's Fees rows: application, blocking, tuition and Annual Fee rows always, other extras
  (Prospectus) only when ticked. Discount = their discount_amount. Billing = revenue - discount.
- Capacity and carry forward (current strength) per campus and grade come from the capacities CTE in Insights query
  br59hj57ib, so they are edited in one place and both dashboards agree.
- GMS Raipur is left out.
CRM datetimes are stored in IST, so their date part is the IST date.

Env: CRM_TOKEN ("key:secret"), or FRAPPE_API_KEY + FRAPPE_API_SECRET.
"""
import json, os, re, sys, time, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone

HOST = "https://gemseducation.m.frappe.cloud"
TOKEN = (os.environ.get("CRM_TOKEN") or f"{os.environ['FRAPPE_API_KEY']}:{os.environ['FRAPPE_API_SECRET']}").strip()
AUTH = {"Authorization": TOKEN if TOKEN.startswith("token ") else f"token {TOKEN}"}
IST = timezone(timedelta(hours=5, minutes=30))

EXCLUDED = {"GEMS Millennium School - Raipur"}
CAP_QUERY = "br59hj57ib"
FEES = ["application_fee", "blocking_fee", "tuition", "Annual Fee", "Prospectus"]   # fee types, in the order stored per deal


def call(path):
    for attempt in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(HOST + path, headers=AUTH), timeout=120) as r: return json.load(r)
        except Exception:
            if attempt == 3: raise
            time.sleep(5 * (attempt + 1))


def get(doctype, fields, filters=None):
    out, start = [], 0
    while True:
        q = {"fields": json.dumps(fields), "limit_start": start, "limit_page_length": 5000, "order_by": "name asc"}
        if filters: q["filters"] = json.dumps(filters)
        page = call(f"/api/resource/{urllib.parse.quote(doctype)}?{urllib.parse.urlencode(q)}")["data"]
        out += page
        if len(page) < 5000: return out
        start += 5000


def capacities():
    q = call(f"/api/resource/Insights%20Query%20v3/{CAP_QUERY}")["data"]
    sql = json.loads(q["operations"])[0]["raw_sql"]
    cte = sql[sql.index("WITH cap AS ("):sql.index("),\nt AS")]
    rows = re.findall(r"SELECT\s+'([^']+)'(?:\s+AS territory)?,\s*'([^']+)'(?:\s+AS grade)?,\s*(\d+)(?:\s+AS capacity)?,\s*(\d+)", cte)
    if len(rows) != cte.count("SELECT"): sys.exit(f"capacities: parsed {len(rows)} of {cte.count('SELECT')} rows in {CAP_QUERY}")
    return [(t, g, int(c), int(e)) for t, g, c, e in rows]


day = lambda s: s[:10] if s else None
has_test = lambda *xs: "test" in " ".join(x for x in xs if x is not None).lower()   # CONCAT_WS(' ', ...) LIKE '%test%'

caps = [r for r in capacities() if r[0] not in EXCLUDED]

first_visit = {}
for v in get("GEMS Visit", ["enquiry", "creation", "scheduled_on"]):
    # booked when created, or on the visit date for a visit entered after the fact (back-filled walk-ins)
    t = min(x for x in (v["creation"], v["scheduled_on"]) if x)
    if v["enquiry"] and (v["enquiry"] not in first_visit or t < first_visit[v["enquiry"]]): first_visit[v["enquiry"]] = t

leads = []
for l in get("CRM Lead", ["name", "territory", "grade_applied", "creation", "modified", "status", "converted", "visit_attempts",
                          "visit_done_on", "is_duplicate", "lead_name", "first_name", "last_name"]):
    t = l["territory"]
    if l["is_duplicate"] or not t or t.lower().endswith("india") or t in EXCLUDED or has_test(l["lead_name"], l["first_name"], l["last_name"]): continue
    booked = (l["visit_attempts"] or 0) > 0 or l["visit_done_on"] or l["status"] in ("Visit Scheduled", "Visit Done") or l["converted"]
    done = l["visit_done_on"] or l["status"] == "Visit Done" or l["converted"]
    leads.append([t, l["grade_applied"] or "Not set", day(l["creation"]),
                  day(first_visit.get(l["name"]) or l["visit_done_on"] or l["modified"]) if booked else None,
                  day(l["visit_done_on"] or l["modified"]) if done else None])

fees = {}   # deal -> [[published, discount] per fee type]
q = {"doctype": "GEMS Application Fee", "parent": "CRM Deal", "limit_page_length": 0,
     "fields": json.dumps(["parent", "parentfield", "charge", "extra_fee_type", "taken", "published", "discount_amount"])}
for f in call("/api/method/frappe.client.get_list?" + urllib.parse.urlencode(q))["message"]:
    if f["parentfield"] != "fees" or f["published"] is None: continue
    kind = f["extra_fee_type"] if f["charge"] == "extra" else f["charge"]
    if f["charge"] == "extra" and kind != "Annual Fee" and not f["taken"]: continue
    if kind not in FEES: sys.exit(f"unknown fee type {kind!r} on {f['parent']}")
    row = fees.setdefault(f["parent"], [[0, 0] for _ in FEES])[FEES.index(kind)]
    row[0] += f["published"]; row[1] += f["discount_amount"] or 0

deals = []
for d in get("CRM Deal", ["name", "territory", "grade_applied", "admission_type", "status", "is_duplicate", "creation",
                          "blocking_fee_paid_on", "enrolled_on", "student_name", "lead_name", "lost_notes"],
             [["status", "in", ["Blocking Fee Paid", "Enrolled"]]]):
    if not d["territory"]: sys.exit(f"{d['name']} is a new admission with no campus")
    if d["is_duplicate"] or d["territory"] in EXCLUDED or has_test(d["name"], d["student_name"], d["lead_name"], d["lost_notes"]): continue
    deals.append([d["territory"], d["grade_applied"] or "Not set", d["admission_type"] or "Normal",
                  day(d["blocking_fee_paid_on"] or d["enrolled_on"] or d["creation"]), fees.get(d["name"], [[0, 0] for _ in FEES])])

# compact: campuses and grades as indexes
campuses = sorted({r[0] for r in caps} | {r[0] for r in leads} | {r[0] for r in deals})
GRADES = ["Pre-Kindergarten", "Nursery", "Junior KG", "Senior KG"] + [f"Grade {n}" for n in range(1, 13)] + ["Not set"]
grades = GRADES + sorted({r[1] for r in leads + deals} - set(GRADES))
ci, gi = campuses.index, grades.index
now = datetime.now(IST)
out = {"generated": now.strftime("%Y-%m-%dT%H:%M"), "today": now.strftime("%Y-%m-%d"), "campuses": campuses, "grades": grades, "fees": FEES,
       "cap": [[ci(t), gi(g), c, e] for t, g, c, e in caps],
       "leads": [[ci(t), gi(g), a, b, c] for t, g, a, b, c in leads],
       "deals": [[ci(t), gi(g), a, dt, f] for t, g, a, dt, f in deals]}
json.dump(out, open(sys.argv[1] if len(sys.argv) > 1 else "business.json", "w"), separators=(",", ":"))
rev = sum(p for d in deals for p, _ in d[4]); disc = sum(x for d in deals for _, x in d[4])
print(f"business: {len(leads)} leads, {len(deals)} new admissions, revenue {rev:,.0f}, discount {disc:,.0f}, billing {rev - disc:,.0f}")
