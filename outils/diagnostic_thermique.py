"""Mise en route de la caméra thermique sur place. Ne demande ni modèle ni caméra RGB.

    py outils/diagnostic_thermique.py sonder --appliquer   trouve la caméra, sa résolution et son format
                                                           (caméra du banc, famille InfiRay : déjà réglée,
                                                           vérifier plutôt avec outils/diag_thermique.py)
    py outils/diagnostic_thermique.py direct               image en direct et verdict ; S enregistre, Q quitte
    py outils/diagnostic_thermique.py zones                dessine les zones à ignorer (vitres, tableau de bord)
    py outils/diagnostic_thermique.py enregistrer S1_poupee  images brutes d'une scène
    py outils/diagnostic_thermique.py rejouer              repasse les images enregistrées, sans caméra

Procédure complète : docs/protocole-thermique-voiture.md
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime
from pathlib import Path

os.environ.setdefault("OPENCV_LOG_LEVEL", "SILENT")  # un index vide ne doit pas noyer le résultat

import cv2  # noqa: E402
import numpy as np  # noqa: E402

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

from care import peripheriques  # noqa: E402
from care.cameras import SourceThermique, normaliser_brut, ouvrir_flux  # noqa: E402
from care.config import charger_config, modifier_config_locale  # noqa: E402
from care.thermique import temperature_plausible, temperatures  # noqa: E402

DOSSIER_BRUTES = RACINE / "data" / "essais" / "brutes" / "thermique"
DIVISEURS = (100, 10, 64)  # centi-kelvins (TLinear), déci-kelvins, 1/64 de kelvin selon les fabricants
FLUX_A_ESSAYER = (
    {"backend": "dshow", "fourcc": "Y16 ", "convert_rgb": 0},
    {"backend": "msmf", "fourcc": "Y16 ", "convert_rgb": 0},
    {"backend": "dshow", "fourcc": None, "convert_rgb": 0},
    {"backend": "auto", "fourcc": None, "convert_rgb": 1},
)


def analyser_image(f):
    """Décrit une image brute. score : 3 températures lisibles, 2 16 bits à calibrer, 1 8 bits gris, 0 couleur."""
    canaux = 1 if f.ndim == 2 else f.shape[2]
    info = {"resolution": f"{f.shape[1]}x{f.shape[0]}", "type": f"{f.dtype}, {canaux} canal(aux)",
            "diviseur_kelvin": None, "temp_min": None, "temp_mediane": None, "temp_max": None}
    if f.dtype == np.uint16:
        for d in DIVISEURS:
            temp = temperatures(f, d)
            if temperature_plausible(temp):
                info.update(score=3, format="16 bits, températures lisibles", diviseur_kelvin=d,
                            temp_min=round(float(temp.min()), 1), temp_mediane=round(float(np.median(temp)), 1),
                            temp_max=round(float(temp.max()), 1))
                return info
        info.update(score=2, format="16 bits, échelle de température inconnue")
        return info
    gris = f.ndim == 2 or f.shape[2] == 1 or (f.shape[2] == 3 and np.ptp(f.astype(np.int16), axis=2).max() <= 2)
    info.update(score=1 if gris else 0, format="8 bits gris, sans température" if gris else "couleur, probablement RGB")
    return info


def lire_image(cap, essais=8):
    """Quelques lectures : les premières images d'une caméra sont souvent vides."""
    f = None
    for _ in range(essais):
        ok, lu = cap.read()
        if ok and lu is not None:
            f = lu
    if f is None:
        return None
    return normaliser_brut(f, int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))


def sonder_index(index):
    """Essaie les modes de lecture d'une caméra ; le meilleur d'abord, [] si l'index est vide."""
    resultats = []
    for flux in FLUX_A_ESSAYER:
        if flux["backend"] == "auto" and not resultats:
            continue  # index vide : ce mode met plusieurs secondes à échouer
        cap = ouvrir_flux(index, flux)
        try:
            f = lire_image(cap) if cap.isOpened() else None
        finally:
            cap.release()
        if f is not None:
            resultats.append({**analyser_image(f), "index": index, "flux": flux, "_image": f})
    return sorted(resultats, key=lambda r: -r["score"])


