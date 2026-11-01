"""Analyse d'un essai : détection RGB, thermique (seuil de chaleur), fusion.

Trois moteurs RGB, choisis dans config.json (`detection.moteur`) :
    "yoloe"   : YOLOE, détecteur à vocabulaire ouvert. On lui donne une liste de
                mots (prompts) : "cell phone", "car key", "wallet"… Pas d'entraînement.
    "coco"    : YOLOv8 classique, limité aux 80 classes COCO (pas de clés, pas de
                portefeuille, pas de carte). Gardé pour comparaison.
    "hybride" : YOLOE + notre modèle entraîné (`detection.modele_custom`, classes
                baby / keys / wallet / card). Les deux tournent sur chaque image et
                les doublons (même libellé, boîtes qui se recouvrent) sont fusionnés.
                Si le modèle entraîné est absent, on retombe sur YOLOE seul.

Si une référence « habitacle vide » a été capturée (care/reference.py) :
    - les détections déjà présentes au même endroit sur la référence sont ignorées
      (boucle de ceinture vue comme un téléphone, console vue comme un sac…) ;
    - les zones qui ont changé par rapport à la référence sont zoomées et
      re-soumises au détecteur ; si rien n'est reconnu, elles sont quand même
      signalées comme « objet non identifié ».

Chaque essai enregistre séparément le verdict RGB et le verdict thermique :
    A1 = RGB seul
    A2 = RGB OU thermique (fusion « OU », maximise le rappel)
"""
import random
import threading
import time

import cv2
import numpy as np

from .reference import iou, recouvrement

# ---- Moteur COCO (yolov8n/s/m/l.pt) --------------------------------------
COCO_VIVANT = {0: "personne", 15: "chat", 16: "chien"}
COCO_VALEUR = {24: "sac à dos", 26: "sac à main", 28: "valise", 63: "ordinateur", 67: "téléphone"}

# ---- Prompts par défaut du moteur YOLOE (surchargeables dans config.json) ----
PROMPTS_VIVANT = ["person", "child", "baby", "cat", "dog"]
PROMPTS_VALEUR = ["cell phone", "car key", "keys", "wallet", "credit card", "handbag",
                  "backpack", "bag", "laptop", "tablet", "glasses", "watch", "headphones"]
LIBELLES = {
    "person": "personne", "child": "enfant", "baby": "bébé", "cat": "chat", "dog": "chien",
    "cell phone": "téléphone", "smartphone": "téléphone", "car key": "clés de voiture",
    "keys": "clés", "wallet": "portefeuille", "credit card": "carte bancaire",
    "handbag": "sac à main", "backpack": "sac à dos", "bag": "sac", "shopping bag": "sac",
    "laptop": "ordinateur", "tablet": "tablette", "glasses": "lunettes", "watch": "montre",
    "headphones": "casque audio", "suitcase": "valise",
    "card": "carte bancaire",  # classes du modèle entraîné (Roboflow care-oubli)
}
# Type de chaque classe du modèle entraîné (surchargeable : detection.classes_custom)
CLASSES_CUSTOM = {"baby": "vivant", "keys": "valeur", "wallet": "valeur", "card": "valeur"}
INCONNU = "objet non identifié"

COULEUR = {"vivant": (60, 60, 230), "valeur": (60, 200, 60), "fixe": (150, 150, 150), "zone": (0, 165, 255)}
_ACCENTS = str.maketrans("àâäéèêëîïôöùûüç", "aaaeeeeiioouuuc")


def _ascii(s):
    """OpenCV ne sait pas dessiner les accents."""
    return str(s).translate(_ACCENTS)


