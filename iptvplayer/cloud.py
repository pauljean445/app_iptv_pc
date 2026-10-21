"""Compte du foyer (Firebase) : connexion par email / mot de passe et accès à la base Firestore (API REST).

Seule la clé publique du projet est dans le code : ce qu'un compte peut lire ou écrire est fixé par les
règles de la base (chaque foyer n'accède qu'à households/<son uid>, et seulement les comptes autorisés).
La clé admin, qui passe outre ces règles, n'est jamais utilisée.
Sur ce PC, account.json garde l'email, l'uid et le jeton de renouvellement de la session, chiffré par
Windows (DPAPI : lisible seulement par cet utilisateur Windows). Le mot de passe n'est jamais enregistré.
L'appli appelle le serveur ; le serveur n'a aucun moyen de joindre le PC.
"""
import base64
import json
import re
import sys
import threading
import time

from . import __version__, config

API_KEY = "AIzaSyCJQAAhNf8j50_M3qt7jP7EKnz_4a2FVf0"  # clé publique du projet (pas un secret)
PROJECT_ID = "iptv-sync-5039f"
ACCOUNT_FILE = "account.json"
AUTH_URL = "https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword"
TOKEN_URL = "https://securetoken.googleapis.com/v1/token"
DOC_NAME = f"projects/{PROJECT_ID}/databases/(default)/documents"
DB_URL = f"https://firestore.googleapis.com/v1/{DOC_NAME}"

_MESSAGES = {
    "INVALID_LOGIN_CREDENTIALS": "email ou mot de passe incorrect",
    "INVALID_PASSWORD": "email ou mot de passe incorrect",
    "EMAIL_NOT_FOUND": "email ou mot de passe incorrect",
    "INVALID_EMAIL": "adresse email invalide",
    "MISSING_PASSWORD": "mot de passe manquant",
    "USER_DISABLED": "ce compte est désactivé",
    "TOO_MANY_ATTEMPTS_TRY_LATER": "trop de tentatives, réessaie dans quelques minutes",
    "TOKEN_EXPIRED": "la session a expiré, reconnecte-toi",
    "INVALID_REFRESH_TOKEN": "la session a expiré, reconnecte-toi",
    "USER_NOT_FOUND": "ce compte n'existe plus",
}


class CloudError(RuntimeError):
    """Échec d'un appel au serveur (réseau, serveur indisponible…) : on réessaiera plus tard."""


class AuthError(CloudError):
    """Identifiants refusés ou session terminée : il faut se reconnecter."""


class Forbidden(CloudError):
    """Le compte est connecté mais les règles de la base ne l'autorisent pas."""


