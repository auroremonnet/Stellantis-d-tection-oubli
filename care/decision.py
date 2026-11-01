"""Décision d'alerte à partir du résultat d'une analyse (Detecteur.analyser).

Règle unique, utilisée par l'essai manuel ET par la surveillance automatique :

    CRITIQUE  un être vivant à protéger est détecté : enfant, bébé, chat, chien
              (RGB), ou source de chaleur vivante (thermique, fusion « OU » = A2).
              Si l'habitacle est censé être vide (surveillance, après le départ du
              conducteur), une « personne » détectée est aussi critique : c'est
              souvent un enfant que le modèle nomme « personne ».
    OBJET     un objet de valeur surveillé (ou une zone nouvelle non identifiée)
              est vu alors qu'aucun adulte n'est à bord.
    rien      sinon. En essai manuel, un adulte présent annule l'alerte objet
              (règle d'origine des alertes ntfy : quelqu'un est là, rien n'est oublié).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime

VIVANTS_A_PROTEGER = frozenset({"enfant", "bébé", "chat", "chien"})
PERSONNE = "personne"
PRESENCE_HUMAINE = "présence humaine"  # « Personne détectée » se lirait « personne n'est détecté »
INCONNU = "objet non identifié"

# Accord grammatical des libellés français (pour des messages lisibles sur le téléphone)
FEMININS = frozenset({"valise", "carte bancaire", "tablette", "montre", "clés", "clés de voiture",
                      "lunettes", "carte", "personne", "présence humaine", "source de chaleur"})
PLURIELS = frozenset({"clés", "clés de voiture", "lunettes"})


@dataclass(frozen=True)
class Alerte:
    niveau: str                          # "critique" | "objet"
    titre: str
    message: str
    elements: tuple[str, ...] = field(default_factory=tuple)
    priorite: str = "high"               # priorité ntfy : "urgent" pour le critique
    tags: str = "rotating_light,oncoming_automobile"

    @property
    def resume(self) -> str:
        return ", ".join(self.elements)

    def en_dict(self) -> dict:
        d = asdict(self)
        d["elements"] = list(self.elements)
        return d


def _liste(noms: list[str]) -> str:
    return noms[0] if len(noms) == 1 else ", ".join(noms[:-1]) + " et " + noms[-1]


def accorder(radical: str, noms: list[str]) -> str:
    """Accorde un participe passé avec les noms listés : accorder("oubli", ["clés"]) → « oubliées »."""
    pluriel = len(noms) > 1 or (len(noms) == 1 and noms[0] in PLURIELS)
    feminin = all(n in FEMININS for n in noms)
    return radical + ("ée" if feminin else "é") + ("s" if pluriel else "")


def _majuscule(s: str) -> str:
    return s[:1].upper() + s[1:]


def _liste_champ(resultat: dict, cle: str) -> list[str]:
    """Accepte une liste (résultat brut) ou une chaîne « a, b » (ligne du journal CSV)."""
    v = resultat.get(cle) or []
    if isinstance(v, str):
        v = [x.strip() for x in v.split(",")]
    return [x for x in v if x]


def decider(resultat: dict, *, habitacle_vide_attendu: bool,
            objets_surveilles: set[str] | frozenset[str] | None = None,
            alerter_inconnu: bool = True, maintenant: datetime | None = None) -> Alerte | None:
    """Renvoie l'alerte à émettre, ou None. `objets_surveilles=None` : tous les objets."""
    heure = (maintenant or datetime.now()).strftime("%H:%M:%S")
    vivants = _liste_champ(resultat, "classes_vivant")
    objets = _liste_champ(resultat, "objets")
    adulte = PERSONNE in vivants

    a_proteger = sorted(v for v in vivants if v in VIVANTS_A_PROTEGER)
    if adulte and habitacle_vide_attendu:
        a_proteger.append(PRESENCE_HUMAINE)
    if resultat.get("vivant_thermique"):
        a_proteger.append("source de chaleur")
    if a_proteger:
        a_proteger = list(dict.fromkeys(a_proteger))  # sans doublon, ordre conservé
        return Alerte(
            niveau="critique",
            titre="CARE · URGENT · Présence dans le véhicule",
            message=f"{_majuscule(_liste(a_proteger))} {accorder('détect', a_proteger)} "
                    f"dans le véhicule à {heure}. "
                    "Vérifiez immédiatement les sièges.",
            elements=tuple(a_proteger), priorite="urgent", tags="warning,baby,oncoming_automobile")

    if adulte:  # quelqu'un est à bord : rien n'est oublié
        return None
    retenus = [o for o in objets
               if (o == INCONNU and alerter_inconnu)
               or (o != INCONNU and (objets_surveilles is None or o in objets_surveilles))]
    if not retenus:
        return None
    retenus = list(dict.fromkeys(retenus))
    return Alerte(
        niveau="objet",
        titre="CARE · Objet oublié",
        message=f"{_majuscule(_liste(retenus))} {accorder('oubli', retenus)} dans le véhicule à {heure}",
        elements=tuple(retenus))