def fusionner(dets, libelle=lambda n: n, iou_min=0.5, prioritaire="custom"):
    """Supprime les doublons ENTRE moteurs : une détection est écartée si une détection
    plus confiante d'un AUTRE moteur, de même libellé, recouvre sa boîte (IoU >= iou_min).
    Le libellé sert de clé commune (« credit card » de YOLOE et « card » du modèle entraîné
    donnent tous deux « carte bancaire »). Deux détections d'un même moteur ne sont jamais
    fusionnées ici : son propre NMS l'a déjà fait, et deux objets voisins (deux
    personnes côte à côte, un trousseau sur un portefeuille) doivent rester distincts.

    En cas de doublon, le moteur `prioritaire` (le modèle entraîné, spécialiste de nos
    classes et de nos conventions de boîtes) l'emporte, quelle que soit la confiance :
    les scores de deux modèles différents ne sont pas comparables entre eux."""
    gardees = []
    for d in sorted(dets, key=lambda d: (d.get("source") != prioritaire, -d["conf"])):
        if not any(g.get("source") != d.get("source")
                   and libelle(g["nom"]) == libelle(d["nom"])
                   and iou(g["boite"], d["boite"]) >= iou_min for g in gardees):
            gardees.append(d)
    return gardees


def est_adulte(det, hauteur_image, hauteur_min=0.35):
    """Un adulte à bord = une « person » dont la boîte occupe une bonne part de la hauteur
    de l'image. Les petits gabarits (enfant dans un siège, bébé) ne comptent pas : ils ne
    doivent jamais empêcher la surveillance de constater le départ du conducteur."""
    if det["nom"] != "person" or det["type"] != "vivant":
        return False
    return (det["boite"][3] - det["boite"][1]) >= hauteur_min * hauteur_image