# ---- Chiffrement du jeton sur le disque (DPAPI) --------------------------- #
def _dpapi(data: bytes, protect: bool) -> bytes:
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    buf = ctypes.create_string_buffer(data, len(data))
    src = Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    dst = Blob()
    crypt32 = ctypes.windll.crypt32
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    # 0x1 = CRYPTPROTECT_UI_FORBIDDEN : jamais de fenêtre de Windows
    if not fn(ctypes.byref(src), None, None, None, None, 0x1, ctypes.byref(dst)):
        raise OSError("DPAPI")
    try:
        return ctypes.string_at(dst.pbData, dst.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(dst.pbData)


def _seal(text: str) -> str:
    raw = text.encode()
    if sys.platform == "win32":
        return "dpapi:" + base64.b64encode(_dpapi(raw, True)).decode()
    return "plain:" + base64.b64encode(raw).decode()  # Linux / macOS : pas de coffre système simple


def _unseal(value: str) -> str:
    kind, _, data = value.partition(":")
    raw = base64.b64decode(data)
    return (_dpapi(raw, False) if kind == "dpapi" else raw).decode()


# ---- Valeurs Firestore ---------------------------------------------------- #
def encode(value) -> dict:
    """Valeur Python (dict, list, str, nombre, bool, None) -> valeur typée de l'API Firestore."""
    if value is None:
        return {"nullValue": None}
    if isinstance(value, bool):
        return {"booleanValue": value}
    if isinstance(value, int):
        return {"integerValue": str(value)}
    if isinstance(value, float):
        return {"doubleValue": value}
    if isinstance(value, str):
        return {"stringValue": value}
    if isinstance(value, dict):
        return {"mapValue": {"fields": {str(k): encode(v) for k, v in value.items()}}}
    if isinstance(value, (list, tuple)):
        return {"arrayValue": {"values": [encode(v) for v in value]}}
    raise TypeError(f"type non pris en charge : {type(value).__name__}")


def decode(value: dict):
    (kind, v), = value.items()
    if kind == "integerValue":
        return int(v)
    if kind == "mapValue":
        return {k: decode(x) for k, x in (v.get("fields") or {}).items()}
    if kind == "arrayValue":
        return [decode(x) for x in v.get("values") or []]
    return v  # nullValue, booleanValue, doubleValue, stringValue, timestampValue…


def field_path(*parts: str) -> str:
    """Chemin d'un champ (« progress.`x:ep:12` ») : les noms hors [A-Za-z_][A-Za-z0-9_]* entre accents graves."""
    def quote(p):
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", p):
            return p
        return "`" + p.replace("\\", "\\\\").replace("`", "\\`") + "`"
    return ".".join(quote(p) for p in parts)


# ---- Appels HTTP ---------------------------------------------------------- #
def _call(method: str, url: str, body=None, token: str | None = None, form: bool = False, timeout: int = 15):
    """Appel JSON ; retourne la réponse décodée, None pour un document absent (404)."""
    import socket
    import urllib.error
    import urllib.parse
    import urllib.request

    headers = {"User-Agent": f"IPTVPlayer/{__version__}"}
    data = None
    if body is not None:
        if form:
            data = urllib.parse.urlencode(body).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        try:
            err = json.loads(e.read()).get("error") or {}
        except ValueError:
            err = {}
        # Authentification : « message » est un code (INVALID_LOGIN_CREDENTIALS…) ; Firestore : un texte
        code = str(err.get("message", "")).split(" ")[0].split(":")[0]
        if code in _MESSAGES:
            raise AuthError(_MESSAGES[code]) from e
        if e.code == 401:
            raise AuthError("la session a expiré, reconnecte-toi") from e
        if e.code == 403:
            raise Forbidden("ce compte n'est pas autorisé sur la base de données") from e
        raise CloudError(f"le serveur a répondu « {e.code} {err.get('message') or e.reason} »") from e
    except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError) as e:
        raise CloudError(f"serveur injoignable ({getattr(e, 'reason', e)})") from e


_session = None


def session() -> "Session":
    """Session du compte du foyer (une seule pour toute l'appli)."""
    global _session
    if _session is None:
        _session = Session()
    return _session


