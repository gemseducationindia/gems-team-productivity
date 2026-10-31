# GEMS Productivity & Business Dashboard

Central desk and school team productivity (calling, visits, lead book, lead status) and the CFO business dashboard (leads,
visits, new admissions, capacity, revenue, discount, billing by campus and grade) from the live GEMS CRM, the same numbers as
the Insights dashboards Central Desk Productivity, School Teams Productivity and Business Dashboard. Corporate sees everything;
each school manager's login sees only the School tab for their campuses: https://gemseducationindia.github.io/gems-team-productivity/

**Refreshed by GitHub Actions** (`.github/workflows/refresh.yml`, every 30 min Mon-Sat 9:00-19:00 IST, needs the `CRM_TOKEN` secret). It builds, encrypts and force-pushes `gh-pages`. `bash refresh.sh` does the same by hand.

- `build.py` pulls users, campus permissions, outgoing calls, leads, open assignments and visits from the CRM and writes
  `productivity.json` (first names and counts only, no lead names or numbers). The rules are at the top of the file.
- `business.py` pulls leads, visits, new admissions and their fee rows and writes `business.json` (Business tab, Corporate only).
  Capacity and carry forward are read from the capacities CTE in Insights query `br59hj57ib`, so edit them there.
- `publish.py productivity.json _site business.json` copies `site/` and writes one encrypted file per login, holding only that login's data.
  The workflow force-pushes the result to the `gh-pages` branch as a single commit.
- `logins.py` adds or removes logins (see below). Logins are in `logins.json`: each has an RSA key pair whose private half is
  encrypted with the password, so the refresh job never needs passwords and adding a login needs no secret.
- Secret: `CRM_TOKEN` (`api_key:api_secret` of the CRM API user) in Settings → Secrets and variables → Actions.

## Add a school manager

    pip install cryptography
    python logins.py add "name@gemsedu.in" "GMS Raipur"                 # several campuses: "GMS Vikhroli, GMS Kalyan"
    git commit -am "Add login" && git push && bash refresh.sh

It prints the new password. Use `--password "..."` to choose one, `python logins.py remove "name@gemsedu.in"` to remove a login,
and `python logins.py add` again with the same name to reset a password.

## Refresh button

Every login's Refresh button loads the newest published copy. For Corporate it also starts `refresh.yml`, which pulls the CRM
again (about a minute). That needs the `CRM_TOKEN` Actions secret, and a fine-grained GitHub token limited to this repo with
Actions: Read and write, saved with `python logins.py dispatch-token "github_pat_..."` (encrypted to the Corporate login's key,
so only that password can use it). Run it again after resetting the Corporate password.
