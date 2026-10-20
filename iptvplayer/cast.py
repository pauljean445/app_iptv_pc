"""Diffusion vers les appareils Google Cast (Chromecast, Google TV, téléviseurs « Chromecast intégré »).

Découverte : requête mDNS « _googlecast._tcp » avec réponse directe (bit QU). Contrairement à la
découverte de VLC, elle fonctionne même quand le réseau Windows est en profil « Public ».
Diffusion : module Chromecast de VLC, qui convertit à la volée ce que la télé ne sait pas lire.
"""
import socket
import struct
import time
from dataclasses import dataclass

MDNS = ("224.0.0.251", 5353)
SERVICE = "_googlecast._tcp.local"


@dataclass(frozen=True)
class CastDevice:
    name: str
    ip: str
    port: int = 8009
    model: str = ""


def _query(name: str) -> bytes:
    qname = b"".join(bytes([len(p)]) + p.encode() for p in name.split(".")) + b"\x00"
    # 1 question, type PTR (12), classe IN avec le bit « réponse directe » (0x8001)
    return struct.pack(">HHHHHH", 0, 0, 1, 0, 0, 0) + qname + struct.pack(">HH", 12, 0x8001)


def _read_name(data: bytes, pos: int) -> tuple[str, int]:
    """Nom DNS (avec pointeurs de compression). Retourne (nom, position après le nom)."""
    labels, jumped, end = [], False, pos
    for _ in range(64):
        n = data[pos]
        if n == 0:
            pos += 1
            break
        if n & 0xC0 == 0xC0:
            if not jumped:
                end = pos + 2
            pos = ((n & 0x3F) << 8) | data[pos + 1]
            jumped = True
            continue
        labels.append(data[pos + 1:pos + 1 + n].decode("utf-8", "replace"))
        pos += 1 + n
    return ".".join(labels), (end if jumped else pos)


def _parse(data: bytes, src_ip: str) -> CastDevice | None:
    try:
        _, flags, qd, an, ns, ar = struct.unpack(">HHHHHH", data[:12])
        pos = 12
        for _ in range(qd):
            _, pos = _read_name(data, pos)
            pos += 4
        txt, port, ip, is_cast = {}, 8009, "", False
        for _ in range(an + ns + ar):
            name, pos = _read_name(data, pos)
            rtype, _, _, rdlen = struct.unpack(">HHIH", data[pos:pos + 10])
            pos += 10
            rdata = data[pos:pos + rdlen]
            if rtype == 12 and SERVICE in name:  # PTR vers une instance Google Cast
                is_cast = True
            elif rtype == 16:  # TXT : fn=nom, md=modèle
                i = 0
                while i < len(rdata):
                    ln = rdata[i]
                    k, _, v = rdata[i + 1:i + 1 + ln].decode("utf-8", "replace").partition("=")
                    txt[k] = v
                    i += 1 + ln
            elif rtype == 33 and len(rdata) >= 6:  # SRV : port
                port = struct.unpack(">H", rdata[4:6])[0]
            elif rtype == 1 and rdlen == 4:  # A : adresse IPv4
                ip = socket.inet_ntoa(rdata)
            pos += rdlen
        if not is_cast and "fn" not in txt:
            return None
        return CastDevice(txt.get("fn") or "Appareil Google Cast", ip or src_ip, port, txt.get("md", ""))
    except (struct.error, IndexError, OSError):
        return None


def discover(timeout: float = 3.0) -> list[CastDevice]:
    """Appareils Google Cast du réseau local (triés par nom)."""
    found: dict[str, CastDevice] = {}
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    try:
        s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        s.bind(("", 0))
        s.settimeout(0.3)
        q = _query(SERVICE)
        end = time.time() + timeout
        next_send = 0.0
        while time.time() < end:
            if time.time() >= next_send:  # on répète la question : un appareil en veille répond parfois tard
                s.sendto(q, MDNS)
                next_send = time.time() + 1.0
            try:
                data, addr = s.recvfrom(9000)
            except socket.timeout:
                continue
            dev = _parse(data, addr[0])
            if dev is not None:
                found[dev.ip] = dev
    finally:
        s.close()
    return sorted(found.values(), key=lambda d: d.name.lower())


# Son converti en AAC stéréo : beaucoup de chaînes diffusent en MPEG Layer 2 (« MP2 ») ou en E-AC3,
# que les Chromecast ne lisent pas. VLC confond le MP2 avec du MP3 (même code « mpga ») et ne le
# convertit pas de lui-même : la télé reste muette ou refuse le flux. Coût : ~10 % d'un cœur.
AUDIO_AAC = "acodec=mp4a,ab=192,channels=2,samplerate=48000"
# Image convertie en H.264 720p (format lu par tous les Chromecast). Mesuré sur ce PC : 2,5 fois plus
# rapide que la lecture grâce aux threads, donc sans saccade. Utilisé seulement si nécessaire.
# « zerolatency » : les images sortent dès qu'elles sont codées (sans attente de 10 images) ; mesuré
# avec un faux récepteur : démarrage, changement de langue et épisode suivant 1 à 2,5 s plus rapides.
VIDEO_H264_720 = ("vcodec=h264,venc=x264{preset=veryfast,tune=zerolatency,profile=high,level=4.1,threads=0},"
                  "vb=3500,height=720,threads=4")


