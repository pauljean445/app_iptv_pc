"""Tâche planifiée (GitHub Actions, chaque nuit) : base commune des notes IMDb des applis IPTV Player.

1. Se connecte au projet Firebase avec le compte « robot » (seul autorisé à écrire la base commune).
2. Lit les titres demandés par les foyers listés (households/<uid>/imdb_req/sNN : un champ par titre, écrit par
   les applis PC / TV / téléphone quand un titre de leur catalogue n'est pas dans la base).
3. Relie les nouveaux titres (numéro TMDB du fournisseur) à IMDb par Wikidata, 50 par appel : identifiant IMDb,
   durée (P2047), année (P577 / P580). Titres inconnus : marqués « ?AAAAMMJJ », réessayés au bout d'une semaine.
4. Prend chez IMDb, pour tous les titres reliés, la note (datasets.imdbws.com/title.ratings.tsv.gz) ET l'année et
   la durée (title.basics.tsv.gz, 230 Mo lus au fil du téléchargement, ~15 s) : fichiers officiels, gratuits pour un
   usage personnel non commercial, publiés chaque jour. TMDB / Wikidata ne servent qu'à relier le numéro TMDB du
   fournisseur à l'identifiant IMDb (IMDb ne fournit pas ce lien), et en secours si IMDb n'a pas l'info.
5. Écrit la base commune imdb/sNN : "m<tmdb>" (film) / "s<tmdb>" (série) = "tt…|note×10|durée min|année".

3 bis. Si TMDB_TOKEN est fourni (clé gratuite de l'API TMDB, la base d'où viennent les numéros du fournisseur) :
   identifiant IMDb, durée et année d'abord par TMDB (complet, même pour les films récents), pour les nouveaux titres
   et ceux à qui il manque une info ; Wikidata seulement pour ce que TMDB ne relie pas.

Variables d'environnement (secrets GitHub) : ROBOT_EMAIL, ROBOT_PASSWORD, HOUSEHOLDS (UID séparés par des virgules),
TMDB_TOKEN (facultatif : « jeton d'accès en lecture » v4 ou clé v3).
Aucun identifiant IPTV n'est utilisé ici. Bibliothèque standard Python seulement.
"""
import gzip
import io
from concurrent.futures import ThreadPoolExecutor, as_completed
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
BASICS_URL = "https://datasets.imdbws.com/title.basics.tsv.gz"
# Wikimedia demande aux programmes de s'identifier (nom + adresse de contact) : sinon, depuis les machines partagées
# de GitHub, les appels sont vite refusés (« 429 Too Many Requests »)
UA = {"User-Agent": "IPTVPlayerImdbJob/1.1 (https://github.com/pauljean445/app_iptv_pc; tache planifiee, usage "
                    "personnel) python-urllib"}
SHARDS = 16
BATCH = 50
MISS_RETRY_DAYS = 7
PAUSE = 2.0               # secondes entre deux lots (deux appels Wikidata chacun)
SAVE_EVERY = 20           # lots : écriture intermédiaire dans la base (rien de perdu si la tâche s'arrête)
WIKIDATA_BUDGET = 45 * 60 # au-delà, la suite est reprise la nuit suivante (la tâche est limitée à 60 min)
TMDB_PROP = {"m": "P4947", "s": "P4983"}
TMDB_URL = "https://api.themoviedb.org/3"
TMDB_RETRY_DAYS = 30      # titre vérifié sur TMDB mais encore incomplet : nouvel essai au bout d'un mois
TMDB_WORKERS = 8
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
    """Appel à l'API Wikidata (lecture seule : pas de « maxlag », réservé aux programmes qui modifient Wikidata et qui
    faisait refuser nos lectures dès que ses serveurs avaient quelques secondes de retard). Trop d'appels (429 / 503) :
    attente (celle demandée par le serveur, au moins 15 s puis de plus en plus), 8 essais au plus."""
    url = "https://www.wikidata.org/w/api.php?" + urlencode({**params, "format": "json"})
    for attempt in range(8):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                data = json.loads(r.read())
                wait = r.headers.get("Retry-After")
        except urllib.error.HTTPError as e:
            if e.code not in (429, 503):
                raise
            wait = e.headers.get("Retry-After")
            data = None
        if data is not None and data.get("error", {}).get("code") != "maxlag":
            return data
        delay = max(int(wait) if str(wait or "").isdigit() else 0, 15 * (attempt + 1))
        log(f"  Wikidata demande d'attendre {delay} s")
        time.sleep(min(delay, 300))
    raise RuntimeError("Wikidata refuse les appels (trop de demandes)")


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


