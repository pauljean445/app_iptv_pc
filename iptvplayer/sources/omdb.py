"""Notes IMDb via l'API OMDb (clé gratuite sur https://www.omdbapi.com/apikey.aspx).

Les réponses sont mises en cache dans meta_cache.json (la clé gratuite est limitée à 1000 requêtes / jour).
"""
import json
import threading
import time
from urllib.parse import urlencode

from .. import config
from .playlist import http_get

_CACHE_FILE = "meta_cache.json"
_MISS_TTL = 7 * 86400  # on retente une recherche infructueuse au bout d'une semaine
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


def lookup(api_key: str, titles: list[str], year: str = "", kind: str = "movie") -> dict:
    """Retourne {"rating": "7.8", "imdb_id": "tt…", "plot": …, "poster": …} ou {} si introuvable."""
    titles = [t for t in dict.fromkeys(t.strip() for t in titles) if t]
    if not api_key or not titles:
        return {}
    cache_key = f"{kind}|{titles[0].lower()}|{year}"
    with _lock:
        hit = _get_cache().get(cache_key)
    if hit is not None and (hit.get("rating") or time.time() - hit.get("t", 0) < _MISS_TTL):
        return hit

    omdb_type = "series" if kind == "series" else "movie"
    found = {}
    attempts = [(t, year) for t in titles] + ([(t, "") for t in titles] if year else [])
    for title, y in attempts:
        params = {"t": title, "type": omdb_type}
        if y:
            params["y"] = y
        data = _query(api_key, **params)
        if data:
            rating = data.get("imdbRating", "")
            found = {
                "rating": rating if rating not in ("", "N/A") else "",
                "imdb_id": data.get("imdbID", ""),
                "plot": data.get("Plot", "") if data.get("Plot") != "N/A" else "",
                "poster": data.get("Poster", "") if str(data.get("Poster", "")).startswith("http") else "",
            }
            break
    found["t"] = time.time()
    with _lock:
        cache = _get_cache()
        cache[cache_key] = found
        config.save_json(_CACHE_FILE, cache)
    return found
