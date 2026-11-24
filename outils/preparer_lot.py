"""Prépare un lot d'images de la voiture pour Roboflow, PRÉ-ANNOTÉ par le modèle actuel.

    python outils/preparer_lot.py                      # toutes les sessions de data/essais/collecte
    python outils/preparer_lot.py --session 20261107   # une seule session
    python outils/preparer_lot.py --brutes             # + images brutes des essais (data/essais/brutes)
    python outils/preparer_lot.py --sans-preannotation # images seules (pas besoin d'ultralytics)

Produit datasets/lot-<date>/ (et le .zip) au format YOLO : images/, labels/, data.yaml.
Dans Roboflow (projet care-oubli) : Upload → glisser le dossier ou le zip → les boîtes
proposées par le modèle apparaissent, il ne reste qu'à les CORRIGER (bien plus rapide que
de tout dessiner). Une image sans boîte est un exemple négatif : la garder, c'est ce qui
apprend au modèle que la boucle de ceinture n'est pas une clé.

Les noms de classe sont ceux de la v1 (baby, card, keys, wallet), plus phone et glasses
pour la v2 : Roboflow les fusionne avec les classes existantes du projet.
"""
from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

CLASSES = ["baby", "card", "keys", "wallet", "phone", "glasses"]   # v1 + téléphone et lunettes (v2)
# nom vu par le détecteur → classe du dataset. Libellés français : moteur « care » ;
# noms anglais : moteurs historiques (YOLOE à prompts, modèle entraîné).
CORRESPONDANCE = {"bébé": "baby", "enfant": "baby", "clés": "keys", "portefeuille": "wallet",
                  "carte bancaire": "card", "téléphone": "phone", "lunettes": "glasses",
                  "baby": "baby", "child": "baby", "keys": "keys", "car key": "keys",
                  "wallet": "wallet", "credit card": "card", "card": "card", "cell phone": "phone",
                  "glasses": "glasses"}
EXT = (".jpg", ".jpeg", ".png")


def images_a_traiter(a) -> list[tuple[Path, str]]:
    """[(chemin, session)] — la session sert de préfixe de nom et de lot Roboflow."""
    out = []
    collecte = RACINE / "data" / "essais" / "collecte"
    if collecte.is_dir():
        for s in sorted(p for p in collecte.iterdir() if p.is_dir()):
            if a.session and s.name not in a.session:
                continue
            out += [(p, s.name) for p in sorted(s.rglob("*")) if p.suffix.lower() in EXT]
    if a.brutes:
        brutes = RACINE / "data" / "essais" / "brutes"
        if brutes.is_dir():
            out += [(p, "essais") for p in sorted(brutes.iterdir()) if p.suffix.lower() in EXT]
    return out


def charger_detecteur(conf_cfg):
    from care.detecteur import Detecteur
    d = Detecteur(conf_cfg)
    t0 = time.time()
    while not d.pret and not d.erreur and time.time() - t0 < 300:
        time.sleep(0.5)
    if not d.pret:
        sys.exit(f"Modèle non chargé : {d.erreur or 'délai dépassé'}")
    if d.avertissement:
        print(f"  ⚠ {d.avertissement}")
    return d


def yolo(boite, w, h) -> str:
    x1, y1, x2, y2 = boite
    x1, x2 = max(0, x1), min(w, x2)
    y1, y2 = max(0, y1), min(h, y2)
    return f"{(x1 + x2) / 2 / w:.6f} {(y1 + y2) / 2 / h:.6f} {(x2 - x1) / w:.6f} {(y2 - y1) / h:.6f}"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--session", nargs="*", help="sessions à inclure (AAAAMMJJ), toutes par défaut")
    ap.add_argument("--brutes", action="store_true", help="ajouter data/essais/brutes")
    ap.add_argument("--sans-preannotation", action="store_true")
    ap.add_argument("--facteur-conf", type=float, default=0.8,
                    help="× seuils de config.json : un peu plus bas qu'en essai, mieux vaut une boîte "
                         "à supprimer qu'une à dessiner")
    ap.add_argument("--sortie", default=None)
    a = ap.parse_args()

    import cv2
    imgs = images_a_traiter(a)
    if not imgs:
        sys.exit("Aucune image. Faire une rafale depuis le dashboard (carte « Collecte dataset »).")
    sortie = Path(a.sortie or RACINE / "datasets" / f"lot-{datetime.now():%Y%m%d-%H%M}")
    (sortie / "images").mkdir(parents=True, exist_ok=True)
    (sortie / "labels").mkdir(exist_ok=True)

    det = None
    if not a.sans_preannotation:
        with open(RACINE / "config.json", encoding="utf-8") as fh:
            cfg = json.load(fh)
        print("Chargement du modèle (pré-annotation)…")
        det = charger_detecteur(cfg)

    compte, negatifs = Counter(), 0
    lignes_lot = []
    for i, (p, session) in enumerate(imgs, 1):
        nom = f"{session}_{p.parent.name}_{p.stem}" if p.parent.name != session else f"{session}_{p.stem}"
        f = cv2.imread(str(p))
        if f is None:
            continue
        shutil.copy2(p, sortie / "images" / f"{nom}{p.suffix.lower()}")
        lignes = []
        if det is not None:
            for d in det.detecter([f], facteur_conf=a.facteur_conf)[0]:
                c = CORRESPONDANCE.get(d["nom"])
                if c is None:
                    continue
                lignes.append(f"{CLASSES.index(c)} {yolo(d['boite'], f.shape[1], f.shape[0])}")
                compte[c] += 1
        (sortie / "labels" / f"{nom}.txt").write_text("\n".join(lignes) + ("\n" if lignes else ""))
        negatifs += not lignes
        lignes_lot.append({"image": f"{nom}{p.suffix.lower()}", "session": session,
                           "etiquette": p.parent.name, "boites": len(lignes)})
        if i % 25 == 0:
            print(f"  {i}/{len(imgs)}")

    (sortie / "data.yaml").write_text(
        "names:\n" + "".join(f"  {i}: {c}\n" for i, c in enumerate(CLASSES)) + f"nc: {len(CLASSES)}\n",
        encoding="utf-8")
    with open(sortie / "lot.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["image", "session", "etiquette", "boites"])
        w.writeheader()
        w.writerows(lignes_lot)
    archive = shutil.make_archive(str(sortie), "zip", sortie)

    print(f"\n{len(lignes_lot)} images → {sortie}")
    if det is not None:
        print("Boîtes proposées : " + (", ".join(f"{c} {n}" for c, n in sorted(compte.items())) or "aucune"))
        print(f"Images sans boîte (négatifs ou objets ratés, à vérifier) : {negatifs}")
    print(f"À glisser dans Roboflow → Upload : {archive}")
    print("Rappel : mettre une session entière dans le même split (test OU train), sinon le test est faussé.")


if __name__ == "__main__":
    main()
