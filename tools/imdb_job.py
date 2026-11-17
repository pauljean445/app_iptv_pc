"""Tâche planifiée (GitHub Actions, chaque nuit) : base commune des notes IMDb des applis IPTV Player.

1. Se connecte au projet Firebase avec le compte « robot » (seul autorisé à écrire la base commune).
2. Lit les titres demandés par les foyers listés (households/<uid>/imdb_req/sNN : un champ par titre, écrit par
   les applis PC / TV / téléphone quand un titre de leur catalogue n'est pas dans la base).
3. Relie les nouveaux titres (numéro TMDB du fournisseur) à IMDb par Wikidata, 50 par appel : identifiant IMDb,
   durée (P2047), année (P577 / P580). Titres inconnus : marqués « ?AAAAMMJJ », réessayés au bout d'une semaine.
4. Met à jour toutes les notes avec le fichier officiel d'IMDb (datasets.imdbws.com/title.ratings.tsv.gz, gratuit
   pour un usage personnel non commercial, publié chaque jour).
5. Écrit la base commune imdb/sNN : "m<tmdb>" (film) / "s<tmdb>" (série) = "tt…|note×10|durée min|année".

Variables d'environnement (secrets GitHub) : ROBOT_EMAIL, ROBOT_PASSWORD, HOUSEHOLDS (UID séparés par des virgules).
Aucun identifiant IPTV n'est utilisé ici. Bibliothèque standard Python seulement.
"""
import gzip
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from urllib.parse import urlencode

API_KEY = "AIzaSyCJQAAhNf8j50_M3qt7jP7EKnz_4a2FVf0"  # clé publique du projet (pas un secret)
PROJECT_ID = "iptv-sync-5039f"
DOC_NAME = f"projects/{PROJECT_ID}/databases/(default)/documents"
DB_URL = f"https://firestore.googleapis.com/v1/{DOC_NAME}"
AUTH_URL = "https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword"
RATINGS_URL = "https://datasets.imdbws.com/title.ratings.tsv.gz"
UA = {"User-Agent": "IPTVPlayer-imdb-job (tâche planifiée, usage personnel)"}
SHARDS = 16
BATCH = 50
MISS_RETRY_DAYS = 7
TMDB_PROP = {"m": "P4947", "s": "P4983"}
UNITS = {"Q7727": 1, "Q25235": 60, "Q11574": 1 / 60}  # minute, heure, seconde


def log(*args):
    print(*args, flush=True)


