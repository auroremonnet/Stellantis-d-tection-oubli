"""Modèle de la version idéale (simulation) : ce que chaque capteur est censé donner, par scénario.

Ce ne sont pas des mesures. Les taux traduisent le comportement attendu du système et ses limites
connues : un enfant caché n'est trouvé que par la thermique et le micro, les caméras ne voient
presque rien de nuit, les essais avec animal se font sans thermique (autre véhicule), une source
chaude inerte trompe parfois la thermique.

Pour chaque scénario et chaque lumière : probabilité que les caméras voient la présence (rgb),
que la thermique la voie (th, None = pas de thermique pour ce scénario), que le micro reconnaisse
un son (son), que l'objet soit signalé (objet), ou qu'une fausse alerte parte (faux_*).
"""
from __future__ import annotations

MODELE = {
    "S1": {"jour": {"rgb": 0.88, "th": 1.0, "son": 0.5}, "nuit": {"rgb": 0.3, "th": 1.0, "son": 0.5}},
    "S2": {"jour": {"rgb": 0.0, "th": 0.9, "son": 0.75}, "nuit": {"rgb": 0.0, "th": 0.9, "son": 0.75}},
    "S3": {"jour": {"rgb": 0.91, "th": None, "son": 0.35}, "nuit": {"rgb": 0.2, "th": None, "son": 0.35}},
    "S4": {"jour": {"rgb": 0.75, "th": None, "son": 0.35}, "nuit": {"rgb": 0.1, "th": None, "son": 0.35}},
    "S5": {"jour": {"objet": 0.94}, "nuit": {"objet": 0.17}},
    "S6": {"jour": {"faux_objet": 0.08}, "nuit": {"faux_objet": 0.0}},
    "S7": {"jour": {}, "nuit": {}},
    "S8": {"jour": {"faux_th": 0.25}, "nuit": {"faux_th": 0.25}},
}
SONS = {"S1": "pleurs", "S2": "pleurs", "S3": "aboiement", "S4": "aboiement"}


class Quotas:
    """Tirages à proportion exacte : sur n essais à probabilité p, environ n × p réussites, sans hasard.
    Un petit échantillon tiré au hasard donnerait des taux qui ne ressemblent pas au modèle."""

    def __init__(self):
        self._reste: dict[tuple, float] = {}

    def tirer(self, cle: tuple, p: float | None) -> bool:
        if not p:
            return False
        r = self._reste.get(cle, 0.5) + p
        self._reste[cle] = r - 1 if r >= 1 else r
        return r >= 1


def lumiere(variante: str) -> str:
    return "nuit" if any(m in str(variante or "").lower() for m in ("nuit", "faible lumi", "sombre")) else "jour"


def simuler(quotas: Quotas, scenario: str, variante: str, objets_photo: list[str] | None = None) -> dict | None:
    """Résultat simulé d'un essai de ce scénario ; None si le scénario n'est pas dans le modèle."""
    if scenario not in MODELE:
        return None
    lum = lumiere(variante)
    m = MODELE[scenario][lum]

    def t(nom):
        return quotas.tirer((scenario, lum, nom), m.get(nom))

    sans_thermique = "th" in m and m["th"] is None
    son = SONS.get(scenario) if t("son") else None
    objets = list(objets_photo or ["sac à main"]) if t("objet") else []
    if t("faux_objet"):
        objets = ["objet non identifié"]
    return {"vivant_rgb": t("rgb"), "vivant_thermique": None if sans_thermique else (t("th") or t("faux_th")),
            "objets": objets, "son": son, "nuit": lum == "nuit"}