def reglages(meilleur):
    """Réglages à fusionner dans config.local.json."""
    cfg = {"camera_thermique": {"index": meilleur["index"], "active": True}, "thermique": {"flux": meilleur["flux"]}}
    if meilleur["diviseur_kelvin"]:
        cfg["thermique"]["diviseur_kelvin"] = meilleur["diviseur_kelvin"]
    return cfg


def conseil(meilleur):
    if meilleur["score"] == 3:
        return ("OK. Vérifie la T° en visant ta main : environ 30 à 35 °C. Sinon, l'échelle détectée est fausse.")
    if meilleur["score"] == 2:
        return ("La caméra envoie du 16 bits mais son échelle est inconnue. Le contraste ne vaut rien sans °C : "
                "enregistre des images et cherche l'échelle dans la documentation du modèle.")
    if meilleur["score"] == 1:
        return ("Pas de température dans ce flux : le banc reste en seuil fixe, peu fiable (fausses alertes "
                "à cause du contraste automatique). Cherche un mode radiométrique ou le logiciel du fabricant.")
    return "Aucun flux thermique reconnu : vérifie le branchement et les autres index."


def cmd_sonder(a):
    indices = [a.index] if a.index is not None else range(10)
    trouves = []
    for i in indices:
        resultats = sonder_index(i)
        if not resultats:
            continue
        print(f"\nIndex {i}")
        for r in resultats:
            temp = ""
            if r["diviseur_kelvin"]:
                temp = f", {r['temp_min']} à {r['temp_max']} °C (médiane {r['temp_mediane']})"
            flux = r["flux"]
            print(f"  {flux['backend']:6} {str(flux['fourcc']):5} : {r['resolution']:>9}  {r['format']}{temp}")
        trouves.append(resultats[0])
    if not trouves:
        print("Aucune caméra trouvée. Vérifie le branchement (hub USB alimenté) puis relance.")
        return 1
    meilleur = max(trouves, key=lambda r: r["score"])
    print(f"\nCaméra thermique probable : index {meilleur['index']}, RÉSOLUTION {meilleur['resolution']}")
    print(f"Format : {meilleur['format']}")
    print(conseil(meilleur))
    if meilleur["score"] == 0:
        return 1
    DOSSIER_BRUTES.mkdir(parents=True, exist_ok=True)
    np.save(DOSSIER_BRUTES / f"{datetime.now():%Y%m%d-%H%M%S}_diagnostic.npy", meilleur["_image"])
    deja_regle = charger_config(str(RACINE)).get("thermique", {}).get("modele") == "tc001"
    if a.appliquer and deja_regle and not a.forcer:
        print("Rien d'écrit : le banc est réglé pour sa caméra InfiRay (thermique.modele = tc001), que ce sondage "
              "ne sait pas lire. Vérifie-la avec : python outils/diag_thermique.py. Autre caméra : ajoute --forcer.")
    elif a.appliquer:
        print(f"Réglages écrits dans {modifier_config_locale(str(RACINE), reglages(meilleur))}")
    else:
        print(f"Pour l'appliquer, relance avec --appliquer : {reglages(meilleur)}")
    return 0


def trouver_thermique(cfg):
    """Même résolution « position → périphérique » que le dashboard (index « auto », nom de la caméra)."""
    c = cfg["camera_thermique"]
    if isinstance(c.get("index"), int) and not c.get("nom"):
        return c["index"]
    _, th = peripheriques.resoudre(cfg.get("cameras_rgb", []), c, peripheriques.lister(), cfg.get("cameras"))
    if not th or th.get("source") is None:
        sys.exit("Caméra thermique introuvable" + (f" : {th['probleme']}" if th and th.get("probleme") else "")
                 + ". Vérifie le branchement, puis python lister_cameras.py.")
    return th["source"]