# ---- Firebase (REST) ----------------------------------------------------------------- #
def http(method: str, url: str, body=None, token: str = "", timeout: int = 60):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={**UA, "Content-Type": "application/json"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise RuntimeError(f"{method} {url.split('?')[0]} -> {e.code} {e.read()[:300]!r}") from None


def sign_in(email: str, password: str) -> str:
    r = http("POST", f"{AUTH_URL}?key={API_KEY}", {"email": email, "password": password, "returnSecureToken": True})
    return r["idToken"]


def get_fields(path: str, token: str) -> dict:
    r = http("GET", f"{DB_URL}/{path}", token=token)
    return {k: v.get("stringValue", "") for k, v in ((r or {}).get("fields") or {}).items()}


def write_fields(path: str, fields: dict, token: str) -> None:
    """Écrit seulement ces champs (les autres restent), par paquets."""
    items = list(fields.items())
    for i in range(0, len(items), 1000):
        chunk = dict(items[i:i + 1000])
        body = {"writes": [{"update": {"name": f"{DOC_NAME}/{path}",
                                       "fields": {k: {"stringValue": v} for k, v in chunk.items()}},
                            "updateMask": {"fieldPaths": list(chunk)}}]}
        http("POST", f"{DB_URL}:commit", body, token=token)


# ---- Wikidata --------------------------------------------------------------------------- #
def wikidata(**params) -> dict:
    url = "https://www.wikidata.org/w/api.php?" + urlencode({**params, "format": "json"})
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        return json.loads(r.read())


def _minutes(claims: list) -> int:
    for c in claims:
        v = c.get("mainsnak", {}).get("datavalue", {}).get("value")
        if isinstance(v, dict):
            factor = UNITS.get(str(v.get("unit", "")).rsplit("/", 1)[-1])
            try:
                if factor:
                    return max(0, round(float(v.get("amount", 0)) * factor))
            except (TypeError, ValueError):
                pass
    return 0


def _year(claims: dict) -> int:
    for prop in ("P577", "P580"):
        years = []
        for c in claims.get(prop, []):
            t = str(c.get("mainsnak", {}).get("datavalue", {}).get("value", {}).get("time", ""))
            if len(t) >= 5 and t[1:5].isdigit():
                years.append(int(t[1:5]))
        if years:
            return min(years)
    return 0


def lookup_batch(kind: str, ids: list[str]) -> dict:
    """{numéro TMDB : (identifiant IMDb, durée, année)} pour ceux que Wikidata connaît."""
    prop = TMDB_PROP[kind]
    search = "haswbstatement:" + "|".join(f"{prop}={i}" for i in ids)
    hits = wikidata(action="query", list="search", srsearch=search, srlimit=BATCH, srprop="")["query"]["search"]
    if not hits:
        return {}
    ents = wikidata(action="wbgetentities", ids="|".join(h["title"] for h in hits), props="claims").get("entities", {})
    wanted, found = set(ids), {}
    for e in ents.values():
        claims = e.get("claims", {})
        tt = next((str(c["mainsnak"]["datavalue"]["value"]) for c in claims.get("P345", [])
                   if str(c.get("mainsnak", {}).get("datavalue", {}).get("value", "")).startswith("tt")), "")
        for c in claims.get(prop, []):
            tmdb = str(c.get("mainsnak", {}).get("datavalue", {}).get("value", ""))
            if tmdb in wanted and tt:
                found[tmdb] = (tt, _minutes(claims.get("P2047", [])), _year(claims))
    return found


# ---- Notes IMDb --------------------------------------------------------------------------- #
def load_ratings() -> dict:
    with urllib.request.urlopen(urllib.request.Request(RATINGS_URL, headers=UA), timeout=120) as r:
        blob = r.read()
    out = {}
    with gzip.open(io.BytesIO(blob), "rt", encoding="utf-8") as f:
        next(f, None)
        for line in f:
            tconst, rating, _ = line.split("\t", 2)
            try:
                out[tconst] = round(float(rating) * 10)
            except ValueError:
                pass
    return out


def encode(tt: str, r: int, d: int, y: int) -> str:
    return f"{tt}|{r if r >= 0 else ''}|{d or ''}|{y or ''}"


def decode(text: str):
    p = (str(text).split("|") + ["", "", "", ""])[:4]
    num = lambda x, default: int(x) if x.isdigit() else default
    return p[0], num(p[1], -1), num(p[2], 0), num(p[3], 0)


# ---- Tâche ------------------------------------------------------------------------------------ #
def main() -> int:
    email, password = os.environ.get("ROBOT_EMAIL", ""), os.environ.get("ROBOT_PASSWORD", "")
    households = [h.strip() for h in os.environ.get("HOUSEHOLDS", "").split(",") if h.strip()]
    if not (email and password and households):
        log("ROBOT_EMAIL, ROBOT_PASSWORD et HOUSEHOLDS sont obligatoires.")
        return 2
    token = sign_in(email, password)
    started = time.time()

    base = {}  # clé -> valeur actuelle de la base commune
    for i in range(SHARDS):
        base.update(get_fields(f"imdb/s{i:02d}", token))
    requested = set()
    for uid in households:
        for i in range(SHARDS):
            requested.update(get_fields(f"households/{uid}/imdb_req/s{i:02d}", token))
    requested = {k for k in requested if len(k) > 1 and k[0] in "ms" and k[1:].isdigit()}
    log(f"base : {len(base)} titres ; demandés : {len(requested)}")

    today = datetime.now(timezone.utc)
    stamp = "?" + today.strftime("%Y%m%d")

    def due(k: str) -> bool:
        v = base.get(k, "")
        if not v:
            return True
        if v.startswith("?"):
            try:
                return (today - datetime.strptime(v[1:9], "%Y%m%d").replace(tzinfo=timezone.utc)).days >= MISS_RETRY_DAYS
            except ValueError:
                return True
        return False

    changes: dict[str, str] = {}
    todo = sorted(k for k in requested if due(k))
    log(f"à relier par Wikidata : {len(todo)}")
    for kind in ("m", "s"):
        keys = [k for k in todo if k[0] == kind]
        for i in range(0, len(keys), BATCH):
            batch = keys[i:i + BATCH]
            for attempt in range(3):
                try:
                    found = lookup_batch(kind, [k[1:] for k in batch])
                    break
                except Exception as e:  # Wikidata refuse des appels trop rapprochés : on patiente
                    log("  Wikidata :", e)
                    time.sleep(20 * (attempt + 1))
            else:
                continue
            for k in batch:
                hit = found.get(k[1:])
                changes[k] = encode(hit[0], -1, hit[1], hit[2]) if hit else stamp
            if (i // BATCH) % 20 == 0:
                log(f"  {kind} : {min(i + BATCH, len(keys))} / {len(keys)}")
            time.sleep(1)

    ratings = load_ratings()
    log(f"notes IMDb : {len(ratings)} titres")
    merged = {**base, **changes}
    for k, v in merged.items():
        if not v or v.startswith("?"):
            continue
        tt, r, d, y = decode(v)
        new = encode(tt, ratings.get(tt, -1), d, y)
        if new != base.get(k):
            changes[k] = new
        elif k in changes and changes[k] != new:
            changes[k] = new

    real = {k: v for k, v in changes.items() if base.get(k) != v}
    by_shard: dict[str, dict] = {}
    for k, v in real.items():
        by_shard.setdefault(f"imdb/s{int(k[1:]) % SHARDS:02d}", {})[k] = v
    for path, fields in sorted(by_shard.items()):
        write_fields(path, fields, token)
    known = sum(1 for v in merged.values() if v and not v.startswith("?"))
    log(f"écrit : {len(real)} titres modifiés ; base : {known} titres reliés à IMDb ; {time.time() - started:.0f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
