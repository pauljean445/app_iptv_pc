"""Favoris, positions de lecture, « Vu récemment », épisodes vus et langues choisies (library.json).

Chaque entrée porte l'heure de sa dernière modification (« t ») et chaque suppression laisse une trace
datée dans « deleted » : en synchronisant plusieurs appareils, on garde pour chaque entrée la version la
plus récente, et un favori retiré sur un appareil ne revient pas depuis un autre. Les traces de plus de
3 mois (contenus terminés ou retirés) sont effacées au chargement ; les contenus en cours sont gardés.
"""
import time

from . import config

MIN_RESUME_MS = 15_000      # en dessous, on ne mémorise pas la position
FINISHED_RATIO = 0.95       # au-delà, le film / l'épisode est considéré comme vu
FINISHED_REMAINING_MS = 90_000  # ... ou s'il reste moins de 1 min 30 (génériques)
PURGE_DAYS = 90             # durée de conservation des traces de suppression

VERSION = 2
# fav      : "onglet|clé" -> {"o": ordre, "t"}            (onglets : live, movie, series, replay)
# progress : clé film / épisode -> {"pos": ms, "len": ms, "t"}
# recent   : clé film / série -> {"kind", "name", "t", "last_ep", "last_label", "total"}
# watched  : clé épisode vu -> {"s": clé de la série, "t"}
# prefs    : clé film / série -> {"audio", "spu", "t"}    (langue et sous-titres choisis)
TABLES = ("fav", "progress", "recent", "watched", "prefs")


def is_finished(pos: int, length: int) -> bool:
    return length > 0 and (pos >= length * FINISHED_RATIO or length - pos <= FINISHED_REMAINING_MS)


def _upgrade(data: dict) -> dict:
    """library.json d'avant la synchronisation : favoris en listes, épisodes vus rangés dans « Vu récemment »."""
    now = time.time()
    fav = {f"{tab}|{key}": {"o": float(i), "t": now}
           for tab, keys in (data.get("favorites") or {}).items() for i, key in enumerate(keys)}
    recent, watched = {}, {}
    for key, entry in (data.get("recent") or {}).items():
        entry = dict(entry)
        for ep in entry.pop("watched", None) or ():
            watched[ep] = {"s": key, "t": entry.get("t", now)}
        recent[key] = entry
    return {"v": VERSION, "fav": fav, "progress": data.get("progress") or {}, "recent": recent,
            "watched": watched, "track_prefs": data.get("track_prefs")}


