"""Téléchargement de films et d'épisodes sur le disque (dossier choisi : Téléchargements, disque externe…).

Une file d'attente traitée un fichier à la fois : chaque téléchargement occupe une connexion de l'abonnement IPTV,
souvent limité à une ou deux. Le fichier est écrit en « nom.ext.part » puis renommé une fois complet ; un
téléchargement interrompu (coupure, appli fermée) reprend là où il s'était arrêté (requête HTTP « Range »).
Le gestionnaire est commun à toute l'appli : il continue pendant un changement de profil.
"""
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from .sources.playlist import USER_AGENT

CHUNK = 512 * 1024
RETRIES = 4  # nouvelles tentatives après une coupure (le fichier reprend où il en était)
UNAVAILABLE = "le fournisseur n'envoie pas ce fichier (indisponible chez lui pour le moment)"

_BAD = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_name(text: str) -> str:
    """Nom de fichier / dossier valable sous Windows."""
    name = _BAD.sub(" ", text).strip().rstrip(". ")
    return re.sub(r"\s{2,}", " ", name)[:150] or "sans titre"


@dataclass(eq=False)
class Job:
    title: str            # libellé affiché (« Film (2024) », « Série · S01E02 »)
    url: str
    dest: Path            # fichier final
    state: str = "waiting"  # waiting | running | done | error | cancelled
    done: int = 0         # octets reçus (fichier .part compris)
    total: int = 0        # taille totale (0 si inconnue)
    error: str = ""
    speed: float = 0.0    # octets / s
    started: float = field(default_factory=time.time)

    @property
    def progress(self) -> float:
        return self.done / self.total if self.total else 0.0


