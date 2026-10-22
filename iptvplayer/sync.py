"""Synchronisation avec le compte du foyer (Firestore) : liste des profils et données de chaque profil.

households/<uid>                  profiles : {pid: {name, color, t}} ; deleted : {profiles: {pid: t}}
households/<uid>/profiles/<pid>   fav, progress, recent, watched, prefs (comme library.json) ; deleted

Pour chaque entrée, la version la plus récente (« t ») gagne, que ce soit une valeur ou une trace de
suppression. Une synchro : lire le document, appliquer ici ce que le serveur a de plus récent, puis envoyer
seulement ce que ce PC a de plus récent, champ par champ. Serveur injoignable : l'appli continue avec ses
données, et ce qui est plus récent ici est renvoyé au passage suivant (rien n'est perdu).
La source IPTV du profil voyage chiffrée (champ secret.source = {"v": bloc vault.py, "t"}, voir source_writes) ;
les autres réglages de profile.json restent propres à chaque appareil.
"""
import shutil
import time

from . import cloud, config, library, vault
from .sources import playlist

PURGE_SECONDS = library.PURGE_DAYS * 86400


def merge(names, tables: dict, deleted: dict, remote: dict | None) -> tuple[bool, dict, list]:
    """Fusionne remote (document du serveur, décodé) dans tables / deleted (données d'ici, modifiées sur place).
    Retourne (données d'ici modifiées, champs à écrire sur le serveur, champs à y effacer)."""
    remote = remote or {}
    rdeleted = remote.get("deleted") or {}
    limit = time.time() - PURGE_SECONDS
    changed, fields, drop = False, {}, []
    for name in names:
        live, dead = tables[name], deleted[name]
        rlive, rdead = remote.get(name) or {}, rdeleted.get(name) or {}
        for key in set(live) | set(dead) | set(rlive) | set(rdead):
            if key in dead and dead[key] < limit:
                del dead[key]  # trace de plus de 3 mois (déjà purgée au chargement si l'appli a redémarré)
            rgone = key not in rlive and key in rdead  # trace de suppression sur le serveur
            if key in rlive:
                rt = rlive[key].get("t", 0)
            elif rgone and rdead[key] >= limit:
                rt = rdead[key]
            else:
                rt = None
                if rgone:  # trace de plus de 3 mois : effacée aussi sur le serveur
                    drop.append(cloud.field_path("deleted", name, key))
                    rgone = False
            lt = live[key].get("t", 0) if key in live else dead.get(key)
            if rt is not None and (lt is None or rt > lt):
                if key in rlive:
                    live[key] = rlive[key]
                    dead.pop(key, None)
                else:
                    live.pop(key, None)
                    dead[key] = rt
                changed = True
            elif lt is not None and (rt is None or lt > rt):
                if key in live:
                    fields[cloud.field_path(name, key)] = live[key]
                    if rgone:
                        drop.append(cloud.field_path("deleted", name, key))
                else:
                    fields[cloud.field_path("deleted", name, key)] = dead[key]
                    if key in rlive:
                        drop.append(cloud.field_path(name, key))
    return changed, fields, drop


# ---- Données d'un profil -------------------------------------------------- #
def library_writes(lib: library.Library, remote: dict | None, pid: str) -> tuple[bool, list]:
    """Fusionne le document du profil dans lib (enregistrée si elle change). Retourne (changée, écritures)."""
    changed, fields, drop = merge(library.TABLES, lib.tables, lib.deleted, remote)
    if changed:
        lib.dirty = True
        lib.save()
    return changed, ([(f"profiles/{pid}", fields, drop)] if fields or drop else [])


def sync_library_now(session: cloud.Session, lib: library.Library, pid: str, timeout: int = 8) -> bool:
    """Synchro complète d'un profil, sans attendre le passage suivant (fermeture, changement de profil)."""
    return sync_profile_now(session, lib, pid, None, timeout)[0]


