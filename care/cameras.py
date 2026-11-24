"""Acquisition des flux caméra.

Chaque caméra tourne dans son propre thread et garde en mémoire la dernière
image reçue : l'interface et l'analyse lisent toujours une image fraîche,
sans file d'attente qui prend du retard.
"""
import math
import os
import threading
import time

import cv2
import numpy as np

BACKEND = cv2.CAP_DSHOW if os.name == "nt" else cv2.CAP_ANY

BACKENDS = {"defaut": BACKEND, "dshow": cv2.CAP_DSHOW, "msmf": cv2.CAP_MSMF, "auto": cv2.CAP_ANY}
FLUX_DEFAUT = {"backend": "defaut", "fourcc": "Y16 ", "convert_rgb": 0}
TEMP_PLAUSIBLE_C = (-40.0, 120.0)  # au-delà, le format supposé des températures est faux

# Valeurs issues de la simulation, à recaler sur le banc ; surchargeables dans config.json → thermique.
#   methode : contraste (rien à capturer), reference (compare à l'habitacle vide), seuil_fixe
#   zones_ignorees : [[x1, y1, x2, y2], ...] en part de l'image (0 à 1), réglées à l'installation
#   diviseur_kelvin : valeur brute / diviseur = kelvins (100 pour le format TLinear)
DEFAUTS_THERMIQUE = {"methode": "contraste", "delta_c": 2.5, "temp_max_vivant_c": 42.0, "temp_corps_c": 37.0,
                     "part_min_image": 0.004, "zones_ignorees": [], "diviseur_kelvin": 100, "flux": FLUX_DEFAUT}


def temperatures(f, diviseur=100):
    """Image 16 bits → températures en °C."""
    return f.astype(np.float32) / diviseur - 273.15


def temperature_plausible(temp):
    return TEMP_PLAUSIBLE_C[0] <= float(np.median(temp)) <= TEMP_PLAUSIBLE_C[1]


def ouvrir_flux(index, flux):
    cap = cv2.VideoCapture(index, BACKENDS[flux.get("backend", "defaut")])
    if flux.get("fourcc"):
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*flux["fourcc"]))
    cap.set(cv2.CAP_PROP_CONVERT_RGB, flux.get("convert_rgb", 0))
    return cap