def load_basics(wanted: set) -> dict:
    """{identifiant IMDb : (durée en minutes, année)} pour les titres voulus, lus au fil du téléchargement."""
    out = {}
    req = urllib.request.Request(BASICS_URL, headers=UA)
    with urllib.request.urlopen(req, timeout=300) as r, gzip.GzipFile(fileobj=r) as g:
        g.readline()  # en-tête : tconst, titleType, primaryTitle, originalTitle, isAdult, startYear, endYear, runtime…
        for raw in g:
            tab = raw.find(b"\t")
            tc = raw[:tab].decode("ascii", "replace")
            if tc not in wanted:
                continue
            p = raw.decode("utf-8", "replace").rstrip("\n").split("\t")
            year = int(p[5]) if p[5].isdigit() else 0
            minutes = int(p[7]) if p[7].isdigit() else 0
            out[tc] = (minutes, year)
    return out


def encode(tt: str, r: int, d: int, y: int, checked: str = "") -> str:
    """5e champ facultatif : date de la dernière vérification sur TMDB (les applis ne lisent que les 4 premiers)."""
    base = f"{tt}|{r if r >= 0 else ''}|{d or ''}|{y or ''}"
    return f"{base}|{checked}" if checked else base


def checked_of(text: str) -> str:
    p = str(text).split("|")
    return p[4] if len(p) > 4 else ""


# ---- TMDB (facultatif) -------------------------------------------------------------------------- #
def tmdb_get(path: str, token: str):
    """GET sur l'API TMDB ; None si le titre n'existe pas ; attend si TMDB demande de ralentir."""
    bearer = len(token) > 40  # jeton v4 (long) ou clé v3 (32 caractères)
    url = f"{TMDB_URL}/{path}" + ("" if bearer else ("&" if "?" in path else "?") + f"api_key={token}")
    headers = {**UA, "Accept": "application/json"}
    if bearer:
        headers["Authorization"] = f"Bearer {token}"
    for attempt in range(5):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if e.code == 401:
                raise RuntimeError("TMDB refuse la clé (401) : vérifier le secret TMDB_TOKEN") from None
            if e.code != 429 and e.code < 500:
                raise
            wait = e.headers.get("Retry-After")
            time.sleep(max(int(wait) if str(wait or "").isdigit() else 0, 2 * (attempt + 1)))
    raise RuntimeError("TMDB ne répond pas")


