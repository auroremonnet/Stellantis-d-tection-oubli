"""Alertes téléphone via ntfy.sh : objet de valeur détecté alors que personne n'est là.

L'Alerteur reçoit chaque frame analysée par le détecteur (voir Detecteur.analyser)
et décide seul d'alerter :
  - l'objet doit être vu en continu pendant `delai_confirmation_s` (anti-fausse alerte) ;
  - aucune personne vue depuis `delai_absence_s` (le conducteur est parti) ;
  - au plus une alerte par objet toutes les `cooldown_s` secondes (anti-spam).
L'envoi part dans un thread et une erreur réseau se limite à un print.
"""
import threading
import time
from datetime import datetime

import cv2
import requests

from care.detecteur import VALEUR

PERSONNE = 0  # id COCO de « person »

DEFAUTS = {
    "actif": True,
    "topic": "care-stellantis-g2-CHANGEMOI",
    "classes_surveillees": sorted(VALEUR.values()),
    "delai_absence_s": 10,
    "delai_confirmation_s": 3,
    "cooldown_s": 60,
}


class Alerteur:
    def __init__(self, cfg=None):
        cfg = {**DEFAUTS, **(cfg or {})}
        self.actif = cfg["actif"]
        self.topic = cfg["topic"]
        self.surveillees = {c for c, nom in VALEUR.items() if nom in set(cfg["classes_surveillees"])}
        self.delai_absence = cfg["delai_absence_s"]
        self.delai_confirmation = cfg["delai_confirmation_s"]
        self.cooldown = cfg["cooldown_s"]
        t = time.time()
        self._derniere_personne = t  # au démarrage, on suppose quelqu'un présent
        self._premiere_vue = {}      # id classe -> début de détection continue
        self._derniere_alerte = {}   # id classe -> dernière alerte envoyée

    def traiter(self, vus, images):
        """À appeler à chaque frame : vus = liste d'ensembles d'ids COCO (un par
        caméra), images = images annotées correspondantes."""
        if not self.actif:
            return
        now = time.time()
        tous = set().union(*vus) if vus else set()
        if PERSONNE in tous:
            self._derniere_personne = now
        for c in list(self._premiere_vue):
            if c not in tous:  # détection interrompue : on repart de zéro
                del self._premiere_vue[c]
        for c in tous & self.surveillees:
            self._premiere_vue.setdefault(c, now)
            if (now - self._derniere_personne < self.delai_absence
                    or now - self._premiere_vue[c] < self.delai_confirmation
                    or now - self._derniere_alerte.get(c, 0) < self.cooldown):
                continue
            self._derniere_alerte[c] = now
            img = next((im for v, im in zip(vus, images) if c in v), None)
            nom = VALEUR[c]
            message = f"{nom[0].upper()}{nom[1:]} oublié{'e' if nom == 'valise' else ''} dans le véhicule à {datetime.now():%H:%M:%S}"
            threading.Thread(target=self.envoyer, args=("CARE · Objet oublié", message, img),
                             daemon=True).start()

    def envoyer(self, titre, message, image=None):
        """Envoi synchrone vers ntfy.sh ; renvoie True si la notification est partie.
        Titre/message/priorité en query params (les headers HTTP cassent les accents)."""
        corps = b""
        if image is not None:
            ok, buf = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if ok:
                corps = buf.tobytes()
        try:
            r = requests.put(
                f"https://ntfy.sh/{self.topic}", data=corps, timeout=10,
                params={"title": titre, "message": message, "priority": "high",
                        "tags": "rotating_light,oncoming_automobile", "filename": "detection.jpg"})
            r.raise_for_status()
            return True
        except Exception as e:  # noqa: BLE001 — une panne réseau ne doit jamais arrêter le banc
            print(f"[alertes] envoi ntfy impossible : {e}")
            return False
