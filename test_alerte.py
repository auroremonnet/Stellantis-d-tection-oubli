"""Envoie une notification de test sur le topic ntfy configuré, sans caméra ni modèle.

    python test_alerte.py

Le topic est lu exactement comme par app.py : `config.json`, puis la section « alertes »
de `config.local.json` (hors dépôt) par-dessus, puis la variable d'environnement
`CARE_NTFY_TOPIC`. À recevoir dans l'appli ntfy abonnée à ce topic avant les essais réels.
"""
import json
import os
from datetime import datetime

import cv2
import numpy as np

from care.alertes import Alerteur

RACINE = os.path.dirname(os.path.abspath(__file__))


def _alertes(nom: str) -> dict:
    """Section « alertes » d'un fichier de configuration (vide s'il n'existe pas)."""
    chemin = os.path.join(RACINE, nom)
    if not os.path.exists(chemin):
        return {}
    with open(chemin, encoding="utf-8") as fh:
        return json.load(fh).get("alertes") or {}


# Le dépôt est public : le vrai topic ne vit que dans config.local.json ou dans
# l'environnement. Même ordre de priorité que app.py.
cfg = {**_alertes("config.json"), **_alertes("config.local.json")}
if os.environ.get("CARE_NTFY_TOPIC"):
    cfg["topic"] = os.environ["CARE_NTFY_TOPIC"]

alerteur = Alerteur(cfg)
image = np.zeros((360, 640, 3), np.uint8)
cv2.putText(image, "CARE - image de test", (150, 190), cv2.FONT_HERSHEY_SIMPLEX, 0.8,
            (255, 255, 255), 2, cv2.LINE_AA)

print(f"Envoi d'une notification de test vers {alerteur.serveur}/{alerteur.topic} ...")
if alerteur.envoyer("CARE · Test", f"Notification de test envoyée à {datetime.now():%H:%M:%S}", image):
    print("Notification envoyée : elle doit apparaître sur le téléphone dans quelques secondes.")
else:
    print(f"Échec de l'envoi : {alerteur.derniere_erreur}")
    print("Vérifier la connexion internet et le topic (config.local.json ou CARE_NTFY_TOPIC).")
