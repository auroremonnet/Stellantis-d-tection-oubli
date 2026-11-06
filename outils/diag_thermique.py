"""Vérifie que la Topdon TC001 donne bien ses TEMPÉRATURES (et pas seulement une image).

    python outils/diag_thermique.py            # trouve la TC001 toute seule
    python outils/diag_thermique.py --index 2  # ou en précisant son index

Dashboard arrêté (sinon la caméra est occupée). Pour chaque façon d'ouvrir la caméra, affiche
la forme du flux et, si les températures sont lisibles, la plage min / max en °C. Main devant
la caméra : la max doit monter vers 30-35 °C. Une image par essai est sauvée dans diag/.
La ligne « → À METTRE dans config.json » donne le réglage qui marche.
"""
import argparse
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from care import peripheriques  # noqa: E402
from care.cameras import decoder_tc001, est_tc001  # noqa: E402

ESSAIS = [("dshow", cv2.CAP_DSHOW), ("msmf", cv2.CAP_MSMF)] if os.name == "nt" else [("", cv2.CAP_ANY)]


def lire(index, backend):
    cap = cv2.VideoCapture(index, backend)
    if not cap.isOpened():
        return None
    cap.set(cv2.CAP_PROP_CONVERT_RGB, 0)
    f = None
    for _ in range(20):
        ok, g = cap.read()
        if ok:
            f = g
    cap.release()
    return f


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", type=int)
    a = ap.parse_args()
    os.makedirs("diag", exist_ok=True)
    if a.index is not None:
        index = [a.index]
    else:
        devs = peripheriques.lister() or [{"index": i, "nom": "?"} for i in range(8)]
        index = [d["index"] for d in devs]
    bon = None
    for i in index:
        for nom, be in ESSAIS:
            f = lire(i, be)
            if f is None:
                continue
            if not est_tc001(f):
                continue  # pas la TC001 (caméra RGB)
            t = decoder_tc001(f)
            if t is None:
                print(f"index {i} {nom:6} flux {f.shape} : converti en couleur, températures perdues")
                continue
            print(f"index {i} {nom:6} flux {f.shape} : températures OK  min {t.min():.1f} °C  "
                  f"max {t.max():.1f} °C  moyenne {t.mean():.1f} °C")
            img = cv2.applyColorMap(np.clip((t - 15) * 10, 0, 255).astype(np.uint8), cv2.COLORMAP_INFERNO)
            cv2.imwrite(f"diag/thermique_{i}_{nom or 'defaut'}.png", cv2.resize(img, (512, 384)))
            bon = bon or (i, nom)
    if bon:
        print(f'\n→ À METTRE dans config.local.json : "camera_thermique": {{"index": {bon[0]}}}, '
              f'"thermique": {{"modele": "tc001", "backend": "{bon[1]}"}}')
    else:
        print("\nAucune TC001 lisible en températures. Envoyer cette sortie (et le nom de la caméra "
              "affiché par python lister_cameras.py --liste).")


if __name__ == "__main__":
    main()
