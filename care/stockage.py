"""Journal des essais (CSV lisible dans Excel) et calcul des métriques."""
import csv
import os
import threading
import tempfile

COLONNES = ["id", "horodatage", "scenario", "variante", "verite", "vivant_rgb", "vivant_thermique",
            "classes_vivant", "objets", "cameras_vivant", "pixels_chauds", "tmax", "latence_s",
             "commentaire", "audio_statut", "sons_audio", "pleurs_score", "aboiement_score",
             "miaulement_score", "son_general", "score_general", "erreur_audio"]


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
            self._migrer_colonnes()
        with open(self.chemin, newline="", encoding="utf-8-sig") as fh:
            self.colonnes = next(csv.reader(fh, delimiter=";"))

    def _migrer_colonnes(self):
        """Ajoute les champs audio aux anciens journaux sans perdre leurs lignes."""
        with open(self.chemin, newline="", encoding="utf-8-sig") as fh:
            lecteur = csv.DictReader(fh, delimiter=";")
            anciennes = lecteur.fieldnames or []
            if all(c in anciennes for c in COLONNES):
                return
            lignes = list(lecteur)
        colonnes = list(dict.fromkeys(anciennes + COLONNES))
        fd, temporaire = tempfile.mkstemp(dir=os.path.dirname(self.chemin), suffix=".csv")
        try:
            with os.fdopen(fd, "w", newline="", encoding="utf-8-sig") as fh:
                writer = csv.DictWriter(fh, fieldnames=colonnes, delimiter=";")
                writer.writeheader()
                writer.writerows(lignes)
            os.replace(temporaire, self.chemin)
        finally:
            if os.path.exists(temporaire):
                os.remove(temporaire)

    def lire(self):
        with self._lock, open(self.chemin, encoding="utf-8-sig") as fh:
            lignes = list(csv.DictReader(fh, delimiter=";"))
        for l in lignes:
            l["vivant_rgb"] = _bool(l["vivant_rgb"])
            l["vivant_thermique"] = _bool(l["vivant_thermique"])
            l.update(evaluer(l))
        return lignes

    def ajouter(self, ligne):
        with self._lock, open(self.chemin, "a", newline="", encoding="utf-8-sig") as fh:
            row = {k: ligne.get(k, "") for k in self.colonnes}
            for k in ("vivant_rgb", "vivant_thermique"):
                row[k] = "" if row[k] in ("", None) else int(bool(row[k]))
            for k in ("classes_vivant", "objets", "cameras_vivant", "sons_audio"):
                if isinstance(row[k], list):
                    row[k] = ", ".join(row[k])
            if row["pixels_chauds"] is None:
                row["pixels_chauds"] = ""
            if row["tmax"] is None:
                row["tmax"] = ""
            if row["score_general"] is None:
                row["score_general"] = ""
            csv.DictWriter(fh, fieldnames=self.colonnes, delimiter=";").writerow(row)

    def supprimer(self, eid):
        with self._lock:
            with open(self.chemin, encoding="utf-8-sig") as fh:
                lignes = [l for l in csv.DictReader(fh, delimiter=";") if l["id"] != eid]
            with open(self.chemin, "w", newline="", encoding="utf-8-sig") as fh:
                w = csv.DictWriter(fh, fieldnames=self.colonnes, delimiter=";")
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
