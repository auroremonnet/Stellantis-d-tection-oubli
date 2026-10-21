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
from care.detecteur import Detecteur, DetecteurDemo, mosaique
from care.stockage import Journal, metriques

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
os.makedirs(IMAGES, exist_ok=True)
JOURNAL = Journal(os.path.join(DATA, "essais.csv"))

# ---- Matériel ------------------------------------------------------------
ClsRGB, ClsTh = (SourceDemo, SourceThermiqueDemo) if DEMO else (Source, SourceThermique)
RGB = [ClsRGB(c["id"], c["index"], c["label"], CFG["resolution"]).demarrer() for c in CFG["cameras_rgb"]]
cth = CFG["camera_thermique"]
THERM = ClsTh(cth["id"], cth["index"], cth["label"], CFG["thermique"]).demarrer() if cth.get("active") else None
SOURCES = {s.id: s for s in RGB + ([THERM] if THERM else [])}
ALERTEUR = Alerteur(CFG.get("alertes"))
DETECTEUR = (DetecteurDemo if DEMO else Detecteur)(CFG, alerteur=ALERTEUR)

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


# ---- API -----------------------------------------------------------------
@app.route("/api/etat")
def etat():
    return jsonify({
        "demo": DEMO,
        "modele": {"pret": DETECTEUR.pret, "nom": CFG["modele"], "erreur": DETECTEUR.erreur},
        "rgb": [s.etat() for s in RGB],
        "thermique": THERM.etat() if THERM else None,
    })


@app.route("/api/config")
def config():
    return jsonify({k: CFG[k] for k in ("scenarios", "variantes", "images_par_essai", "repetitions_cible")})


@app.route("/api/essais")
def essais():
    lignes = JOURNAL.lire()
    return jsonify({"essais": lignes[::-1], "metriques": metriques(lignes)})


@app.route("/api/essais", methods=["POST"])
def nouvel_essai():
    d = request.get_json(force=True)
    if d.get("verite") not in ("vivant", "objet", "vide") or not d.get("scenario"):
        return jsonify({"erreur": "Scénario et vérité terrain obligatoires"}), 400
    if DEMO:  # la scène simulée suit la vérité terrain déclarée
        for s in SOURCES.values():
            s.scene = d["verite"]
        time.sleep(0.3)
    try:
        r = DETECTEUR.analyser(RGB, THERM, d["verite"])
    except RuntimeError as e:
        return jsonify({"erreur": str(e)}), 503
    finally:
        if DEMO:
            for s in SOURCES.values():
                s.scene = "vide"

    eid = datetime.now().strftime("%Y%m%d-%H%M%S")
    m = mosaique(r["images_rgb"])
    if m is not None:
        cv2.imwrite(os.path.join(IMAGES, f"{eid}_rgb.jpg"), m)
    if r["image_thermique"] is not None:
        cv2.imwrite(os.path.join(IMAGES, f"{eid}_th.jpg"), r["image_thermique"])

    ligne = {k: v for k, v in r.items() if k not in ("images_rgb", "image_thermique")}
    ligne.update({"id": eid, "horodatage": datetime.now().isoformat(timespec="seconds"),
                  "scenario": d["scenario"], "variante": d.get("variante", ""),
                  "verite": d["verite"], "commentaire": d.get("commentaire", "")})
    JOURNAL.ajouter(ligne)
    return jsonify(next(l for l in JOURNAL.lire() if l["id"] == eid))


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
