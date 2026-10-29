"""Build the site: copy site/, then encrypt productivity.json once per login in logins.json, holding only that login's data.

    python publish.py productivity.json _site [business.json]

Corporate ("all") gets both teams and the Business tab (business.json, see business.py). A school login gets the School tab only, for its campuses, re-indexed so nothing about other
campuses or the central desk is inside. Each file = RSA-OAEP(SHA-256)-wrapped AES key (256 bytes) + IV (12) + AES-256-GCM(gzip(JSON)).
"""
import gzip, json, os, secrets, shutil, sys
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import base64

HERE = os.path.dirname(os.path.abspath(__file__))
src, out = json.load(open(sys.argv[1])), sys.argv[2]
if len(sys.argv) > 3: src["biz"] = json.load(open(sys.argv[3]))
logins = json.load(open(os.path.join(HERE, "logins.json")))


def subset(d, allowed):
    if allowed == "all": return dict(d, role="corporate")
    keep = [i for i, c in enumerate(d["campuses"]) if c in allowed]
    cmap = {i: n for n, i in enumerate(keep)}
    pmap = {}
    people = []
    for i, p in enumerate(d["people"]):
        if p["t"] == "s" and p["c"] in cmap: pmap[i] = len(people); people.append(dict(p, c=cmap[p["c"]]))
    rows = lambda rs: [r[:-1] + [[pmap[p] for p in r[-1]]] for r in rs if all(p in pmap for p in r[-1])]
    return dict(d, role="school", campuses=[d["campuses"][i] for i in keep], people=people,
                days=[[r[0], pmap[r[1]], *r[2:]] for r in d["days"] if r[1] in pmap],
                sbook=[[r[0], [pmap[p] for p in r[1]], r[2]] for r in d["sbook"] if all(p in pmap for p in r[1])],
                svis=rows(d["svis"]), cbook=[], cvis=[], biz=None)


if os.path.exists(out): shutil.rmtree(out)
shutil.copytree(os.path.join(HERE, "site"), out)
index = {}
for u, e in logins.items():
    data = subset(src, e["campuses"])
    k, iv = secrets.token_bytes(32), secrets.token_bytes(12)
    pub = serialization.load_der_public_key(base64.b64decode(e["pub"]))
    wrapped = pub.encrypt(k, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None))
    blob = gzip.compress(json.dumps(data, separators=(",", ":")).encode(), mtime=0)
    open(os.path.join(out, e["file"]), "wb").write(wrapped + iv + AESGCM(k).encrypt(iv, blob, None))
    index[u] = {k2: e[k2] for k2 in ("iter", "salt", "key", "file", "dispatch") if k2 in e}
    print(f"{u[:8]}: {data['role']}, {len(data['campuses'])} campuses, {len(data['people'])} people")
json.dump(index, open(os.path.join(out, "users.json"), "w"), indent=1)
open(os.path.join(out, ".nojekyll"), "w").close()
