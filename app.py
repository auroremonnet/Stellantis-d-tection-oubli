"""CARE - Groupe 2 - Dashboard de test « détection d'oubli dans l'habitacle »

    python app.py            # avec le matériel (config.json)
    python app.py --demo     # sans matériel, flux et détections simulés

Puis ouvrir http://localhost:5000
"""
import argparse
import json
import os
import time
import webbrowser
from datetime import datetime
from threading import Timer

import cv2
from flask import Flask, Response, abort, jsonify, render_template, request, send_file, send_from_directory

from care.alertes import Alerteur
from care.cameras import Source, SourceDemo, SourceThermique, SourceThermiqueDemo
from care.decision import decider
from care.detecteur import Detecteur, DetecteurDemo, mosaique
from care.reference import Reference
from care.stockage import Journal, metriques
from care.surveillance import Branchements, MachineOubli, Parametres, Superviseur

RACINE = os.path.dirname(os.path.abspath(__file__))

parser = argparse.ArgumentParser()
parser.add_argument("--demo", action="store_true", help="flux et détections simulés")
parser.add_argument("--port", type=int, default=5000)
parser.add_argument("--no-browser", action="store_true")
ARGS = parser.parse_args()

with open(os.path.join(RACINE, "config.json"), encoding="utf-8") as fh:
    CFG = json.load(fh)

DEMO = ARGS.demo
DATA = os.path.join(RACINE, "data", "demo" if DEMO else "essais")
IMAGES = os.path.join(DATA, "images")
BRUTES = os.path.join(DATA, "brutes")      # images sans annotation, pour enrichir le dataset
os.makedirs(IMAGES, exist_ok=True)
JOURNAL = Journal(os.path.join(DATA, "essais.csv"))
EVENEMENTS = os.path.join(DATA, "evenements.jsonl")
VERITES = ("vivant", "objet", "vide")

# ---- Matériel ------------------------------------------------------------
ClsRGB, ClsTh = (SourceDemo, SourceThermiqueDemo) if DEMO else (Source, SourceThermique)
RGB = [ClsRGB(c["id"], c["index"], c["label"], CFG["resolution"]).demarrer() for c in CFG["cameras_rgb"]]
cth = CFG["camera_thermique"]
THERM = ClsTh(cth["id"], cth["index"], cth["label"], CFG["thermique"]).demarrer() if cth.get("active") else None
SOURCES = {s.id: s for s in RGB + ([THERM] if THERM else [])}
DETECTEUR = (DetecteurDemo if DEMO else Detecteur)(CFG)
REF_PARAMS = {"iou_fixe": 0.5, "seuil_changement": 35, "aire_min": 1500, "part_max_image": 0.6, "zones_max": 6}
REF_PARAMS.update(CFG.get("reference", {}))
REFERENCE = Reference(os.path.join(DATA, "reference"), REF_PARAMS)

CFG_ALERTES = dict(CFG.get("alertes", {}))
if DEMO and not CFG_ALERTES.get("en_demo", False):
    CFG_ALERTES["actif"] = False  # pas de notification réelle en démo, sauf demande explicite
ALERTEUR = Alerteur(CFG_ALERTES)


# ---- Enregistrement commun (essai manuel et surveillance automatique) ----------
def _capturer_brutes():
    return {s.id: f for s in RGB if (f := s.derniere()) is not None}


def _enregistrer(r, contexte, mode, brutes=None, niveau_alerte=None):
    """Sauve les images et, si la vérité terrain est connue, ajoute la ligne au journal."""
    eid = r.get("id") or datetime.now().strftime("%Y%m%d-%H%M%S")
    m = mosaique(r.get("images_rgb") or [])
    if m is not None:
        cv2.imwrite(os.path.join(IMAGES, f"{eid}_rgb.jpg"), m)
    if r.get("image_thermique") is not None:
        cv2.imwrite(os.path.join(IMAGES, f"{eid}_th.jpg"), r["image_thermique"])
    if brutes and CFG.get("sauver_images_brutes", True):
        os.makedirs(BRUTES, exist_ok=True)
        for sid, f in brutes.items():
            cv2.imwrite(os.path.join(BRUTES, f"{eid}_{sid}.jpg"), f)
    if contexte.get("verite") not in VERITES or not contexte.get("scenario"):
        return eid, None  # surveillance « libre » : pas de vérité terrain, pas de ligne au journal
    ligne = {k: v for k, v in r.items() if not k.startswith("image")}
    ligne.update({"id": eid, "horodatage": datetime.now().isoformat(timespec="seconds"),
                  "scenario": contexte["scenario"], "variante": contexte.get("variante", ""),
                  "verite": contexte["verite"], "commentaire": contexte.get("commentaire", ""),
                  "moteur": DETECTEUR.moteur, "mode": mode,
                  "alerte": niveau_alerte or ""})
    JOURNAL.ajouter(ligne)
    return eid, next((l for l in JOURNAL.lire() if l["id"] == eid), None)