def demarrer_source(cfg):
    c = cfg["camera_thermique"]
    source = SourceThermique(c["id"], trouver_thermique(cfg), c["label"], cfg["thermique"]).demarrer()
    limite = time.time() + 10
    while source.derniere() is None:
        if time.time() > limite:
            sys.exit(f"Pas d'image sur l'index {c['index']} ({source.erreur}). Lancer d'abord : sonder --appliquer")
        time.sleep(0.1)
    return source


def enregistrer(source, nom, n=30, dossier=DOSSIER_BRUTES):
    """Empile n images brutes distinctes dans un .npy, relu ensuite par « rejouer »."""
    images, dernier, limite = [], 0.0, time.time() + 2 * n
    while len(images) < n and time.time() < limite:
        if source.stamp != dernier:
            dernier = source.stamp
            images.append(source.derniere())
        time.sleep(0.02)
    dossier.mkdir(parents=True, exist_ok=True)
    chemin = dossier / f"{datetime.now():%Y%m%d-%H%M%S}_{nom}.npy"
    np.save(chemin, np.stack(images))
    return chemin


def cmd_enregistrer(a):
    source = demarrer_source(charger_config(str(RACINE)))
    print(f"Enregistré : {enregistrer(source, a.nom, a.images)}")
    source.arreter()
    return 0


def legende(m, params=None):
    """Une ligne sur l'image : de quoi régler le seuil sur place (écart mesuré / seuil appliqué)."""
    tmax = "" if m["tmax"] is None else f" | max {m['tmax']:.1f} C"
    ecart = ""
    if m.get("ecart_max") is not None:
        unite = "C" if m["unite"] == "°C" else "comptes"
        seuil = "" if params is None else f" (seuil {params['delta_c' if unite == 'C' else 'delta_comptes']:g})"
        ecart = f" | ecart max {m['ecart_max']:.0f} {unite}{seuil}" if unite == "comptes" \
            else f" | ecart max {m['ecart_max']:.1f} C{seuil}"
    texte = f"{m['resolution']} | {m['methode']}{tmax}{ecart} | {'CHAUD' if m['chaud'] else 'rien'}"
    return texte.replace("é", "e")


