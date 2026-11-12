"""Moteurs de détection : chargement des modèles et inférence.

Un moteur expose deux temps, pour qu'un essai de plusieurs images reste rapide :
    observer(images)                 passe légère sur chaque image (détecteurs seuls) ;
    conclure(image, observations, zones)   une fois par caméra : vote sur l'essai, puis
                                     identification (classifieur, pour le moteur « care »).

Moteurs :
    "care"      localiser (YOLOE + modèle entraîné) puis nommer (MobileCLIP). Par défaut.
    "hybride"   YOLOE + modèle entraîné, noms du détecteur.      } gardés pour comparaison
    "yoloe"     YOLOE seul.                                       } (outils/evaluer.py)
    "coco"      YOLOv8 classique, 80 classes COCO.                }
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .catalogue import INCONNU, VALEUR, VIVANT, Catalogue
from .geometrie import recouvrement
from .identification import (
    ENTRAINE,
    YOLOE,
    ZONE,
    Candidat,
    Detection,
    Regles,
    fusionner,
    preparer_candidats,
    suivre,
    trancher,
    voter,
)

RACINE = Path(__file__).resolve().parent.parent.parent

# ---- vocabulaire des moteurs historiques ----------------------------------------
COCO_VIVANT = {0: "personne", 15: "chat", 16: "chien"}
COCO_VALEUR = {24: "sac à dos", 26: "sac à main", 28: "valise", 63: "ordinateur", 67: "téléphone"}
PROMPTS_VIVANT = ["person", "child", "baby", "cat", "dog"]
PROMPTS_VALEUR = ["cell phone", "car key", "keys", "wallet", "credit card", "handbag",
                  "backpack", "bag", "laptop", "tablet", "glasses", "watch", "headphones"]
LIBELLES = {
    "person": "personne", "child": "enfant", "baby": "bébé", "cat": "chat", "dog": "chien",
    "cell phone": "téléphone", "smartphone": "téléphone", "car key": "clés de voiture",
    "keys": "clés", "wallet": "portefeuille", "credit card": "carte bancaire",
    "handbag": "sac à main", "backpack": "sac à dos", "bag": "sac", "shopping bag": "sac",
    "laptop": "ordinateur", "tablet": "tablette", "glasses": "lunettes", "watch": "montre",
    "headphones": "casque audio", "suitcase": "valise",
    "card": "carte bancaire",  # classes du modèle entraîné (Roboflow care-oubli)
}
CLASSES_CUSTOM = {"baby": "vivant", "keys": "valeur", "wallet": "valeur", "card": "valeur"}


@dataclass
class Conclusion:
    """Ce qu'un moteur affirme d'une caméra à la fin d'un essai."""
    vivants: list[Detection] = field(default_factory=list)
    objets: list[Detection] = field(default_factory=list)
    inconnues: list[list] = field(default_factory=list)     # zones nouvelles non identifiées

    @property
    def detections(self) -> list[Detection]:
        return self.vivants + self.objets


def _chemin(valeur: str) -> str:
    p = Path(valeur)
    return str(p if p.is_absolute() or not (RACINE / p).exists() else RACINE / p)


def _boites(resultat):
    b = resultat.boxes
    return zip(b.cls.tolist(), b.conf.tolist(), b.xyxy.tolist())


