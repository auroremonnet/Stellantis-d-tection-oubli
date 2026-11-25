"""Assistant « quelle caméra est où » — à lancer une fois installé dans la voiture.

    python lister_cameras.py            liste les caméras, puis demande la position de chacune
    python lister_cameras.py --liste    liste seulement (rien n'est écrit)

Pour chaque caméra branchée (la webcam du PC est signalée et proposée en dernier), une
fenêtre d'aperçu EN DIRECT s'ouvre au premier plan : cliquer dessus puis appuyer sur la touche
de la position filmée (1 à 4, t pour la thermique, Espace pour passer, r pour rouvrir la
caméra si l'image est noire, q pour arrêter). Le résultat est écrit dans config.local.json
(ignoré par git, propre à ce PC) : config.json n'est pas touché.

Si on débranche / rebranche les caméras sur d'autres ports, relancer l'assistant : le
dashboard prévient au démarrage quand le nom vu à un index ne correspond plus.
"""
import argparse
import contextlib
import json
import os
import sys
import time

import cv2

from care import peripheriques
from care.cameras import est_tc001, image_visible

RACINE = os.path.dirname(os.path.abspath(__file__))
BACKEND = cv2.CAP_DSHOW if os.name == "nt" else cv2.CAP_ANY


def charger_config():
    with open(os.path.join(RACINE, "config.json"), encoding="utf-8") as fh:
        cfg = json.load(fh)
    local = os.path.join(RACINE, "config.local.json")
    loc = {}
    if os.path.exists(local):
        with open(local, encoding="utf-8") as fh:
            loc = json.load(fh)
    return cfg, loc, local


def ouvrir(index):
    cap = cv2.VideoCapture(index, BACKEND)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return cap


def image_valable(f) -> bool:
    """Une vraie image : ni absente, ni noire (les premières le sont souvent)."""
    return f is not None and f.size > 0 and float(f.mean()) > 4


def apercu(index, attente_s=3.0):
    """Une image de la caméra, en lui laissant le temps de démarrer ; None si elle ne donne rien."""
    cap = ouvrir(index)
    f, fin = None, time.time() + attente_s
    try:
        while time.time() < fin:
            ok, img = cap.read()
            if ok and img is not None:
                f = img
                if image_valable(img):
                    break
            else:
                time.sleep(0.05)
    finally:
        cap.release()
    return f


def afficher(img):
    if est_tc001(img):  # flux thermique InfiRay / TC001 : n'afficher que le bloc image
        img = image_visible(img)
    if img.ndim == 2 or img.dtype != "uint8":
        img = cv2.normalize(img, None, 0, 255, cv2.NORM_MINMAX).astype("uint8")
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    h, w = img.shape[:2]
    return cv2.resize(img, (960, max(1, int(960 * h / w))))