def cmd_direct(a):
    source = demarrer_source(charger_config(str(RACINE)))
    print("Q : quitter. S : enregistrer la scène.")
    numero = 0
    while True:
        m, img = source.mesure(), source.apercu()
        if img is not None:
            for couleur, epaisseur in (((0, 0, 0), 3), ((255, 255, 255), 1)):
                cv2.putText(img, legende(m, source.params), (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.5, couleur,
                            epaisseur, cv2.LINE_AA)
            cv2.imshow("Thermique CARE", img)
        touche = cv2.waitKey(50) & 0xFF
        if touche in (ord("q"), 27):
            break
        if touche == ord("s"):
            numero += 1
            print(f"Enregistré : {enregistrer(source, f'{a.nom}_{numero}')}")
    source.arreter()
    cv2.destroyAllWindows()
    return 0


def en_fractions(rectangles, largeur, hauteur):
    """Rectangles (x, y, l, h) en pixels → zones en part de l'image, indépendantes de la résolution."""
    return [[round(x / largeur, 3), round(y / hauteur, 3), round((x + l) / largeur, 3), round((y + h) / hauteur, 3)]
            for x, y, l, h in rectangles]


def cmd_zones(a):
    source = demarrer_source(charger_config(str(RACINE)))
    img = source.apercu()
    source.arreter()
    print("Dessine chaque zone à la souris, ENTRÉE pour valider la zone, ÉCHAP pour terminer.")
    rectangles = cv2.selectROIs("Zones a ignorer", img, False, False)
    cv2.destroyAllWindows()
    zones = en_fractions([tuple(int(v) for v in r) for r in rectangles], img.shape[1], img.shape[0])
    print(f"Zones : {zones}")
    print(f"Écrit dans {modifier_config_locale(str(RACINE), {'thermique': {'zones_ignorees': zones}})}")
    return 0


def rejouer_fichier(chemin, params, reference=None):
    """Verdict de chaque méthode sur un .npy (une image ou une pile), même règle qu'un essai."""
    images = np.load(chemin, allow_pickle=False)
    if images.ndim == 2 or (images.ndim == 3 and images.shape[2] in (2, 3)):
        images = images[None]
    methodes = {"contraste": "contraste", "seuil fixe": "seuil_fixe"}
    if reference is not None:
        methodes["référence"] = "reference"
    ligne = {"fichier": Path(chemin).name}
    for nom, methode in methodes.items():
        source = SourceThermique("rejeu", 0, "Rejeu", {**params, "methode": methode})
        if isinstance(reference, tuple):          # (champ, unité), comme le rend reference_depuis
            source.poser_reference(*reference)
        elif reference is not None:               # tableau seul : des températures en °C
            source.poser_reference(reference)
        hits = 0
        for f in images:
            m = source.analyser(f)
            hits += int(m["chaud"])
            ligne["resolution"] = m["resolution"]
            ligne["tmax"] = None if m["tmax"] is None else round(m["tmax"], 1)
            if m["ecart_max"] is not None:
                ligne["ecart_max"] = max(ligne.get("ecart_max", m["ecart_max"]), m["ecart_max"])
        ligne[nom] = hits / len(images) >= 0.5
    return ligne


def reference_depuis(chemin, params):
    """(champ médian, unité) d'un enregistrement d'habitacle vide, décodé comme le fait le banc."""
    vide = np.load(chemin, allow_pickle=False)
    vide = vide[None] if vide.ndim == 2 else vide
    source = SourceThermique("rejeu", 0, "Rejeu", params)
    champs = [source.champ(f) for f in vide]
    champs = [(c, u) for c, u in champs if c is not None]
    if not champs:
        sys.exit(f"{chemin} : aucune mesure exploitable (flux 8 bits ou converti en couleur).")
    return np.median([c for c, _ in champs], axis=0).astype(np.float32), champs[0][1]


def cmd_rejouer(a):
    cfg = charger_config(str(RACINE))
    params = cfg["thermique"]
    dossier = Path(a.dossier)
    fichiers = sorted(p for p in dossier.rglob("*.npy") if not p.name.endswith("_diagnostic.npy"))
    if not fichiers:
        print(f"Aucune image dans {dossier}")
        return 1
    reference = reference_depuis(a.reference, params) if a.reference else None
    for f in fichiers:
        l = rejouer_fichier(f, params, reference)
        verdicts = "  ".join(f"{k}={'CHAUD' if v else 'rien'}" for k, v in l.items()
                             if k not in ("fichier", "resolution", "tmax", "ecart_max"))
        ecart = "" if l.get("ecart_max") is None else f"  écart max {l['ecart_max']:.0f}"
        print(f"{l['fichier']:50} {l['resolution']:>9}  max {l['tmax']}{ecart}  {verdicts}")
    return 0


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sous = ap.add_subparsers(dest="commande", required=True)
    p = sous.add_parser("sonder")
    p.add_argument("--index", type=int)
    p.add_argument("--appliquer", action="store_true", help="écrit les réglages dans config.local.json")
    p.add_argument("--forcer", action="store_true", help="écrit même si le banc est réglé pour la caméra InfiRay")
    p.set_defaults(fn=cmd_sonder)
    p = sous.add_parser("direct")
    p.add_argument("--nom", default="scene")
    p.set_defaults(fn=cmd_direct)
    p = sous.add_parser("zones")
    p.set_defaults(fn=cmd_zones)
    p = sous.add_parser("enregistrer")
    p.add_argument("nom")
    p.add_argument("--images", type=int, default=30)
    p.set_defaults(fn=cmd_enregistrer)
    p = sous.add_parser("rejouer")
    p.add_argument("--dossier", default=str(DOSSIER_BRUTES.parent))
    p.add_argument("--reference", help=".npy d'un habitacle vide, pour comparer à la méthode référence")
    p.set_defaults(fn=cmd_rejouer)
    a = ap.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
