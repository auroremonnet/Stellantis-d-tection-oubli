"""Simule la caméra thermique sur les scénarios S1 à S8, sans matériel.

    py outils/simuler_thermique.py
    py outils/simuler_thermique.py --mode 8bits

Les images synthétiques passent par le vrai code du banc (SourceThermique.mesure) avec les
seuils de config.json et la règle de décision d'un essai. Compare le seuil fixe, le contraste
dans l'image (avec ou sans zones ignorées) et la référence habitacle vide. Écrit un rapport Markdown + JSON et deux planches d'images
dans rapports/.

ATTENTION : les températures, tailles et champ de vision ci-dessous sont des HYPOTHÈSES. Le
simulateur compare des réglages et révèle des défauts de logique ; il ne prouve pas la
performance réelle de la caméra, qui reste à mesurer sur le banc.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

from care.cameras import SourceThermique, temperatures  # noqa: E402

# ---- Hypothèses physiques (à remplacer par des mesures dès qu'une caméra est disponible) ----
PEAU = 36.0
TRANSMISSION = {"peau": 0.85, "vetement": 0.5, "couverture": 0.25, "fourrure": 0.35}
AMBIANCES = {"hiver": 5, "frais": 15, "tempéré": 22, "chaud": 30, "canicule": 45}
CHAMP_VISION_DEG = 56
BRUIT_C = 0.1        # bruit du capteur
FLOU_PIXELS = 0.6    # une optique réelle étale un point sur les pixels voisins
SURECHANTILLON = 4   # chaque pixel capteur moyenne ce qu'il voit, y compris le fond

SCENARIOS = {
    "S1": ("Enfant dans siège auto", True),
    "S2": ("Enfant sous couverture", True),
    "S3": ("Animal sur banquette", True),
    "S4": ("Animal au sol, à moitié caché", True),
    "S5": ("Objet de valeur", False),
    "S6": ("Objet anodin", False),
    "S7": ("Habitacle vide", False),
    "S7t": ("Vide, tableau de bord au soleil", False),
    "S7s": ("Vide, siège encore chaud", False),
    "S8": ("Gourde chaude à 55 °C", False),
    "S8b": ("Sac au soleil (ambiance + 15 °C)", False),
}
RESOLUTION_CAMERA = (256, 192)  # caméra imposée du projet
ZONE_TABLEAU_DE_BORD = [0, 0, 1, 0.2]
METHODES = {
    "seuil fixe": {"methode": "seuil_fixe"},
    "référence": {"methode": "reference"},
    "contraste": {"methode": "contraste", "zones_ignorees": []},
    "contraste + zones": {"methode": "contraste", "zones_ignorees": [ZONE_TABLEAU_DE_BORD]},
}


def surface(ambiance, matiere):
    """Température de surface : entre l'ambiance et la peau, selon ce qui recouvre le corps."""
    return ambiance + (PEAU - ambiance) * TRANSMISSION[matiere]


def elements(scenario, ambiance):
    """Formes de la scène : (x m, y m, demi-largeur m, demi-hauteur m, température), dans l'ordre de dessin."""
    corps = surface(ambiance, "vetement")
    fourrure = surface(ambiance, "fourrure")
    return {
        "S1": [(0, 0.15, 0.15, 0.2, corps), (0, -0.15, 0.075, 0.09, surface(ambiance, "peau"))],
        "S2": [(0, 0, 0.2, 0.3, surface(ambiance, "couverture"))],
        "S3": [(0, 0.05, 0.25, 0.12, fourrure), (0.22, -0.05, 0.07, 0.07, fourrure),
               (0.27, -0.05, 0.02, 0.02, surface(ambiance, "peau"))],
        "S4": [(0, 0.2, 0.25, 0.06, fourrure), (0.22, 0.18, 0.07, 0.04, fourrure),
               (0.27, 0.18, 0.02, 0.015, surface(ambiance, "peau"))],
        "S5": [(0, 0.1, 0.17, 0.11, ambiance + 2)],
        "S6": [(0, 0.1, 0.2, 0.12, ambiance + 0.5)],
        "S7": [],
        "S7t": [],
        "S7s": [(0, 0.1, 0.2, 0.25, ambiance + 6)],
        "S8": [(0, 0, 0.035, 0.125, max(ambiance, 55))],
        "S8b": [(0, 0.1, 0.2, 0.15, ambiance + 15)],
    }[scenario]


