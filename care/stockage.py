"""Journal des essais (CSV lisible dans Excel) et calcul des métriques."""
import csv
import os
import threading

from .metriques_detection import canonique

COLONNES = ["id", "horodatage", "scenario", "variante", "verite", "vivant_rgb", "vivant_thermique",
            "classes_vivant", "objets", "cameras_vivant", "pixels_chauds", "tmax", "latence_s",
            "commentaire", "moteur", "zones_nouvelles", "reference_utilisee", "lumiere_changee",
            "mode", "alerte", "latence_alerte_s", "objets_poses"]

OBJECTIF_NCAP_S = 15  # Euro NCAP 2026 : premier avertissement < 15 s après le départ

# Un objet posé est « retrouvé » si l'une de ces détections apparaît (après synonymes) :
# le banc pose « un sac », le détecteur répond « sac à main » ou « sac à dos ».
FAMILLES = {"sac": {"sac", "sac à main", "sac à dos"}, "poupon": {"bébé", "personne"}}
NON_IDENTIFIABLES = {"autre"}  # pas de libellé détecteur correspondant : seul le signalement compte
CATEGORIE = {"objet": "valeur", "vide": "anodin", "vivant": "vivant"}


def _bool(v):
    return None if v in ("", None) else str(v) in ("1", "True", "true")


def _liste(v):
    """« téléphone, clés » (CSV) ou ["téléphone", "clés"] → liste nettoyée."""
    if isinstance(v, (list, tuple)):
        return [str(x).strip() for x in v if str(x).strip()]
    return [x.strip() for x in str(v or "").split(",") if x.strip()]


def _float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


