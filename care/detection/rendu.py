"""Rendu des résultats sur les images : boîtes annotées et mosaïque des caméras."""
from __future__ import annotations

import cv2
import numpy as np

from .catalogue import INCONNU

COULEUR = {"vivant": (60, 60, 230), "valeur": (60, 200, 60), "fixe": (150, 150, 150), "zone": (0, 165, 255)}
_ACCENTS = str.maketrans("àâäéèêëîïôöùûüç", "aaaeeeeiioouuuc")


def _ascii(s) -> str:
    """OpenCV ne sait pas dessiner les accents."""
    return str(s).translate(_ACCENTS)


def _etiquette(img, texte, x1, y1, couleur, echelle):
    (tw, th), _ = cv2.getTextSize(texte, cv2.FONT_HERSHEY_SIMPLEX, echelle, 1)
    cv2.rectangle(img, (x1, max(0, y1 - th - 8)), (x1 + tw + 6, max(th + 8, y1)), couleur, -1)
    cv2.putText(img, texte, (x1 + 3, max(th + 3, y1 - 5)), cv2.FONT_HERSHEY_SIMPLEX, echelle,
                (255, 255, 255), 1, cv2.LINE_AA)


def annoter(image, detections=(), fixes=(), inconnues=()):
    """Dessine les détections retenues (couleur selon la catégorie), les objets déjà
    présents sur la référence (gris, trait fin) et les zones nouvelles non identifiées."""
    img = image.copy()
    e = max(0.5, 0.5 * img.shape[1] / 640)
    for d in fixes:
        x1, y1, x2, y2 = (int(v) for v in d.boite)
        cv2.rectangle(img, (x1, y1), (x2, y2), COULEUR["fixe"], 1)
        cv2.putText(img, _ascii(f"deja la : {d.cle}"), (x1, max(12, y1 - 4)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9 * e, COULEUR["fixe"], 1, cv2.LINE_AA)
    for d in detections:
        x1, y1, x2, y2 = (int(v) for v in d.boite)
        couleur = COULEUR.get(d.categorie, COULEUR["valeur"])
        cv2.rectangle(img, (x1, y1), (x2, y2), couleur, 2)
        _etiquette(img, _ascii(f"{d.cle} {d.conf:.0%}"), x1, y1, couleur, e)
    for z in inconnues:
        x1, y1, x2, y2 = (int(v) for v in z)
        cv2.rectangle(img, (x1, y1), (x2, y2), COULEUR["zone"], 2)
        _etiquette(img, _ascii(INCONNU), x1, y1, COULEUR["zone"], e)
    return img


def mosaique(images, w=640, h=360):
    imgs = [cv2.resize(i, (w, h)) for i in images if i is not None]
    if not imgs:
        return None
    if len(imgs) == 1:
        return imgs[0]
    if len(imgs) == 2:
        return np.hstack(imgs)
    while len(imgs) < 4:
        imgs.append(np.zeros((h, w, 3), np.uint8))
    return np.vstack([np.hstack(imgs[:2]), np.hstack(imgs[2:4])])