def _journaliser_evenement(evt):
    with open(EVENEMENTS, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({**evt.en_dict(), "source": "surveillance"}, ensure_ascii=False) + "\n")


# ---- Surveillance automatique (simulation de l'oubli de bout en bout) ----------
def _analyser_surveillance(contexte):
    brutes = _capturer_brutes()
    r = DETECTEUR.analyser(RGB, THERM, contexte.get("verite"), reference=None if DEMO else REFERENCE)
    r["id"] = datetime.now().strftime("%Y%m%d-%H%M%S")
    r["_brutes"] = brutes
    return r


def _enregistrer_surveillance(r, contexte):
    alerte = r.get("alerte") or {}
    _enregistrer(r, contexte, "auto", r.pop("_brutes", None), alerte.get("niveau"))


def _demo_scene(scene):
    for s in SOURCES.values():
        if hasattr(s, "scene"):
            s.scene = scene


SUPERVISEUR = Superviseur(
    MachineOubli(Parametres.depuis_config(CFG.get("surveillance"))),
    Branchements(
        presence_adulte=lambda: DETECTEUR.presence_adulte(RGB),
        analyser=_analyser_surveillance,
        decider=lambda r: decider(r, habitacle_vide_attendu=True,
                                  objets_surveilles=ALERTEUR.surveillees,
                                  alerter_inconnu=ALERTEUR.alerter_inconnu),
        notifier=lambda alerte, r, motif: ALERTEUR.notifier(
            alerte, mosaique(r.get("images_rgb") or []), motif),
        enregistrer=_enregistrer_surveillance,
        journaliser=_journaliser_evenement,
    ),
    periode_s=float(CFG.get("surveillance", {}).get("periode_s", 0.5)),
)

app = Flask(__name__)


def _jpeg(img, qualite=70):
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, qualite])
    return buf.tobytes() if ok else None


# ---- Pages ---------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/snapshot/<sid>")
def snapshot(sid):
    s = SOURCES.get(sid)
    if s is None:
        abort(404)
    img = s.apercu()
    if img is None:
        abort(503)
    if img.shape[1] > 640:
        img = cv2.resize(img, (640, int(640 * img.shape[0] / img.shape[1])))
    return Response(_jpeg(img), mimetype="image/jpeg", headers={"Cache-Control": "no-store"})


@app.route("/images/<path:nom>")
def images(nom):
    return send_from_directory(IMAGES, nom)


@app.route("/reference/<sid>.jpg")
def image_reference(sid):
    img = REFERENCE.images.get(sid)
    if img is None:
        abort(404)
    if img.shape[1] > 640:
        img = cv2.resize(img, (640, int(640 * img.shape[0] / img.shape[1])))
    return Response(_jpeg(img), mimetype="image/jpeg", headers={"Cache-Control": "no-store"})


# ---- API -----------------------------------------------------------------
@app.route("/api/etat")
def etat():
    return jsonify({
        "demo": DEMO,
        "modele": {"pret": DETECTEUR.pret, "nom": DETECTEUR.modele, "moteur": DETECTEUR.moteur,
                   "erreur": DETECTEUR.erreur, "avertissement": DETECTEUR.avertissement,
                   "custom": DETECTEUR.custom is not None},
        "alertes": ALERTEUR.etat(),
        "rgb": [s.etat() for s in RGB],
        "thermique": THERM.etat() if THERM else None,
        "reference": REFERENCE.etat(),
    })


@app.route("/api/config")
def config():
    out = {k: CFG[k] for k in ("scenarios", "variantes", "images_par_essai", "repetitions_cible")}
    out["detection"] = {"moteur": DETECTEUR.moteur, "modele": DETECTEUR.modele,
                        "prompts_vivant": DETECTEUR.prompts_vivant, "prompts_valeur": DETECTEUR.prompts_valeur}
    return jsonify(out)


@app.route("/api/reference", methods=["POST"])
def capturer_reference():
    if DEMO:
        return jsonify({"erreur": "Pas de référence en mode démo"}), 400
    if not DETECTEUR.pret:
        return jsonify({"erreur": "Modèle pas encore chargé"}), 503
    if not any(s.derniere() is not None for s in RGB):
        return jsonify({"erreur": "Aucune image caméra disponible"}), 503
    return jsonify(REFERENCE.capturer(RGB, DETECTEUR))


@app.route("/api/reference", methods=["DELETE"])
def effacer_reference():
    REFERENCE.effacer()
    return jsonify(REFERENCE.etat())