class Journal:
    def __init__(self, chemin):
        self.chemin = chemin
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(chemin), exist_ok=True)
        if not os.path.exists(chemin):
            with open(chemin, "w", newline="", encoding="utf-8-sig") as fh:
                csv.writer(fh, delimiter=";").writerow(COLONNES)
        else:
            self._migrer()

    def _migrer(self):
        """Ajoute les colonnes manquantes à un CSV écrit par une version précédente."""
        with open(self.chemin, encoding="utf-8-sig") as fh:
            r = csv.reader(fh, delimiter=";")
            entete = next(r, None)
            lignes = list(r)
        if entete is None or entete == COLONNES:
            return
        with open(self.chemin, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.DictWriter(fh, fieldnames=COLONNES, delimiter=";")
            w.writeheader()
            for l in lignes:
                w.writerow({k: v for k, v in zip(entete, l) if k in COLONNES})

    def lire(self):
        with self._lock, open(self.chemin, encoding="utf-8-sig") as fh:
            lignes = list(csv.DictReader(fh, delimiter=";"))
        for l in lignes:
            for k in COLONNES:
                l.setdefault(k, "")
            l["vivant_rgb"] = _bool(l["vivant_rgb"])
            l["vivant_thermique"] = _bool(l["vivant_thermique"])
            l["reference_utilisee"] = _bool(l["reference_utilisee"])
            l["lumiere_changee"] = _bool(l["lumiere_changee"])
            l.update(evaluer(l))
            l["niveau_alerte"] = niveau_alerte(l)
        return lignes

    def ajouter(self, ligne):
        with self._lock, open(self.chemin, "a", newline="", encoding="utf-8-sig") as fh:
            row = {k: ligne.get(k, "") for k in COLONNES}
            for k in ("vivant_rgb", "vivant_thermique", "reference_utilisee", "lumiere_changee"):
                row[k] = "" if row[k] in ("", None) else int(bool(row[k]))
            for k in ("classes_vivant", "objets", "cameras_vivant", "objets_poses"):
                if isinstance(row[k], (list, tuple)):
                    row[k] = ", ".join(row[k])
            row = {k: ("" if v is None else v) for k, v in row.items()}
            csv.DictWriter(fh, fieldnames=COLONNES, delimiter=";").writerow(row)

    def supprimer(self, eid):
        with self._lock:
            with open(self.chemin, encoding="utf-8-sig") as fh:
                lignes = [l for l in csv.DictReader(fh, delimiter=";") if l["id"] != eid]
            with open(self.chemin, "w", newline="", encoding="utf-8-sig") as fh:
                w = csv.DictWriter(fh, fieldnames=COLONNES, delimiter=";")
                w.writeheader()
                w.writerows(lignes)


def _classe(verite, vivant):
    v = verite == "vivant"
    return {(True, True): "VP", (True, False): "FN", (False, True): "FP", (False, False): "VN"}[(v, bool(vivant))]


def evaluer(l):
    """Résultat de l'essai pour chaque approche."""
    a1 = bool(l["vivant_rgb"])
    out = {"A1": _classe(l["verite"], a1), "A2": None, "decision_A1": _decision(a1, l["objets"])}
    if l["vivant_thermique"] is not None:
        a2 = a1 or bool(l["vivant_thermique"])
        out["A2"] = _classe(l["verite"], a2)
        out["decision_A2"] = _decision(a2, l["objets"])
    return out


def _decision(vivant, objets):
    return "CRITIQUE" if vivant else ("ALERTE" if objets else "RAS")


def _ratio(a, b):
    return None if b == 0 else round(a / b, 3)


def metriques(lignes):
    res = {"total": len(lignes), "approches": {}, "scenarios": [], "objets": None}
    for app in ("A1", "A2"):
        r = [l[app] for l in lignes if l.get(app)]
        lat = [float(l["latence_s"]) for l in lignes if l.get(app) and l["latence_s"]]
        vp, fn, fp, vn = (r.count(x) for x in ("VP", "FN", "FP", "VN"))
        res["approches"][app] = {
            "n": len(r), "VP": vp, "FN": fn, "FP": fp, "VN": vn,
            "rappel": _ratio(vp, vp + fn), "taux_fp": _ratio(fp, fp + vn),
            "precision": _ratio(vp, vp + fp),
            "latence": round(sum(lat) / len(lat), 2) if lat else None,
        }
    # Rappel par scénario (scénarios avec présence vivante uniquement)
    for sc in sorted({l["scenario"] for l in lignes}):
        ls = [l for l in lignes if l["scenario"] == sc]
        ligne = {"scenario": sc, "n": len(ls), "verite": ls[0]["verite"]}
        for app in ("A1", "A2"):
            r = [l[app] for l in ls if l.get(app)]
            if ls[0]["verite"] == "vivant":
                ligne[app] = _ratio(r.count("VP"), len(r))
            else:  # pour les scènes sans vivant : taux de bonne non-alerte
                ligne[app] = _ratio(r.count("VN"), len(r))
            ligne[app + "_n"] = len(r)
        res["scenarios"].append(ligne)
    obj = [l for l in lignes if l["verite"] == "objet"]
    if obj:
        res["objets"] = _ratio(sum(1 for l in obj if l["objets"]), len(obj))
    res["thermique_mesuree"] = any(l.get("vivant_thermique") is not None for l in lignes)
    res["indicateurs"] = indicateurs(lignes)
    res["par_objet"] = detection_par_objet(lignes)
    return res


# ---- Indicateurs clés du dashboard ------------------------------------------------
def niveau_alerte(l):
    """Niveau d'alerte de l'essai : "critique", "objet" ou None.

    Les essais écrits avant la colonne `alerte` (colonne `mode` vide) n'ont pas de niveau
    enregistré : on le déduit de leur décision, sinon ils compteraient à tort comme
    « aucune alerte » (faux 0 % d'objets détectés).
    """
    if l.get("mode"):
        return l.get("alerte") or None
    dec = l.get("decision_A2") or l.get("decision_A1")
    if dec is None:
        dec = evaluer(l).get("decision_A2") or evaluer(l)["decision_A1"]
    return {"CRITIQUE": "critique", "ALERTE": "objet"}.get(dec)


def _niveau(l):
    return l["niveau_alerte"] if "niveau_alerte" in l else niveau_alerte(l)


def indicateurs(lignes):
    """Les 4 chiffres du rapport. `taux` vaut None (affiché « — ») tant qu'il n'y a pas d'essai."""
    # 1. Présences vivantes : meilleure approche disponible essai par essai (A2 si thermique)
    viv = [l for l in lignes if l["verite"] == "vivant"]
    vus = [(l.get("A2") or l["A1"]) == "VP" for l in viv]
    avec_th = sum(1 for l in viv if l.get("A2"))
    approche = None if not viv else "A2" if avec_th == len(viv) else "A1" if avec_th == 0 else "A1/A2"
    # 2. Objets oubliés : l'essai a produit une alerte « objet »
    obj = [l for l in lignes if l["verite"] == "objet"]
    obj_ok = sum(1 for l in obj if _niveau(l) == "objet")
    # 3. Fausses alertes : habitacle sans risque, mais une alerte (quel que soit le niveau)
    vide = [l for l in lignes if l["verite"] == "vide"]
    fa = sum(1 for l in vide if _niveau(l))
    # 4. Latence départ → verdict, essais automatiques uniquement
    lat = [v for l in lignes if l.get("mode") == "auto"
           and (v := _float(l.get("latence_alerte_s"))) is not None]
    pire = max(lat) if lat else None
    return {
        "vivant": {"n": len(viv), "detectes": sum(vus), "taux": _ratio(sum(vus), len(viv)),
                   "approche": approche},
        "objets": {"n": len(obj), "detectes": obj_ok, "taux": _ratio(obj_ok, len(obj))},
        "fausses_alertes": {"n": len(vide), "alertes": fa, "taux": _ratio(fa, len(vide))},
        "latence": {"n": len(lat), "moyenne": round(sum(lat) / len(lat), 2) if lat else None,
                    "pire": pire, "objectif_s": OBJECTIF_NCAP_S,
                    "conforme": None if pire is None else pire <= OBJECTIF_NCAP_S},
    }


def retrouve(objet_pose, detections):
    """L'objet posé figure-t-il parmi les détections (synonymes et familles compris) ?"""
    c = canonique(objet_pose)
    acceptes = {canonique(x) for x in FAMILLES.get(c, {c})}
    return any(canonique(d) in acceptes for d in detections)


def detection_par_objet(lignes):
    """Une entrée par (objet posé, catégorie) : identifié = retrouvé nommément dans les
    détections ; signalé = l'essai a produit une alerte (y compris « objet non identifié »)."""
    acc = {}
    for l in lignes:
        poses = _liste(l.get("objets_poses"))
        if not poses:
            continue
        detections = _liste(l.get("objets")) + _liste(l.get("classes_vivant"))
        alerte = bool(_niveau(l))
        cat = CATEGORIE.get(l["verite"], l["verite"])
        for o in dict.fromkeys(poses):
            a = acc.setdefault((o, cat), {"objet": o, "categorie": cat, "n": 0, "identifies": 0, "signales": 0})
            a["n"] += 1
            a["identifies"] += retrouve(o, detections)
            a["signales"] += alerte
    out = []
    for a in acc.values():
        identifiable = a["objet"] not in NON_IDENTIFIABLES
        a["identifiable"] = identifiable
        a["taux"] = _ratio(a["identifies"], a["n"]) if identifiable else None
        a["taux_signale"] = _ratio(a["signales"], a["n"])
        out.append(a)
    ordre = {"valeur": 0, "anodin": 1, "vivant": 2}
    return sorted(out, key=lambda a: (ordre.get(a["categorie"], 9), -a["n"], a["objet"]))
