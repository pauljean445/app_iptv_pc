"""Base commune des notes IMDb (lue par le PC, la TV et le téléphone ; remplie par une tâche planifiée).

Firestore :
- imdb/s00 … s15 (hors des foyers, lue par tous les foyers, écrite seulement par le compte « robot » de la tâche
  GitHub tools/imdb_job.py, chaque nuit) : un champ par titre, réparti selon son numéro TMDB :
      "m1185344": "tt29256561|47|101|2026"  film TMDB 1185344 : identifiant IMDb | note × 10 | durée (min) | année
      "s1396":    "tt0903747|95||2008"      série TMDB 1396 ; "?20261117" = inconnu de Wikidata ce jour-là
- households/<uid>/imdb_req/s00 … s15 : titres du catalogue de ce foyer à relier (un champ vide par titre), écrits
  par l'appli quand ils ne sont pas dans la base ; la tâche les traite la nuit suivante.
Copie locale imdb_base.json : notes affichées dès le lancement, aussi hors ligne.
"""
import threading
import time

from . import config

SHARDS = 16
LOCAL = "imdb_base.json"


def key_of(it) -> str:
    """Clé d'une entrée du catalogue (« m123 » film, « s456 » série), "" sans numéro TMDB."""
    tmdb = str(getattr(it, "tmdb", "") or "")
    if not tmdb.isdigit() or it.kind not in ("movie", "series"):
        return ""
    return ("m" if it.kind == "movie" else "s") + tmdb


def shard(key: str) -> str:
    return f"s{int(key[1:]) % SHARDS:02d}"


def decode(text: str) -> tuple[str, int, int, int] | None:
    """(identifiant IMDb, note × 10 ou -1, durée, année), None si le titre n'est pas (encore) relié à IMDb."""
    p = (str(text).split("|") + ["", "", "", ""])[:4]
    if not p[0].startswith("tt"):
        return None
    num = lambda x, default: int(x) if x.isdigit() else default
    return p[0], num(p[1], -1), num(p[2], 0), num(p[3], 0)


class Base:
    def __init__(self):
        self.lock = threading.Lock()
        data = config.load_json(LOCAL)
        if data.get("v") != 3:
            data = {}
        self.values: dict[str, str] = dict(data.get("values") or {})      # copie de la base commune
        self.requested: set[str] = set(data.get("requested") or [])        # déjà inscrits pour ce foyer
        self.pulled = float(data.get("pulled") or 0)

    def get(self, key: str):
        return decode(self.values[key]) if key and key in self.values else None

    def save(self) -> None:
        with self.lock:
            data = {"v": 3, "values": self.values, "requested": sorted(self.requested), "pulled": self.pulled}
        config.save_json(LOCAL, data)

    def sync(self, session, keys: list[str]) -> bool:
        """Lit la base commune, puis inscrit pour la tâche de la nuit les titres du catalogue qui n'y sont pas.
        Retourne True si des notes ont changé ici."""
        changed = False
        for i in range(SHARDS):
            try:
                doc = session.get_root_doc(f"imdb/s{i:02d}") or {}
            except Exception:
                break  # base commune pas encore lisible (règle) ou hors ligne : on inscrit quand même les titres
            with self.lock:
                for k, v in doc.items():
                    if isinstance(v, str) and self.values.get(k) != v:
                        self.values[k] = v
                        changed = True
        self.pulled = time.time()
        with self.lock:
            missing = [k for k in dict.fromkeys(keys) if k and k not in self.values and k not in self.requested]
        by_shard: dict[str, dict] = {}
        for k in missing:
            by_shard.setdefault(shard(k), {})[k] = ""
        for name, fields in by_shard.items():
            items = list(fields.items())
            for i in range(0, len(items), 1000):
                chunk = dict(items[i:i + 1000])
                session.commit([(f"imdb_req/{name}", chunk, [])], timeout=30)
                with self.lock:
                    self.requested.update(chunk)
        self.save()
        return changed


_base: Base | None = None


def base() -> Base:
    global _base
    if _base is None:
        _base = Base()
    return _base