def sync_profile_now(session: cloud.Session, lib: library.Library, pid: str, own: dict | None,
                     timeout: int = 8) -> tuple[bool, bool, bool]:
    """Comme sync_library_now, avec la source IPTV du profil si own (ses réglages) est donné.
    Retourne (données changées, source adoptée, own modifié : à enregistrer)."""
    remote = session.get_doc(f"profiles/{pid}", timeout)
    changed, writes = library_writes(lib, remote, pid)
    adopted = modified = False
    if own is not None:
        adopted, modified, fields = source_writes(pid, own, remote, session.vault_key)
        writes = with_fields(writes, pid, fields)
    session.commit(writes, timeout)
    return changed, adopted, modified


# ---- Source IPTV du profil (chiffrée) ------------------------------------- #
def source_writes(pid: str, own: dict, remote: dict | None, key: bytes | None) -> tuple[bool, bool, dict]:
    """Source IPTV du profil (même règle que Sync.sourceWrites côté TV). Le compte sert à configurer les appareils
    qui n'en ont pas : un profil SANS abonnement ici prend celui du compte (déchiffré dans own). Un profil qui en a
    un le garde toujours (chaque appareil peut avoir le sien, ex. un lien « TV » différent de celui du PC) ; il
    l'envoie au compte s'il n'y en a pas, s'il y est indéchiffrable (mot de passe changé) ou après un changement
    fait ici (source_t plus récent). Rien si l'utilisateur ne veut pas d'identifiants enregistrés (remember) ou
    pour un fichier M3U local. own (réglages du profil) est modifié sur place.
    Retourne (source adoptée, own modifié, champs à écrire)."""
    if key is None or own.get("remember") is False:
        return False, False, {}
    lt = float(own.get("source_t") or 0)
    r = ((remote or {}).get("secret") or {}).get("source")
    r = r if isinstance(r, dict) else None
    rt = float(r.get("t") or 0) if r else 0.0
    data = vault.decrypt(key, pid, str(r.get("v", ""))) if r else None
    if playlist.source_from_config(own) is None:
        if data is None:
            return False, False, {}
        for k in vault.KEYS:
            own[k] = data.get(k) or ""
        own["remember"] = True
        own["source_t"] = rt
        return True, True, {}
    if own.get("mode") == "file":
        return False, False, {}  # fichier de ce PC : sans objet ailleurs
    if r is None or data is None or lt > rt:
        t = lt if (r is None or lt > rt) else time.time()
        modified = t != lt
        own["source_t"] = t
        blob = vault.encrypt(key, pid, {k: own.get(k) or "" for k in vault.KEYS})
        return False, modified, {cloud.field_path("secret", "source"): {"v": blob, "t": t}}
    return False, False, {}


def with_fields(writes: list, pid: str, fields: dict) -> list:
    """Ajoute des champs à l'écriture du document du profil (ou en crée une)."""
    if not fields:
        return writes
    path = f"profiles/{pid}"
    for i, (p, f, d) in enumerate(writes):
        if p == path and f is not None:
            return writes[:i] + [(p, {**f, **fields}, d)] + writes[i + 1:]
    return writes + [(path, fields, ())]