def scene_temperatures(scenario, ambiance, resolution, distance, rng):
    """Carte des températures vue par le capteur (°C), sans bruit, avec décalage aléatoire de la scène.
    L'ambiance varie de ±1,5 °C d'un appel à l'autre : l'habitacle dérive depuis la référence."""
    w, h = resolution
    W, H = w * SURECHANTILLON, h * SURECHANTILLON
    px_par_m = W / (2 * distance * math.tan(math.radians(CHAMP_VISION_DEG) / 2))
    amb = ambiance + rng.uniform(-1.5, 1.5)
    gradient = np.linspace(-1, 1, H, dtype=np.float32)[:, None]  # habitacle pas parfaitement uniforme
    temp = np.repeat(amb + gradient, W, axis=1)
    if scenario == "S7t":  # structure fixe, présente aussi sur la référence
        temp[:round(H * ZONE_TABLEAU_DE_BORD[3]), :] += 12
    dx, dy = rng.uniform(-0.05, 0.05, 2)
    for x, y, rx, ry, t in elements(scenario, amb):
        centre = (round(W / 2 + (x + dx) * px_par_m), round(H / 2 + (y + dy) * px_par_m))
        axes = (max(1, round(rx * px_par_m)), max(1, round(ry * px_par_m)))
        cv2.ellipse(temp, centre, axes, 0, 0, 360, float(t), -1)
    temp = cv2.resize(temp, (w, h), interpolation=cv2.INTER_AREA)
    return cv2.GaussianBlur(temp, (0, 0), FLOU_PIXELS)


def encoder(temp, mode):
    """Convertit en ce que le banc reçoit de la caméra : TLinear 16 bits, ou 8 bits à contraste auto."""
    if mode == "16bits":
        return np.clip((temp + 273.15) * 100, 0, 65535).astype(np.uint16)
    etendue = max(float(temp.max() - temp.min()), 1e-6)
    return ((temp - temp.min()) * (255 / etendue)).astype(np.uint8)


def source_thermique(params, pixels_min=None):
    """Source du banc, jamais démarrée : aucun accès caméra, on lui injecte les images."""
    p = dict(params)
    if pixels_min is not None:
        p["pixels_chauds_min"] = pixels_min
    return SourceThermique("sim", 0, "Simulation", p)


def reference_simulee(scenario, ambiance, resolution, distance, rng, images=5):
    """Même calcul que Reference._capturer_thermique, sur un habitacle vide simulé."""
    base = scene_temperatures("S7t" if scenario == "S7t" else "S7", ambiance, resolution, distance, rng)
    return np.median([temperatures(encoder(base + rng.normal(0, BRUIT_C, base.shape), "16bits"))
                      for _ in range(images)], axis=0).astype(np.float32)


def essai(source, scenario, ambiance, resolution, distance, images, mode, rng, methode=None):
    """Un essai : même décision que Detecteur.analyser (chaud sur au moins 50 % des images)."""
    if methode is not None:
        source.params = {**source.params, **METHODES[methode]}
    source.reference = None
    if source.params["methode"] == "reference":
        source.reference = reference_simulee(scenario, ambiance, resolution, distance, rng)
    base = scene_temperatures(scenario, ambiance, resolution, distance, rng)
    hits = 0
    for _ in range(images):
        source.frame = encoder(base + rng.normal(0, BRUIT_C, base.shape), mode)
        hits += int(source.mesure()["chaud"])
    return hits / images >= 0.5


def taux_vivant(source, scenario, ambiance, resolution, distance, cfg, mode, rng, methode):
    """Part des essais où la thermique répond « vivant »."""
    n = cfg["repetitions_cible"]
    return sum(essai(source, scenario, ambiance, resolution, distance, cfg["images_par_essai"], mode, rng, methode)
               for _ in range(n)) / n


def par_ambiance(cfg, resolution, distance, mode, rng):
    source = source_thermique(cfg["thermique"])
    return {m: {s: {a: taux_vivant(source, s, t, resolution, distance, cfg, mode, rng, m)
                    for a, t in AMBIANCES.items()} for s in SCENARIOS}
            for m in METHODES}


def par_resolution(cfg, resolutions, distances, ambiance, mode, rng, methode="contraste + zones"):
    """Résolution × distance, avec la méthode prévue pour la voiture."""
    source = source_thermique(cfg["thermique"])
    return [{"resolution": f"{r[0]}x{r[1]}", "methode": methode, "distance_m": d,
             "taux": {s: taux_vivant(source, s, ambiance, r, d, cfg, mode, rng, methode) for s in SCENARIOS}}
            for r in resolutions for d in distances]


def justesse(taux_scenarios, ambiance):
    """Part de bonnes réponses sur tous les scénarios, pour une ambiance."""
    return sum(t[ambiance] if SCENARIOS[s][1] else 1 - t[ambiance] for s, t in taux_scenarios.items()) / len(SCENARIOS)


