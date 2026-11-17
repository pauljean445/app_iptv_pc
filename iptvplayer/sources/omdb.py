"""Notes IMDb via l'API OMDb (clé gratuite sur https://www.omdbapi.com/apikey.aspx).

OMDb ne connaît que les titres anglais : une recherche avec le titre français du fournisseur échoue presque
toujours. On passe donc d'abord par l'identifiant TMDB que donne le fournisseur : Wikidata (gratuit, sans clé)
fait le lien TMDB -> IMDb, puis OMDb est interrogé par identifiant IMDb. Recherche par titre en dernier recours.
Les réponses sont mises en cache dans meta_cache.json (la clé gratuite est limitée à 1000 requêtes / jour).
"""
import json
import re
import threading
import time
import urllib.request
from urllib.parse import urlencode

from .. import config
from .playlist import http_get
from . import imdb_ratings

_CACHE_FILE = "meta_cache.json"
_MISS_TTL = 7 * 86400  # on retente une recherche infructueuse au bout d'une semaine
_NO_RATING_TTL = 86400  # titre trouvé sans note IMDb (encore « N/A » chez OMDb) : nouvel essai le lendemain
_lock = threading.Lock()
_cache: dict | None = None


class InvalidKey(RuntimeError):
    pass


def _get_cache() -> dict:
    global _cache
    if _cache is None:
        _cache = config.load_json(_CACHE_FILE)
    return _cache


def _query(api_key: str, **params) -> dict:
    url = "https://www.omdbapi.com/?" + urlencode({"apikey": api_key, **params})
    data = json.loads(http_get(url, timeout=15).decode("utf-8", errors="replace"))
    if data.get("Response") == "False":
        err = data.get("Error", "")
        if "API key" in err or "limit" in err.lower():
            raise InvalidKey(f"OMDb : {err}")
        return {}
    return data


def remember_rating(item_key: str, rating: str) -> None:
    """Note IMDb trouvée pour une entrée du catalogue : réaffichée dans les listes aux prochains lancements."""
    if not item_key or not rating:
        return
    with _lock:
        cache = _get_cache()
        if cache.get("imdb_ratings", {}).get(item_key) == rating:
            return
        cache.setdefault("imdb_ratings", {})[item_key] = rating
        config.save_json(_CACHE_FILE, cache)


def known_ratings() -> dict:
    """{clé d'entrée : note IMDb} des titres déjà trouvés."""
    with _lock:
        return dict(_get_cache().get("imdb_ratings", {}))


_YEAR_SUFFIX = re.compile(r"\s*[(\[]\s*(?:19|20)\d{2}\s*[)\]]\s*$")


