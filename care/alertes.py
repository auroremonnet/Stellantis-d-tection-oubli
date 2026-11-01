"""Alertes téléphone via ntfy.sh (gratuit, sans compte : le topic fait office de mot de passe).

Reçoit des `Alerte` déjà décidées (care/decision.py) et se charge de l'envoi :
    - une notification par alerte, avec l'image annotée de l'analyse ;
    - cooldown par objet (`cooldown_s`) : pas deux fois le même objet coup sur coup d'un
      essai à l'autre. Jamais pour une alerte critique (enfant, animal) ; les rappels
      d'escalade passent outre et la levée d'alerte remet le compteur à zéro ;
    - priorité ntfy « urgent » pour le critique (sonne même en mode silencieux sur Android) ;
    - l'envoi part dans un thread : une panne réseau ne bloque jamais le banc ;
    - garde-fou : rien ne part tant que le topic n'a pas été remplacé (le dépôt est public,
      le vrai topic vit dans config.local.json ou dans CARE_NTFY_TOPIC) ;
    - bouton « Je m'en occupe » sur les alertes critiques et les rappels : un appui lève
      l'alerte sur le banc (voir `url_banc`), sans attendre le retour du conducteur ;
    - un appui sur la notification elle-même ouvre la page de suivi du banc (`/suivi`).

Les libellés surveillés sont les libellés français du détecteur (« téléphone »,
« portefeuille », « clés »…), indépendants du moteur (COCO, YOLOE ou modèle entraîné).
"""
from __future__ import annotations

import threading
import time

import cv2
import requests

# Un topic qui contient ce mot n'a pas été configuré : on refuse d'envoyer (sinon la
# notification part sur un topic public que n'importe qui peut lire ou alimenter).
SENTINELLE_TOPIC = "CHANGEMOI"

DEFAUTS = {
    "actif": True,
    "topic": "CHANGEMOI-voir-config.local.json",
    "serveur": "https://ntfy.sh",
    "classes_surveillees": None,      # None = tous les objets de valeur du détecteur
    "alerter_objet_inconnu": True,    # zone nouvelle non reconnue → alerte quand même
    "cooldown_s": 60,
    "url_banc": "",                   # ex. http://192.168.1.90:5000 — hors dépôt (config.local.json)
}
MOTIFS = {
    "alerte": "",
    "rappel": "RAPPEL · ",
    "acquittement": "Alerte levée · ",
    "acquittement_distant": "Alerte levée · ",
}
ACQUITTEMENTS = frozenset({"acquittement", "acquittement_distant"})
MESSAGES_ACQUITTEMENT = {
    "acquittement": "Le conducteur est revenu au véhicule.",
    "acquittement_distant": "Alerte prise en charge depuis la notification : "
                            "les rappels sont arrêtés.",
}
# Titre complet, et non préfixe + titre de l'alerte : sur le téléphone, « pris en charge à
# distance » doit se distinguer d'un retour réellement constaté du conducteur.
TITRES_ACQUITTEMENT = {"acquittement_distant": "Alerte levée · pris en charge à distance"}

# Bouton d'action de la notification : un POST sur le banc lève l'alerte et stoppe les rappels.
LIBELLE_ACQUITTEMENT = "Je m'en occupe"
CHEMIN_ACQUITTEMENT = "/api/surveillance/acquitter"
CHEMIN_SUIVI = "/suivi"           # page ouverte en touchant la notification


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
        self.url_banc = str(cfg["url_banc"] or "").rstrip("/")
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
        acquittement = motif in ACQUITTEMENTS
        with self._lock:
            if acquittement:
                # l'alerte est levée : un nouvel oubli doit pouvoir réalerter tout de suite
                for e in alerte.elements:
                    self._derniere.pop(e, None)
            elif motif == "alerte" and alerte.niveau != "critique":
                # anti-spam pour les objets seulement : une présence vivante n'est JAMAIS filtrée
                frais = [e for e in alerte.elements if now - self._derniere.get(e, 0) >= self.cooldown]
                if not frais:
                    return False
            if not acquittement:
                for e in alerte.elements:
                    self._derniere[e] = now
        titre = TITRES_ACQUITTEMENT.get(motif) or MOTIFS.get(motif, "") + alerte.titre
        if acquittement:
            message, priorite, tags = MESSAGES_ACQUITTEMENT[motif], "default", "white_check_mark"
            image = None
        else:
            message, priorite, tags = alerte.message, alerte.priorite, alerte.tags
        args = (titre, message, image, priorite, tags, self._actions(alerte, motif), self.lien_suivi)
        if self._synchrone:
            return self.envoyer(*args)
        threading.Thread(target=self.envoyer, args=args, daemon=True).start()
        return True

    @property
    def lien_suivi(self) -> str:
        """Page ouverte en touchant la notification (en-tête ntfy « Click ») : l'état du banc,
        la dernière alerte et le bouton d'acquittement, lisibles sur un téléphone."""
        return f"{self.url_banc}{CHEMIN_SUIVI}" if self.url_banc else ""

    def _actions(self, alerte, motif: str) -> str:
        """En-tête ntfy « Actions » : bouton « Je m'en occupe » sur les alertes critiques et
        sur les rappels (jamais sur une alerte objet ni sur un acquittement). Vide si
        `url_banc` n'est pas configuré — le téléphone doit pouvoir joindre le banc, donc
        être sur le même réseau.

        Le bouton part dans un en-tête HTTP et non en paramètre d'URL : ntfy ne documente
        `actions` qu'en en-tête. Son libellé est donc volontairement en ASCII, puisque ce
        sont les accents qui cassent les en-têtes (d'où titre et message en query params)."""
        if not self.url_banc or motif not in ("alerte", "rappel"):
            return ""
        if motif == "alerte" and getattr(alerte, "niveau", None) != "critique":
            return ""
        return (f"http, {LIBELLE_ACQUITTEMENT}, {self.url_banc}{CHEMIN_ACQUITTEMENT}, "
                "method=POST, clear=true")

    def envoyer(self, titre, message, image=None, priorite="high",
                tags="rotating_light,oncoming_automobile", actions="", clic="") -> bool:
        """Envoi synchrone vers ntfy ; renvoie True si la notification est partie.
        Titre/message/priorité en query params (les headers HTTP cassent les accents) ;
        le bouton d'action et le lien du clic, eux, passent en en-têtes (`Actions`, `Click`)."""
        if SENTINELLE_TOPIC in self.topic.upper():
            self.derniere_erreur = (
                f"topic ntfy non configuré ({self.topic!r}) : définir \"alertes\": "
                '{"topic": "..."} dans config.local.json (hors dépôt) ou la variable '
                "d'environnement CARE_NTFY_TOPIC")
            print(f"[alertes] envoi annulé — {self.derniere_erreur}")
            return False
        corps = b""
        params = {"title": titre, "message": message, "priority": priorite, "tags": tags}
        if image is not None:
            ok, buf = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if ok:
                corps = buf.tobytes()
                params["filename"] = "detection.jpg"
        entetes = {}
        if actions:
            entetes["Actions"] = actions
        if clic:
            entetes["Click"] = clic
        try:
            r = requests.put(f"{self.serveur}/{self.topic}", data=corps, params=params,
                             headers=entetes or None, timeout=10)
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
