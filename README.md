# GEMS Productivity & Business Dashboard

Central desk and school team productivity (calling, visits, lead book, lead status) and the CFO business dashboard (leads,
visits, new admissions, capacity, revenue, discount, billing by campus and grade) from the live GEMS CRM, the same numbers as
the Insights dashboards Central Desk Productivity, School Teams Productivity and Business Dashboard. Corporate sees everything;
each school manager's login sees only the School tab for their campuses: https://gemseducationindia.github.io/gems-team-productivity/

**Refreshed by a Claude scheduled task** that runs `bash refresh.sh` (build, encrypt, force-push `gh-pages`). `.github/workflows/refresh.yml` is a manual backup that needs the `CRM_TOKEN` secret.

- `build.py` pulls users, campus permissions, all calls (incoming + outgoing), leads, open assignments and visits from the CRM and writes
  `productivity.json` (first names and counts only, no lead names or numbers). The rules are at the top of the file.
- `targets.json` holds the 2027-28 admission target per campus and the monthly phasing; the Business tab shows Target, % Ach and Target to Date from it. Edit it to change a target.
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

A central desk counsellor gets their own login with only their own Central desk row (opening on Today) and their own calls in
the Call audit tab:

    python logins.py counsellor "Arya" "arya.suresh@gemsedu.in" --password "..."

The CRM email is stored only as a hash. The shared central desk login (`python logins.py add "Centraldesk" central`) sees the
Central desk tab for the whole desk, opening on Today, and no Call audit tab. The Call audit tab for a new login appears after the next call audit publish.

It prints the new password. Use `--password "..."` to choose one, `python logins.py remove "name@gemsedu.in"` to remove a login,
and `python logins.py add` again with the same name to reset a password.

## Users tab (admins)

Admin logins (the "Admin" login; `python logins.py admin NAME on`) get a **Users** tab to add users, change what they can see, set
passwords and remove them, right in the dashboard. It saves `logins.json` to `main` through the GitHub API with a fine-grained
token (this repo only; Contents and Actions read and write) that an admin pastes once; the token is stored encrypted to each
admin's key, like the dispatch token. Each login's `meta` holds its name and private key sealed to the admins' keys, so admins
see logins by name and a password reset keeps the key pair (the Call audit tab keeps working). Password changes and removals
also patch the published `users.json` at once; every change then starts `refresh.yml` so new users go live in about two minutes,
and the scheduled refresh picks them up anyway. Logins made before the Users tab have no stored private key: their first reset
from the Users tab makes a new key pair (live after the refresh; their Call audit tab returns after the next call audit publish).

## Refresh button

Every login's Refresh button loads the newest published copy. For Corporate it also starts `refresh.yml`, which pulls the CRM
again (about a minute). That needs the `CRM_TOKEN` Actions secret, and a fine-grained GitHub token limited to this repo with
Actions: Read and write, saved with `python logins.py dispatch-token "github_pat_..."` (encrypted to the Corporate login's key,
so only that password can use it). Run it again after resetting the Corporate password.