def normaliser_brut(f, largeur=0, hauteur=0):
    """Selon le pilote, le 16 bits arrive tel quel, en 2 canaux de 8 bits ou en tampon à plat.
    Certaines caméras empilent deux images (256x384) : l'image visible, puis les températures."""
    if f.dtype == np.uint8 and f.ndim == 3 and f.shape[2] == 2:
        f = f[..., 0].astype(np.uint16) | (f[..., 1].astype(np.uint16) << 8)
    elif f.ndim == 2 and 1 in f.shape and largeur and hauteur:
        if f.dtype == np.uint8 and f.size == 2 * largeur * hauteur:
            f = np.frombuffer(f.tobytes(), dtype="<u2").reshape(hauteur, largeur).copy()
        elif f.dtype == np.uint16 and f.size == largeur * hauteur:
            f = f.reshape(hauteur, largeur)
    if f.dtype == np.uint16 and f.ndim == 2 and f.shape[0] * 2 == f.shape[1] * 3:
        return f[f.shape[0] // 2:]  # format 2:3 : deux images 4:3 empilées, les températures en bas
    return f


def masque_zones(forme, zones):
    """Vrai sur les pixels des zones ignorées, indiquées en part de l'image."""
    h, w = forme[:2]
    masque = np.zeros((h, w), bool)
    for x1, y1, x2, y2 in zones:
        masque[round(y1 * h):round(y2 * h), round(x1 * w):round(x2 * w)] = True
    return masque


def fond_uniforme(temp, p):
    """Fond estimé dans l'image elle-même : aucune capture à faire par l'utilisateur."""
    ignore = masque_zones(temp.shape, p.get("zones_ignorees", []))
    valeurs = temp[~ignore] if not ignore.all() else temp
    return np.full(temp.shape, np.median(valeurs), np.float32)


def masque_vivant(temp, ref, p):
    """Zones qui peuvent être un corps vivant, par écart à ref (fond de l'image ou habitacle vide)."""
    p = {**DEFAUTS_THERMIQUE, **p}
    ignore = masque_zones(temp.shape, p["zones_ignorees"])
    diff = temp - ref
    diff = diff - np.median(diff[~ignore] if not ignore.all() else diff)  # réchauffement global de l'habitacle
    plus_chaud = diff > p["delta_c"]
    # dans un habitacle plus chaud que le corps, un être vivant apparaît comme une zone plus froide
    plus_froid = (ref > p["temp_corps_c"]) & (diff < -p["delta_c"])
    # marge : le flou de l'optique déborde du bord d'une zone ignorée
    marge = cv2.dilate(ignore.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    masque = (plus_chaud | plus_froid) & ~marge
    # trop chaud pour être vivant (gourde, objet au soleil) : on l'écarte avec son halo de flou,
    # sans écarter tout ce qui le touche, pour qu'un objet chaud ne masque pas un enfant
    brulant = plus_chaud & (temp > p["temp_max_vivant_c"])
    if brulant.any():
        halo = cv2.dilate(brulant.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
        masque &= ~halo
    # taille en part de l'image : le réglage ne dépend pas de la résolution de la caméra
    _, etiquettes, stats, _ = cv2.connectedComponentsWithStats(masque.astype(np.uint8), connectivity=8)
    taille_min = max(1, p["part_min_image"] * masque.size)
    gardees = [i for i in range(1, len(stats)) if stats[i, cv2.CC_STAT_AREA] >= taille_min]
    return np.isin(etiquettes, gardees)


class Source:
    """Caméra RGB réelle, lue en continu dans un thread."""

    def __init__(self, sid, index, label, resolution):
        self.id, self.index, self.label = sid, index, label
        self.resolution = resolution
        self.frame = None
        self.stamp = 0.0
        self.ok = False
        self.erreur = ""
        self._lock = threading.Lock()
        self._stop = False
        self._thread = threading.Thread(target=self._boucle, daemon=True)

    def demarrer(self):
        self._thread.start()
        return self

    def arreter(self):
        self._stop = True

    def _ouvrir(self):
        cap = cv2.VideoCapture(self.index, BACKEND)
        # MJPG : indispensable pour faire passer plusieurs flux 720p sur un seul hub USB
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.resolution[0])
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.resolution[1])
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return cap

    def _lire(self, cap):
        return cap.read()

    def _boucle(self):
        while not self._stop:
            cap = self._ouvrir()
            if not cap.isOpened():
                self.ok, self.erreur = False, f"index {self.index} introuvable"
                cap.release()
                time.sleep(3)
                continue
            echecs = 0
            while not self._stop:
                ok, f = self._lire(cap)
                if not ok or f is None:
                    echecs += 1
                    if echecs > 30:
                        self.ok, self.erreur = False, "flux interrompu"
                        break
                    time.sleep(0.05)
                    continue
                echecs = 0
                with self._lock:
                    self.frame, self.stamp = f, time.time()
                self.ok, self.erreur = True, ""
            cap.release()
            time.sleep(1)

    def derniere(self):
        with self._lock:
            return None if self.frame is None else self.frame.copy()

    def apercu(self):
        """Image affichable (BGR 8 bits) pour le dashboard."""
        return self.derniere()

    def etat(self):
        return {"id": self.id, "label": self.label, "index": self.index,
                "ok": self.ok and time.time() - self.stamp < 3, "erreur": self.erreur}


class SourceThermique(Source):
    """Caméra thermique, à la résolution qu'elle fournit. Tente le flux brut 16 bits (radiométrique)."""

    def __init__(self, sid, index, label, params):
        super().__init__(sid, index, label, (160, 120))
        self.params = {**DEFAUTS_THERMIQUE, **params}
        self.mode = "?"
        self.methode = "?"
        self.reference = None  # températures de l'habitacle vide (°C), posées par care.reference

    def _ouvrir(self):
        return ouvrir_flux(self.index, {**FLUX_DEFAUT, **self.params["flux"]})

    def _lire(self, cap):
        ok, f = cap.read()
        if ok and f is not None:
            f = normaliser_brut(f, int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
        return ok, f

    def vers_celsius(self, f):
        return temperatures(f, self.params["diviseur_kelvin"])

    def masque_chaud(self, f):
        """Retourne (masque des pixels chauds, image 8 bits, température max ou None)."""
        p = self.params
        if f.dtype == np.uint16:
            temp = self.vers_celsius(f)
            self.mode = "radiométrique" if temperature_plausible(temp) else "16 bits non calibré"
            # échelle fixe 15-40 °C : un habitacle vide reste sombre au lieu d'amplifier le bruit
            img = np.clip((temp - 15) * (255 / 25), 0, 255).astype(np.uint8)
            tmax = float(temp.max())
            if p["methode"] == "seuil_fixe":
                self.methode = "seuil fixe"
                return temp > p["seuil_celsius"], img, tmax
            ref = self.reference
            if p["methode"] == "reference" and ref is not None and ref.shape == temp.shape:
                self.methode = "référence"
                return masque_vivant(temp, ref, p), img, tmax
            self.methode = "contraste"
            return masque_vivant(temp, fond_uniforme(temp, p), p), img, tmax
        self.mode = "8 bits"
        self.methode = "seuil fixe"  # pas de température : aucune comparaison fiable
        g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY) if f.ndim == 3 else f
        return g > p["seuil_8bit"], g, None

    def mesure(self):
        f = self.derniere()
        if f is None:
            return None
        masque, img, tmax = self.masque_chaud(f)
        nb = int(masque.sum())
        # contraste et référence : masque_vivant a déjà écarté les zones trop petites
        chaud = nb >= self.params["pixels_chauds_min"] if self.methode == "seuil fixe" else nb > 0
        return {"pixels_chauds": nb, "tmax": tmax, "mode": self.mode, "methode": self.methode,
                "resolution": f"{f.shape[1]}x{f.shape[0]}", "chaud": chaud, "img": img, "masque": masque}

    def apercu(self):
        m = self.mesure()
        if m is None:
            return None
        couleur = cv2.applyColorMap(cv2.resize(m["img"], (640, 480), interpolation=cv2.INTER_NEAREST),
                                    cv2.COLORMAP_INFERNO)
        contour = cv2.resize(m["masque"].astype(np.uint8) * 255, (640, 480),
                             interpolation=cv2.INTER_NEAREST)
        cnts, _ = cv2.findContours(contour, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(couleur, cnts, -1, (255, 255, 255), 2)
        return couleur

    def etat(self):
        e = super().etat()
        m = self.mesure() if e["ok"] else None
        e.update({"mode": self.mode, "methode": self.methode,
                  "resolution": None if m is None else m["resolution"],
                  "pixels_chauds": None if m is None else m["pixels_chauds"],
                  "tmax": None if m is None or m["tmax"] is None else round(m["tmax"], 1)})
        return e


# --------------------------------------------------------------------------
# Mode démo : flux synthétiques pour développer le dashboard sans matériel
# --------------------------------------------------------------------------

class SourceDemo(Source):
    def __init__(self, sid, index, label, resolution):
        super().__init__(sid, index, label, resolution)
        self.scene = "vide"  # mis à jour par l'application pendant un essai

    def _ouvrir(self):
        return _FauxCap()

    def _lire(self, cap):
        time.sleep(1 / 15)
        t = time.time()
        h, w = 360, 640
        img = np.full((h, w, 3), (52, 46, 42), np.uint8)
        # banquette
        cv2.rectangle(img, (40, 200), (600, 340), (78, 70, 64), -1)
        cv2.rectangle(img, (40, 120), (600, 210), (90, 82, 75), -1)
        if self.scene == "conducteur":  # adulte au premier plan (surveillance automatique)
            x = int(330 + 25 * math.sin(t * 0.6 + self.index))
            cv2.circle(img, (x, 95), 48, (150, 170, 205), -1)
            cv2.ellipse(img, (x, 260), (110, 120), 0, 0, 360, (95, 75, 60), -1)
        elif self.scene == "vivant":
            x = int(320 + 40 * math.sin(t * 0.8 + self.index))
            cv2.circle(img, (x, 190), 34, (150, 170, 205), -1)
            cv2.ellipse(img, (x, 270), (60, 50), 0, 0, 360, (120, 90, 160), -1)
        elif self.scene == "objet":
            cv2.rectangle(img, (260, 240), (380, 320), (40, 60, 110), -1)
        bruit = np.random.randint(0, 12, img.shape, np.uint8)
        img = cv2.add(img, bruit)
        cv2.putText(img, "DEMO", (w - 70, h - 14), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                    (230, 230, 230), 1, cv2.LINE_AA)
        return True, img


class SourceThermiqueDemo(SourceThermique):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.scene = "vide"

    def _ouvrir(self):
        return _FauxCap()

    def _lire(self, cap):
        time.sleep(1 / 9)
        yy, xx = np.mgrid[0:60, 0:80]
        temp = np.full((60, 80), 22.0) + np.random.randn(60, 80) * 0.3
        if self.scene in ("vivant", "conducteur"):
            cx = 40 + 6 * math.sin(time.time() * 0.8)
            temp += 13 * np.exp(-(((xx - cx) / 9) ** 2 + ((yy - 32) / 12) ** 2))
        return True, ((temp + 273.15) * 100).astype(np.uint16)


class _FauxCap:
    def isOpened(self):
        return True

    def release(self):
        pass