def vignette(source, scenario, ambiance, resolution, distance, mode, rng, texte):
    source.frame = encoder(scene_temperatures(scenario, ambiance, resolution, distance, rng)
                           + rng.normal(0, BRUIT_C, (resolution[1], resolution[0])), mode)
    img = cv2.resize(source.apercu(), (256, 192), interpolation=cv2.INTER_AREA)
    verdict = "CHAUD" if source.mesure()["chaud"] else "rien"
    for couleur, epaisseur in (((0, 0, 0), 3), ((255, 255, 255), 1)):
        cv2.putText(img, f"{texte} : {verdict}", (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.45, couleur, epaisseur,
                    cv2.LINE_AA)
    return img


def planches(cfg, resolutions, distances, mode, rng, base):
    """Deux planches, méthode prévue pour la voiture : tous les scénarios × ambiances, et S1 selon résolution × distance."""
    ascii_amb = {"hiver": "hiver", "frais": "frais", "tempéré": "tempere", "chaud": "chaud", "canicule": "canicule"}
    s = source_thermique({**cfg["thermique"], **METHODES["contraste + zones"]})
    lignes = [np.hstack([vignette(s, sc, t, RESOLUTION_CAMERA, 1.0, mode, rng, f"{sc} {ascii_amb[a]}")
                         for a, t in AMBIANCES.items()]) for sc in SCENARIOS]
    cv2.imwrite(str(base.with_name(base.name + "_scenarios.png")), np.vstack(lignes))
    lignes = [np.hstack([vignette(s, "S1", AMBIANCES["tempéré"], r, d, mode, rng, f"{r[0]}x{r[1]} {d} m")
                         for d in distances]) for r in resolutions]
    cv2.imwrite(str(base.with_name(base.name + "_resolution.png")), np.vstack(lignes))


def rapport_markdown(cfg, mode, ambiances, resolutions, distance):
    pct = lambda v: f"{v * 100:.0f} %"  # noqa: E731
    th = cfg["thermique"]
    colonnes = " | ".join(f"{a} ({t} °C)" for a, t in AMBIANCES.items())
    l = ["# Simulation de la caméra thermique", "",
         f"Mode {mode}. Seuil fixe : {th['seuil_celsius']} °C (16 bits) ou {th['seuil_8bit']}/255 (8 bits), "
         f"{th['pixels_chauds_min']} pixels. Contraste et référence : écart {th.get('delta_c')} °C, "
         f"{th.get('part_min_image', 0) * 100:.1f} % de l'image, maximum vivant {th.get('temp_max_vivant_c')} °C. "
         f"{cfg['repetitions_cible']} essais par case.", "",
         "**Résultat de simulation sur des températures supposées : à confirmer sur le banc réel.**", "",
         f"## Bonnes réponses, tous scénarios ({RESOLUTION_CAMERA[0]}x{RESOLUTION_CAMERA[1]}, {distance} m)", "",
         f"| Méthode | {colonnes} |", "|---|" + "---|" * len(AMBIANCES)]
    for m, taux in ambiances.items():
        l.append(f"| {m} | " + " | ".join(pct(justesse(taux, a)) for a in AMBIANCES) + " |")
    for m, taux in ambiances.items():
        l += ["", f"## Essais répondant « vivant », méthode {m} "
                  f"({RESOLUTION_CAMERA[0]}x{RESOLUTION_CAMERA[1]}, {distance} m)", "",
              "Attendu : 100 % pour S1 à S4, 0 % pour les autres.", "",
              f"| Scénario | Attendu | {colonnes} |", "|---|---|" + "---|" * len(AMBIANCES)]
        for s, (nom, vivant) in SCENARIOS.items():
            l.append(f"| {s} {nom} | {'vivant' if vivant else 'rien'} | "
                     + " | ".join(pct(taux[s][a]) for a in AMBIANCES) + " |")
    l += ["", "## Résolution et distance (ambiance tempérée)", "",
          "| Résolution | Méthode | Distance | " + " | ".join(SCENARIOS) + " |",
          "|---|---|---|" + "---|" * len(SCENARIOS)]
    for r in resolutions:
        l.append(f"| {r['resolution']} | {r['methode']} | {r['distance_m']} m | "
                 + " | ".join(pct(r["taux"][s]) for s in SCENARIOS) + " |")
    return "\n".join(l) + "\n"


def lire_resolution(texte):
    w, h = texte.lower().split("x")
    return int(w), int(h)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=str(RACINE / "config.json"))
    ap.add_argument("--mode", choices=("16bits", "8bits"), default="16bits")
    ap.add_argument("--resolutions", nargs="+", type=lire_resolution,
                    default=[RESOLUTION_CAMERA])
    ap.add_argument("--distances", nargs="+", type=float, default=[1.0, 1.5, 2.5])
    ap.add_argument("--graine", type=int, default=42)
    ap.add_argument("--sortie", default=str(RACINE / "rapports"))
    a = ap.parse_args()

    cfg = json.loads(Path(a.config).read_text(encoding="utf-8"))
    rng = np.random.default_rng(a.graine)
    ambiances = par_ambiance(cfg, RESOLUTION_CAMERA, 1.0, a.mode, rng)
    resolutions = par_resolution(cfg, a.resolutions, a.distances, AMBIANCES["tempéré"], a.mode, rng)

    sortie = Path(a.sortie)
    sortie.mkdir(parents=True, exist_ok=True)
    base = sortie / f"thermique_{a.mode}_{datetime.now():%Y%m%d-%H%M%S}"
    planches(cfg, a.resolutions, a.distances, a.mode, rng, base)
    md = rapport_markdown(cfg, a.mode, ambiances, resolutions, 1.0)
    base.with_suffix(".md").write_text(md, encoding="utf-8")
    base.with_suffix(".json").write_text(
        json.dumps({"mode": a.mode, "graine": a.graine, "ambiances": ambiances, "resolutions": resolutions},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    print(md)
    print(f"Rapport : {base}.md")


if __name__ == "__main__":
    main()
