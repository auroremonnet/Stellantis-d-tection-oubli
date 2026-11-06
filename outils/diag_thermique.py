"""Vérifie que la caméra thermique donne bien ses DONNÉES (et pas seulement une image).

    python outils/diag_thermique.py            # trouve la thermique toute seule
    python outils/diag_thermique.py --index 0  # ou en précisant son index (celui de lister_cameras.py)

Dashboard arrêté (sinon la caméra est occupée). Ouvre la caméra exactement comme le dashboard,
pour chaque backend et chaque mode (256x392 : caméra du banc, 256x384 : TC001), et affiche :
  - « radiométrique » : températures lues (main devant la caméra : la max monte vers 30-35 °C) ;
  - « relatif » : comptes bruts du capteur (pas de °C) ; affiche le nombre de pixels chauds
    avec le seuil actuel. Habitacle vide : il doit rester ~0. Main devant : il doit monter.
Une image par essai est sauvée dans diag/. La ligne « → À METTRE » donne le réglage qui marche.
"""
import argparse
import json
import os
import sys

import cv2
import numpy as np

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RACINE)
from care import peripheriques  # noqa: E402
from care.cameras import SourceThermique, decoder_trame  # noqa: E402

BACKENDS = ["msmf", "dshow"] if os.name == "nt" else [""]
RESOLUTIONS = [[256, 392], [256, 384]]


def params_config():
    with open(os.path.join(RACINE, "config.json"), encoding="utf-8") as fh:
        p = json.load(fh)["thermique"]
    local = os.path.join(RACINE, "config.local.json")
    if os.path.exists(local):
        with open(local, encoding="utf-8") as fh:
            p.update(json.load(fh).get("thermique", {}))
    return p


def lire(index, params):
    cap = SourceThermique("thermal", index, "diag", params)._ouvrir()
    if not cap.isOpened():
        return None
    f = None
    for _ in range(25):  # les premières images peuvent être vides
        ok, g = cap.read()
        if ok:
            f = g
    cap.release()
    return f


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", type=int)
    a = ap.parse_args()
    os.makedirs(os.path.join(RACINE, "diag"), exist_ok=True)
    base = params_config()
    devs = peripheriques.lister() or [{"index": i, "nom": "?"} for i in range(8)]
    if a.index is not None:
        devs = [d for d in devs if d["index"] == a.index] or [{"index": a.index, "nom": "?"}]
    else:  # jamais la webcam du PC (liste « exclure » de config.json)
        with open(os.path.join(RACINE, "config.json"), encoding="utf-8") as fh:
            exclure = json.load(fh).get("cameras", {}).get("exclure", peripheriques.EXCLURE_DEFAUT)
        devs = [d for d in devs if not peripheriques._contient(d["nom"], exclure)]
    bon = None
    for d in devs:
        for be in BACKENDS:
            for res in RESOLUTIONS:
                p = {**base, "backend": be, "resolution": res}
                f = lire(d["index"], p)
                tag = f"index {d['index']} ({d['nom']}) {be or 'défaut':5} {res[0]}x{res[1]}"
                if f is None:
                    print(f"{tag} : pas d'image")
                    continue
                s = SourceThermique("thermal", d["index"], "diag", p)
                masque, img, tmax = s.masque_chaud(f)
                info = f"flux {f.shape} → mode « {s.mode} », {int(masque.sum())} pixels chauds"
                if tmax is not None:
                    info += f", max {tmax:.1f} °C"
                elif decoder_trame(f) is not None:
                    brut = decoder_trame(f)[0]
                    info += (f", comptes min/médiane/max {brut.min()}/{int(np.median(brut))}/{brut.max()}"
                             f" (seuil : fond + {p.get('seuil_comptes', 200)})")
                print(f"{tag} : {info}")
                nom = f"thermique_{d['index']}_{be or 'defaut'}_{res[1]}.png"
                cv2.imwrite(os.path.join(RACINE, "diag", nom),
                            cv2.resize(cv2.applyColorMap(img, cv2.COLORMAP_INFERNO), (512, 384)))
                if bon is None and ("radiométrique" in s.mode or "relatif" in s.mode):
                    bon = (d["index"], be, res)
    if bon:
        print(f'\n→ À METTRE dans config.local.json : "camera_thermique": {{"index": {bon[0]}}}, '
              f'"thermique": {{"backend": "{bon[1]}", "resolution": {bon[2]}}}')
    else:
        print("\nAucune donnée thermique lisible. Envoyer cette sortie (et celle de "
              "python lister_cameras.py --liste).")


if __name__ == "__main__":
    main()
