"""Journal des essais (CSV lisible dans Excel) et calcul des métriques."""
import csv
import os
import threading

COLONNES = ["id", "horodatage", "scenario", "variante", "verite", "vivant_rgb", "vivant_thermique",
            "classes_vivant", "objets", "cameras_vivant", "pixels_chauds", "tmax", "latence_s",
            "commentaire", "moteur", "zones_nouvelles", "reference_utilisee", "lumiere_changee",
            "mode", "alerte", "latence_alerte_s"]


def _bool(v):
    return None if v in ("", None) else str(v) in ("1", "True", "true")


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
        return lignes

    def ajouter(self, ligne):
        with self._lock, open(self.chemin, "a", newline="", encoding="utf-8-sig") as fh:
            row = {k: ligne.get(k, "") for k in COLONNES}
            for k in ("vivant_rgb", "vivant_thermique", "reference_utilisee", "lumiere_changee"):
                row[k] = "" if row[k] in ("", None) else int(bool(row[k]))
            for k in ("classes_vivant", "objets", "cameras_vivant"):
                if isinstance(row[k], list):
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
    return res
