"""Quelle caméra physique pour quelle position de l'habitacle ?

Sur un PC portable, l'index 0 est presque toujours la webcam intégrée, et les index des
caméras USB changent selon l'ordre de branchement. Ce module associe chaque position de
config.json à un périphérique réel, par NOM plutôt que par numéro, et écarte la webcam du PC.

Chaque caméra de config.json accepte, au choix :
    "index": 2              un numéro fixe (comme avant)
    "index": "auto"         la prochaine caméra libre qui n'est pas la webcam du PC
    "nom":   "USB Camera"   la prochaine caméra libre dont le nom contient ce texte
    "url":   "rtsp://…"     une caméra IP (flux RTSP / HTTP)
`index` + `nom` ensemble : l'index est utilisé, le nom sert de vérification (s'il ne
correspond plus, c'est que les index ont bougé → relancer lister_cameras.py).
"""
from __future__ import annotations

import glob
import os
from pathlib import Path

# Morceaux de nom typiques d'une webcam intégrée de PC portable (comparaison sans casse).
EXCLURE_DEFAUT = ["integrated", "intégrée", "built-in", "facetime", "webcam", "ir camera",
                  "windows hello", "virtual", "obs ", "droidcam", "camo"]
# Morceaux de nom typiques d'une caméra thermique (PureThermal / Lepton, Topdon, InfiRay…).
THERMIQUE_DEFAUT = ["purethermal", "lepton", "thermal", "flir", "topdon", "tc001", "infiray", "seek"]


def lister() -> list[dict] | None:
    """[{index, nom}] des caméras vues par le système, dans l'ordre des index OpenCV.
    None si le système ne donne pas les noms (le banc retombe alors sur les index)."""
    if os.name == "nt":
        try:  # DirectShow : même ordre que cv2.VideoCapture(i, cv2.CAP_DSHOW)
            from pygrabber.dshow_graph import FilterGraph
            return [{"index": i, "nom": n} for i, n in enumerate(FilterGraph().get_input_devices())]
        except Exception:  # noqa: BLE001 — pygrabber absent ou COM indisponible
            return None
    noeuds = sorted(glob.glob("/sys/class/video4linux/video*"),
                    key=lambda p: int(p.rsplit("video", 1)[1]))
    if not noeuds:
        return None
    out = []
    for p in noeuds:
        try:  # chaque caméra crée 2 nœuds sous Linux : seul l'index 0 porte l'image
            if Path(p, "index").read_text().strip() != "0":
                continue
            nom = Path(p, "name").read_text().strip()
        except OSError:
            continue
        out.append({"index": int(p.rsplit("video", 1)[1]), "nom": nom})
    return out


def lister_msmf() -> list[dict] | None:
    """[{index, nom}] des caméras dans l'ordre des index OpenCV du backend Media Foundation
    (cv2.CAP_MSMF), qui N'EST PAS celui de DirectShow. None hors Windows ou en cas d'échec.
    Utile pour la thermique : seul MSMF donne son flux brut (les températures)."""
    if os.name != "nt":
        return None
    try:
        return _enumerer_msmf()
    except Exception:  # noqa: BLE001 — Media Foundation absent (Windows N…)
        return None


def _enumerer_msmf():
    import ctypes
    import uuid
    from ctypes import POINTER, byref, c_void_p, wintypes

    class GUID(ctypes.Structure):
        _fields_ = [("octets", ctypes.c_ubyte * 16)]

    def guid(s):
        g = GUID()
        ctypes.memmove(g.octets, uuid.UUID(s).bytes_le, 16)
        return g

    def methode(objet, rang, *types):  # appel COM « à la main » : n-ième entrée de la vtable
        vtable = ctypes.cast(objet, POINTER(POINTER(c_void_p))).contents
        return ctypes.WINFUNCTYPE(ctypes.c_long, c_void_p, *types)(vtable[rang])

    ole32, mfplat, mf = ctypes.windll.ole32, ctypes.windll.mfplat, ctypes.windll.mf
    ole32.CoInitializeEx(None, 0)          # déjà initialisé dans ce thread : sans effet
    mfplat.MFStartup(0x00020070, 0)
    attr = c_void_p()
    if mfplat.MFCreateAttributes(byref(attr), 1):
        return None
    try:
        cle = guid("c60ac5fe-252a-478f-a0ef-bc8fa5f7cad3")      # MF_DEVSOURCE_ATTRIBUTE_SOURCE_TYPE
        video = guid("8ac3587a-4ae7-42d8-99e0-0a6013eef90f")    # …_SOURCE_TYPE_VIDCAP_GUID
        methode(attr, 24, c_void_p, c_void_p)(attr, byref(cle), byref(video))   # SetGUID
        tableau, n = c_void_p(), ctypes.c_uint32()
        if mf.MFEnumDeviceSources(attr, byref(tableau), byref(n)):
            return None
        nom = guid("60d0e559-52f8-4fa2-bbce-acdb34a8ec01")      # MF_DEVSOURCE_ATTRIBUTE_FRIENDLY_NAME
        devs = ctypes.cast(tableau, POINTER(c_void_p))
        out = []
        for i in range(n.value):
            s, lg = wintypes.LPWSTR(), ctypes.c_uint32()
            hr = methode(devs[i], 13, c_void_p, c_void_p, c_void_p)(devs[i], byref(nom), byref(s),
                                                                    byref(lg))  # GetAllocatedString
            out.append({"index": i, "nom": s.value if hr == 0 else ""})
            if hr == 0:
                ole32.CoTaskMemFree(s)
            methode(devs[i], 2)(devs[i])   # Release
        ole32.CoTaskMemFree(tableau)
        return out
    finally:
        methode(attr, 2)(attr)


