"""Entraîne le modèle CARE (baby / keys / wallet / card) et le dépose dans modeles/.

    # depuis Roboflow (clé API dans la variable d'environnement, jamais dans le code)
    set ROBOFLOW_API_KEY=xxxxxxxx            (Windows)   export ROBOFLOW_API_KEY=xxxxxxxx (Mac/Linux)
    python entrainement/entrainer.py --version 1

    # depuis un export YOLO déjà sur le disque
    python entrainement/entrainer.py --donnees chemin/vers/data.yaml

Réglages par défaut tirés du guide de fine-tuning Ultralytics pour un petit jeu de
données proche de COCO : YOLO26s pré-entraîné, 10 premières couches gelées, AdamW
lr0=0.001, arrêt précoce (patience 20). Les augmentations (mosaïque, flips, HSV) sont
faites par Ultralytics à chaque epoch : la version Roboflow n'en contient pas.

Produit :
    modeles/<nom>.pt    poids à utiliser (detection.modele_custom, moteur "hybride")
    modeles/<nom>.json  fiche du modèle : jeu de données, réglages, métriques sur le TEST
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
WORKSPACE, PROJET = "aurores-workspace-zu1oe", "care-oubli"


def telecharger(version: int, dossier: Path) -> Path:
    """Télécharge la version Roboflow au format YOLO et renvoie le data.yaml corrigé."""
    cle = os.environ.get("ROBOFLOW_API_KEY")
    if not cle:
        sys.exit("ROBOFLOW_API_KEY absente. Roboflow → Settings → API Keys, puis la définir "
                 "dans le terminal (voir l'en-tête du script).")
    from roboflow import Roboflow
    ds = (Roboflow(api_key=cle).workspace(WORKSPACE).project(PROJET)
          .version(version).download("yolov8", location=str(dossier / f"{PROJET}-v{version}")))
    return corriger_yaml(Path(ds.location) / "data.yaml")


def corriger_yaml(chemin: Path) -> Path:
    """Les data.yaml exportés par Roboflow pointent vers « ../train/images » : chemins
    relatifs faux selon le dossier courant. On réécrit les splits reconnus (structure
    Roboflow train|valid|test/images) depuis la racine du jeu ; un data.yaml d'une autre
    structure (ex. images/train) est laissé tel quel."""
    import yaml
    cfg = yaml.safe_load(chemin.read_text(encoding="utf-8"))
    racine = chemin.parent.resolve()
    roboflow = {s: d for s, d in (("train", "train"), ("val", "valid"), ("test", "test"))
                if (racine / d / "images").is_dir()}
    if not roboflow:
        return chemin
    cfg["path"] = str(racine)
    for split, dossier in roboflow.items():
        cfg[split] = f"{dossier}/images"
    chemin.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return chemin


def fiche(modele, metriques, split: str) -> dict:
    """Métriques lisibles (et sérialisables) d'un appel model.val()."""
    noms = modele.names
    par_classe = {}
    for i, c in enumerate(metriques.box.ap_class_index):
        p, r, ap50, ap = metriques.box.class_result(i)
        par_classe[noms[int(c)]] = {"precision": round(float(p), 3), "rappel": round(float(r), 3),
                                    "mAP50": round(float(ap50), 3), "mAP50-95": round(float(ap), 3)}
    return {"split": split,
            "mAP50": round(float(metriques.box.map50), 3),
            "mAP50-95": round(float(metriques.box.map), 3),
            "precision": round(float(metriques.box.mp), 3),
            "rappel": round(float(metriques.box.mr), 3),
            "par_classe": par_classe}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--version", type=int, help="version du jeu Roboflow care-oubli")
    src.add_argument("--donnees", type=Path, help="data.yaml d'un export YOLO local")
    ap.add_argument("--modele", default="yolo26s.pt", help="poids de départ (yolo26n/s/m.pt, yolo11s.pt…)")
    ap.add_argument("--epochs", type=int, default=100)
    ap.add_argument("--imgsz", type=int, default=640, help="1280 aide les petits objets (clés, carte)")
    ap.add_argument("--batch", type=int, default=16, help="-1 = automatique selon la mémoire GPU")
    ap.add_argument("--freeze", type=int, default=10, help="couches gelées (0 = tout ré-entraîner)")
    ap.add_argument("--patience", type=int, default=20)
    ap.add_argument("--device", default=None, help="0 (GPU), cpu, mps… — auto par défaut")
    ap.add_argument("--nom", default="care-v1", help="nom du modèle produit dans modeles/")
    ap.add_argument("--sortie", type=Path, default=RACINE / "runs", help="dossier des runs Ultralytics")
    ap.add_argument("--donnees-dir", type=Path, default=RACINE / "datasets")
    a = ap.parse_args(argv)

    data = telecharger(a.version, a.donnees_dir) if a.version else corriger_yaml(a.donnees.resolve())
    print(f"Jeu de données : {data}")

    from ultralytics import YOLO
    modele = YOLO(a.modele)
    modele.train(data=str(data), epochs=a.epochs, imgsz=a.imgsz, batch=a.batch, freeze=a.freeze,
                 patience=a.patience, optimizer="AdamW", lr0=0.001, cos_lr=True, warmup_epochs=1,
                 seed=0, deterministic=True, device=a.device, project=str(a.sortie), name=a.nom,
                 exist_ok=True, plots=True)
    meilleur = Path(modele.trainer.best)

    final = YOLO(str(meilleur))
    import yaml
    a_test = bool(yaml.safe_load(data.read_text(encoding="utf-8")).get("test"))  # clé vide = pas de test
    split = "test" if a_test else "val"  # le test n'a servi à aucun réglage : chiffre honnête
    m = final.val(data=str(data), split=split, imgsz=a.imgsz, batch=a.batch if a.batch > 0 else 16,
                  device=a.device, project=str(a.sortie), name=f"{a.nom}-{split}", exist_ok=True,
                  plots=True)

    dest = RACINE / "modeles"
    dest.mkdir(exist_ok=True)
    shutil.copy2(meilleur, dest / f"{a.nom}.pt")
    infos = {
        "nom": a.nom,
        "date": datetime.now().isoformat(timespec="seconds"),
        "jeu_de_donnees": f"roboflow:{WORKSPACE}/{PROJET}/{a.version}" if a.version else str(data),
        "base": a.modele,
        "reglages": {k: getattr(a, k) for k in ("epochs", "imgsz", "batch", "freeze", "patience")},
        "classes": list(final.names.values()),
        "epochs_effectives": int(getattr(modele.trainer, "epoch", -1)) + 1,
        "metriques": fiche(final, m, split),
        "run": str(meilleur.parent.parent),
    }
    (dest / f"{a.nom}.json").write_text(json.dumps(infos, ensure_ascii=False, indent=2), encoding="utf-8")

    r = infos["metriques"]
    print(f"\n✔ Modèle : {dest / (a.nom + '.pt')}")
    print(f"  {split} : mAP50 {r['mAP50']:.3f} · précision {r['precision']:.3f} · rappel {r['rappel']:.3f}")
    for c, v in r["par_classe"].items():
        print(f"    {c:<10} mAP50 {v['mAP50']:.3f}  P {v['precision']:.3f}  R {v['rappel']:.3f}")
    print("  Le banc l'utilise automatiquement (moteur « hybride », detection.modele_custom).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
