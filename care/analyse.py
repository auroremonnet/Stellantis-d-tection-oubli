"""Analyse du journal d'essais pour la vue « Résultats » : critères, approches, jour/nuit, échecs.

Fonctions pures : elles prennent les lignes du journal (care.stockage.Journal.lire) et rendent
des dictionnaires prêts à afficher. Chaque taux est donné avec son effectif (k réussites sur n
essais) et son intervalle de confiance de Wilson à 95 % : dix essais ne prouvent pas grand-chose,
et l'afficher vaut mieux que de laisser le jury le découvrir.

Trois approches sont comparées sur les essais « vivant » :
    A1  caméras RGB seules
    A2  RGB ou thermique
    A3  RGB ou thermique ou micro
"""
from __future__ import annotations

import math

OBJECTIFS = {
    "rappel_vivant": 0.9,        # présences vivantes détectées, tous capteurs
    "rappel_objet": 0.8,         # essais « objet de valeur » où un objet est signalé
    "fausses_alertes": 0.1,      # essais sans rien à signaler qui déclenchent quand même
    "delai_alerte_s": 15.0,      # Euro NCAP 2026 : alerte dans les 15 s
}
APPROCHES = (("A1", "Caméras RGB"), ("A2", "RGB + thermique"), ("A3", "RGB + thermique + micro"))
NUIT = ("nuit", "faible lumi", "sombre")


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    """Intervalle de confiance à 95 % d'une proportion k/n (méthode de Wilson)."""
    if n <= 0:
        return None
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    demi = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return round(max(0.0, centre - demi), 3), round(min(1.0, centre + demi), 3)


def taux(k: int, n: int) -> dict:
    ic = wilson(k, n)
    return {"k": k, "n": n, "valeur": None if n == 0 else round(k / n, 3),
            "bas": None if ic is None else ic[0], "haut": None if ic is None else ic[1]}


# ---- lecture d'une ligne du journal ----------------------------------------------
def _vrai(v) -> bool:
    return v is True or str(v).strip().lower() in ("1", "true", "vrai", "oui")


def _liste(v) -> list[str]:
    if isinstance(v, list):
        return [str(x) for x in v if x]
    return [x.strip() for x in str(v or "").split(",") if x.strip()]


def _nombre(v) -> float | None:
    try:
        return None if v in (None, "") else float(v)
    except (TypeError, ValueError):
        return None


def lumiere(ligne: dict) -> str:
    """« nuit » ou « jour », d'après la variante choisie pour l'essai."""
    return "nuit" if any(m in str(ligne.get("variante", "")).lower() for m in NUIT) else "jour"


def capteurs(ligne: dict) -> dict:
    """Ce que chaque capteur a dit d'une présence vivante. None = capteur absent de l'essai."""
    th = ligne.get("vivant_thermique")
    micro_ok = str(ligne.get("audio_statut", "")).strip() == "ok"
    return {"rgb": _vrai(ligne.get("vivant_rgb")),
            "thermique": None if th in (None, "") else _vrai(th),
            "micro": bool(_liste(ligne.get("sons_audio"))) if micro_ok else None}


def vivant_detecte(ligne: dict, approche: str) -> bool | None:
    """Verdict « présence vivante » de l'approche ; None si un capteur qu'elle exige manque."""
    c = capteurs(ligne)
    if approche == "A1":
        return c["rgb"]
    if c["thermique"] is None:
        return None
    if approche == "A2":
        return c["rgb"] or c["thermique"]
    return None if c["micro"] is None else (c["rgb"] or c["thermique"] or c["micro"])


def alerte_emise(ligne: dict) -> bool:
    """Le système a-t-il signalé quelque chose (présence ou objet) pendant cet essai ?"""
    if str(ligne.get("alerte", "")).strip():
        return True
    c = capteurs(ligne)
    return bool(c["rgb"] or c["thermique"] or c["micro"] or _liste(ligne.get("objets")))


def reussi(ligne: dict) -> bool:
    """L'essai a-t-il donné le résultat attendu pour sa vérité terrain ?"""
    v = ligne.get("verite")
    if v == "vivant":
        c = capteurs(ligne)
        return bool(c["rgb"] or c["thermique"] or c["micro"])
    if v == "objet":
        return bool(_liste(ligne.get("objets")))
    return not alerte_emise(ligne)