class Session:
    """Session du compte du foyer sur ce PC. Utilisable depuis plusieurs threads."""

    def __init__(self):
        data = config.load_json(ACCOUNT_FILE)
        self.email: str = data.get("email", "")
        self.uid: str = data.get("uid", "")
        try:
            self._refresh = _unseal(data["token"]) if data.get("token") else ""
        except (OSError, ValueError, UnicodeDecodeError):
            self._refresh = ""  # jeton illisible (autre utilisateur Windows…) : il faudra se reconnecter
        self._id_token, self._expires = "", 0.0
        self._lock = threading.Lock()

    @property
    def signed_in(self) -> bool:
        return bool(self.uid and self._refresh)

    def _store(self) -> None:
        config.save_json(ACCOUNT_FILE, {"email": self.email, "uid": self.uid,
                                        "token": _seal(self._refresh) if self._refresh else ""})

    def sign_in(self, email: str, password: str) -> None:
        """Connexion (réseau, à lancer hors de l'interface). Vérifie aussi que le compte a accès à la base."""
        r = _call("POST", f"{AUTH_URL}?key={API_KEY}",
                  {"email": email, "password": password, "returnSecureToken": True})
        with self._lock:
            self.email, self.uid = r.get("email") or email, r["localId"]
            self._refresh = r["refreshToken"]
            self._id_token, self._expires = r["idToken"], time.time() + int(r.get("expiresIn", 3600))
        try:
            self.get_doc("")  # document du foyer : absent (None) au début, mais lisible si le compte est autorisé
        except Forbidden:
            self.sign_out()
            raise
        self._store()

    def sign_out(self) -> None:
        """Oublie la session (l'email reste, pour pré-remplir la prochaine connexion)."""
        with self._lock:
            self.uid = self._refresh = self._id_token = ""
            self._expires = 0.0
        self._store()

    def _token(self) -> str:
        """Jeton d'accès valide (1 h), renouvelé au besoin avec le jeton de renouvellement."""
        with self._lock:
            if not self._refresh:
                raise AuthError("ce PC n'est pas connecté au compte du foyer")
            if self._id_token and time.time() < self._expires - 120:
                return self._id_token
            refresh = self._refresh
        try:
            r = _call("POST", f"{TOKEN_URL}?key={API_KEY}",
                      {"grant_type": "refresh_token", "refresh_token": refresh}, form=True)
        except AuthError:
            self.sign_out()  # mot de passe changé, compte désactivé ou supprimé
            raise
        with self._lock:
            self._id_token, self._expires = r["id_token"], time.time() + int(r.get("expires_in", 3600))
            changed = r["refresh_token"] != self._refresh
            self._refresh = r["refresh_token"]
        if changed:
            self._store()
        return self._id_token

    # ---- Documents du foyer (chemins relatifs à households/<uid>) --------- #
    def _doc_url(self, path: str) -> str:
        return f"{DB_URL}/households/{self.uid}" + (f"/{path}" if path else "")

    def get_doc(self, path: str, timeout: int = 15) -> dict | None:
        """Champs du document (décodés), None s'il n'existe pas."""
        r = _call("GET", self._doc_url(path), token=self._token(), timeout=timeout)
        return None if r is None else {k: decode(v) for k, v in (r.get("fields") or {}).items()}

    def commit(self, writes: list, timeout: int = 15) -> None:
        """Écritures groupées, appliquées ensemble ou pas du tout. Chaque écriture : (chemin, champs, à effacer).
        champs = {chemin de champ (field_path) : valeur} : seuls ces champs sont écrits et ceux de « à effacer »
        supprimés ; le reste du document ne change pas (on n'écrase pas ce qu'un autre appareil vient d'écrire).
        champs = None : le document est supprimé."""
        body = []
        for path, fields, delete in writes:
            name = f"{DOC_NAME}/households/{self.uid}" + (f"/{path}" if path else "")
            if fields is None:
                body.append({"delete": name})
                continue
            nested: dict = {}
            for fp, value in fields.items():
                node = nested
                parts = _split_path(fp)
                for part in parts[:-1]:
                    node = node.setdefault(part, {})
                node[parts[-1]] = value
            body.append({"update": {"name": name, "fields": {k: encode(v) for k, v in nested.items()}},
                         "updateMask": {"fieldPaths": [*fields, *delete]}})
        if body:
            _call("POST", f"{DB_URL}:commit", {"writes": body}, token=self._token(), timeout=timeout)


def _split_path(path: str) -> list[str]:
    """Inverse de field_path."""
    parts, cur, i, quoted = [], "", 0, False
    while i < len(path):
        ch = path[i]
        if quoted and ch == "\\":
            cur += path[i + 1]
            i += 2
            continue
        if ch == "`":
            quoted = not quoted
        elif ch == "." and not quoted:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
        i += 1
    parts.append(cur)
    return parts
