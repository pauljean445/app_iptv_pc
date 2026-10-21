"""Favoris, positions de lecture et « Vu récemment » (enregistrés dans library.json)."""
import time

from . import config

MIN_RESUME_MS = 15_000      # en dessous, on ne mémorise pas la position
FINISHED_RATIO = 0.95       # au-delà, le film / l'épisode est considéré comme vu
FINISHED_REMAINING_MS = 90_000  # ... ou s'il reste moins de 1 min 30 (génériques)


def is_finished(pos: int, length: int) -> bool:
    return length > 0 and (pos >= length * FINISHED_RATIO or length - pos <= FINISHED_REMAINING_MS)


class Library:
    def __init__(self, folder=None):
        self.folder = folder or config.profile_dir()  # dossier du profil (fixé : changer de profil = autre Library)
        data = config.load_json("library.json", self.folder)
        self.favorites: dict[str, list[str]] = data.get("favorites") or {}
        # clé film / épisode -> {"pos": ms, "len": ms, "t": timestamp}
        self.progress: dict[str, dict] = data.get("progress") or {}
        # clé film / série -> {"kind", "name", "t", "last_ep", "watched": [clés d'épisodes], "total"}
        self.recent: dict[str, dict] = data.get("recent") or {}
        self._fav_sets = {tab: set(keys) for tab, keys in self.favorites.items()}
        self.dirty = False

    def save(self, force: bool = False) -> None:
        if self.dirty or force:
            config.save_json("library.json", {
                "favorites": self.favorites, "progress": self.progress, "recent": self.recent,
            }, self.folder)
            self.dirty = False

    # ---- Favoris (par onglet : live, movie, series, replay) --------------- #
    def is_favorite(self, tab: str, key: str) -> bool:
        return key in self._fav_sets.get(tab, ())

    def toggle_favorite(self, tab: str, key: str) -> bool:
        keys = self.favorites.setdefault(tab, [])
        s = self._fav_sets.setdefault(tab, set())
        if key in s:
            s.discard(key)
            keys.remove(key)
            added = False
        else:
            s.add(key)
            keys.append(key)
            added = True
        self.dirty = True
        self.save()
        return added

    def favorite_keys(self, tab: str) -> list[str]:
        return list(self.favorites.get(tab, []))

    def move_favorite(self, tab: str, key: str, before: str | None) -> None:
        """Change l'ordre des favoris : key passe juste avant before (à la fin si None)."""
        keys = self.favorites.get(tab, [])
        if key not in keys or key == before:
            return
        keys.remove(key)
        keys.insert(keys.index(before) if before in keys else len(keys), key)
        self.dirty = True
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

    def is_watched(self, episode) -> bool:
        parent = episode.parent
        entry = self.recent.get(parent.key) if parent is not None else None
        return bool(entry) and episode.key in entry.get("watched", ())

    def update(self, item, pos: int, length: int, finished: bool) -> None:
        """Enregistre l'avancement d'un film ou d'un épisode."""
        now = time.time()
        if item.kind == "movie":
            if finished:
                self.progress.pop(item.key, None)
                self.recent.pop(item.key, None)
            elif pos >= MIN_RESUME_MS:
                self.progress[item.key] = {"pos": pos, "len": length, "t": now}
                self.recent[item.key] = {"kind": "movie", "name": item.name, "t": now}
            else:
                return
            self.dirty = True
        elif item.kind == "episode" and item.parent is not None:
            show = item.parent
            entry = self.recent.get(show.key) or {"kind": "series", "name": show.name, "watched": []}
            watched = list(entry.get("watched", []))
            if finished:
                self.progress.pop(item.key, None)
                if item.key not in watched:
                    watched.append(item.key)
            elif pos >= MIN_RESUME_MS:
                self.progress[item.key] = {"pos": pos, "len": length, "t": now}
            elif show.key not in self.recent:
                return
            label = f"S{item.season:02d}E{item.episode:02d}" if (item.season or item.episode) else item.name
            entry.update(t=now, last_ep=item.key, last_label=label, watched=watched, name=show.name)
            all_keys = {e.key for e in (show.episodes or [])}
            if all_keys:
                entry["total"] = len(all_keys)
            if all_keys and all_keys <= set(watched):
                # Toute la série a été vue : on la retire de « Vu récemment »
                self.recent.pop(show.key, None)
                for k in all_keys:
                    self.progress.pop(k, None)
            else:
                self.recent[show.key] = entry
            self.dirty = True

    def recent_keys(self, kind: str) -> list[str]:
        rows = [(v.get("t", 0), k) for k, v in self.recent.items() if v.get("kind") == kind]
        return [k for _, k in sorted(rows, reverse=True)]

    def remove_recent(self, key: str, episode_keys=()) -> None:
        self.recent.pop(key, None)
        self.progress.pop(key, None)
        for k in episode_keys:
            self.progress.pop(k, None)
        self.dirty = True
        self.save()
