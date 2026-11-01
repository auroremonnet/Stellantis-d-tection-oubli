"""Envoie une notification de test sur le topic ntfy configuré, sans caméra ni modèle.

    python test_alerte.py

À recevoir dans l'appli ntfy (abonnée au topic de config.json) avant les essais réels.
"""
import json
import os
from datetime import datetime

import cv2
import numpy as np

from care.alertes import Alerteur

RACINE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(RACINE, "config.json"), encoding="utf-8") as fh:
    cfg = json.load(fh).get("alertes")

alerteur = Alerteur(cfg)
image = np.zeros((360, 640, 3), np.uint8)
cv2.putText(image, "CARE - image de test", (150, 190), cv2.FONT_HERSHEY_SIMPLEX, 0.8,
            (255, 255, 255), 2, cv2.LINE_AA)

print(f"Envoi d'une notification de test vers https://ntfy.sh/{alerteur.topic} ...")
if alerteur.envoyer("CARE · Test", f"Notification de test envoyée à {datetime.now():%H:%M:%S}", image):
    print("Notification envoyée : elle doit apparaître sur le téléphone dans quelques secondes.")
else:
    print("Échec de l'envoi : vérifier la connexion internet et le topic dans config.json.")