# ---- Liste des profils ---------------------------------------------------- #
def profiles_writes(cfg: dict, remote: dict | None, uid: str) -> tuple[bool, list, list, list]:
    """Fusionne la liste des profils du foyer dans cfg (réglages chargés par config.load).
    Retourne (liste modifiée, écritures, profils retirés de ce PC, profils ajoutés à ce PC)."""
    old = {p["id"]: p for p in cfg["profiles"]}
    live = {pid: {"name": p["name"], "color": p["color"], "t": p.get("t", 0)} for pid, p in old.items()}
    dead = dict(cfg.get("profiles_deleted") or {})
    synced = cfg.get("sync_uid")  # compte avec lequel ce PC s'est déjà synchronisé
    if synced != uid and (synced or (remote or {}).get("profiles")):
        # Ce PC rejoint un foyer : il prend ses profils, ceux d'ici sont laissés de côté (sans trace de
        # suppression). Ce sont ceux d'un autre compte (changement de compte : ils sont sur son serveur et ne
        # doivent pas passer dans ce foyer), ou ceux d'un PC jamais synchronisé alors que le foyer a déjà les siens.
        # Seul un PC jamais synchronisé, face à un foyer vide, envoie ses profils (premier envoi des données).
        live, dead = {}, {}
    changed, fields, drop = merge(("profiles",), {"profiles": live}, {"profiles": dead}, remote)
    added = sorted((pid for pid in live if pid not in old), key=lambda pid: live[pid]["t"])
    removed = [pid for pid in old if pid not in live]
    cfg["profiles"] = ([dict(old[pid], **live[pid]) for pid in old if pid in live]
                       + [dict(live[pid], id=pid) for pid in added])
    cfg["profiles_deleted"] = dead
    cfg["sync_uid"] = uid
    writes = [("", fields, drop)] if fields or drop else []
    # Profil supprimé ici : ses données sont effacées du serveur avec lui
    writes += [(f"profiles/{pid}", None, ()) for pid in dead
               if cloud.field_path("deleted", "profiles", pid) in fields]
    return changed or bool(removed or added), writes, removed, added


def apply_profiles(cfg: dict, removed: list, added: list, source_pid: str | None) -> None:
    """Dossiers des profils arrivés d'un autre appareil, avec la source IPTV de source_pid (un foyer = un
    abonnement) ; suppression de ceux des profils retirés. Il reste toujours au moins un profil."""
    source = dict(config.read_profile(source_pid), profile=source_pid) if source_pid else None
    for pid in added:
        config.init_profile_folder(pid, source)
    if not cfg["profiles"]:
        config.create_profile(cfg, "Principal", config.PROFILE_COLORS[0], source)
    for pid in removed:
        shutil.rmtree(config.profile_dir(pid), ignore_errors=True)


def startup(session: cloud.Session) -> None:
    """Au lancement, avant « Qui regarde ? » : met à jour la liste des profils du foyer. Serveur injoignable :
    on continue avec ceux de ce PC. Lève AuthError si la session n'est plus valable (à reconnecter)."""
    cfg = config.load()
    current = config.current_profile()
    fresh = not cfg.get("sync_uid")  # jamais synchronisé (données d'avant la synchro)
    try:
        remote = session.get_doc("", timeout=8)
        _, writes, removed, added = profiles_writes(cfg, remote, session.uid)
        apply_profiles(cfg, removed, added, current)
        ids = [p["id"] for p in cfg["profiles"]]
        config.set_profile(current if current in ids else ids[0])
        config.save_common(cfg, config.current_profile())
        session.commit(writes, timeout=8)
        if fresh and not added:
            # Premier passage de ce compte sur ce PC, foyer encore vide : on envoie aussi les données des profils
            for pid in ids:
                own = config.read_profile(pid)
                if sync_profile_now(session, library.Library(config.profile_dir(pid)), pid, own)[2]:
                    config.write_profile(pid, own)
        # Profils sans abonnement sur ce PC (nouvel appareil, profil créé ailleurs) : celui du compte, déchiffré
        for pid in ids:
            own = config.read_profile(pid)
            if session.vault_key and playlist.source_from_config(own) is None:
                if source_writes(pid, own, session.get_doc(f"profiles/{pid}", timeout=8), session.vault_key)[1]:
                    config.write_profile(pid, own)
    except cloud.Forbidden:
        session.sign_out()  # compte retiré des comptes autorisés
        raise cloud.AuthError("l'accès de ce compte a été retiré")
    except cloud.AuthError:
        raise
    except cloud.CloudError:
        pass