class Detecteur:
    def __init__(self, cfg):
        self.cfg = cfg
        d = cfg.get("detection", {})
        self.moteur = d.get("moteur", "coco")
        self.modele = d.get("modele", cfg.get("modele", "yolov8n.pt"))
        self.moteur_base = "coco" if self.moteur == "coco" else "yoloe"
        if self.moteur == "coco" and "yoloe" in str(self.modele):
            # le champ `modele` désigne les poids YOLOE : COCO a ses propres poids
            self.modele = d.get("modele_coco", "yolov8m.pt")
        self.prompts_vivant = d.get("prompts_vivant", PROMPTS_VIVANT)
        self.prompts_valeur = d.get("prompts_valeur", PROMPTS_VALEUR)
        self.libelles = {**LIBELLES, **d.get("libelles", {})}
        self.conf_vivant = d.get("confiance_vivant", cfg.get("confiance_min", 0.4))
        self.conf_objet = d.get("confiance_objet", 0.25)
        self.imgsz = d.get("imgsz", 640)
        self.zoom_zones = d.get("zoom_zones", True)
        self.alerte_inconnu = d.get("alerte_zone_inconnue", True)
        self.modele_custom = d.get("modele_custom", "modeles/care-v1.pt")
        self.classes_custom = {**CLASSES_CUSTOM, **d.get("classes_custom", {})}
        self.conf_custom = d.get("confiance_custom", 0.35)
        self.hauteur_adulte = d.get("hauteur_min_adulte", 0.35)
        self.model = None
        self.custom = None          # modèle entraîné (moteur hybride)
        self.erreur = ""
        self.avertissement = ""
        self._lock = threading.Lock()          # un essai à la fois
        self._lock_inference = threading.Lock()  # un appel au modèle à la fois (surveillance + essai)
        threading.Thread(target=self._charger, daemon=True).start()

    # ---- chargement ------------------------------------------------------
    def _charger(self):
        try:
            if self.moteur == "hybride":
                self._charger_custom()
            if self.moteur in ("yoloe", "hybride"):
                from ultralytics import YOLOE
                m = YOLOE(self.modele)
                noms = list(self.prompts_vivant) + list(self.prompts_valeur)
                m.set_classes(noms, m.get_text_pe(noms))
                self._noms = noms
                self._type = {i: ("vivant" if i < len(self.prompts_vivant) else "valeur") for i in range(len(noms))}
                self._classes = None
            else:
                from ultralytics import YOLO
                m = YOLO(self.modele)
                self._noms = {**COCO_VIVANT, **COCO_VALEUR}
                self._type = {**{c: "vivant" for c in COCO_VIVANT}, **{c: "valeur" for c in COCO_VALEUR}}
                self._classes = list(self._noms)
            m(np.zeros((360, 640, 3), np.uint8), verbose=False, imgsz=self.imgsz)  # préchauffage
            self.model = m
        except Exception as e:  # noqa: BLE001
            self.erreur = str(e)

    def _charger_custom(self):
        import os

        from ultralytics import YOLO
        if not os.path.exists(self.modele_custom):
            self.avertissement = (f"Modèle entraîné introuvable ({self.modele_custom}) : "
                                  "YOLOE seul. Voir entrainement/README.md")
            return
        m = YOLO(self.modele_custom)
        inconnues = sorted(set(m.names.values()) - set(self.classes_custom))
        if inconnues:
            self.avertissement = f"Classes du modèle entraîné ignorées : {', '.join(inconnues)}"
        self._noms_custom = m.names
        m(np.zeros((360, 640, 3), np.uint8), verbose=False, imgsz=self.imgsz)
        self.custom = m

    @property
    def pret(self):
        return self.model is not None

    def libelle(self, nom):
        return self.libelles.get(nom, nom)

    # ---- inférence ---------------------------------------------------------
    def detecter(self, frames, facteur_conf=1.0):
        """Pour chaque image : liste de {nom, type, conf, boite}. Seuil par type (× facteur_conf)."""
        seuils = {"vivant": self.conf_vivant * facteur_conf, "valeur": self.conf_objet * facteur_conf}
        kw = {"conf": min(seuils.values()), "verbose": False, "imgsz": self.imgsz}
        if self._classes:
            kw["classes"] = self._classes
        with self._lock_inference:
            res = self.model(frames, **kw)
            res_custom = None
            if self.custom is not None:
                res_custom = self.custom(frames, conf=self.conf_custom * facteur_conf,
                                         verbose=False, imgsz=self.imgsz)
        out = self._lire(res, seuils)
        if res_custom is not None:
            for dets, r in zip(out, res_custom):
                for c, p, b in zip(r.boxes.cls.tolist(), r.boxes.conf.tolist(), r.boxes.xyxy.tolist()):
                    nom = self._noms_custom[int(c)]
                    t = self.classes_custom.get(nom)
                    if t is not None:
                        dets.append({"nom": nom, "type": t, "conf": float(p),
                                     "boite": [int(v) for v in b], "source": "custom"})
            out = [fusionner(dets, self.libelle) for dets in out]
        return out

    def presence_adulte(self, sources):
        """Vrai si un adulte est vu sur au moins une caméra (surveillance automatique)."""
        frames = [f for f in (s.derniere() for s in sources) if f is not None]
        if not frames or not self.pret:
            return False
        for f, dets in zip(frames, self.detecter(frames)):
            if any(est_adulte(d, f.shape[0], self.hauteur_adulte) for d in dets):
                return True
        return False

    def _lire(self, res, seuils):
        out = []
        for r in res:
            dets = []
            for c, p, b in zip(r.boxes.cls.tolist(), r.boxes.conf.tolist(), r.boxes.xyxy.tolist()):
                c = int(c)
                t = self._type.get(c)
                if t is None:
                    continue
                if p < seuils[t]:
                    continue
                dets.append({"nom": self._noms[c], "type": t, "conf": float(p),
                             "boite": [int(v) for v in b], "source": self.moteur_base})
            out.append(dets)
        return out

    def _zoomer(self, frame, zone):
        """Re-détecte sur un recadrage agrandi de la zone (petits objets : clés, carte)."""
        h, w = frame.shape[:2]
        x1, y1, x2, y2 = zone
        mx, my = int((x2 - x1) * 0.4) + 16, int((y2 - y1) * 0.4) + 16
        cx1, cy1, cx2, cy2 = max(0, x1 - mx), max(0, y1 - my), min(w, x2 + mx), min(h, y2 + my)
        crop = frame[cy1:cy2, cx1:cx2]
        if crop.size == 0:
            return None
        # la zone est déjà connue comme nouvelle : on accepte un score plus bas qu'en plein champ
        dets = [d for d in self.detecter([crop], facteur_conf=0.8)[0] if d["type"] == "valeur"]
        if not dets:
            return None
        best = max(dets, key=lambda d: d["conf"])
        best["boite"] = [best["boite"][0] + cx1, best["boite"][1] + cy1, best["boite"][2] + cx1, best["boite"][3] + cy1]
        return best

    # ---- analyse d'un essai ----------------------------------------------
    def analyser(self, rgb, thermique, verite=None, reference=None):
        """rgb : liste de Source ; thermique : SourceThermique ou None ; reference : Reference ou None."""
        if not self.pret:
            raise RuntimeError("Modèle pas encore chargé" + (f" : {self.erreur}" if self.erreur else ""))
        n = self.cfg["images_par_essai"]
        ratio = self.cfg["ratio_presence"]
        t0 = time.time()
        compte = {}                                   # nom -> nb d'images où il est vu (toutes caméras)
        par_cam = {s.id: {"vivant": set(), "valeur": set(), "frame": None, "dets": [], "fixes": [],
                          "masque": None, "nb_masques": 0} for s in rgb}
        hits_th, pix_max, tmax, img_th = 0, 0, None, None

        with self._lock:
            for _ in range(n):
                frames, ids = [], []
                for s in rgb:
                    f = s.derniere()
                    if f is not None:
                        frames.append(f)
                        ids.append(s.id)
                if frames:
                    for sid, f, dets in zip(ids, frames, self.detecter(frames)):
                        pc = par_cam[sid]
                        gardees, fixes = [], []
                        for d in dets:
                            (fixes if reference is not None and reference.est_fixe(sid, d) else gardees).append(d)
                        pc["frame"], pc["dets"], pc["fixes"] = f, gardees, fixes
                        for d in gardees:
                            pc[d["type"]].add(d["nom"])
                        for nom in {d["nom"] for d in gardees}:
                            compte[nom] = compte.get(nom, 0) + 1
                        if reference is not None and reference.a(sid):
                            m = reference.masque_changement(sid, f)
                            if m is not None:
                                pc["masque"] = m.astype(np.float32) if pc["masque"] is None else pc["masque"] + m
                                pc["nb_masques"] += 1
                if thermique is not None:
                    m = thermique.mesure()
                    if m is not None:
                        hits_th += int(m["chaud"])
                        pix_max = max(pix_max, m["pixels_chauds"])
                        if m["tmax"] is not None:
                            tmax = max(tmax or -999, m["tmax"])
                time.sleep(0.05)
            if thermique is not None:
                img_th = thermique.apercu()

            # ---- consolidation sur l'essai ----
            presents = {nom for nom, k in compte.items() if k / n >= ratio}
            noms_vivant = {nom for nom in presents if any(nom in pc["vivant"] for pc in par_cam.values())}
            noms_valeur = {nom for nom in presents if any(nom in pc["valeur"] for pc in par_cam.values())}
            cams_vivant = sorted(sid for sid, pc in par_cam.items() if pc["vivant"] & noms_vivant)
            nb_zones, inconnu, lumiere, annotees = 0, False, False, []

            for pc in par_cam.values():
                f = pc["frame"]
                if f is None:
                    continue
                zones, invalide = [], False
                if pc["masque"] is not None and pc["nb_masques"]:
                    zones, invalide = reference.zones(pc["masque"] / pc["nb_masques"], f.shape)
                lumiere = lumiere or invalide
                gardees = [d for d in pc["dets"] if d["nom"] in presents]
                for z in zones:
                    if any(recouvrement(z, d["boite"]) >= 0.3 for d in gardees):
                        continue  # zone déjà expliquée par une détection
                    nb_zones += 1
                    nom = None
                    if self.zoom_zones:
                        d = self._zoomer(f, z)
                        if d is not None:
                            nom = d["nom"]
                            gardees.append({**d, "zoom": True})
                            noms_valeur.add(nom)
                    if nom is None:
                        inconnu = True
                        gardees.append({"nom": INCONNU, "type": "zone", "conf": None, "boite": z})
                annotees.append(self._annoter(f, gardees, pc["fixes"]))

        objets = sorted(self.libelle(x) for x in noms_valeur)
        if inconnu and self.alerte_inconnu:
            objets.append(INCONNU)
        vivant_th = None if thermique is None else hits_th / n >= 0.5
        return {
            "vivant_rgb": bool(noms_vivant),
            "vivant_thermique": vivant_th,
            "classes_vivant": sorted(self.libelle(x) for x in noms_vivant),
            "objets": objets,
            "cameras_vivant": cams_vivant,
            "zones_nouvelles": nb_zones,
            "reference_utilisee": bool(reference is not None and reference.etat()["active"]),
            "lumiere_changee": lumiere,
            "pixels_chauds": pix_max if thermique is not None else None,
            "tmax": None if tmax is None else round(tmax, 1),
            "latence_s": round(time.time() - t0, 2),
            "images_rgb": annotees,
            "image_thermique": img_th,
        }

    def _annoter(self, frame, gardees, fixes):
        img = frame.copy()
        for d in fixes:
            x1, y1, x2, y2 = d["boite"]
            cv2.rectangle(img, (x1, y1), (x2, y2), COULEUR["fixe"], 1)
            cv2.putText(img, _ascii(f"fixe: {self.libelle(d['nom'])}"), (x1, max(12, y1 - 4)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, COULEUR["fixe"], 1, cv2.LINE_AA)
        for d in gardees:
            x1, y1, x2, y2 = d["boite"]
            col = COULEUR.get(d["type"], COULEUR["valeur"])
            conf = "" if d["conf"] is None else f" {d['conf']:.2f}"
            txt = _ascii(self.libelle(d["nom"]) + conf + (" zoom" if d.get("zoom") else ""))
            cv2.rectangle(img, (x1, y1), (x2, y2), col, 2)
            (tw, th), _ = cv2.getTextSize(txt, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
            cv2.rectangle(img, (x1, max(0, y1 - th - 8)), (x1 + tw + 6, max(th + 8, y1)), col, -1)
            cv2.putText(img, txt, (x1 + 3, max(th + 3, y1 - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                        (255, 255, 255), 1, cv2.LINE_AA)
        return img


class DetecteurDemo(Detecteur):
    """Simule des détections réalistes : le RGB rate des présences, la thermique moins."""

    def _charger(self):
        self.model = "demo"

    def detecter(self, frames, facteur_conf=1.0):
        return [[] for _ in frames]

    def presence_adulte(self, sources):
        """En démo, le conducteur est « à bord » quand la scène simulée le montre."""
        return any(getattr(s, "scene", "") == "conducteur" for s in sources)

    def analyser(self, rgb, thermique, verite=None, reference=None):
        t0 = time.time()
        time.sleep(1.2)
        r = random.random
        vivant_rgb = (verite == "vivant" and r() < 0.68) or (verite != "vivant" and r() < 0.06)
        vivant_th = None
        if thermique is not None:
            vivant_th = (verite == "vivant" and r() < 0.9) or (verite != "vivant" and r() < 0.12)
        objets = ["sac à main"] if verite == "objet" and r() < 0.8 else []
        images = []
        for s in rgb:
            f = s.derniere()
            if f is not None:
                if vivant_rgb:
                    cv2.rectangle(f, (250, 140), (400, 330), (60, 200, 60), 2)
                    cv2.putText(f, "personne 0.71", (250, 132), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                                (60, 200, 60), 1, cv2.LINE_AA)
                images.append(f)
        return {
            "vivant_rgb": vivant_rgb, "vivant_thermique": vivant_th,
            "classes_vivant": ["personne"] if vivant_rgb else [], "objets": objets,
            "cameras_vivant": [rgb[2].id] if vivant_rgb and len(rgb) > 2 else [],
            "zones_nouvelles": 1 if objets else 0, "reference_utilisee": False, "lumiere_changee": False,
            "pixels_chauds": (140 if vivant_th else 3) if thermique is not None else None,
            "tmax": (35.1 if vivant_th else 22.8) if thermique is not None else None,
            "latence_s": round(time.time() - t0, 2),
            "images_rgb": images,
            "image_thermique": thermique.apercu() if thermique is not None else None,
        }


def mosaique(images, w=640, h=360):
    imgs = [cv2.resize(i, (w, h)) for i in images if i is not None]
    if not imgs:
        return None
    if len(imgs) == 1:
        return imgs[0]
    if len(imgs) == 2:
        return np.hstack(imgs)
    while len(imgs) < 4:
        imgs.append(np.zeros((h, w, 3), np.uint8))
    return np.vstack([np.hstack(imgs[:2]), np.hstack(imgs[2:4])])