def index_msmf(index_dshow, dshow=None, msmf=None):
    """Index Media Foundation de la caméra vue à `index_dshow` sous DirectShow (même nom ;
    à nom égal, même rang). None si on ne peut pas faire la correspondance."""
    dshow = lister() if dshow is None else dshow
    msmf = lister_msmf() if msmf is None else msmf
    if not dshow or not msmf:
        return None
    nom = next((d["nom"] for d in dshow if d["index"] == index_dshow), None)
    if nom is None:
        return None
    rang = [d["index"] for d in dshow if d["nom"] == nom].index(index_dshow)
    memes = [d["index"] for d in msmf if d["nom"] == nom]
    return memes[rang] if rang < len(memes) else None


def _contient(nom: str, morceaux) -> bool:
    n = (nom or "").lower()
    return any(m.lower() in n for m in morceaux)


def resoudre(cameras_rgb, thermique, peripheriques, cfg_cameras=None):
    """Associe chaque position à un périphérique.

    Renvoie (rgb, thermique) : copies des entrées de config avec en plus
        "source"       index entier ou URL à passer à OpenCV (None : aucune caméra libre)
        "peripherique" nom du périphérique retenu ("" si inconnu)
        "probleme"     message à afficher dans le dashboard ("" si tout va bien)
    """
    cfg_cameras = cfg_cameras or {}
    exclure = cfg_cameras.get("exclure", EXCLURE_DEFAUT)
    mots_th = cfg_cameras.get("thermique", THERMIQUE_DEFAUT)
    noms = None if peripheriques is None else {p["index"]: p["nom"] for p in peripheriques}
    pris: set[int] = set()

    def libre(filtre):
        if noms is None:
            return None
        return next((i for i in sorted(noms) if i not in pris and filtre(noms[i])), None)

    def placer(cam, est_thermique):
        c = dict(cam)
        c.update(source=None, peripherique="", probleme="")
        idx, nom = cam.get("index"), cam.get("nom")
        if cam.get("url"):
            c["source"], c["peripherique"] = cam["url"], "caméra IP"
            return c
        if isinstance(idx, int):
            c["source"] = idx
            pris.add(idx)
            if noms is not None:
                vu = noms.get(idx)
                c["peripherique"] = vu or ""
                if vu is None:
                    c["probleme"] = f"aucune caméra à l'index {idx}"
                elif nom and nom.lower() not in vu.lower():
                    c["probleme"] = (f"index {idx} = « {vu} », attendu « {nom} » : "
                                     "les index ont bougé, relancer lister_cameras.py")
                elif not est_thermique and _contient(vu, exclure):
                    c["probleme"] = f"index {idx} = « {vu} » : c'est la webcam du PC"
            return c
        if noms is None:
            # noms illisibles : on suppose la webcam du PC en 0 et les caméras de la voiture
            # ensuite, dans l'ordre (l'ancien comportement du banc)
            i = next(i for i in range(1, 100) if i not in pris)
            pris.add(i)
            c["source"] = i
            c["probleme"] = (f"noms des caméras illisibles (pygrabber manquant ?) : index {i} "
                             "supposé, vérifier avec lister_cameras.py")
            return c
        if nom:
            i = libre(lambda n: nom.lower() in n.lower())
            manque = f"aucune caméra libre nommée « {nom} »"
        elif est_thermique:
            i = libre(lambda n: _contient(n, mots_th))
            manque = "aucune caméra thermique reconnue (renseigner son nom ou son index)"
        else:
            i = libre(lambda n: not _contient(n, exclure) and not _contient(n, mots_th))
            manque = "pas assez de caméras branchées (webcam du PC écartée)"
        if i is None:
            c["probleme"] = manque
            return c
        pris.add(i)
        c["source"], c["peripherique"] = i, noms[i]
        return c

    # index fixes d'abord : un « auto » ne doit pas voler une caméra explicitement affectée
    fixes = [isinstance(c.get("index"), int) or bool(c.get("url")) for c in cameras_rgb]
    th = None
    th_fixe = bool(thermique) and (isinstance(thermique.get("index"), int) or bool(thermique.get("url")))
    if thermique and thermique.get("active") and th_fixe:
        th = placer(thermique, True)
    rgb = [placer(c, False) if f else None for c, f in zip(cameras_rgb, fixes)]
    th_auto = bool(thermique) and thermique.get("active") and not th_fixe
    if th_auto and noms is not None:
        th = placer(thermique, True)   # avant les RGB « auto », sinon elle serait prise pour une RGB
    rgb = [r if r is not None else placer(c, False) for r, c in zip(rgb, cameras_rgb)]
    if th_auto and noms is None:
        th = placer(thermique, True)   # sans les noms : après les RGB, comme l'ancien index 5
    return rgb, th


def rapport(rgb, th) -> str:
    lignes = ["Caméras :"]
    for c in rgb + ([th] if th else []):
        src = "—" if c["source"] is None else c["source"]
        etat = f"  ⚠ {c['probleme']}" if c["probleme"] else ""
        lignes.append(f"  {c['label']:<32} → {src!s:<4} {c['peripherique']}{etat}")
    return "\n".join(lignes)