def obtenu(ligne: dict) -> str:
    """Ce que le système a répondu, en clair."""
    c, morceaux = capteurs(ligne), []
    if c["rgb"]:
        morceaux.append("présence vue par les caméras" + (f" ({', '.join(_liste(ligne.get('classes_vivant')))})"
                                                          if _liste(ligne.get("classes_vivant")) else ""))
    if c["thermique"]:
        morceaux.append("source de chaleur")
    if c["micro"]:
        morceaux.append("son : " + ", ".join(_liste(ligne.get("sons_audio"))))
    if _liste(ligne.get("objets")):
        morceaux.append("objets : " + ", ".join(_liste(ligne.get("objets"))))
    return " · ".join(morceaux) or "rien à signaler"


ATTENDU = {"vivant": "présence vivante détectée", "objet": "objet de valeur signalé", "vide": "rien à signaler"}


# ---- agrégats ---------------------------------------------------------------------
def _approches(lignes: list[dict]) -> list[dict]:
    vivants = [l for l in lignes if l.get("verite") == "vivant"]
    sans = [l for l in lignes if l.get("verite") != "vivant"]
    out = []
    for cle, nom in APPROCHES:
        v = [x for x in (vivant_detecte(l, cle) for l in vivants) if x is not None]
        f = [x for x in (vivant_detecte(l, cle) for l in sans) if x is not None]
        out.append({"cle": cle, "nom": nom, "rappel": taux(sum(v), len(v)),
                    "fausses_presences": taux(sum(f), len(f))})
    return out


def _criteres(lignes: list[dict], objectifs: dict) -> list[dict]:
    vivants = [l for l in lignes if l.get("verite") == "vivant"]
    objets = [l for l in lignes if l.get("verite") == "objet"]
    vides = [l for l in lignes if l.get("verite") == "vide"]
    presence = taux(sum(reussi(l) for l in vivants), len(vivants))
    objet = taux(sum(reussi(l) for l in objets), len(objets))
    fausses = taux(sum(alerte_emise(l) for l in vides), len(vides))
    delais = [d for d in (_nombre(l.get("latence_alerte_s")) for l in lignes) if d is not None]
    # apport de la thermique : présences ratées par les caméras et rattrapées par la thermique
    paires = [(capteurs(l)["rgb"], capteurs(l)["thermique"]) for l in vivants]
    paires = [(r, t) for r, t in paires if t is not None]
    rattrapes = sum(1 for r, t in paires if not r and t)
    manques_rgb = sum(1 for r, _ in paires if not r)

    def etat(t, seuil, plus_grand=True):
        if t["valeur"] is None:
            return None
        return t["valeur"] >= seuil if plus_grand else t["valeur"] <= seuil

    return [
        {"cle": "presence", "libelle": "Présences vivantes détectées",
         "detail": "essais enfant et animal, tous capteurs",
         "cible": f"au moins {round(100 * objectifs['rappel_vivant'])} %", **presence,
         "atteint": etat(presence, objectifs["rappel_vivant"])},
        {"cle": "thermique", "libelle": "Apport de la thermique",
         "detail": "présences ratées par les caméras, rattrapées par la thermique",
         "cible": "au moins une présence rattrapée", "k": rattrapes, "n": manques_rgb,
         "valeur": None if not paires else (None if manques_rgb == 0 else round(rattrapes / manques_rgb, 3)),
         "bas": None, "haut": None, "essais": len(paires),
         "atteint": None if not paires or manques_rgb == 0 else rattrapes > 0},
        {"cle": "objet", "libelle": "Objets de valeur signalés", "detail": "essais avec un objet oublié",
         "cible": f"au moins {round(100 * objectifs['rappel_objet'])} %", **objet,
         "atteint": etat(objet, objectifs["rappel_objet"])},
        {"cle": "fausses", "libelle": "Fausses alertes", "detail": "essais sans rien à signaler qui déclenchent",
         "cible": f"au plus {round(100 * objectifs['fausses_alertes'])} %", **fausses,
         "atteint": etat(fausses, objectifs["fausses_alertes"], plus_grand=False)},
        {"cle": "delai", "libelle": "Délai d'alerte",
         "detail": "du départ du conducteur à l'alerte, surveillance automatique",
         "cible": f"{objectifs['delai_alerte_s']:g} s au plus", "n": len(delais), "k": None,
         "valeur": None if not delais else round(sum(delais) / len(delais), 1),
         "pire": None if not delais else round(max(delais), 1), "bas": None, "haut": None, "unite": "s",
         "atteint": None if not delais else max(delais) <= objectifs["delai_alerte_s"]},
    ]