def choisir_en_direct(d, positions, n, total):
    """Montre la caméra en direct et attend une touche DANS la fenêtre. Renvoie « 1 »…« 9 »,
    « t », « » (passer) ou « q » (arrêter). L'aperçu ne se fige pas : on voit ce qu'on bouge."""
    titre = "CARE - quelle camera est-ce ?"
    aide = "  ".join(f"{i + 1}={p['label']}" for i, p in enumerate(positions)) + "  t=thermique"
    cv2.namedWindow(titre, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(titre, 960, 600)
    with contextlib.suppress(cv2.error):
        cv2.setWindowProperty(titre, cv2.WND_PROP_TOPMOST, 1)   # devant le terminal
    cap, derniere, debut = ouvrir(d["index"]), d["image"], time.time()
    try:
        while True:
            ok, f = cap.read()
            if ok and image_valable(f):
                derniere, debut = f, time.time()
            elif time.time() - debut > 4:   # plus d'image : on rouvre la caméra toute seule
                cap.release()
                cap, debut = ouvrir(d["index"]), time.time()
            vue = afficher(derniere)
            bandeau = [f"Camera {n}/{total} : index {d['index']} {d['nom'] or ''} {d['genre']}".strip(), aide,
                       "Espace=passer  r=rouvrir  q=arreter" + ("" if ok else "   (image figee, camera muette)")]
            cv2.rectangle(vue, (0, 0), (vue.shape[1], 92), (30, 20, 14), -1)
            for i, ligne in enumerate(bandeau):
                cv2.putText(vue, ligne.encode("ascii", "replace").decode(), (12, 26 + 28 * i),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.62, (255, 255, 255), 1, cv2.LINE_AA)
            cv2.imshow(titre, vue)
            k = cv2.waitKey(40) & 0xFF
            c = chr(k).lower() if k != 255 else ""
            if c == "r":
                cap.release()
                cap, debut = ouvrir(d["index"]), time.time()
            elif c in ("q", "t") or (c.isdigit() and 1 <= int(c) <= len(positions)):
                return c
            elif k in (32, 13, 27):   # Espace, Entrée, Échap : passer
                return ""
            if cv2.getWindowProperty(titre, cv2.WND_PROP_VISIBLE) < 1:   # fenêtre fermée à la souris
                return ""
    finally:
        cap.release()
        cv2.destroyAllWindows()
        cv2.waitKey(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--liste", action="store_true", help="lister sans rien écrire")
    ap.add_argument("--max", type=int, default=10, help="index testés si les noms sont illisibles")
    a = ap.parse_args()
    cfg, loc, chemin_local = charger_config()
    exclure = cfg.get("cameras", {}).get("exclure", peripheriques.EXCLURE_DEFAUT)
    mots_th = cfg.get("cameras", {}).get("thermique", peripheriques.THERMIQUE_DEFAUT)

    devs = peripheriques.lister()
    if devs is None:
        print("Noms des caméras illisibles (sous Windows : pip install pygrabber). Test des index…")
        devs = [{"index": i, "nom": ""} for i in range(a.max)]
    print("\nCaméras détectées :")
    trouvees = []
    for d in devs:
        f = apercu(d["index"])
        if f is None:
            if d["nom"]:
                print(f"  index {d['index']:<2} {d['nom']:<35} (pas d'image : débrancher / rebrancher son câble)")
            continue
        genre = ("webcam du PC" if peripheriques._contient(d["nom"], exclure) else
                 "thermique ?" if peripheriques._contient(d["nom"], mots_th) or f.shape[1] <= 160
                 or est_tc001(f) else "")
        print(f"  index {d['index']:<2} {d['nom'] or '?':<35} {f.shape[1]}x{f.shape[0]}  {genre}")
        trouvees.append({**d, "image": f, "genre": genre})
    if a.liste or not trouvees:
        return

    positions = cfg["cameras_rgb"]
    th = cfg["camera_thermique"]
    print("\nUne fenêtre s'ouvre pour chaque caméra, en direct. Cliquer dessus, puis appuyer sur :\n  "
          + "  ".join(f"{i + 1}={p['label']}" for i, p in enumerate(positions))
          + "  t=thermique  Espace=passer  r=rouvrir la caméra  q=arrêter\n")
    affect, th_aff = {}, None
    # webcam du PC en dernier : on finit souvent avant
    ordre = sorted(trouvees, key=lambda d: d["genre"] == "webcam du PC")
    for n, d in enumerate(ordre, 1):
        rep = choisir_en_direct(d, positions, n, len(ordre))
        if rep == "q":
            print("Arrêt demandé : rien n'est écrit.")
            return
        if rep == "t":
            th_aff = d
            print(f"  index {d['index']} → thermique")
        elif rep.isdigit():
            ancien = affect.get(int(rep) - 1)
            if ancien:
                print(f"  ⚠ {positions[int(rep) - 1]['label']} était déjà donnée à l'index "
                      f"{ancien['index']} : remplacée")
            affect[int(rep) - 1] = d
            print(f"  index {d['index']} → {positions[int(rep) - 1]['label']}")
        else:
            print(f"  index {d['index']} → ignorée")
        if len(affect) == len(positions) and (th_aff or not th.get("active")):
            break

    rgb = []
    for i, p in enumerate(positions):
        d = affect.get(i)
        e = {k: v for k, v in p.items() if k not in ("index", "nom", "url")}
        if d:
            e.update(index=d["index"], **({"nom": d["nom"]} if d["nom"] else {}))
        else:
            e["index"] = "auto"
            print(f"  ⚠ {p['label']} : aucune caméra choisie, laissée en « auto »")
        rgb.append(e)
    loc["cameras_rgb"] = rgb
    # les caméras avant servent à savoir si le conducteur est à bord (surveillance automatique)
    avant = [p["id"] for i, p in enumerate(positions) if i in affect and p["label"].lower().startswith("avant")]
    if avant and not loc.get("surveillance", {}).get("cameras_conducteur"):
        loc["surveillance"] = {**loc.get("surveillance", {}), "cameras_conducteur": avant}
        print(f"  caméras du conducteur : {', '.join(avant)}")
    if th_aff:
        loc["camera_thermique"] = {**loc.get("camera_thermique", {}), "index": th_aff["index"], "active": True,
                                   **({"nom": th_aff["nom"]} if th_aff["nom"] else {})}
    with open(chemin_local, "w", encoding="utf-8") as fh:
        json.dump(loc, fh, ensure_ascii=False, indent=2)
    print(f"\nÉcrit dans {os.path.basename(chemin_local)}. Lancer le dashboard : les positions "
          "s'affichent sous chaque flux, vérifier qu'elles sont dans le bon ordre.")


if __name__ == "__main__":
    sys.exit(main())
