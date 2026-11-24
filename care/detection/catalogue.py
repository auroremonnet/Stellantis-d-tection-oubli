"""Catalogue des classes reconnues : la seule source de vérité du vocabulaire.

Chaque classe a un libellé français (sa clé), une catégorie et deux listes de mots anglais :
    mots          donnés au détecteur YOLOE, qui s'en sert pour LOCALISER des objets ;
    descriptions  données au classifieur MobileCLIP, qui s'en sert pour NOMMER un recadrage.
Le fond (siège, boucle de ceinture, câble…) est décrit lui aussi : c'est ce qui permet au
classifieur de répondre « ce n'est rien d'intéressant » plutôt que de forcer un objet.

Pour ajouter un objet sans toucher au code, voir `detection.catalogue` dans config.json :
    "catalogue": {"parapluie": {"categorie": "valeur", "mots": ["umbrella"],
                                "descriptions": ["an umbrella"]}}
"""
from __future__ import annotations

from dataclasses import dataclass

VIVANT, VALEUR, FOND = "vivant", "valeur", "_fond"
INCONNU = "objet non identifié"


@dataclass(frozen=True)
class Classe:
    cle: str                       # libellé français, affiché et journalisé
    categorie: str                 # VIVANT ou VALEUR
    mots: tuple[str, ...]          # prompts du détecteur
    descriptions: tuple[str, ...]  # descriptions du classifieur


def _c(cle, categorie, mots, descriptions) -> Classe:
    return Classe(cle, categorie, tuple(mots), tuple(descriptions))


CLASSES_DEFAUT = (
    _c("personne", VIVANT, ["person"], ["a person", "an adult sitting in a car"]),
    _c("enfant", VIVANT, ["child"], ["a child", "a toddler"]),
    _c("bébé", VIVANT, ["baby"], ["a baby", "a baby doll", "an infant in a car seat"]),
    _c("chat", VIVANT, ["cat"], ["a cat"]),
    _c("chien", VIVANT, ["dog"], ["a dog"]),
    _c("téléphone", VALEUR, ["cell phone", "smartphone", "mobile phone"],
       ["a smartphone", "a mobile phone", "the back of a smartphone"]),
    _c("clés", VALEUR, ["keys", "car key", "key"],
       ["a bunch of keys", "a car key fob", "keys on a keyring"]),
    _c("portefeuille", VALEUR, ["wallet", "purse"], ["a wallet", "a leather wallet"]),
    _c("carte bancaire", VALEUR, ["credit card", "card"], ["a credit card", "a bank card"]),
    _c("lunettes", VALEUR, ["glasses", "eyeglasses"], ["a pair of glasses", "eyeglasses", "sunglasses"]),
    _c("montre", VALEUR, ["watch", "wristwatch"], ["a wristwatch", "a smartwatch"]),
    _c("ordinateur", VALEUR, ["laptop"], ["a laptop computer"]),
    _c("tablette", VALEUR, ["tablet"], ["a tablet computer"]),
    _c("sac à main", VALEUR, ["handbag"], ["a handbag", "a purse bag"]),
    _c("sac à dos", VALEUR, ["backpack", "bag"], ["a backpack"]),
    _c("valise", VALEUR, ["suitcase"], ["a suitcase"]),
    _c("casque audio", VALEUR, ["headphones"], ["headphones"]),
)

# Mots donnés au détecteur pour qu'il propose aussi le décor : une boîte « boucle de
# ceinture » bien placée vaut mieux qu'une boucle rangée de force dans « clés ».
MOTS_FOND = ("seat belt buckle", "cable", "car seat", "box")

DESCRIPTIONS_FOND = (
    "an empty car seat", "car seat fabric", "the backrest of a car seat", "a headrest",
    "a seat belt buckle", "a seat belt", "a seat belt anchor", "a cable", "a usb hub with cables",
    "the center console of a car", "a car door panel", "a car floor mat", "a cardboard box",
    "a plastic wrapper", "a piece of paper", "a water bottle", "a jacket",
    "a blurry photo of nothing",
)

# Classes du modèle entraîné (Roboflow care-oubli) → clé du catalogue
CLASSES_ENTRAINEES = {"baby": "bébé", "keys": "clés", "wallet": "portefeuille", "card": "carte bancaire",
                      "phone": "téléphone", "glasses": "lunettes", "watch": "montre", "laptop": "ordinateur",
                      "bag": "sac à dos", "handbag": "sac à main", "person": "personne", "cat": "chat", "dog": "chien"}


class Catalogue:
    def __init__(self, classes=CLASSES_DEFAUT, mots_fond=MOTS_FOND, descriptions_fond=DESCRIPTIONS_FOND,
                 classes_entrainees=None):
        self.classes: dict[str, Classe] = {c.cle: c for c in classes}
        self.mots_fond = tuple(mots_fond)
        self.descriptions_fond = tuple(descriptions_fond)
        self.classes_entrainees = {**CLASSES_ENTRAINEES, **(classes_entrainees or {})}
        self._cle_du_mot = {m: c.cle for c in self.classes.values() for m in c.mots}

    @classmethod
    def depuis_config(cls, detection: dict | None) -> Catalogue:
        d = detection or {}
        classes = {c.cle: c for c in CLASSES_DEFAUT}
        for cle, v in (d.get("catalogue") or {}).items():
            if v is None:                       # "montre": null → classe retirée
                classes.pop(cle, None)
                continue
            base = classes.get(cle)
            classes[cle] = _c(cle, v.get("categorie", base.categorie if base else VALEUR),
                              v.get("mots", base.mots if base else [cle]),
                              v.get("descriptions", base.descriptions if base else [cle]))
        return cls(classes.values(),
                   descriptions_fond=DESCRIPTIONS_FOND + tuple(d.get("descriptions_fond", ())),
                   classes_entrainees=d.get("classes_entrainees"))

    # ---- vocabulaire du détecteur ------------------------------------------
    def mots(self) -> list[str]:
        """Tous les prompts du détecteur : vivants, objets, puis décor."""
        return [m for c in self.classes.values() for m in c.mots] + list(self.mots_fond)

    def cle_du_mot(self, mot: str) -> str | None:
        """Clé de la classe désignée par un mot du détecteur (None : décor)."""
        return self._cle_du_mot.get(mot)

    def cle_entrainee(self, nom: str) -> str | None:
        """Clé de la classe désignée par une classe du modèle entraîné."""
        cle = self.classes_entrainees.get(nom, self._cle_du_mot.get(nom, nom))
        return cle if cle in self.classes else None

    def categorie(self, cle: str | None) -> str | None:
        c = self.classes.get(cle) if cle else None
        return c.categorie if c else None

    def cles(self, categorie: str) -> list[str]:
        return [c.cle for c in self.classes.values() if c.categorie == categorie]

    # ---- vocabulaire du classifieur ----------------------------------------
    def descriptions(self) -> list[tuple[str, str]]:
        """[(clé ou FOND, description)] dans l'ordre présenté au classifieur."""
        return ([(c.cle, d) for c in self.classes.values() for d in c.descriptions]
                + [(FOND, d) for d in self.descriptions_fond])
