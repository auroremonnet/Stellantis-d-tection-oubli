"""Écoute continue du micro et reconnaissance des sons ciblés.

Le callback audio conserve uniquement quelques secondes en mémoire. Les formes
d'onde sont écrasées et jamais écrites sur disque.
"""
from collections import deque
from math import gcd
import threading
import time

import numpy as np


MODEL_ID = "MIT/ast-finetuned-audioset-10-10-0.4593"
CLASSES_AUDIO = {
    "pleurs": ("Baby cry, infant cry", "Crying, sobbing"),
    "aboiement": ("Bark",),
    "miaulement": ("Meow",),
}
PAROLE_AUDIOSET = {
    "Speech", "Male speech, man speaking", "Female speech, woman speaking",
    "Child speech, kid speaking", "Conversation", "Speech synthesizer",
    "Hubbub, speech noise, speech babble", "Narration, monologue",
}


def sons_retenus(scores, seuil):
    """Plusieurs événements peuvent être reconnus dans la même fenêtre."""
    return [nom for nom, score in scores.items() if score >= seuil]


def extraire_sons(scores, label2id, id2label, top_k=3):
    """Scores CARE, classement global et classement indépendant de la parole."""
    scores = np.asarray(scores)
    cibles = {nom: round(max(float(scores[label2id[classe]]) for classe in classes), 3)
              for nom, classes in CLASSES_AUDIO.items()}
    indices = np.argsort(scores)[::-1][:top_k]
    generaux = [{"label": str(id2label[int(i)]), "score": round(float(scores[i]), 3)}
                for i in indices]
    hors_parole = [{"label": str(id2label[int(i)]), "score": round(float(scores[i]), 3)}
                   for i in np.argsort(scores)[::-1]
                   if str(id2label[int(i)]) not in PAROLE_AUDIOSET][:top_k]
    return cibles, generaux, hors_parole


def _resultat(statut, scores=None, sons=None, generaux=None, hors_parole=None,
              seuil_general=0.3, erreur=""):
    scores = scores or {}
    generaux = generaux or []
    hors_parole = hors_parole or []
    premier = generaux[0] if generaux and generaux[0]["score"] >= seuil_general else None
    premier_hors_parole = (hors_parole[0] if hors_parole and
                           hors_parole[0]["score"] >= seuil_general else None)
    return {"audio_statut": statut, "sons_audio": sons or [],
            **{f"{nom}_score": scores.get(nom) for nom in CLASSES_AUDIO},
            "top_sons": generaux,
            "son_general": premier["label"] if premier else "",
            "score_general": premier["score"] if premier else None,
            "top_sons_hors_parole": hors_parole,
            "son_hors_parole": premier_hors_parole["label"] if premier_hors_parole else "",
            "score_hors_parole": premier_hors_parole["score"] if premier_hors_parole else None,
            "erreur_audio": erreur}


def _fusionner_candidats(mesures, index, top_k):
    candidats = {}
    for mesure in mesures:
        for candidat in mesure[index]:
            label = candidat["label"]
            candidats[label] = max(candidats.get(label, 0), candidat["score"])
    return [{"label": label, "score": score}
            for label, score in sorted(candidats.items(),
                                       key=lambda item: item[1], reverse=True)[:top_k]]


