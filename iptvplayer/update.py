"""Mise à jour depuis l'appli : dernière version publiée sur GitHub (page « Releases » du dépôt).

Publier une version : augmenter __version__ (iptvplayer/__init__.py), lancer build_installer.bat, puis
créer sur GitHub une release avec le tag « v<version> » (ex. v1.2.0) et y joindre l'installeur
dist\\IPTVPlayer-Setup-<version>.exe. Le texte de la release est montré dans l'appli.
L'appli télécharge l'installeur, le lance en mode silencieux et se ferme ; l'installeur remplace
l'application puis la relance. Les réglages (%APPDATA%) ne sont pas touchés.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from . import __version__

REPO = "pauljean445/app_iptv_pc"  # dépôt GitHub public qui héberge les releases
API = f"https://api.github.com/repos/{REPO}/releases/latest"
USER_AGENT = f"IPTVPlayer/{__version__}"


class Cancelled(Exception):
    pass


def supported() -> bool:
    """Seulement pour l'application installée (pas depuis les sources)."""
    return sys.platform == "win32" and getattr(sys, "frozen", False)


def _version(text: str) -> tuple:
    return tuple(int(n) for n in re.findall(r"\d+", text)[:3])


def _open(url: str, timeout: int):
    # Import différé, comme pour le catalogue : urllib/ssl ne servent qu'au réseau.
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"})
    return urllib.request.urlopen(req, timeout=timeout)


def check(timeout: int = 10) -> dict | None:
    """{"version", "notes", "url", "name", "size"} si une version plus récente est publiée, sinon None."""
    import urllib.error
    try:
        with _open(API, timeout) as resp:
            rel = json.load(resp)
    except urllib.error.HTTPError as e:
        if e.code == 404:  # dépôt privé ou aucune release publiée
            raise RuntimeError("aucune version publiée n'est accessible") from e
        raise RuntimeError(f"GitHub a répondu « {e.code} {e.reason} »") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"impossible de joindre GitHub : {e.reason}") from e
    version = (rel.get("tag_name") or "").lstrip("vV")
    if not version or _version(version) <= _version(__version__):
        return None
    asset = next((a for a in rel.get("assets", []) if a.get("name", "").lower().endswith(".exe")), None)
    if asset is None:
        return None
    return {"version": version, "notes": (rel.get("body") or "").strip(), "url": asset["browser_download_url"],
            "name": Path(asset["name"]).name, "size": int(asset.get("size") or 0)}


def download(info: dict, progress=None, cancelled=None) -> str:
    """Télécharge l'installeur dans le dossier temporaire et retourne son chemin.
    progress(reçu, total) et cancelled() sont appelés depuis le thread du téléchargement."""
    dest = Path(tempfile.gettempdir()) / info["name"]
    part = dest.with_name(dest.name + ".part")
    done = 0
    with _open(info["url"], 30) as resp, open(part, "wb") as f:
        total = int(resp.headers.get("Content-Length") or info["size"] or 0)
        while chunk := resp.read(256 * 1024):
            if cancelled is not None and cancelled():
                break
            f.write(chunk)
            done += len(chunk)
            if progress is not None:
                progress(done, total)
    if cancelled is not None and cancelled():
        part.unlink(missing_ok=True)
        raise Cancelled()
    if total and done != total:
        part.unlink(missing_ok=True)
        raise RuntimeError("téléchargement incomplet")
    os.replace(part, dest)
    return str(dest)


def install(path: str) -> None:
    """Lance l'installeur sans questions (fenêtre de progression seule) ; l'appli doit se fermer
    aussitôt. « /relaunch=1 » : l'installeur relance l'appli à la fin (voir installer/IPTVPlayer.iss)."""
    subprocess.Popen([path, "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS", "/relaunch=1"],
                     close_fds=True)
