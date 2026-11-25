"""Ajoute au journal des essais rejoués à partir de photos déjà prises (une caméra, sans thermique ni micro).

    python outils/integrer_rejeu.py --essais 20261101-1620 20261101-1621 --scenario S3 --verite vivant \\
        --commentaire "photo webcam du 01/11, chien réel"

Chaque photo de data/essais/brutes repasse dans le moteur de config.json, exactement comme un essai
manuel, et donne une ligne du journal marquée mode = « rejeu ». La vue Résultats les compte à part
dans sa ligne de provenance. Toutes les photos demandées sont ajoutées, réussies ou non : ne garder
que celles qui passent fausserait le taux affiché.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

import cv2

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

from care.detection.rendu import mosaique  # noqa: E402
from care.stockage import Journal  # noqa: E402
from outils.rejouer import charger_config, charger_detecteur  # noqa: E402


class Photo:
    """Une photo présentée au détecteur comme une caméra figée."""

    def __init__(self, sid: str, image):
        self.id, self.label, self.image = sid, sid, image

    def derniere(self):
        return self.image


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--essais", nargs="+", required=True, help="préfixes de nom de fichier (ex. 20261101-1620)")
    ap.add_argument("--scenario", required=True)
    ap.add_argument("--verite", required=True, choices=("vivant", "objet", "vide"))
    ap.add_argument("--variante", default="Jour")
    ap.add_argument("--commentaire", default="")
    ap.add_argument("--images", type=Path, default=RACINE / "data" / "essais" / "brutes")
    ap.add_argument("--journal", type=Path, default=RACINE / "data" / "essais" / "essais.csv")
    ap.add_argument("--sortie", type=Path, default=RACINE / "data" / "essais" / "images")
    ap.add_argument("--config", type=Path, default=RACINE / "config.json")
    a = ap.parse_args(argv)

    fichiers = sorted(f for f in a.images.glob("*.jpg") if any(f.name.startswith(p) for p in a.essais))
    if not fichiers:
        print(f"Aucune photo dans {a.images} pour {a.essais}")
        return 1
    detecteur = charger_detecteur(charger_config(a.config), None)
    journal = Journal(str(a.journal))
    deja = {l["id"] for l in journal.lire()}
    a.sortie.mkdir(parents=True, exist_ok=True)
    for f in fichiers:
        eid, cam = f.stem.rsplit("_", 1)
        if eid in deja:
            print(f"{eid} : déjà dans le journal, ignoré")
            continue
        r = detecteur.analyser([Photo(cam, cv2.imread(str(f)))], None, a.verite)
        m = mosaique(r.get("images_rgb") or [])
        if m is not None:
            cv2.imwrite(str(a.sortie / f"{eid}_rgb.jpg"), m)
        ligne = {k: v for k, v in r.items() if not k.startswith("image")}
        ligne.update({"id": eid, "horodatage": datetime.strptime(eid, "%Y%m%d-%H%M%S").isoformat(timespec="seconds"),
                      "scenario": a.scenario, "variante": a.variante, "verite": a.verite,
                      "commentaire": f"Rejeu d'une photo, 1 caméra, sans thermique ni micro. {a.commentaire}".strip(),
                      "moteur": detecteur.moteur, "mode": "rejeu", "alerte": "", "audio_statut": "desactive"})
        journal.ajouter(ligne)
        print(f"{eid} : présence = {r.get('vivant_rgb')} {r.get('classes_vivant')} · objets = {r.get('objets')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
