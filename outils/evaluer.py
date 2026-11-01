"""Compare les moteurs de détection sur le même jeu de test annoté (export YOLO).

    python outils/evaluer.py --donnees datasets/care-oubli-v1/data.yaml
    python outils/evaluer.py --donnees ... --moteurs yoloe custom hybride --split test

Pour chaque moteur : précision / rappel / F1 par classe (IoU >= 0,5), taux d'alerte
correcte par image (l'image contenait-elle un objet évalué, et l'a-t-on signalé ?) et
latence par image. Écrit un rapport Markdown + JSON dans rapports/ — directement
réutilisable dans le livrable (tableau « YOLOE vs modèle entraîné vs hybride »).

Moteurs :
    coco, yoloe, hybride   le Detecteur du banc, configuré par config.json
    custom                 le modèle entraîné seul (detection.modele_custom)
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import cv2

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

from care.detecteur import LIBELLES, Detecteur  # noqa: E402
from care.metriques_detection import Evaluation, canonique  # noqa: E402

CLASSES_CARE = ("bébé", "clés", "portefeuille", "carte bancaire")
EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def lire_jeu(data_yaml: Path, split: str):
    """Itère sur (chemin image, [(libellé, boîte xyxy pixels)]) d'un export YOLO."""
    import yaml
    cfg = yaml.safe_load(data_yaml.read_text(encoding="utf-8"))
    noms = cfg["names"]
    noms = noms if isinstance(noms, dict) else dict(enumerate(noms))
    racine = Path(cfg.get("path") or data_yaml.parent)
    if not racine.is_absolute():
        racine = (data_yaml.parent / racine).resolve()
    rel = cfg.get(split) or cfg.get("val")
    if rel is None:
        sys.exit(f"Pas de split « {split} » dans {data_yaml}")
    dossier = (racine / rel).resolve()
    for img in sorted(p for p in dossier.rglob("*") if p.suffix.lower() in EXTENSIONS):
        yield img, chemin_label(img), noms


def chemin_label(img):
    """Convention YOLO : …/images/x.jpg → …/labels/x.txt (dernier dossier « images »).
    Indépendant du séparateur, donc valable sous Windows comme sous Linux."""
    parties = list(img.parts)
    for i in range(len(parties) - 2, -1, -1):
        if parties[i] == "images":
            parties[i] = "labels"
            return type(img)(*parties).with_suffix(".txt")
    return img.with_suffix(".txt")


def verites(lbl: Path, noms: dict, w: int, h: int):
    out = []
    if lbl.exists():
        for ligne in lbl.read_text(encoding="utf-8").split("\n"):
            v = ligne.split()
            if len(v) < 5:
                continue
            c, cx, cy, bw, bh = int(v[0]), *map(float, v[1:5])
            nom = noms.get(c, str(c))
            boite = [(cx - bw / 2) * w, (cy - bh / 2) * h, (cx + bw / 2) * w, (cy + bh / 2) * h]
            out.append((canonique(LIBELLES.get(nom, nom)), boite))
    return out


class MoteurCustom:
    """Le modèle entraîné seul, sans YOLOE (pour isoler son apport)."""

    def __init__(self, cfg):
        from ultralytics import YOLO
        d = cfg.get("detection", {})
        chemin = RACINE / d.get("modele_custom", "modeles/care-v1.pt")
        if not chemin.exists():
            raise FileNotFoundError(f"{chemin} introuvable : entraîner d'abord (entrainement/entrainer.py)")
        self.m = YOLO(str(chemin))
        self.conf = d.get("confiance_custom", 0.35)
        self.imgsz = d.get("imgsz", 640)

    def predire(self, img):
        r = self.m(img, conf=self.conf, imgsz=self.imgsz, verbose=False)[0]
        return [(LIBELLES.get(self.m.names[int(c)], self.m.names[int(c)]), float(p), b)
                for c, p, b in zip(r.boxes.cls.tolist(), r.boxes.conf.tolist(), r.boxes.xyxy.tolist())]


class MoteurBanc:
    def __init__(self, cfg, moteur):
        cfg = {**cfg, "detection": {**cfg.get("detection", {}), "moteur": moteur}}
        self.d = Detecteur(cfg)
        t0 = time.time()
        while not self.d.pret and not self.d.erreur and time.time() - t0 < 900:
            time.sleep(0.5)
        if not self.d.pret:
            raise RuntimeError(self.d.erreur or "chargement trop long")
        if self.d.avertissement:
            print(f"  ⚠ {self.d.avertissement}")

    def predire(self, img):
        return [(self.d.libelle(x["nom"]), x["conf"], x["boite"]) for x in self.d.detecter([img])[0]]


