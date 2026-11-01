"""Alertes téléphone via ntfy.sh (gratuit, sans compte : le topic fait office de mot de passe).

Reçoit des `Alerte` déjà décidées (care/decision.py) et se charge de l'envoi :
    - une notification par alerte, avec l'image annotée de l'analyse ;
    - cooldown par objet (`cooldown_s`) : pas deux fois le même objet coup sur coup d'un
      essai à l'autre. Jamais pour une alerte critique (enfant, animal) ; les rappels
      d'escalade passent outre et la levée d'alerte remet le compteur à zéro ;
    - priorité ntfy « urgent » pour le critique (sonne même en mode silencieux sur Android) ;
    - l'envoi part dans un thread : une panne réseau ne bloque jamais le banc.

Les libellés surveillés sont les libellés français du détecteur (« téléphone »,
« portefeuille », « clés »…), indépendants du moteur (COCO, YOLOE ou modèle entraîné).
"""
from __future__ import annotations

import threading
import time

import cv2
import requests

DEFAUTS = {
    "actif": True,
    "topic": "care-stellantis-g2-CHANGEMOI",
    "serveur": "https://ntfy.sh",
    "classes_surveillees": None,      # None = tous les objets de valeur du détecteur
    "alerter_objet_inconnu": True,    # zone nouvelle non reconnue → alerte quand même
    "cooldown_s": 60,
}
MOTIFS = {
    "alerte": "",
    "rappel": "RAPPEL · ",
    "acquittement": "Alerte levée · ",
}


class Alerteur:
    def __init__(self, cfg: dict | None = None, envoi_synchrone: bool = False):
        cfg = {**DEFAUTS, **(cfg or {})}
        self.actif = bool(cfg["actif"])
        self.topic = cfg["topic"]
        self.serveur = cfg["serveur"].rstrip("/")
        cs = cfg["classes_surveillees"]
        self.surveillees = None if cs is None else frozenset(cs)
        self.alerter_inconnu = bool(cfg["alerter_objet_inconnu"])
        self.cooldown = float(cfg["cooldown_s"])
        self._synchrone = envoi_synchrone
        self._derniere = {}           # élément -> horodatage du dernier envoi
        self._lock = threading.Lock()
        self.envois = 0               # compteur (affiché dans le dashboard)
        self.derniere_erreur = ""

    def notifier(self, alerte, image=None, motif: str = "alerte") -> bool:
        """Programme l'envoi de l'alerte ; renvoie False si rien n'est envoyé
        (alertes coupées ou cooldown)."""
        if not self.actif or alerte is None:
            return False
        now = time.time()
        with self._lock:
            if motif == "acquittement":
                # le conducteur est revenu : un nouvel oubli doit pouvoir réalerter tout de suite
                for e in alerte.elements:
                    self._derniere.pop(e, None)
            elif motif == "alerte" and alerte.niveau != "critique":
                # anti-spam pour les objets seulement : une présence vivante n'est JAMAIS filtrée
                frais = [e for e in alerte.elements if now - self._derniere.get(e, 0) >= self.cooldown]
                if not frais:
                    return False
            if motif != "acquittement":
                for e in alerte.elements:
                    self._derniere[e] = now
        titre = MOTIFS.get(motif, "") + alerte.titre
        if motif == "acquittement":
            message, priorite, tags = "Le conducteur est revenu au véhicule.", "default", "white_check_mark"
            image = None
        else:
            message, priorite, tags = alerte.message, alerte.priorite, alerte.tags
        args = (titre, message, image, priorite, tags)
        if self._synchrone:
            return self.envoyer(*args)
        threading.Thread(target=self.envoyer, args=args, daemon=True).start()
        return True

    def envoyer(self, titre, message, image=None, priorite="high",
                tags="rotating_light,oncoming_automobile") -> bool:
        """Envoi synchrone vers ntfy ; renvoie True si la notification est partie.
        Titre/message/priorité en query params (les headers HTTP cassent les accents)."""
        corps = b""
        params = {"title": titre, "message": message, "priority": priorite, "tags": tags}
        if image is not None:
            ok, buf = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if ok:
                corps = buf.tobytes()
                params["filename"] = "detection.jpg"
        try:
            r = requests.put(f"{self.serveur}/{self.topic}", data=corps, params=params, timeout=10)
            r.raise_for_status()
            self.envois += 1
            self.derniere_erreur = ""
            return True
        except Exception as e:  # noqa: BLE001 — une panne réseau ne doit jamais arrêter le banc
            self.derniere_erreur = str(e)
            print(f"[alertes] envoi ntfy impossible : {e}")
            return False

    def etat(self) -> dict:
        return {"actif": self.actif, "topic": self.topic, "envois": self.envois,
                "erreur": self.derniere_erreur}
