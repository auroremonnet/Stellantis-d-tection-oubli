"""Alertes téléphone via ntfy.sh : objet de valeur détecté alors que personne n'est là.

L'Alerteur travaille au rythme des essais : pendant Detecteur.analyser il accumule,
frame par frame, les objets surveillés vus (et garde la meilleure image annotée par
objet), puis conclure_essai() décide :
  - alerte seulement si aucune personne n'a été vue sur tout l'essai (toutes caméras) ;
  - un objet est retenu s'il est vu dans au moins `ratio_confirmation` des frames ;
  - au plus une notification par essai, listant tous les objets oubliés ;
  - cooldown par objet de `cooldown_s` secondes entre deux essais (anti-spam).
L'envoi part dans un thread et une erreur réseau se limite à un print.
"""
import threading
import time
from datetime import datetime

import cv2
import requests

from care.detecteur import VALEUR

PERSONNE = 0  # id COCO de « person »
FEMININS = {"valise"}

DEFAUTS = {
    "actif": True,
    "topic": "care-stellantis-g2-CHANGEMOI",
    "classes_surveillees": sorted(VALEUR.values()),
    "ratio_confirmation": 0.5,
    "cooldown_s": 60,
}


class Alerteur:
    def __init__(self, cfg=None):
        cfg = {**DEFAUTS, **(cfg or {})}
        self.actif = cfg["actif"]
        self.topic = cfg["topic"]
        self.surveillees = {c for c, nom in VALEUR.items() if nom in set(cfg["classes_surveillees"])}
        self.ratio_confirmation = cfg["ratio_confirmation"]
        self.cooldown = cfg["cooldown_s"]
        self._derniere_alerte = {}  # id classe -> dernière alerte envoyée (persiste entre essais)
        self._reinitialiser()

    def _reinitialiser(self):
        self._frames = 0        # itérations de l'essai en cours
        self._personne = False  # une personne vue sur au moins une frame ?
        self._compte = {}       # id classe -> nb d'itérations où l'objet est vu
        self._meilleure = {}    # id classe -> (confiance max, image annotée)

    def traiter(self, vus, images):
        """À appeler à chaque frame de l'essai : vus = liste de {id COCO: confiance max}
        (un dict par caméra), images = images annotées correspondantes."""
        if not self.actif:
            return
        self._frames += 1
        if any(PERSONNE in v for v in vus):
            self._personne = True
        for c in self.surveillees:
            confs = [(v[c], img) for v, img in zip(vus, images) if c in v]
            if confs:
                self._compte[c] = self._compte.get(c, 0) + 1
                conf, img = max(confs, key=lambda t: t[0])
                if conf > self._meilleure.get(c, (0.0, None))[0]:
                    self._meilleure[c] = (conf, img)

    def conclure_essai(self):
        """À la fin de l'essai : au plus une notification, listant tous les objets oubliés."""
        if not self.actif or not self._frames:
            return
        now = time.time()
        oublies = []
        if not self._personne:
            oublies = sorted(
                c for c, k in self._compte.items()
                if k / self._frames >= self.ratio_confirmation
                and now - self._derniere_alerte.get(c, 0) >= self.cooldown)
        if oublies:
            for c in oublies:
                self._derniere_alerte[c] = now
            noms = [VALEUR[c] for c in oublies]
            liste = " et ".join([", ".join(noms[:-1]), noms[-1]] if len(noms) > 1 else noms)
            if len(noms) > 1:
                accord = "oubliés"
            else:
                accord = "oubliée" if noms[0] in FEMININS else "oublié"
            message = (f"{liste[0].upper()}{liste[1:]} {accord} dans le véhicule"
                       f" à {datetime.now():%H:%M:%S}")
            img = max((self._meilleure[c] for c in oublies), key=lambda t: t[0])[1]
            threading.Thread(target=self.envoyer, args=("CARE · Objet oublié", message, img),
                             daemon=True).start()
        self._reinitialiser()

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
