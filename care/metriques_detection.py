"""Métriques de détection boîte par boîte, indépendantes du moteur.

Les vérités terrain (export YOLO de Roboflow : baby, keys, wallet, card) et les
prédictions (YOLOE : "car key", "credit card"… ; modèle entraîné : "keys", "card"…)
sont ramenées au même libellé français canonique avant comparaison. On peut ainsi
mesurer YOLOE, le modèle entraîné et l'hybride sur exactement les mêmes images.

Appariement standard (type VOC/COCO à un seul seuil) : par image et par classe, les
prédictions sont triées par confiance décroissante et chacune prend la vérité libre de
meilleur IoU si IoU >= seuil (VP), sinon c'est un faux positif.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from .reference import iou

# Plusieurs libellés désignent le même objet (fusion des moteurs et évaluation). « enfant »
# (prompt YOLOE) et « bébé » (classe entraînée) désignent le même poupon dans un siège auto :
# sans ce rapprochement, la comparaison YOLOE vs modèle entraîné serait biaisée contre YOLOE.
SYNONYMES = {"clés de voiture": "clés", "carte": "carte bancaire", "smartphone": "téléphone",
             "enfant": "bébé"}


def canonique(libelle: str) -> str:
    return SYNONYMES.get(libelle, libelle)


@dataclass
class Compteur:
    vp: int = 0
    fp: int = 0
    fn: int = 0
    confiances_vp: list = field(default_factory=list)

    @property
    def precision(self) -> float | None:
        return None if self.vp + self.fp == 0 else self.vp / (self.vp + self.fp)

    @property
    def rappel(self) -> float | None:
        return None if self.vp + self.fn == 0 else self.vp / (self.vp + self.fn)

    @property
    def f1(self) -> float | None:
        p, r = self.precision, self.rappel
        if p is None or r is None or p + r == 0:
            return None if p is None or r is None else 0.0
        return 2 * p * r / (p + r)

    def en_dict(self) -> dict:
        arr = lambda v: None if v is None else round(v, 3)  # noqa: E731
        return {"VP": self.vp, "FP": self.fp, "FN": self.fn, "precision": arr(self.precision),
                "rappel": arr(self.rappel), "f1": arr(self.f1)}


def apparier(verites: list[tuple[str, list]], predictions: list[tuple[str, float, list]],
             seuil_iou: float = 0.5) -> dict[str, Compteur]:
    """verites : [(libellé, boîte)] ; predictions : [(libellé, conf, boîte)] pour UNE image."""
    res: dict[str, Compteur] = defaultdict(Compteur)
    par_classe_v = defaultdict(list)
    for lib, b in verites:
        par_classe_v[canonique(lib)].append(b)
    par_classe_p = defaultdict(list)
    for lib, c, b in predictions:
        par_classe_p[canonique(lib)].append((c, b))
    for cls in set(par_classe_v) | set(par_classe_p):
        libres = list(par_classe_v.get(cls, []))
        for conf, b in sorted(par_classe_p.get(cls, []), key=lambda x: -x[0]):
            meilleur, k = 0.0, -1
            for i, v in enumerate(libres):
                o = iou(b, v)
                if o > meilleur:
                    meilleur, k = o, i
            if k >= 0 and meilleur >= seuil_iou:
                res[cls].vp += 1
                res[cls].confiances_vp.append(conf)
                libres.pop(k)
            else:
                res[cls].fp += 1
        res[cls].fn += len(libres)
    return res


@dataclass
class Evaluation:
    """Accumule les résultats image par image."""
    classes: tuple[str, ...]
    seuil_iou: float = 0.5
    par_classe: dict = field(default_factory=lambda: defaultdict(Compteur))
    images: int = 0
    # niveau « alerte » : l'image contient-elle au moins un objet évalué, et l'a-t-on signalé ?
    alerte: Compteur = field(default_factory=Compteur)
    latences: list = field(default_factory=list)

    def ajouter(self, verites, predictions, latence_s: float | None = None) -> None:
        classes = {canonique(c) for c in self.classes}
        verites = [(canonique(lib), b) for lib, b in verites if canonique(lib) in classes]
        predictions = [(canonique(lib), c, b) for lib, c, b in predictions if canonique(lib) in classes]
        for cls, cpt in apparier(verites, predictions, self.seuil_iou).items():
            tot = self.par_classe[cls]
            tot.vp, tot.fp, tot.fn = tot.vp + cpt.vp, tot.fp + cpt.fp, tot.fn + cpt.fn
            tot.confiances_vp += cpt.confiances_vp
        attendu, signale = bool(verites), bool(predictions)
        if attendu and signale:
            self.alerte.vp += 1
        elif signale:
            self.alerte.fp += 1
        elif attendu:
            self.alerte.fn += 1
        self.images += 1
        if latence_s is not None:
            self.latences.append(latence_s)

    def global_(self) -> Compteur:
        g = Compteur()
        for c in self.par_classe.values():
            g.vp, g.fp, g.fn = g.vp + c.vp, g.fp + c.fp, g.fn + c.fn
        return g

    def en_dict(self) -> dict:
        lat = sorted(self.latences)
        return {
            "images": self.images,
            "seuil_iou": self.seuil_iou,
            "par_classe": {c: self.par_classe[canonique(c)].en_dict() for c in self.classes},
            "global": self.global_().en_dict(),
            "alerte_par_image": self.alerte.en_dict(),
            "latence_moyenne_s": round(sum(lat) / len(lat), 3) if lat else None,
            "latence_p95_s": round(lat[int(0.95 * (len(lat) - 1))], 3) if lat else None,
        }