def _wikidata(**params) -> dict:
    url = "https://www.wikidata.org/w/api.php?" + urlencode({**params, "format": "json"})
    req = urllib.request.Request(url, headers={"User-Agent": "IPTVPlayer (lecteur IPTV de bureau)"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8", errors="replace"))


def imdb_from_tmdb(tmdb_id: str, kind: str = "movie") -> str | None:
    """Identifiant IMDb (« tt… ») d'un film / d'une série TMDB, via Wikidata ; "" si inconnu (mis en cache),
    None si Wikidata n'a pas répondu (rien en cache : nouvel essai à la prochaine ouverture de la fiche)."""
    tmdb_id = str(tmdb_id or "").strip()
    if not tmdb_id.isdigit():
        return ""
    key = f"wd|{kind}|{tmdb_id}"
    with _lock:
        hit = _get_cache().get(key)
    if hit is not None and (hit.get("imdb") or time.time() - hit.get("t", 0) < _MISS_TTL):
        return hit.get("imdb", "")
    prop = "P4983" if kind == "series" else "P4947"  # identifiant TMDB série / film
    # API classique de Wikidata (le service SPARQL est souvent bridé) : élément portant cet identifiant TMDB,
    # puis sa propriété P345 (identifiant IMDb)
    for attempt in range(2):  # Wikidata refuse parfois des appels trop rapprochés : un nouvel essai 1 s après
        try:
            hits = _wikidata(action="query", list="search", srsearch=f"haswbstatement:{prop}={tmdb_id}",
                             srlimit=1, srprop="")["query"]["search"]
            imdb = ""
            if hits:
                claims = _wikidata(action="wbgetclaims", entity=hits[0]["title"], property="P345").get("claims", {})
                values = [c.get("mainsnak", {}).get("datavalue", {}).get("value", "") for c in claims.get("P345", [])]
                imdb = next((v for v in values if str(v).startswith("tt")), "")
            break
        except Exception:
            if attempt:
                return None  # Wikidata injoignable
            time.sleep(1)
    with _lock:
        cache = _get_cache()
        cache[key] = {"imdb": imdb, "t": time.time()}
        config.save_json(_CACHE_FILE, cache)
    return imdb


def lookup(api_key: str, titles: list[str], year: str = "", kind: str = "movie", tmdb_id: str = "") -> dict:
    """Retourne {"rating": "7.8", "imdb_id": "tt…", "plot": …, "poster": …} ou {} si introuvable.
    Sans clé OMDb : identifiant IMDb par Wikidata (TMDB du fournisseur) et note du fichier officiel d'IMDb. Avec une
    clé : OMDb en plus (titres absents de Wikidata, résumé anglais, affiche)."""
    found = _lookup_omdb(api_key, titles, year, kind, tmdb_id) if api_key else {}
    tt = found.get("imdb_id") or ""
    if not tt and tmdb_id:
        tt = imdb_from_tmdb(tmdb_id, kind) or ""
    # Seule la note du fichier officiel d'IMDb est affichée (celle d'OMDb est souvent ancienne ou absente)
    return {**found, "imdb_id": tt, "rating": imdb_ratings.rating(tt) if tt else ""}


def _lookup_omdb(api_key: str, titles: list[str], year: str = "", kind: str = "movie", tmdb_id: str = "") -> dict:
    """Fiche OMDb (mise en cache) : identifiant IMDb, résumé anglais, affiche, note OMDb."""
    titles = [t for t in dict.fromkeys(_YEAR_SUFFIX.sub("", t).strip() for t in titles) if t]
    if not api_key or not (titles or tmdb_id):
        return {}
    cache_key = f"v2|{kind}|tmdb:{tmdb_id}" if tmdb_id else f"v2|{kind}|{titles[0].lower()}|{year}"
    with _lock:
        hit = _get_cache().get(cache_key)
    # Titre trouvé mais encore sans note (film récent : OMDb recopie les notes IMDb avec du retard) : on redemande
    # chaque jour ; titre introuvable : chaque semaine
    retry = _NO_RATING_TTL if hit and hit.get("imdb_id") else _MISS_TTL
    if hit is not None and (hit.get("rating") or time.time() - hit.get("t", 0) < retry):
        return hit

    omdb_type = "series" if kind == "series" else "movie"
    found = {}
    imdb = imdb_from_tmdb(tmdb_id, kind) if tmdb_id else ""
    unsure = imdb is None  # Wikidata muet : un échec ici ne prouve pas que le titre est introuvable
    attempts = [{"i": imdb}] if imdb else []
    attempts += [{"t": t, "type": omdb_type, "y": year} for t in titles if year]
    attempts += [{"t": t, "type": omdb_type} for t in titles]
    for params in attempts:
        data = _query(api_key, **params)
        if data:
            rating = data.get("imdbRating", "")
            found = {
                "rating": rating if rating not in ("", "N/A") else "",
                "imdb_id": data.get("imdbID", ""),
                "plot": data.get("Plot", "") if data.get("Plot") != "N/A" else "",
                "poster": data.get("Poster", "") if str(data.get("Poster", "")).startswith("http") else "",
                "year": str(data.get("Year", ""))[:4] if str(data.get("Year", ""))[:4].isdigit() else "",
                "runtime": int(str(data.get("Runtime", "")).split()[0]) if str(data.get("Runtime", "")).split()[:1]
                and str(data.get("Runtime", "")).split()[0].isdigit() else 0,
            }
            break
    found["t"] = time.time()
    if unsure and not found.get("imdb_id"):
        return found  # pas mis en cache : on réessaiera quand Wikidata répondra
    with _lock:
        cache = _get_cache()
        cache[cache_key] = found
        config.save_json(_CACHE_FILE, cache)
    return found