def evaluer(moteur, jeu, classes, seuil_iou):
    ev = Evaluation(classes=classes, seuil_iou=seuil_iou)
    for img_path, lbl, noms in jeu:
        img = cv2.imread(str(img_path))
        if img is None:
            continue
        h, w = img.shape[:2]
        t0 = time.perf_counter()
        preds = moteur.predire(img)
        ev.ajouter(verites(lbl, noms, w, h), preds, time.perf_counter() - t0)
    return ev


def _p(v):
    return "—" if v is None else f"{100 * v:.0f} %"


def rapport_markdown(resultats: dict, classes, meta: dict) -> str:
    lignes = [f"# Évaluation des moteurs de détection — {meta['date']}", "",
              f"Jeu : `{meta['donnees']}` · split **{meta['split']}** · {meta['images']} images · "
              f"IoU ≥ {meta['seuil_iou']}", "",
              "## Vue d'ensemble", "",
              "| Moteur | Précision | Rappel | F1 | Alerte correcte (image) | Fausses alertes | Latence moy. |",
              "|---|---|---|---|---|---|---|"]
    for nom, r in resultats.items():
        if "erreur" in r:
            lignes.append(f"| {nom} | erreur : {r['erreur']} |||||| ")
            continue
        g, a = r["global"], r["alerte_par_image"]
        lignes.append(f"| **{nom}** | {_p(g['precision'])} | {_p(g['rappel'])} | {_p(g['f1'])} | "
                      f"{_p(a['rappel'])} | {a['FP']} | {r['latence_moyenne_s']} s |")
    lignes += ["", "## Par classe (rappel / précision)", "",
               "| Moteur | " + " | ".join(classes) + " |", "|---|" + "---|" * len(classes)]
    for nom, r in resultats.items():
        if "erreur" in r:
            continue
        cells = [f"{_p(r['par_classe'][c]['rappel'])} / {_p(r['par_classe'][c]['precision'])}" for c in classes]
        lignes.append(f"| {nom} | " + " | ".join(cells) + " |")
    lignes += ["", "*Rappel : part des objets présents qui sont trouvés. Précision : part des "
               "détections qui sont justes. « Alerte correcte » : images contenant un objet évalué "
               "pour lesquelles au moins une détection a été produite.*", ""]
    return "\n".join(lignes)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--donnees", type=Path, required=True, help="data.yaml de l'export YOLO")
    ap.add_argument("--split", default="test")
    ap.add_argument("--moteurs", nargs="+", default=["yoloe", "custom", "hybride"],
                    choices=["coco", "yoloe", "custom", "hybride"])
    ap.add_argument("--classes", nargs="+", default=list(CLASSES_CARE), help="libellés français évalués")
    ap.add_argument("--config", type=Path, default=RACINE / "config.json")
    ap.add_argument("--seuil-iou", type=float, default=0.5)
    ap.add_argument("--max-images", type=int, default=None)
    ap.add_argument("--sortie", type=Path, default=RACINE / "rapports")
    a = ap.parse_args(argv)

    cfg = json.loads(a.config.read_text(encoding="utf-8"))
    jeu = list(lire_jeu(a.donnees.resolve(), a.split))[: a.max_images]
    if not jeu:
        sys.exit("Aucune image trouvée.")
    classes = tuple(canonique(c) for c in a.classes)
    print(f"{len(jeu)} images · classes évaluées : {', '.join(classes)}")

    resultats = {}
    for nom in a.moteurs:
        print(f"→ {nom}")
        try:
            moteur = MoteurCustom(cfg) if nom == "custom" else MoteurBanc(cfg, nom)
            resultats[nom] = evaluer(moteur, jeu, classes, a.seuil_iou).en_dict()
            g = resultats[nom]["global"]
            print(f"  précision {_p(g['precision'])} · rappel {_p(g['rappel'])} · F1 {_p(g['f1'])}")
        except Exception as e:  # noqa: BLE001 — un moteur indisponible n'empêche pas les autres
            resultats[nom] = {"erreur": str(e)}
            print(f"  ✖ {e}")

    meta = {"date": datetime.now().strftime("%Y-%m-%d %H:%M"), "donnees": str(a.donnees),
            "split": a.split, "images": len(jeu), "seuil_iou": a.seuil_iou}
    a.sortie.mkdir(parents=True, exist_ok=True)
    base = a.sortie / f"evaluation-{datetime.now():%Y%m%d-%H%M%S}"
    base.with_suffix(".json").write_text(json.dumps({"meta": meta, "resultats": resultats},
                                                    ensure_ascii=False, indent=2), encoding="utf-8")
    base.with_suffix(".md").write_text(rapport_markdown(resultats, classes, meta), encoding="utf-8")
    print(f"\nRapport : {base.with_suffix('.md')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
