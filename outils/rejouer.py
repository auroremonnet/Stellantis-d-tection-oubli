"""Rejoue la détection sur les images brutes des essais et la note contre une vérité terrain.

    python outils/rejouer.py                              # moteur de config.json
    python outils/rejouer.py --moteurs care hybride yoloe # comparaison avant / après
    python outils/rejouer.py --annoter rapports/rejeu     # + images annotées pour vérifier à l'œil

Sert à vérifier qu'un réglage ou un nouveau modèle améliore vraiment les choses, sur les
mêmes images, sans retourner dans la voiture. Les images sont celles que le banc enregistre
à chaque essai (data/essais/brutes/<essai>_<caméra>.jpg) ; la vérité terrain est un fichier
JSON : un point par objet (voir tests/donnees/verite_voiture_20261106.json).

Avec --reference, les objets déjà présents sur la référence « habitacle vide » sont écartés,
comme en essai réel (les images doivent venir des mêmes positions de caméra).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

import cv2

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

from care.metriques_detection import Compteur, apparier_points  # noqa: E402

VERITE_DEFAUT = RACINE / "tests" / "donnees" / "verite_voiture_20261106.json"


def charger_config(chemin: Path) -> dict:
    cfg = json.loads(chemin.read_text(encoding="utf-8"))
    local = chemin.with_name("config.local.json")
    if local.exists():
        for k, v in json.loads(local.read_text(encoding="utf-8")).items():
            cfg[k] = {**cfg.get(k, {}), **v} if isinstance(v, dict) else v
    return cfg


def charger_detecteur(cfg: dict, moteur: str | None):
    from care.detecteur import Detecteur
    if moteur:
        cfg = {**cfg, "detection": {**cfg.get("detection", {}), "moteur": moteur}}
    d = Detecteur(cfg)
    t0 = time.time()
    while not d.pret and not d.erreur and time.time() - t0 < 900:
        time.sleep(0.5)
    if not d.pret:
        raise RuntimeError(d.erreur or "chargement trop long")
    return d


def rejouer(detecteur, images: dict, verite: dict, reference=None, annoter: Path | None = None):
    from care.detection.identification import Detection
    from care.detection.rendu import annoter as dessiner
    total: dict[str, Compteur] = defaultdict(Compteur)
    fausses_alertes, vides, duree = 0, 0, 0.0
    for nom, attendus in verite.items():
        img = images.get(nom)
        if img is None:
            continue
        t0 = time.perf_counter()
        dets = [d for d in detecteur.detecter([img])[0] if d["type"] == "valeur"]
        duree += time.perf_counter() - t0
        gardees = [Detection(detecteur.libelle(d["nom"]), "valeur", d["conf"], d["boite"]) for d in dets]
        fixes = []
        cam = nom.rsplit("_", 1)[-1]
        if reference is not None and reference.a(cam):
            cp = reference.comparer(cam, img)
            fixes = [d for d in gardees if reference.deja_la(cam, d, None if cp.inutilisable else cp)]
            gardees = [d for d in gardees if d not in fixes]
        preds = [(d.cle, d.conf, d.boite) for d in gardees]
        for cle, c in apparier_points([tuple(v) for v in attendus], preds, img.shape[1], img.shape[0]).items():
            t = total[cle]
            t.vp, t.fp, t.fn = t.vp + c.vp, t.fp + c.fp, t.fn + c.fn
        if not any(g != "?" for g, *_ in attendus):
            vides += 1
            fausses_alertes += bool(preds) and any(
                not any(g == "?" and b[0] - 30 <= x <= b[2] + 30 and b[1] - 30 <= y <= b[3] + 30
                        for g, x, y in attendus) for _, _, b in preds)
        if annoter is not None:
            annoter.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(annoter / f"{nom}.jpg"), dessiner(img, gardees, fixes))
    return total, {"images": len(images), "vides": vides, "fausses_alertes": fausses_alertes,
                   "s_par_image": duree / max(1, len(images))}


def _p(v):
    return "  —" if v is None else f"{100 * v:3.0f} %"


def tableau(nom: str, total: dict, meta: dict) -> str:
    g = Compteur()
    lignes = [f"\n== moteur {nom} · {meta['images']} images · {meta['s_par_image']:.2f} s/image ==",
              f"{'classe':18s} trouvés   rappel  précision"]
    for cle in sorted(total):
        c = total[cle]
        g.vp, g.fp, g.fn = g.vp + c.vp, g.fp + c.fp, g.fn + c.fn
        lignes.append(f"{cle:18s} {c.vp:3d}/{c.vp + c.fn:<3d}  {_p(c.rappel)}  {_p(c.precision)}"
                      + (f"   (+{c.fp} en trop)" if c.fp else ""))
    lignes.append(f"{'TOTAL':18s} {g.vp:3d}/{g.vp + g.fn:<3d}  {_p(g.rappel)}  {_p(g.precision)}   F1 {_p(g.f1)}")
    lignes.append(f"habitacle vide : {meta['fausses_alertes']} fausse(s) alerte(s) sur {meta['vides']} images")
    return "\n".join(lignes)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--images", type=Path, default=RACINE / "data" / "essais" / "brutes")
    ap.add_argument("--verite", type=Path, default=VERITE_DEFAUT)
    ap.add_argument("--moteurs", nargs="+", default=[None], help="care, hybride, yoloe, coco (défaut : config.json)")
    ap.add_argument("--reference", type=Path, default=None, help="dossier d'une référence (data/essais/reference)")
    ap.add_argument("--essais", nargs="*", help="ne rejouer que ces essais (préfixes de nom de fichier)")
    ap.add_argument("--annoter", type=Path, default=None, help="dossier où écrire les images annotées")
    ap.add_argument("--config", type=Path, default=RACINE / "config.json")
    a = ap.parse_args(argv)

    verite = json.loads(a.verite.read_text(encoding="utf-8"))["images"]
    if a.essais:
        verite = {k: v for k, v in verite.items() if any(k.startswith(e) for e in a.essais)}
    images = {k: cv2.imread(str(a.images / f"{k}.jpg")) for k in verite}
    images = {k: v for k, v in images.items() if v is not None}
    if not images:
        sys.exit(f"Aucune image de la vérité terrain trouvée dans {a.images}")
    cfg = charger_config(a.config)
    reference = None
    if a.reference:
        from care.reference import Reference
        reference = Reference(str(a.reference), cfg.get("reference"))
    for moteur in a.moteurs:
        d = charger_detecteur(cfg, moteur)
        sortie = a.annoter / d.moteur if a.annoter else None
        print(tableau(d.moteur, *rejouer(d, images, verite, reference, sortie)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