class Library:
    def __init__(self, folder=None):
        self.folder = folder or config.profile_dir()  # dossier du profil (fixé : changer de profil = autre Library)
        data = config.load_json("library.json", self.folder)
        self.dirty = data.get("v") != VERSION
        if self.dirty:
            data = _upgrade(data)
        self.tables: dict[str, dict] = {name: data.get(name) or {} for name in TABLES}
        deleted = data.get("deleted") or {}
        self.deleted: dict[str, dict] = {name: deleted.get(name) or {} for name in TABLES}
        self.fav, self.progress, self.recent, self.watched, self.prefs = (self.tables[n] for n in TABLES)
        # Langues mémorisées avant la synchronisation (déplacées de profile.json par config)
        for key, pref in (data.get("track_prefs") or {}).items():
            if key not in self.prefs:
                self.prefs[key] = dict(pref, t=time.time())
                self.dirty = True
        self._purge()
        self.save()

    def save(self, force: bool = False) -> None:
        if self.dirty or force:
            config.save_json("library.json", {"v": VERSION, **self.tables, "deleted": self.deleted}, self.folder)
            self.dirty = False

    def _stamp(self, table: str, key: str) -> float:
        """Heure de la modification, toujours après la précédente de cette entrée (horloge à paliers sous
        Windows) : sinon une suppression juste après un ajout aurait la même heure et ne gagnerait pas."""
        old = self.tables[table].get(key, {}).get("t") or self.deleted[table].get(key) or 0
        return max(time.time(), old + 0.001)

    def _put(self, table: str, key: str, entry: dict) -> None:
        entry["t"] = self._stamp(table, key)
        self.tables[table][key] = entry
        self.deleted[table].pop(key, None)
        self.dirty = True

    def _drop(self, table: str, key: str) -> None:
        if key in self.tables[table]:
            self.deleted[table][key] = self._stamp(table, key)
            del self.tables[table][key]
            self.dirty = True

    def _purge(self) -> None:
        limit = time.time() - PURGE_DAYS * 86400
        for marks in self.deleted.values():
            for key in [k for k, t in marks.items() if t < limit]:
                del marks[key]
                self.dirty = True

    def reset(self) -> None:
        """Efface tout le profil (changement de fournisseur IPTV : les clés ne correspondent plus)."""
        for name in TABLES:
            for key in list(self.tables[name]):
                self._drop(name, key)
        self.save()

    # ---- Favoris (par onglet : live, movie, series, replay) --------------- #
    def _fav_rows(self, tab: str) -> list[tuple[float, str]]:
        prefix = tab + "|"
        return sorted((v["o"], k[len(prefix):]) for k, v in self.fav.items() if k.startswith(prefix))

    def is_favorite(self, tab: str, key: str) -> bool:
        return f"{tab}|{key}" in self.fav

    def toggle_favorite(self, tab: str, key: str) -> bool:
        fk = f"{tab}|{key}"
        added = fk not in self.fav
        if added:
            rows = self._fav_rows(tab)
            self._put("fav", fk, {"o": rows[-1][0] + 1 if rows else 0.0})
        else:
            self._drop("fav", fk)
        self.save()
        return added

    def favorite_keys(self, tab: str) -> list[str]:
        return [k for _, k in self._fav_rows(tab)]

    def move_favorite(self, tab: str, key: str, before: str | None) -> None:
        """Change l'ordre des favoris : key passe juste avant before (à la fin si None)."""
        keys = self.favorite_keys(tab)
        if key not in keys or key == before:
            return
        keys.remove(key)
        i = keys.index(before) if before in keys else len(keys)
        # Seul le favori déplacé change : il prend un ordre entre ses deux nouveaux voisins
        lo = self.fav[f"{tab}|{keys[i - 1]}"]["o"] if i > 0 else None
        hi = self.fav[f"{tab}|{keys[i]}"]["o"] if i < len(keys) else None
        if lo is None:
            o = hi - 1 if hi is not None else 0.0
        elif hi is None:
            o = lo + 1
        else:
            o = (lo + hi) / 2
        if lo is not None and hi is not None and not lo < o < hi:
            # Plus de place entre les deux voisins (nombreux déplacements au même endroit) : on renumérote
            keys.insert(i, key)
            for n, k in enumerate(keys):
                self._put("fav", f"{tab}|{k}", {"o": float(n)})
        else:
            self._put("fav", f"{tab}|{key}", {"o": o})
        self.save()

    # ---- Reprise de lecture ----------------------------------------------- #
    def resume_position(self, key: str) -> int:
        p = self.progress.get(key)
        if not p:
            return 0
        pos, length = int(p.get("pos", 0)), int(p.get("len", 0))
        if pos < MIN_RESUME_MS or is_finished(pos, length):
            return 0
        return pos

    def watched_keys(self, show_key: str) -> set[str]:
        return {k for k, v in self.watched.items() if v.get("s") == show_key}

    def is_watched(self, episode) -> bool:
        parent = episode.parent
        return parent is not None and parent.key in self.recent and episode.key in self.watched

    def set_unwatched(self, episode) -> None:
        self._drop("watched", episode.key)

    def update(self, item, pos: int, length: int, finished: bool) -> None:
        """Enregistre l'avancement d'un film ou d'un épisode."""
        if item.kind == "movie":
            if finished:
                self._drop("progress", item.key)
                self._drop("recent", item.key)
            elif pos >= MIN_RESUME_MS:
                self._put("progress", item.key, {"pos": pos, "len": length})
                self._put("recent", item.key, {"kind": "movie", "name": item.name})
        elif item.kind == "episode" and item.parent is not None:
            show = item.parent
            if finished:
                self._drop("progress", item.key)
                if item.key not in self.watched:
                    self._put("watched", item.key, {"s": show.key})
            elif pos >= MIN_RESUME_MS:
                self._put("progress", item.key, {"pos": pos, "len": length})
            elif show.key not in self.recent:
                return
            label = f"S{item.season:02d}E{item.episode:02d}" if (item.season or item.episode) else item.name
            entry = dict(self.recent.get(show.key) or {"kind": "series"})
            entry.update(last_ep=item.key, last_label=label, name=show.name)
            all_keys = {e.key for e in (show.episodes or [])}
            if all_keys:
                entry["total"] = len(all_keys)
            if all_keys and all_keys <= self.watched_keys(show.key):
                # Toute la série a été vue : on la retire de « Vu récemment »
                self._drop("recent", show.key)
                for k in all_keys:
                    self._drop("progress", k)
                    self._drop("watched", k)
            else:
                self._put("recent", show.key, entry)

    def recent_keys(self, kind: str) -> list[str]:
        rows = [(v.get("t", 0), k) for k, v in self.recent.items() if v.get("kind") == kind]
        return [k for _, k in sorted(rows, reverse=True)]

    def remove_recent(self, key: str, episode_keys=()) -> None:
        self._drop("recent", key)
        self._drop("progress", key)
        for k in episode_keys:
            self._drop("progress", k)
        for k in self.watched_keys(key):
            self._drop("watched", k)
        self.save()

    # ---- Langue et sous-titres mémorisés (par film ou par série) ----------- #
    def set_pref(self, key: str, kind: str, value) -> None:
        """kind : "audio" ou "spu" ; value : piste choisie (tracks.Track.pref()) ou "off"."""
        entry = dict(self.prefs.get(key) or {})
        entry[kind] = value
        self._put("prefs", key, entry)
        self.save()