def _par_scenario(lignes: list[dict], scenarios: list[dict], cible: int) -> list[dict]:
    noms = {s["code"]: s for s in scenarios}
    codes = list(noms) + sorted({l.get("scenario") for l in lignes} - set(noms) - {None, ""})
    out = []
    for code in codes:
        ls = [l for l in lignes if l.get("scenario") == code]
        s = noms.get(code, {})
        ligne = {"code": code, "nom": s.get("nom", code), "verite": s.get("verite", ls[0]["verite"] if ls else ""),
                 "cible": cible, **taux(sum(reussi(l) for l in ls), len(ls))}
        for lum in ("jour", "nuit"):
            sous = [l for l in ls if lumiere(l) == lum]
            ligne[lum] = taux(sum(reussi(l) for l in sous), len(sous))
        out.append(ligne)
    return out


def _par_capteur(lignes: list[dict]) -> dict:
    vivants = [l for l in lignes if l.get("verite") == "vivant"]
    sans = [l for l in lignes if l.get("verite") != "vivant"]
    out = {}
    for cle in ("rgb", "thermique", "micro"):
        v = [capteurs(l)[cle] for l in vivants if capteurs(l)[cle] is not None]
        f = [capteurs(l)[cle] for l in sans if capteurs(l)[cle] is not None]
        seul = sum(1 for l in vivants if capteurs(l)[cle] and not any(
            capteurs(l)[autre] for autre in ("rgb", "thermique", "micro") if autre != cle))
        out[cle] = {"rappel": taux(sum(v), len(v)), "fausses_presences": taux(sum(f), len(f)),
                    "seul_a_detecter": seul, "essais": len(v) + len(f)}
    objets = [l for l in lignes if l.get("verite") == "objet"]
    compte: dict[str, int] = {}
    for l in objets:
        for o in _liste(l.get("objets")):
            compte[o] = compte.get(o, 0) + 1
    out["rgb"]["objets"] = taux(sum(reussi(l) for l in objets), len(objets))
    out["rgb"]["objets_nommes"] = sorted(({"libelle": k, "essais": v} for k, v in compte.items()),
                                         key=lambda x: -x["essais"])
    return out


def _echecs(lignes: list[dict], maximum: int = 12) -> list[dict]:
    rates = [l for l in lignes if not reussi(l)]
    rates.sort(key=lambda l: str(l.get("horodatage", "")), reverse=True)
    return [{"id": l.get("id"), "horodatage": l.get("horodatage"), "scenario": l.get("scenario"),
             "variante": l.get("variante"), "attendu": ATTENDU.get(l.get("verite"), ""), "obtenu": obtenu(l),
             "commentaire": l.get("commentaire", ""), "luminosite": l.get("luminosite", "")}
            for l in rates[:maximum]]


def analyser(lignes: list[dict], scenarios: list[dict] | None = None, repetitions_cible: int = 10,
             objectifs: dict | None = None) -> dict:
    """Tout ce qu'affiche la vue « Résultats », à partir des lignes du journal."""
    objectifs = {**OBJECTIFS, **(objectifs or {})}
    dates = sorted(str(l.get("horodatage", ""))[:10] for l in lignes if l.get("horodatage"))
    par_lumiere = []
    for lum in ("jour", "nuit"):
        sous = [l for l in lignes if lumiere(l) == lum]
        par_lumiere.append({"lumiere": lum, "essais": len(sous), "criteres": _criteres(sous, objectifs),
                            "approches": _approches(sous)})
    return {
        "essais": len(lignes),
        "provenance": {"du": dates[0] if dates else None, "au": dates[-1] if dates else None,
                       "automatiques": sum(1 for l in lignes if l.get("mode") == "auto"),
                       "manuels": sum(1 for l in lignes if l.get("mode") != "auto"),
                       "jour": par_lumiere[0]["essais"], "nuit": par_lumiere[1]["essais"]},
        "objectifs": objectifs,
        "criteres": _criteres(lignes, objectifs),
        "approches": _approches(lignes),
        "par_lumiere": par_lumiere,
        "par_scenario": _par_scenario(lignes, scenarios or [], repetitions_cible),
        "capteurs": _par_capteur(lignes),
        "echecs": _echecs(lignes),
        "nb_echecs": sum(1 for l in lignes if not reussi(l)),
    }