# Module « sans direct » : VLC annonce tout flux envoyé à la télé comme du direct ("streamType":"LIVE",
# écrit en dur dans le module Chromecast). La télé affiche alors « Différé : 1 s » à chaque pause d'un
# film. On en fait une copie privée où ce type est remplacé par "NONE" (même longueur), sous un autre
# nom de module, chargée en plus de l'original : films, séries et replays passent par elle, le direct
# garde le module d'origine. Si la copie n'est pas possible, tout passe par le module d'origine.
VOD_MODULE = "chromecvod"
_VOD_PATCHES = (
    (b',"streamType":"LIVE"\x00', b',"streamType":"NONE"\x00', 1),
    (b"\x00stream_out_chromecast\x00", b"\x00stream_out_chromecvod\x00", 2),  # nom du module
    (b"\x00chromecast\x00", b"\x00" + VOD_MODULE.encode() + b"\x00", 1),        # nom dans « #chromecast{…} »
    # Sous-modules internes, renommés aussi : sinon VLC prend ceux de l'original, qui envoient à la
    # télé un 2e chargement marqué « direct » (double démarrage, « Différé » de retour).
    (b"\x00chromecast-proxy\x00", b"\x00chromecvod-proxy\x00", 1),
    (b"\x00chromecast-proxy:\x00", b"\x00chromecvod-proxy:\x00", 1),
    (b"\x00chromecast-http\x00", b"\x00chromecvod-http\x00", 1),
    (b"access=chromecast-http}", b"access=chromecvod-http}", 1),
)
_PATCH_VERSION = 2  # à augmenter quand _VOD_PATCHES change : la copie est alors refaite
vod_ready = False


def prepare_vod_module(vlc_dir, cache_dir) -> bool:
    """Crée (si besoin) la copie du module et la déclare à VLC. À appeler avant de créer l'instance VLC."""
    global vod_ready
    import ctypes
    import os
    from pathlib import Path
    src = Path(vlc_dir) / "plugins" / "stream_out" / "libstream_out_chromecast_plugin.dll"
    out_dir = Path(cache_dir) / "vlc_plugins"
    dst = out_dir / "libstream_out_chromecvod_plugin.dll"
    stamp = out_dir / "source.txt"
    try:
        st = src.stat()
        sig = f"{src}|{st.st_size}|{int(st.st_mtime)}|v{_PATCH_VERSION}"
        if not dst.exists() or not stamp.exists() or stamp.read_text(encoding="utf-8") != sig:
            data = src.read_bytes()
            for old, new, count in _VOD_PATCHES:
                if data.count(old) != count:  # version de VLC inconnue : on ne touche à rien
                    return False
                data = data.replace(old, new)
            out_dir.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(data)
            stamp.write_text(sig, encoding="utf-8")
    except OSError:
        return False
    # Dossier de modules supplémentaire, lu par VLC au démarrage. VLC lit l'environnement de sa propre
    # bibliothèque C : on le déclare aussi pour celle-ci (msvcrt), pas seulement pour Python.
    paths = os.pathsep.join(p for p in (os.environ.get("VLC_PLUGIN_PATH", ""), str(out_dir)) if p)
    entry = f"VLC_PLUGIN_PATH={paths}"
    os.environ["VLC_PLUGIN_PATH"] = paths
    for crt in ("msvcrt", "ucrtbase"):
        try:
            getattr(ctypes.cdll, crt)._putenv(entry.encode("mbcs"))
        except (OSError, AttributeError):
            pass
    vod_ready = True
    return True


def media_options(dev: CastDevice, convert_audio: bool = False, burn_subtitles: bool = False,
                  convert_video: bool = False, live: bool = True) -> list[str]:
    """Options à ajouter au média VLC pour l'envoyer vers l'appareil.

    convert_audio  : son en AAC (direct et replays : son souvent incompatible).
    burn_subtitles : sous-titres choisis incrustés dans l'image (un Chromecast ne les affiche pas seul).
    convert_video  : « mode compatible », image convertie et désentrelacée (chaînes qui ne passent pas).
    live           : direct ; sinon (films, séries, replays) la télé n'affiche pas « Différé » en pause.
    """
    module = "chromecast" if live or not vod_ready else VOD_MODULE
    chain = f"{module}{{ip={dev.ip},port={dev.port}}}"
    if burn_subtitles or convert_video:
        video = VIDEO_H264_720 + (",deinterlace" if convert_video else "") + (",soverlay" if burn_subtitles else "")
        chain = f"transcode{{{video},{AUDIO_AAC}}}:{chain}"
    elif convert_audio:
        chain = f"transcode{{{AUDIO_AAC}}}:{chain}"
    # no-sout-all : seules les pistes choisies (langue, sous-titres) partent vers la télé. Sans cela VLC
    # les envoie toutes et le Chromecast lit la première : le choix de langue était ignoré.
    opts = [f":sout=#{chain}", ":no-sout-all", ":demux-filter=demux_chromecast", ":sout-keep"]
    if not burn_subtitles:
        # Aucune piste de sous-titres vers la télé : certaines chaînes en ajoutent par moments (télétexte,
        # sous-titres sourds et malentendants) et l'envoi s'interrompait (« errors with codec subt »).
        opts.append(":no-sout-spu")
    return opts
