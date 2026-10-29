"""Add, reset or remove a dashboard login. Logins live in logins.json in this repo, so adding one needs no GitHub secret.

    python logins.py add "Corporate" all
    python logins.py add "dip.kumar@gemsedu.in" "GMS Vikhroli, GMS Kalyan"      # prints a new password
    python logins.py add "dip.kumar@gemsedu.in" "GMS Vikhroli" --password "..."  # set your own password
    python logins.py remove "dip.kumar@gemsedu.in"
    python logins.py list

Each login gets its own RSA key pair. The public key is stored as is; the private key is stored encrypted with a key derived from
the password (PBKDF2-SHA256, 600k iterations, AES-256-GCM). The refresh job encrypts each login's data with its public key, so
it never needs the passwords, and only someone with the password can open the private key in the browser.
"""
import base64, hashlib, json, os, secrets, sys
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logins.json")
SHORT = {"GMS Gurugram": "GEMS Millennium School - Gurugram", "GMS Indirapuram": "GEMS Millennium School - Indirapuram",
         "GMS Kochi": "GEMS Millennium School - Kochi", "GMS Varanasi": "GEMS Millennium School - Varanasi",
         "GMS Raipur": "GEMS Millennium School - Raipur", "GMS Vikhroli": "GEMS Millennium School - Vikhroli",
         "GMS Kalyan": "GEMS Millennium School - Kalyan", "GMA Kochi": "GEMS Modern Academy - Kochi",
         "GMA Coimbatore": "GEMS Modern Academy - Coimbatore", "GSE Jodhpur": "GEMS School of Excellence - Jodhpur",
         "GSE Lucknow": "GEMS School of Excellence - Lucknow", "Little GEMS Kochi": "Little GEMS - Kochi"}
uid = lambda name: hashlib.sha256(("gems-productivity:" + name.strip().lower()).encode()).hexdigest()[:32]
b64 = lambda b: base64.b64encode(b).decode()


def load(): return json.load(open(FILE)) if os.path.exists(FILE) else {}
def save(d): json.dump(d, open(FILE, "w"), indent=1, sort_keys=True); open(FILE, "a").write("\n")


def add(name, scope, password=None):
    campuses = "all" if scope.strip().lower() == "all" else [SHORT.get(c.strip(), c.strip()) for c in scope.split(",") if c.strip()]
    if campuses != "all":
        bad = [c for c in campuses if c not in SHORT.values()]
        if bad: sys.exit(f"Unknown campus: {bad}. Use short names like {', '.join(list(SHORT)[:3])}.")
    password = password or "-".join(secrets.token_urlsafe(4).replace("-", "x").replace("_", "y") for _ in range(3))
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pkcs8 = key.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    spki = key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    salt, iv = secrets.token_bytes(16), secrets.token_bytes(12)
    kek = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=600000).derive(password.encode())
    inner = json.dumps({"name": name.strip(), "pk": b64(pkcs8)}).encode()
    d = load(); u = uid(name)
    d[u] = {"campuses": campuses, "iter": 600000, "salt": b64(salt), "key": b64(iv + AESGCM(kek).encrypt(iv, inner, None)),
            "pub": b64(spki), "file": "d-" + u[:16] + ".enc"}
    save(d)
    print(f"Login: {name.strip()}\nPassword: {password}\nSees: {'all campuses' if campuses == 'all' else ', '.join(campuses)}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    if cmd == "add":
        pw = sys.argv[sys.argv.index("--password") + 1] if "--password" in sys.argv else None
        add(sys.argv[2], sys.argv[3], pw)
    elif cmd == "remove":
        d = load(); print("removed" if d.pop(uid(sys.argv[2]), None) else "no such login"); save(d)
    else:
        for u, e in load().items(): print(u, e["campuses"])
