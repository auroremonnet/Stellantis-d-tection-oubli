"""Faible lumière : rendre une image sombre et bruitée exploitable par les modèles.

De nuit ou en pénombre, la caméra monte son gain : l'image est sombre et couverte de bruit, et
les détecteurs ne voient plus rien (mesuré en simulant la pénombre sur les images du 06/11 :
88 % → 9 % d'objets retrouvés). Deux remèdes, chacun déclenché par ce qu'il corrige :

    moyenner    quand l'image est BRUITÉE (écart entre deux images successives). La scène est
                immobile, le bruit non : la moyenne de N images divise le bruit par √N.
                C'est le remède principal.
    eclaircir   quand l'image est SOMBRE : ramène la luminosité médiane à celle du jour
                (courbe gamma) après un léger flou.

Sous `seuil_noir`, il n'y a plus de signal du tout : la caméra est déclarée aveugle, et seuls
la thermique et le son peuvent encore détecter une présence.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class Reglages:
    seuil_bruit: float = 5.0     # bruit (niveaux de gris) au-delà duquel on moyenne des rafales
    seuil_sombre: float = 55.0   # luminosité médiane (0..255) sous laquelle on éclaircit
    seuil_noir: float = 20.0     # en dessous : caméra aveugle
    cible: float = 115.0         # luminosité médiane visée après éclaircissement
    flou: float = 1.0            # écart-type du flou de débruitage (pixels, pour 640 de large)
    rafale: int = 4              # images moyennées à chaque passe quand il fait sombre

    @classmethod
    def depuis_config(cls, d: dict | None) -> Reglages:
        d = d or {}
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


def luminosite(image) -> float:
    """Luminosité médiane de l'image (0 = noir, 255 = blanc)."""
    return float(np.median(cv2.cvtColor(image[::4, ::4], cv2.COLOR_BGR2GRAY)))


def bruit(image_a, image_b) -> float:
    """Bruit de la caméra, estimé sur deux images successives d'une scène immobile (écart-type
    robuste de leur différence, en niveaux de gris). Un objet qui bouge ne le fausse pas."""
    if image_a.shape != image_b.shape:
        return 0.0
    a = cv2.cvtColor(image_a[::3, ::3], cv2.COLOR_BGR2GRAY).astype(np.float32)
    b = cv2.cvtColor(image_b[::3, ::3], cv2.COLOR_BGR2GRAY).astype(np.float32)
    d = a - b
    return float(1.4826 * np.median(np.abs(d - np.median(d))) / np.sqrt(2.0))


def eclaircir(image, r: Reglages | None = None):
    """Image inchangée s'il fait assez clair ; sinon débruitée et éclaircie."""
    r = r or Reglages()
    mediane = luminosite(image)
    if mediane >= r.seuil_sombre:
        return image
    x = image.astype(np.float32) / 255.0
    if r.flou > 0:
        x = cv2.GaussianBlur(x, (0, 0), r.flou * image.shape[1] / 640.0)
    gamma = np.log(r.cible / 255.0) / np.log(max(mediane, 2.0) / 255.0)     # médiane → cible
    return (np.clip(x, 0.0, 1.0) ** gamma * 255.0).astype(np.uint8)


def nettoyer(source_rafale, premiere, moyenne: Moyenne, r: Reglages):
    """Image à montrer aux modèles pour cette passe : moyenne cumulée de rafales si la caméra
    est bruitée, puis éclaircie si elle est sombre. `source_rafale(k)` rend jusqu'à k images
    distinctes, la première étant `premiere`. Renvoie (image, bruit mesuré)."""
    images = source_rafale(2) if moyenne.n == 0 else []
    niveau = bruit(images[0], images[1]) if len(images) >= 2 else moyenne.bruit
    moyenne.bruit = niveau
    if niveau > r.seuil_bruit:
        moyenne.ajouter(images or [premiere])
        moyenne.ajouter(source_rafale(r.rafale)[1:])
        return eclaircir(moyenne.image(), r), niveau
    return eclaircir(premiere, r), niveau


class Moyenne:
    """Moyenne cumulée des images d'une caméra pendant un essai."""

    def __init__(self):
        self._somme = None
        self.n = 0
        self.bruit = 0.0     # dernier bruit mesuré sur cette caméra

    def ajouter(self, images) -> None:
        for img in images:
            if self._somme is None:
                self._somme = img.astype(np.float32)
            elif img.shape == self._somme.shape:
                self._somme += img
            else:
                continue
            self.n += 1

    def image(self):
        return None if self._somme is None else (self._somme / self.n).astype(np.uint8)