class DownloadManager(QObject):
    """File de téléchargements. changed est émis (depuis le thread de téléchargement : connexion en file Qt)
    à chaque changement d'état, et au plus deux fois par seconde pendant un téléchargement."""

    changed = Signal()

    def __init__(self):
        super().__init__()
        self.jobs: list[Job] = []
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._cancel: set[Job] = set()
        self._thread = threading.Thread(target=self._run, daemon=True, name="downloads")
        self._thread.start()

    # ---- File d'attente ---------------------------------------------------- #
    def add(self, entries: list[tuple[str, str, Path]]) -> int:
        """entries : (libellé, url, fichier final). Ignore les fichiers déjà téléchargés ou déjà en file.
        Retourne le nombre de téléchargements ajoutés."""
        added = 0
        with self._lock:
            queued = {j.dest for j in self.jobs if j.state in ("waiting", "running")}
            for title, url, dest in entries:
                if dest in queued or dest.exists():
                    continue
                self.jobs.append(Job(title, url, dest))
                added += 1
        if added:
            self._wake.set()
            self.changed.emit()
        return added

    def cancel(self, job: Job) -> None:
        with self._lock:
            if job.state == "waiting":
                job.state = "cancelled"
            elif job.state == "running":
                self._cancel.add(job)
        self.changed.emit()

    def cancel_all(self) -> None:
        for job in list(self.jobs):
            if job.state in ("waiting", "running"):
                self.cancel(job)

    def retry(self, job: Job) -> None:
        with self._lock:
            if job.state in ("error", "cancelled"):
                job.state, job.error = "waiting", ""
        self._wake.set()
        self.changed.emit()

    def clear_finished(self) -> None:
        with self._lock:
            self.jobs = [j for j in self.jobs if j.state in ("waiting", "running")]
        self.changed.emit()

    @property
    def active(self) -> list[Job]:
        return [j for j in self.jobs if j.state in ("waiting", "running")]

    def summary(self) -> str:
        """« 2 en file · 45 % » pour le bouton du bandeau ; vide s'il n'y a rien en cours."""
        active = self.active
        if not active:
            return ""
        running = next((j for j in active if j.state == "running"), None)
        pct = f" · {int(running.progress * 100)} %" if running and running.total else ""
        return f"{len(active)}{pct}"

    # ---- Thread de téléchargement ------------------------------------------ #
    def _next(self) -> Job | None:
        with self._lock:
            job = next((j for j in self.jobs if j.state == "waiting"), None)
            if job is not None:
                job.state = "running"
            return job

    def _run(self):
        while True:
            job = self._next()
            if job is None:
                self._wake.wait()
                self._wake.clear()
                continue
            self.changed.emit()
            for attempt in range(RETRIES + 1):
                try:
                    self._download(job)
                    job.state = "done"
                    break
                except _Cancelled:
                    job.state = "cancelled"
                    job.dest.with_name(job.dest.name + ".part").unlink(missing_ok=True)  # pas de déchet
                    break
                except _Transient as e:
                    job.error = str(e)
                    if attempt == RETRIES:
                        job.state = "error"
                    else:
                        time.sleep(3 * (attempt + 1))  # puis reprise à la position atteinte
                except Exception as e:  # erreur définitive (fichier introuvable, disque plein…)
                    job.error = str(e) or e.__class__.__name__
                    job.state = "error"
                    break
            with self._lock:
                self._cancel.discard(job)
            self.changed.emit()

    def _download(self, job: Job):
        import socket
        import urllib.error
        import urllib.request

        job.dest.parent.mkdir(parents=True, exist_ok=True)
        part = job.dest.with_name(job.dest.name + ".part")
        have = part.stat().st_size if part.exists() else 0
        headers = {"User-Agent": USER_AGENT}
        if have:
            headers["Range"] = f"bytes={have}-"
        req = urllib.request.Request(job.url, headers=headers)
        try:
            resp = urllib.request.urlopen(req, timeout=30)
        except urllib.error.HTTPError as e:
            if e.code == 416 and have:  # déjà complet
                part.replace(job.dest)
                job.done = job.total = have
                return
            if e.code >= 500 or e.code in (403, 429):  # serveur saturé, connexions simultanées dépassées
                raise _Transient(f"le serveur a répondu « {e.code} »") from e
            raise RuntimeError(f"le serveur a répondu « {e.code} »") from e
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError) as e:
            raise _Transient(f"serveur injoignable ({getattr(e, 'reason', e)})") from e
        with resp:
            # Film indisponible chez le fournisseur : il répond « 200 » avec une page vide au lieu de la vidéo
            if resp.headers.get("Content-Type", "").lower().startswith("text/"):
                raise RuntimeError(UNAVAILABLE)
            length = int(resp.headers.get("Content-Length") or 0)
            if resp.status == 206 and have:
                mode = "ab"
            else:  # le serveur ne sait pas reprendre : on recommence au début
                mode, have = "wb", 0
            job.total = have + length if length else 0
            job.done = have
            last_emit, last_done, last_t = 0.0, have, time.time()
            try:
                with open(part, mode) as f:
                    while True:
                        if job in self._cancel:
                            raise _Cancelled()
                        chunk = resp.read(CHUNK)
                        if not chunk:
                            break
                        f.write(chunk)
                        job.done += len(chunk)
                        now = time.time()
                        if now - last_emit > 0.5:
                            job.speed = (job.done - last_done) / max(now - last_t, 0.001)
                            last_done, last_t, last_emit = job.done, now, now
                            self.changed.emit()
            except (socket.timeout, TimeoutError, ConnectionError, OSError) as e:
                if isinstance(e, OSError) and getattr(e, "errno", None) == 28:
                    raise RuntimeError("disque plein") from e
                raise _Transient(f"coupure ({e})") from e
        if job.done == 0:
            part.unlink(missing_ok=True)
            raise RuntimeError(UNAVAILABLE)
        if job.total and job.done < job.total:
            raise _Transient("téléchargement incomplet")
        part.replace(job.dest)


class _Transient(Exception):
    pass


class _Cancelled(Exception):
    pass


_manager: DownloadManager | None = None


def manager() -> DownloadManager:
    global _manager
    if _manager is None:
        _manager = DownloadManager()
    return _manager
