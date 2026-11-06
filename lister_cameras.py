"""Assistant « quelle caméra est où » — à lancer une fois installé dans la voiture.

    python lister_cameras.py            liste les caméras, puis demande la position de chacune
    python lister_cameras.py --liste    liste seulement (rien n'est écrit)

Pour chaque caméra branchée (la webcam du PC est signalée et proposée en dernier), une
fenêtre d'aperçu s'ouvre : taper dans le terminal la position qu'elle filme. Le résultat est
écrit dans config.local.json (ignoré par git, propre à ce PC) : config.json n'est pas touché.

Si on débranche / rebranche les caméras sur d'autres ports, relancer l'assistant : le
dashboard prévient au démarrage quand le nom vu à un index ne correspond plus.
"""
import argparse
import json
import os
import sys

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


def apercu(index):
    cap = cv2.VideoCapture(index, BACKEND)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    ok, f = False, None
    for _ in range(10):  # les premières images sont souvent noires
        ok, f = cap.read()
    cap.release()
    return f if ok else None


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
                print(f"  index {d['index']:<2} {d['nom']:<35} (pas d'image)")
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
    choix = "  ".join(f"{i + 1}={p['label']}" for i, p in enumerate(positions))
    print(f"\nPour chaque aperçu, taper la position filmée :\n  {choix}  t=thermique  "
          "Entrée=ignorer (webcam du PC…)\n")
    affect, th_aff = {}, None
    # webcam du PC en dernier : on finit souvent avant
    for d in sorted(trouvees, key=lambda d: d["genre"] == "webcam du PC"):
        titre = f"index {d['index']} - {d['nom'] or '?'}"
        img = d["image"]
        if est_tc001(img):  # flux thermique InfiRay / TC001 : n'afficher que le bloc image
            img = image_visible(img)
        if img.ndim == 2 or img.dtype != "uint8":
            img = cv2.normalize(img, None, 0, 255, cv2.NORM_MINMAX).astype("uint8")
        cv2.imshow(titre, img)
        cv2.waitKey(300)
        rep = input(f"{titre} ({d['genre'] or 'caméra USB'}) → position ? ").strip().lower()
        cv2.destroyAllWindows()
        if rep == "t":
            th_aff = d
        elif rep.isdigit() and 1 <= int(rep) <= len(positions):
            affect[int(rep) - 1] = d
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
    if th_aff:
        loc["camera_thermique"] = {**loc.get("camera_thermique", {}), "index": th_aff["index"], "active": True,
                                   **({"nom": th_aff["nom"]} if th_aff["nom"] else {})}
    with open(chemin_local, "w", encoding="utf-8") as fh:
        json.dump(loc, fh, ensure_ascii=False, indent=2)
    print(f"\nÉcrit dans {os.path.basename(chemin_local)}. Lancer le dashboard : les positions "
          "s'affichent sous chaque flux, vérifier qu'elles sont dans le bon ordre.")


if __name__ == "__main__":
    sys.exit(main())
