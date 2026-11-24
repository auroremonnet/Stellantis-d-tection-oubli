"""Comparaison d'une image à la référence « habitacle vide » de la même caméra.

Répond à deux questions :
    zones()          où y a-t-il quelque chose de NOUVEAU ? (propositions d'objets, même
                     pour ce qu'aucun modèle ne sait nommer)
    part_changee()   cette boîte était-elle DÉJÀ LÀ ? (boucle de ceinture, clés rangées
                     dans la console : détectées, mais pas oubliées)

La comparaison est faite pour résister à ce qui change tout le temps dans une voiture :
    - l'exposition et la balance des blancs de la caméra : on compare la luminance après
      avoir retiré le champ d'éclairage lisse (rapport des deux images, très flouté), et la
      couleur (a, b de Lab) après recalage de sa médiane ;
    - une caméra légèrement bougée : la référence est recalée par translation ;
    - un câble déplacé : une zone filiforme n'est pas un objet.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class Reglages:
    seuil_luminance: float = 24.0      # écart de luminance (0..255) pour « a changé »
    seuil_couleur: float = 13.0        # écart de couleur (distance a,b de Lab)
    seuil_luminance_fin: float = 12.0  # seuils sensibles, pour « cette boîte était-elle déjà là ? »
    seuil_couleur_fin: float = 8.0
    part_min: float = 0.0005           # aire minimale d'une zone, en part de l'image
    part_max: float = 0.25             # au-delà, ce n'est pas un objet posé
    part_image_max: float = 0.35       # au-delà, toute l'image a changé : lumière, caméra bougée
    remplissage_min: float = 0.2       # zone / boîte englobante : en dessous, c'est un câble
    zones_max: int = 8
    decalage_max: float = 0.06         # recalage maximal de la caméra, en part de l'image

    @classmethod
    def depuis_config(cls, d: dict | None) -> Reglages:
        d = d or {}
        champs = {k: d[k] for k in cls.__dataclass_fields__ if k in d}
        return cls(**champs)


def recaler(reference, image, decalage_max: float = 0.06):
    """Translate la référence pour la superposer à l'image.
    Renvoie (référence recalée, fiable, (dx, dy)). `fiable` est faux si la caméra a trop
    bougé : la référence est alors à refaire."""
    e = 320.0 / image.shape[1]
    a = cv2.resize(cv2.cvtColor(reference, cv2.COLOR_BGR2GRAY), None, fx=e, fy=e).astype(np.float32)
    b = cv2.resize(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), None, fx=e, fy=e).astype(np.float32)
    (dx, dy), reponse = cv2.phaseCorrelate(a, b, cv2.createHanningWindow(a.shape[::-1], cv2.CV_32F))
    dx, dy = dx / e, dy / e
    if reponse < 0.15 or max(abs(dx), abs(dy)) < 1.0:
        return reference, True, (0.0, 0.0)           # pas de décalage mesurable
    if max(abs(dx) / image.shape[1], abs(dy) / image.shape[0]) > decalage_max:
        return reference, False, (dx, dy)
    m = np.float32([[1, 0, dx], [0, 1, dy]])
    return (cv2.warpAffine(reference, m, (image.shape[1], image.shape[0]), borderMode=cv2.BORDER_REPLICATE),
            True, (dx, dy))


class Comparaison:
    """Écarts pixel à pixel entre une image et la référence de sa caméra."""

    def __init__(self, reference, image, reglages: Reglages | None = None):
        self.r = reglages or Reglages()
        if reference.shape[:2] != image.shape[:2]:
            reference = cv2.resize(reference, (image.shape[1], image.shape[0]))
        reference, self.recalage_fiable, (dx, dy) = recaler(reference, image, self.r.decalage_max)
        self.echelle = image.shape[1] / 640.0
        self.noyau = int(round(2 * self.echelle)) * 2 + 1
        k = (self.noyau, self.noyau)
        a = cv2.cvtColor(cv2.GaussianBlur(reference, k, 0), cv2.COLOR_BGR2LAB).astype(np.float32)
        b = cv2.cvtColor(cv2.GaussianBlur(image, k, 0), cv2.COLOR_BGR2LAB).astype(np.float32)
        rapport = np.clip((b[..., 0] + 8) / (a[..., 0] + 8), 0.6, 1.6)
        champ = cv2.GaussianBlur(rapport, (0, 0), 50 * self.echelle)
        self.luminance = np.abs(b[..., 0] - np.clip(a[..., 0] * champ, 0, 255))
        for c in (1, 2):
            b[..., c] += np.median(a[..., c]) - np.median(b[..., c])
        self.couleur = np.hypot(a[..., 1] - b[..., 1], a[..., 2] - b[..., 2])
        if self.recalage_fiable and (dx or dy):       # bords sans référence après recalage : ignorés
            bx, by = int(abs(dx)) + self.noyau + 2, int(abs(dy)) + self.noyau + 2
            for ecart in (self.luminance, self.couleur):
                ecart[:by], ecart[-by:], ecart[:, :bx], ecart[:, -bx:] = 0, 0, 0, 0
        self._masque = None

    def masque(self) -> np.ndarray:
        """Masque binaire (0/1) des pixels qui ont changé, nettoyé du bruit."""
        if self._masque is None:
            m = ((self.luminance > self.r.seuil_luminance) | (self.couleur > self.r.seuil_couleur)).astype(np.uint8)
            k = self.noyau
            m = cv2.morphologyEx(m, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k + 2, k + 2)))
            self._masque = cv2.morphologyEx(m, cv2.MORPH_CLOSE,
                                            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (4 * k + 1, 4 * k + 1)))
        return self._masque

    @property
    def inutilisable(self) -> bool:
        """Presque toute l'image a changé (lumière, caméra déplacée) : la référence est à refaire."""
        return (not self.recalage_fiable) or float(self.masque().mean()) > self.r.part_image_max

    def zones(self) -> list[list[int]]:
        """Boîtes des zones nouvelles, de la plus grande à la plus petite."""
        if self.inutilisable:
            return []
        m = self.masque()
        h, w = m.shape
        n, _, stats, _ = cv2.connectedComponentsWithStats(m, 8)
        zones = []
        for i in range(1, n):
            x, y, bw, bh, a = (int(v) for v in stats[i])
            if a < self.r.part_min * w * h or bw * bh > self.r.part_max * w * h:
                continue
            if a / float(bw * bh) < self.r.remplissage_min:
                continue
            zones.append((a, [x, y, x + bw, y + bh]))
        zones.sort(key=lambda z: -z[0])
        return [z[1] for z in zones[: self.r.zones_max]]

    def part_changee(self, boite) -> float:
        """Part des pixels de la boîte qui diffèrent de la référence (seuils sensibles)."""
        h, w = self.luminance.shape
        x1, y1 = max(0, int(boite[0])), max(0, int(boite[1]))
        x2, y2 = min(w, int(boite[2])), min(h, int(boite[3]))
        if x2 <= x1 or y2 <= y1:
            return 0.0
        dl, dc = self.luminance[y1:y2, x1:x2], self.couleur[y1:y2, x1:x2]
        return float(((dl > self.r.seuil_luminance_fin) | (dc > self.r.seuil_couleur_fin)).mean())