class Moteur:
    """Socle commun : réglages, modèle de base, modèle entraîné facultatif."""
    nom = ""

    def __init__(self, cfg: dict):
        d = cfg.get("detection", {})
        self.d = d
        self.modele = d.get("modele", cfg.get("modele", "yoloe-11s-seg.pt"))
        self.imgsz = d.get("imgsz", 640)
        self.conf_vivant = d.get("confiance_vivant", cfg.get("confiance_min", 0.4))
        self.conf_custom = d.get("confiance_custom", 0.35)
        self.ratio = cfg.get("ratio_presence", 0.5)
        self.chemin_custom = _chemin(d.get("modele_custom", "modeles/care-v1.pt"))
        self.base = None
        self.custom = None
        self.avertissement = ""

    # -- chargement --
    def charger(self) -> None:
        raise NotImplementedError

    def _charger_custom(self, classes_connues) -> None:
        import os

        from ultralytics import YOLO
        if not os.path.exists(self.chemin_custom):
            self.avertissement = (f"Modèle entraîné introuvable ({self.chemin_custom}) : "
                                  "YOLOE seul. Voir entrainement/README.md")
            return
        m = YOLO(self.chemin_custom)
        inconnues = sorted(n for n in m.names.values() if not classes_connues(n))
        if inconnues:
            self.avertissement = f"Classes du modèle entraîné ignorées : {', '.join(inconnues)}"
        self._prechauffer(m)
        self.custom = m

    def _prechauffer(self, modele) -> None:
        modele(np.zeros((360, 640, 3), np.uint8), verbose=False, imgsz=self.imgsz)

    # -- inférence --
    def observer(self, images, facteur_conf: float = 1.0) -> list:
        raise NotImplementedError

    def conclure(self, image, observations: list, zones=(), garder=None) -> Conclusion:
        """`garder(boîte) -> bool` (facultatif) : ne considérer que ces boîtes — avec une
        référence, celles dont les pixels ont changé. Le reste était déjà là."""
        raise NotImplementedError

    def personnes(self, images, imgsz: int) -> list[list[list]]:
        """Boîtes « personne » de chaque image (surveillance : modèle de base seul, image réduite)."""
        raise NotImplementedError

    def libelle(self, nom: str) -> str:
        return nom


# =============================================================================
class MoteurCare(Moteur):
    """Localiser puis nommer."""
    nom = "care"

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self.catalogue = Catalogue.depuis_config(self.d)
        self.regles = Regles.depuis_config(self.d.get("regles"))
        self.classifieur = None
        self._mots: list[str] = []

    def charger(self) -> None:
        from ultralytics import YOLOE as ModeleYoloe

        from .classifieur import Classifieur
        self._charger_custom(lambda n: self.catalogue.cle_entrainee(n) is not None)
        m = ModeleYoloe(_chemin(self.modele))
        self._mots = self.catalogue.mots()
        m.set_classes(self._mots, m.get_text_pe(self._mots))
        self._prechauffer(m)
        self.classifieur = Classifieur(self.catalogue, RACINE, marge=self.d.get("marge_recadrage", 0.15),
                                       taille=self.d.get("taille_recadrage", 224))
        self.base = m

    def observer(self, images, facteur_conf: float = 1.0) -> list[list[Candidat]]:
        """Propositions brutes de chaque image : boîtes de YOLOE (seuil très bas) et du modèle entraîné."""
        r = self.regles
        res = self.base(images, conf=r.conf_proposition, imgsz=self.imgsz, verbose=False, iou=0.6, max_det=100)
        out = [[Candidat(b, YOLOE, float(p), self.catalogue.cle_du_mot(self._mots[int(c)]))
                for c, p, b in _boites(x)] for x in res]
        if self.custom is not None:
            res = self.custom(images, conf=r.conf_entraine, imgsz=self.imgsz, verbose=False)
            for cands, x in zip(out, res):
                for c, p, b in _boites(x):
                    cle = self.catalogue.cle_entrainee(self.custom.names[int(c)])
                    if cle is not None:
                        cands.append(Candidat(b, ENTRAINE, float(p), cle))
        return out

    def _vivant_sur(self, c: Candidat, facteur: float = 1.0) -> bool:
        """Être vivant annoncé par un détecteur avec assez de confiance pour s'en passer du classifieur."""
        if self.catalogue.categorie(c.cle) != VIVANT:
            return False
        return c.conf >= (self.conf_custom if c.source == ENTRAINE else self.conf_vivant) * facteur

    def conclure(self, image, observations: list[list[Candidat]], zones=(), garder=None) -> Conclusion:
        # 1. êtres vivants : même règle qu'avant (détecteur confiant, présent sur assez d'images)
        vivants = []
        for c in voter([[c for c in obs if self._vivant_sur(c)] for obs in observations], self.ratio):
            vivants.append(Detection(c.cle, VIVANT, c.conf, c.boite, (c.source,)))
        vivants = self._sans_doublon_vivant(vivants)
        # 2. tout le reste est une boîte à nommer
        reste = suivre([[c for c in obs if not self._vivant_sur(c)] for obs in observations], self.ratio)
        if garder is not None:          # inutile de nommer ce qui n'a pas bougé depuis la référence
            reste = [c for c in reste if garder(c.boite)]
        reste += [Candidat(list(z), ZONE) for z in zones]
        candidats = preparer_candidats(reste, image.shape, self.regles)
        probas = self.classifieur.classer(image, [c.boite for c in candidats])
        detections, inconnues = trancher(candidats, probas, self.catalogue, self.regles)
        vivants += [d for d in detections if d.categorie == VIVANT
                    and all(recouvrement(d.boite, v.boite) < 0.5 for v in vivants)]
        return Conclusion(vivants, [d for d in detections if d.categorie == VALEUR], inconnues)

    @staticmethod
    def _sans_doublon_vivant(vivants: list[Detection]) -> list[Detection]:
        """Le modèle entraîné et YOLOE voient le même bébé : on garde le modèle entraîné."""
        from .geometrie import iou
        gardes: list[Detection] = []
        for d in sorted(vivants, key=lambda d: (ENTRAINE not in d.sources, -d.conf)):
            if not any(g.sources != d.sources and iou(g.boite, d.boite) >= 0.5 for g in gardes):
                gardes.append(d)
        return gardes

    def personnes(self, images, imgsz: int) -> list[list[list]]:
        idx = self._mots.index("person") if "person" in self._mots else None
        if idx is None:
            return [[] for _ in images]
        res = self.base(images, conf=self.conf_vivant, classes=[idx], verbose=False, imgsz=imgsz)
        return [x.boxes.xyxy.tolist() for x in res]