class DetecteurAudio:
    def __init__(self, cfg):
        self.cfg = cfg
        self.modele = None
        self.extracteur = None
        self.erreur = ""
        self._lock = threading.Lock()
        self._mesures = deque(maxlen=120)  # début, fin, calcul, CARE, top global, top hors parole
        self._derniers_sons = {}
        self._flux_ok = False
        self._micro_nom = ""
        self._niveau_db = None
        self._niveau_stamp = 0.0
        if cfg.get("active", False):
            threading.Thread(target=self._boucle, daemon=True).start()

    def _charger(self):
        from transformers import AutoFeatureExtractor, AutoModelForAudioClassification

        extracteur = AutoFeatureExtractor.from_pretrained(MODEL_ID)
        modele = AutoModelForAudioClassification.from_pretrained(MODEL_ID)
        modele.eval()
        manquantes = {classe for classes in CLASSES_AUDIO.values() for classe in classes} - set(modele.config.label2id)
        if manquantes:
            raise RuntimeError(f"Classes audio absentes du modèle : {', '.join(sorted(manquantes))}")
        self.extracteur = extracteur
        self.modele = modele

    def _classer(self, signal, frequence):
        import torch
        from scipy.signal import resample_poly

        if frequence != 16000:
            facteur = gcd(frequence, 16000)
            signal = resample_poly(signal, 16000 // facteur,
                                   frequence // facteur).astype(np.float32)
        entree = self.extracteur(signal, sampling_rate=16000, return_tensors="pt")
        with torch.inference_mode():
            logits = self.modele(**entree).logits[0]
        sorties = torch.sigmoid(logits)
        return extraire_sons(sorties.cpu().numpy(), self.modele.config.label2id,
                             self.modele.config.id2label,
                             top_k=int(self.cfg.get("top_k", 3)))

    def _ecouter(self, sd):
        appareil = self.cfg.get("index")
        appareil = None if appareil is None else int(appareil)
        info_micro = sd.query_devices(appareil, "input")
        frequence = int(info_micro["default_samplerate"])
        duree = float(self.cfg.get("duree_s", 3))
        duree_courte = float(self.cfg.get("duree_courte_s", duree))
        intervalle = float(self.cfg.get("intervalle_s", 1))
        if duree <= 0 or duree_courte <= 0 or duree_courte > duree or intervalle <= 0:
            raise ValueError("Durées audio invalides : 0 < duree_courte_s <= duree_s et intervalle_s > 0")
        fenetre = int(frequence * duree)
        fenetre_courte = int(frequence * duree_courte)
        limite = fenetre + int(frequence * 0.5)
        morceaux = deque()
        verrou = threading.Lock()
        total = 0

        def callback(indata, frames, temps, statut):
            nonlocal total
            bloc = indata[:, 0].copy()
            niveau_db = max(-60.0, 20 * np.log10(max(float(np.sqrt(np.mean(bloc * bloc))), 1e-6)))
            with verrou:
                morceaux.append(bloc)
                total += len(bloc)
                while total > limite and morceaux:
                    total -= len(morceaux.popleft())
            with self._lock:
                self._niveau_db = round(niveau_db, 1)
                self._niveau_stamp = time.monotonic()

        with sd.InputStream(samplerate=frequence, channels=1, dtype="float32",
                            device=appareil, callback=callback):
            with self._lock:
                self._flux_ok = True
                self.erreur = ""
                self._micro_nom = info_micro["name"]
            dernier_calcul = 0.0
            court = duree_courte < duree
            while True:
                time.sleep(0.1)
                if time.monotonic() - dernier_calcul < intervalle:
                    continue
                taille = fenetre_courte if court else fenetre
                with verrou:
                    if total < taille:
                        continue
                    signal = np.concatenate(list(morceaux))[-taille:]
                fin_fenetre = time.monotonic()
                scores, generaux, hors_parole = self._classer(signal, frequence)
                instant = time.monotonic()
                seuil = float(self.cfg.get("seuil", 0.5))
                with self._lock:
                    self._mesures.append((fin_fenetre - taille / frequence,
                                          fin_fenetre, instant, scores, generaux, hors_parole))
                    for nom in sons_retenus(scores, seuil):
                        self._derniers_sons[nom] = instant
                dernier_calcul = instant
                court = not court if duree_courte < duree else False

    def _boucle(self):
        try:
            import sounddevice as sd
            self._charger()
        except Exception as exc:
            with self._lock:
                self.erreur = str(exc)
            return
        while True:
            try:
                self._ecouter(sd)
            except Exception as exc:
                with self._lock:
                    self._flux_ok = False
                    self.erreur = str(exc)
                    self._niveau_db = None
                time.sleep(3)  # rebranchements du microphone

    def instantane(self, depuis=None):
        if not self.cfg.get("active", False):
            return _resultat("desactive")
        with self._lock:
            erreur = self.erreur
            pret = self.modele is not None
            flux_ok = self._flux_ok
            mesures = list(self._mesures)
            derniers_sons = dict(self._derniers_sons)
        if erreur:
            return _resultat("erreur", erreur=erreur)
        if not pret or not flux_ok:
            return _resultat("chargement")
        maintenant = time.monotonic()
        fraicheur = max(5.0, 2 * float(self.cfg.get("intervalle_s", 1)))
        if depuis is None:
            if not mesures or maintenant - mesures[-1][2] > fraicheur:
                return _resultat("attente")
            maintien = float(self.cfg.get("maintien_s", 4))
            recentes = [m for m in mesures if maintenant - m[2] <= maintien] or mesures[-1:]
            scores = {nom: max(m[3][nom] for m in recentes) for nom in CLASSES_AUDIO}
            generaux = mesures[-1][4]
            hors_parole = _fusionner_candidats(recentes, 5, int(self.cfg.get("top_k", 3)))
            sons = [nom for nom, stamp in derniers_sons.items()
                    if maintenant - stamp <= maintien]
        else:
            selection = [m for m in mesures if m[0] >= depuis]
            if not selection:
                return _resultat("attente")
            scores = {nom: max(m[3][nom] for m in selection) for nom in CLASSES_AUDIO}
            top_k = int(self.cfg.get("top_k", 3))
            generaux = _fusionner_candidats(selection, 4, top_k)
            hors_parole = _fusionner_candidats(selection, 5, top_k)
            sons = sons_retenus(scores, float(self.cfg.get("seuil", 0.5)))
        return _resultat("ok", scores, sons, generaux, hors_parole,
                         seuil_general=float(self.cfg.get("seuil_general", 0.3)))

    def etat(self):
        with self._lock:
            micro_nom = self._micro_nom
            niveau_db = self._niveau_db if time.monotonic() - self._niveau_stamp < 2 else None
        return {"active": bool(self.cfg.get("active", False)),
                "pret": self.modele is not None,
                "erreur": self.erreur,
                "modele": MODEL_ID,
                "micro": micro_nom,
                "niveau_db": niveau_db,
                "mesure": self.instantane()}