@app.route("/api/essais")
def essais():
    lignes = JOURNAL.lire()
    return jsonify({"essais": lignes[::-1], "metriques": metriques(lignes)})


@app.route("/api/essais", methods=["POST"])
def nouvel_essai():
    d = request.get_json(force=True)
    if d.get("verite") not in ("vivant", "objet", "vide") or not d.get("scenario"):
        return jsonify({"erreur": "Scénario et vérité terrain obligatoires"}), 400
    if SUPERVISEUR.actif:
        return jsonify({"erreur": "Surveillance automatique en cours : la désarmer d'abord"}), 409
    if DEMO:  # la scène simulée suit la vérité terrain déclarée
        _demo_scene(d["verite"])
        time.sleep(0.3)
    brutes = _capturer_brutes()
    try:
        r = DETECTEUR.analyser(RGB, THERM, d["verite"], reference=None if DEMO else REFERENCE)
    except RuntimeError as e:
        return jsonify({"erreur": str(e)}), 503
    finally:
        if DEMO:
            _demo_scene("vide")

    # Essai manuel : règle d'origine des alertes (un adulte présent annule l'alerte objet)
    alerte = decider(r, habitacle_vide_attendu=False, objets_surveilles=ALERTEUR.surveillees,
                     alerter_inconnu=ALERTEUR.alerter_inconnu)
    if alerte is not None:
        ALERTEUR.notifier(alerte, mosaique(r["images_rgb"]))
    _eid, ligne = _enregistrer(r, d, "manuel", brutes, alerte and alerte.niveau)
    return jsonify(ligne)


# ---- API surveillance automatique -----------------------------------------
@app.route("/api/surveillance")
def surveillance_etat():
    return jsonify(SUPERVISEUR.instantane())


@app.route("/api/surveillance/armer", methods=["POST"])
def surveillance_armer():
    d = request.get_json(silent=True) or {}
    if d.get("verite") and d["verite"] not in VERITES:
        return jsonify({"erreur": f"Vérité terrain inconnue : {d['verite']}"}), 400
    if not DETECTEUR.pret:
        return jsonify({"erreur": "Modèle pas encore chargé"}), 503
    if not DEMO and d.get("capturer_reference", True):
        if not any(s.derniere() is not None for s in RGB):
            return jsonify({"erreur": "Aucune image caméra disponible"}), 503
        REFERENCE.capturer(RGB, DETECTEUR)  # habitacle vide au moment d'armer
    if DEMO:
        _demo_scene("vide")
    contexte = {k: d.get(k, "") for k in ("scenario", "variante", "verite", "commentaire")}
    SUPERVISEUR.armer(contexte)
    return jsonify(SUPERVISEUR.instantane())


@app.route("/api/surveillance/desarmer", methods=["POST"])
def surveillance_desarmer():
    SUPERVISEUR.desarmer()
    if DEMO:
        _demo_scene("vide")
    return jsonify(SUPERVISEUR.instantane())


@app.route("/api/surveillance/verrouiller", methods=["POST"])
def surveillance_verrouiller():
    SUPERVISEUR.verrouiller()
    return jsonify(SUPERVISEUR.instantane())


@app.route("/api/surveillance/demo", methods=["POST"])
def surveillance_demo():
    """Mode démo uniquement : le conducteur monte (True) ou descend (False). En descendant,
    il laisse dans l'habitacle ce que prévoit la vérité terrain du scénario armé."""
    if not DEMO:
        abort(404)
    occupant = bool((request.get_json(silent=True) or {}).get("occupant"))
    verite = SUPERVISEUR.contexte.get("verite") or "vide"
    _demo_scene("conducteur" if occupant else verite)
    return jsonify(SUPERVISEUR.instantane())


@app.route("/api/essais/<eid>", methods=["DELETE"])
def supprimer(eid):
    JOURNAL.supprimer(eid)
    for suffixe in ("_rgb.jpg", "_th.jpg"):
        p = os.path.join(IMAGES, eid + suffixe)
        if os.path.exists(p):
            os.remove(p)
    return jsonify({"ok": True})


@app.route("/api/export")
def export():
    return send_file(JOURNAL.chemin, as_attachment=True,
                     download_name=f"care_essais_{datetime.now():%Y%m%d}.csv")


if __name__ == "__main__":
    url = f"http://localhost:{ARGS.port}"
    print(f"\n  CARE dashboard {'(DÉMO) ' if DEMO else ''}-> {url}\n")
    if not ARGS.no_browser:
        Timer(1.5, lambda: webbrowser.open(url)).start()
    app.run(host="0.0.0.0", port=ARGS.port, threaded=True, debug=False)