# =============================================================================
class MoteurHistorique(Moteur):
    """Moteurs d'avant la refonte (coco, yoloe, hybride) : le nom vient du détecteur."""

    def __init__(self, cfg: dict, nom: str):
        super().__init__(cfg)
        self.nom = nom
        self.coco = nom == "coco"
        if self.coco and "yoloe" in str(self.modele):
            self.modele = self.d.get("modele_coco", "yolov8m.pt")
        h = {**self.d, **self.d.get("historique", {})}     # réglages propres à ces moteurs
        self.conf_objet = h.get("confiance_objet", 0.25)
        self.zoom_zones = h.get("zoom_zones", True)
        self.prompts_vivant = h.get("prompts_vivant", PROMPTS_VIVANT)
        self.prompts_valeur = h.get("prompts_valeur", PROMPTS_VALEUR)
        self.libelles = {**LIBELLES, **h.get("libelles", {})}
        self.classes_custom = {**CLASSES_CUSTOM, **h.get("classes_custom", {})}
        self._noms, self._type, self._classes = {}, {}, None

    def libelle(self, nom: str) -> str:
        return self.libelles.get(nom, nom)

    def charger(self) -> None:
        if self.nom == "hybride":
            self._charger_custom(lambda n: n in self.classes_custom)
        if self.coco:
            from ultralytics import YOLO
            m = YOLO(_chemin(self.modele))
            self._noms = {**COCO_VIVANT, **COCO_VALEUR}
            self._type = {**{c: "vivant" for c in COCO_VIVANT}, **{c: "valeur" for c in COCO_VALEUR}}
            self._classes = list(self._noms)
        else:
            from ultralytics import YOLOE as ModeleYoloe
            m = ModeleYoloe(_chemin(self.modele))
            noms = list(self.prompts_vivant) + list(self.prompts_valeur)
            m.set_classes(noms, m.get_text_pe(noms))
            self._noms = dict(enumerate(noms))
            self._type = {i: ("vivant" if i < len(self.prompts_vivant) else "valeur") for i in range(len(noms))}
        self._prechauffer(m)
        self.base = m

    def observer(self, images, facteur_conf: float = 1.0) -> list[list[dict]]:
        """Détections déjà seuillées et fusionnées de chaque image (dictionnaires bruts)."""
        seuils = {"vivant": self.conf_vivant * facteur_conf, "valeur": self.conf_objet * facteur_conf}
        kw = {"conf": min(seuils.values()), "verbose": False, "imgsz": self.imgsz}
        if self._classes:
            kw["classes"] = self._classes
        out = []
        for x in self.base(images, **kw):
            dets = []
            for c, p, b in _boites(x):
                t = self._type.get(int(c))
                if t is not None and p >= seuils[t]:
                    dets.append({"nom": self._noms[int(c)], "type": t, "conf": float(p),
                                 "boite": [int(v) for v in b], "source": "coco" if self.coco else "yoloe"})
            out.append(dets)
        if self.custom is not None:
            res = self.custom(images, conf=self.conf_custom * facteur_conf, verbose=False, imgsz=self.imgsz)
            for dets, x in zip(out, res):
                for c, p, b in _boites(x):
                    nom = self.custom.names[int(c)]
                    t = self.classes_custom.get(nom)
                    if t is not None:
                        dets.append({"nom": nom, "type": t, "conf": float(p),
                                     "boite": [int(v) for v in b], "source": "custom"})
            out = [fusionner(dets, self.libelle) for dets in out]
        return out

    def conclure(self, image, observations: list[list[dict]], zones=(), garder=None) -> Conclusion:
        n = max(1, len(observations))
        compte: dict[str, int] = {}
        for obs in observations:
            for nom in {d["nom"] for d in obs}:
                compte[nom] = compte.get(nom, 0) + 1
        presents = {nom for nom, k in compte.items() if k / n >= self.ratio}
        c = Conclusion()
        for d in (observations[-1] if observations else []):
            if d["nom"] in presents:
                det = Detection(self.libelle(d["nom"]), d["type"], d["conf"], d["boite"], (d["source"],),
                                extra={"nom": d["nom"]})
                (c.vivants if d["type"] == "vivant" else c.objets).append(det)
        for z in zones:
            if any(recouvrement(z, d.boite) >= 0.3 for d in c.objets):
                continue
            trouve = self._zoomer(image, z) if self.zoom_zones else None
            if trouve is not None:
                c.objets.append(trouve)
            else:
                c.inconnues.append(list(z))
        return c

    def _zoomer(self, image, zone) -> Detection | None:
        """Re-détecte sur un recadrage agrandi de la zone (petits objets : clés, carte)."""
        h, w = image.shape[:2]
        x1, y1, x2, y2 = zone
        mx, my = int((x2 - x1) * 0.4) + 16, int((y2 - y1) * 0.4) + 16
        cx1, cy1, cx2, cy2 = max(0, x1 - mx), max(0, y1 - my), min(w, x2 + mx), min(h, y2 + my)
        crop = image[cy1:cy2, cx1:cx2]
        if crop.size == 0:
            return None
        dets = [d for d in self.observer([crop], facteur_conf=0.8)[0] if d["type"] == "valeur"]
        if not dets:
            return None
        d = max(dets, key=lambda d: d["conf"])
        b = [d["boite"][0] + cx1, d["boite"][1] + cy1, d["boite"][2] + cx1, d["boite"][3] + cy1]
        return Detection(self.libelle(d["nom"]), "valeur", d["conf"], b, (d["source"], "zoom"), extra={"nom": d["nom"]})

    def personnes(self, images, imgsz: int) -> list[list[list]]:
        idx = next((c for c, n in self._noms.items() if n in ("person", "personne")), None)
        if idx is None:
            return [[] for _ in images]
        res = self.base(images, conf=self.conf_vivant, classes=[idx], verbose=False, imgsz=imgsz)
        return [x.boxes.xyxy.tolist() for x in res]


MOTEURS = ("care", "hybride", "yoloe", "coco")


def creer(cfg: dict) -> Moteur:
    nom = cfg.get("detection", {}).get("moteur", "care")
    if nom == "care":
        return MoteurCare(cfg)
    if nom in MOTEURS:
        return MoteurHistorique(cfg, nom)
    raise ValueError(f"Moteur de détection inconnu : {nom!r} (choix : {', '.join(MOTEURS)})")


__all__ = ["Moteur", "MoteurCare", "MoteurHistorique", "Conclusion", "creer", "MOTEURS", "LIBELLES", "INCONNU"]
