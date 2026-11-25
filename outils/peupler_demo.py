"""Remplit le journal du MODE DÉMO avec une série complète d'essais simulés.

    python outils/peupler_demo.py                 # 10 répétitions par scénario, de jour et de nuit
    python outils/peupler_demo.py --repetitions 3 # plus rapide
    python outils/peupler_demo.py --vider         # repartir d'un journal de démo vide
    python outils/peupler_demo.py --max S3=5 S4=5 # au plus 5 essais pour ces scénarios (jour et nuit confondus)

Sert à montrer le dashboard « plein », tel qu'il sera une fois toute la campagne faite : tous les
scénarios, jour et nuit, plus quelques cycles de surveillance automatique pour le délai d'alerte.

Ces essais sont SIMULÉS (flux synthétiques, détections tirées au hasard par DetecteurDemo). Ils vont
dans data/demo/, jamais dans le journal des vrais essais (data/essais/), et le dashboard les affiche
sous le bandeau « MODE DÉMO » et l'étiquette « Données de démonstration ». Ce ne sont pas des résultats.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent


def appel(base: str, chemin: str, corps: dict | None = None, delai: float = 60):
    donnees = None if corps is None else json.dumps(corps).encode()
    req = urllib.request.Request(base + chemin, data=donnees, headers={"Content-Type": "application/json"},
                                 method="GET" if corps is None else "POST")
    with urllib.request.urlopen(req, timeout=delai) as r:
        return json.loads(r.read() or b"{}")


def attendre(base: str, pret, delai_s: float, pas_s: float = 0.5):
    fin = time.time() + delai_s
    while time.time() < fin:
        try:
            v = pret()
            if v:
                return v
        except (urllib.error.URLError, ConnectionError, OSError):
            pass
        time.sleep(pas_s)
    raise TimeoutError("le dashboard de démo ne répond pas")


def cycle_automatique(base: str, verite: str, scenario: str, variante: str) -> None:
    """Un oubli complet : le conducteur monte, descend, le système analyse et décide."""
    appel(base, "/api/surveillance/armer", {"scenario": scenario, "variante": variante, "verite": verite})
    appel(base, "/api/surveillance/demo", {"occupant": True})
    attendre(base, lambda: appel(base, "/api/surveillance")["etat"] == "occupe", 20)
    appel(base, "/api/surveillance/demo", {"occupant": False})
    time.sleep(2)
    attendre(base, lambda: appel(base, "/api/surveillance")["etat"] in ("alerte", "veille"), 60)
    appel(base, "/api/surveillance/desarmer", {})


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--repetitions", type=int, default=10, help="essais par scénario et par variante")
    ap.add_argument("--cycles", type=int, default=6, help="cycles de surveillance automatique")
    ap.add_argument("--vider", action="store_true", help="effacer d'abord le journal de démo")
    ap.add_argument("--max", nargs="*", default=[], metavar="CODE=N",
                    help="plafond d'essais pour un scénario, toutes variantes confondues (ex. S3=5 S4=5)")
    ap.add_argument("--ideal", action="store_true",
                    help="version idéale : le système visé en fin de projet (journal data/demo-ideal)")
    ap.add_argument("--port", type=int, default=5177)
    a = ap.parse_args(argv)

    journal = RACINE / "data" / ("demo-ideal" if a.ideal else "demo") / "essais.csv"
    if a.vider and journal.exists():
        journal.unlink()
    base = f"http://127.0.0.1:{a.port}"
    # aucune notification pendant le remplissage, même si alertes.en_demo est activé sur ce PC
    env = {**os.environ, "CARE_NTFY_TOPIC": "CHANGEMOI-remplissage-demo"}
    commande = [sys.executable, str(RACINE / "app.py"), "--demo", "--no-browser", "--port", str(a.port)]
    commande += ["--ideal"] if a.ideal else []
    serveur = subprocess.Popen(commande, cwd=RACINE, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        attendre(base, lambda: appel(base, "/api/etat")["modele"]["pret"], 120)
        cfg = appel(base, "/api/config")
        variantes = [v for v in cfg["variantes"] if v.lower().startswith(("jour", "nuit"))] or cfg["variantes"][:1]
        plafond = {c: int(n) for c, n in (m.split("=", 1) for m in a.max)}
        plan = []
        for s in cfg["scenarios"]:
            serie = [(s, v) for _ in range(a.repetitions) for v in variantes]   # jour et nuit alternés
            plan += serie[:plafond.get(s["code"], len(serie))]
        note = "essai simulé (version idéale)" if a.ideal else "essai simulé (mode démo)"
        for fait, (s, v) in enumerate(plan, 1):
            appel(base, "/api/essais", {"scenario": s["code"], "variante": v, "verite": s["verite"],
                                        "commentaire": note})
            print(f"\r{fait}/{len(plan)} essais simulés", end="", flush=True)
        print()
        vivants = [s for s in cfg["scenarios"] if s["verite"] == "vivant"] or cfg["scenarios"]
        for i in range(a.cycles):
            s = vivants[i % len(vivants)]
            cycle_automatique(base, s["verite"], s["code"], variantes[i % len(variantes)])
            print(f"\r{i + 1}/{a.cycles} cycles de surveillance", end="", flush=True)
        lanceur = "lancer_ideal.bat" if a.ideal else "lancer_demo.bat"
        print(f"\nJournal rempli : {journal}\nLancer {lanceur} puis ouvrir /resultats.")
    finally:
        serveur.terminate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