def tmdb_lookup(key: str, token: str):
    """(identifiant IMDb ou "", durée en minutes, année) d'un titre TMDB ; None s'il n'existe pas sur TMDB."""
    tid = key[1:]
    if key[0] == "m":
        d = tmdb_get(f"movie/{tid}?append_to_response=external_ids", token)
        if d is None:
            return None
        tt = d.get("imdb_id") or (d.get("external_ids") or {}).get("imdb_id") or ""
        minutes = int(d.get("runtime") or 0)
        date = str(d.get("release_date") or "")
    else:
        d = tmdb_get(f"tv/{tid}?append_to_response=external_ids", token)
        if d is None:
            return None
        tt = (d.get("external_ids") or {}).get("imdb_id") or ""
        runs = d.get("episode_run_time") or []
        minutes = int(runs[0]) if runs else 0
        date = str(d.get("first_air_date") or "")
    year = int(date[:4]) if date[:4].isdigit() else 0
    return (tt if str(tt).startswith("tt") else ""), minutes, year


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
    written: dict[str, str] = {}

    def flush(values: dict) -> None:
        """Écrit dans la base ce qui a changé depuis le dernier envoi."""
        todo_w = {k: v for k, v in values.items() if base.get(k) != v and written.get(k) != v}
        by = {}
        for k, v in todo_w.items():
            by.setdefault(f"imdb/s{int(k[1:]) % SHARDS:02d}", {})[k] = v
        for path, fields in sorted(by.items()):
            write_fields(path, fields, token)
        written.update(todo_w)

    tmdb_token = os.environ.get("TMDB_TOKEN", "").strip()
    day = today.strftime("%Y%m%d")
    if tmdb_token:
        def since(datestr: str) -> int:
            try:
                return (today - datetime.strptime(datestr[:8], "%Y%m%d").replace(tzinfo=timezone.utc)).days
            except ValueError:
                return 10 ** 6

        def needs_tmdb(k: str) -> bool:
            v = changes.get(k, base.get(k, ""))
            if not v:
                return True
            if v.startswith("?"):
                # « ?AAAAMMJJT » : TMDB n'a pas trouvé -> nouvel essai au bout d'un mois ;
                # « ?AAAAMMJJ » : seul Wikidata a échoué -> TMDB tout de suite
                return since(v[1:9]) >= TMDB_RETRY_DAYS if v.endswith("T") else True
            tt, r, d, y = decode(v)
            if tt and d and y:
                return False  # complet
            c = checked_of(v)
            try:
                return not c or (today - datetime.strptime(c, "%Y%m%d").replace(tzinfo=timezone.utc)).days >= TMDB_RETRY_DAYS
            except ValueError:
                return True
        keys = sorted(k for k in requested if needs_tmdb(k))
        log(f"à compléter par TMDB : {len(keys)}")
        done_n, errors = 0, 0
        with ThreadPoolExecutor(TMDB_WORKERS) as ex:
            futures = {ex.submit(tmdb_lookup, k, tmdb_token): k for k in keys}
            for fut in as_completed(futures):
                k = futures[fut]
                try:
                    res = fut.result()
                except Exception as e:
                    errors += 1
                    if errors <= 3 or "401" in str(e):
                        log("  TMDB :", e)
                    if "401" in str(e):
                        ex.shutdown(cancel_futures=True)
                        break
                    continue
                old = changes.get(k, base.get(k, ""))
                ot, orr, od, oy = decode(old) if old.startswith("tt") else ("", -1, 0, 0)
                if res is None:
                    tt, d, y = ot, od, oy
                else:
                    tt, d, y = res[0] or ot, res[1] or od, res[2] or oy
                if tt:
                    changes[k] = encode(tt, orr, d, y, day)
                elif not old.startswith("tt"):
                    changes[k] = "?" + day + "T"  # TMDB ne relie pas ce titre à IMDb (réessai dans un mois)
                done_n += 1
                if done_n % 1000 == 0:
                    flush(changes)
                    log(f"  TMDB : {done_n} / {len(keys)} (enregistré)")
        flush(changes)
        log(f"  TMDB : {done_n} titres vérifiés, {errors} erreurs")

    # Wikidata : nouveaux titres que TMDB n'a pas reliés (ou tous, sans clé TMDB)
    todo = sorted(k for k in requested if due(k) and not changes.get(k, "").startswith("tt"))
    log(f"à relier par Wikidata : {len(todo)}")
    lots = 0
    stopped = False
    for kind in ("m", "s"):
        keys = [k for k in todo if k[0] == kind]
        for i in range(0, len(keys), BATCH):
            if time.time() - started > WIKIDATA_BUDGET:
                stopped = True
                break
            batch = keys[i:i + BATCH]
            try:
                found = lookup_batch(kind, [k[1:] for k in batch])
            except Exception as e:
                log("  Wikidata :", e, "- arrêt pour cette nuit, reprise la nuit suivante")
                stopped = True
                break
            for k in batch:
                hit = found.get(k[1:])
                if hit:
                    changes[k] = encode(hit[0], -1, hit[1], hit[2])
                elif not changes.get(k, "").startswith("?"):
                    changes[k] = stamp  # (marqueur TMDB du même passage gardé)
            lots += 1
            if lots % SAVE_EVERY == 0:
                flush(changes)
                log(f"  {kind} : {min(i + BATCH, len(keys))} / {len(keys)} (enregistré)")
            time.sleep(PAUSE)
        if stopped:
            break
    if stopped:
        log(f"  {len(changes)} titres traités cette nuit sur {len(todo)}")

    ratings = load_ratings()
    log(f"notes IMDb : {len(ratings)} titres")
    merged = {**base, **changes}
    linked = {decode(v)[0] for v in merged.values() if v and v.startswith("tt")}
    try:
        basics = load_basics(linked)
        log(f"années et durées IMDb : {len(basics)} titres")
    except Exception as e:  # fichier indisponible : on garde ce qu'on a
        log("  title.basics :", e)
        basics = {}
    for k, v in merged.items():
        if not v or v.startswith("?"):
            continue
        tt, r, d, y = decode(v)
        bd, by = basics.get(tt, (0, 0))
        new = encode(tt, ratings.get(tt, -1), bd or d, by or y, checked_of(v))
        if new != base.get(k):
            changes[k] = new
        elif k in changes and changes[k] != new:
            changes[k] = new

    flush(changes)
    real = {k: v for k, v in changes.items() if base.get(k) != v}
    known = sum(1 for v in {**merged, **changes}.values() if v and not v.startswith("?"))
    log(f"écrit : {len(real)} titres modifiés ; base : {known} titres reliés à IMDb ; {time.time() - started:.0f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
