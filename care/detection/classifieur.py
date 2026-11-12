"""Classifieur « recadrage → classe du catalogue » (MobileCLIP, sans entraînement).

On compare l'empreinte du recadrage aux empreintes des descriptions du catalogue
(« a photo of a wallet », « a photo of a seat belt buckle »…). Le résultat est une
probabilité par classe ; le fond est une classe comme une autre, ce qui permet de répondre
« rien d'intéressant ».
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from .catalogue import FOND, Catalogue
from .clip_image import TourImage, preparer

GABARIT = "a photo of {}"
TEMPERATURE = 100.0     # échelle des logits de CLIP
FICHIER = "mobileclip_blt.ts"


def recadrer(image, boite, marge: float = 0.15):
    """Recadrage de la boîte, avec un peu de contexte, posé au centre d'un carré gris
    (le classifieur attend une image carrée : on ne déforme pas l'objet)."""
    h, w = image.shape[:2]
    x1, y1, x2, y2 = boite
    mx, my = (x2 - x1) * marge + 4, (y2 - y1) * marge + 4
    c = image[int(max(0, y1 - my)):int(min(h, y2 + my)), int(max(0, x1 - mx)):int(min(w, x2 + mx))]
    if c.size == 0:
        return np.full((8, 8, 3), 127, np.uint8)
    cote = max(c.shape[:2])
    carre = np.full((cote, cote, 3), 127, np.uint8)
    oy, ox = (cote - c.shape[0]) // 2, (cote - c.shape[1]) // 2
    carre[oy:oy + c.shape[0], ox:ox + c.shape[1]] = c
    return carre


def agreger(probas_par_description, cles) -> dict[str, float]:
    """Somme les probabilités des descriptions d'une même classe."""
    out: dict[str, float] = {}
    for cle, p in zip(cles, probas_par_description):
        out[cle] = out.get(cle, 0.0) + float(p)
    return out


class Classifieur:
    def __init__(self, catalogue: Catalogue, racine: Path, marge: float = 0.15, lot: int = 16,
                 taille: int = 224):
        import torch
        self.torch = torch
        self.marge, self.lot, self.taille = marge, lot, taille
        chemin = racine / FICHIER
        if not chemin.exists():                       # YOLOE l'a téléchargé à son premier lancement
            from ultralytics.utils.downloads import attempt_download_asset
            chemin = Path(attempt_download_asset(FICHIER))
        clip_ts = torch.jit.load(str(chemin), map_location="cpu").eval()
        self.tour = TourImage.depuis_torchscript(clip_ts.state_dict())
        paires = catalogue.descriptions()
        self.cles = [cle for cle, _ in paires]
        with torch.no_grad():
            t = clip_ts(self._jetons([GABARIT.format(d) for _, d in paires]))
            self.textes = t / t.norm(dim=-1, keepdim=True)
        del clip_ts                                   # la tour texte ne sert plus : ~250 Mo rendus

    @staticmethod
    def _jetons(textes):
        try:
            import clip
        except ImportError:                           # installé par ultralytics pour YOLOE
            from ultralytics.utils.checks import check_requirements
            check_requirements("git+https://github.com/ultralytics/CLIP.git")
            import clip
        return clip.tokenize(textes, truncate=True)

    def classer(self, image, boites) -> list[dict[str, float]]:
        """Pour chaque boîte : {clé de classe ou FOND: probabilité} (somme = 1)."""
        if not boites:
            return []
        torch, out = self.torch, []
        with torch.no_grad():
            for i in range(0, len(boites), self.lot):
                x = preparer([recadrer(image, b, self.marge) for b in boites[i:i + self.lot]], self.taille)
                f = self.tour(x)
                f = f / f.norm(dim=-1, keepdim=True)
                p = (TEMPERATURE * f @ self.textes.T).softmax(-1)
                out += [agreger(ligne, self.cles) for ligne in p.tolist()]
        return out


__all__ = ["Classifieur", "recadrer", "agreger", "FOND"]
