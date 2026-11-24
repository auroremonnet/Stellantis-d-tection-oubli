"""Analyse d'un essai : plusieurs images de chaque caméra → un verdict.

    1. pendant ~1 s, chaque caméra fournit `n` images ; le moteur les observe (passe légère) ;
    2. par caméra, le moteur conclut : êtres vivants, objets de valeur, zones non identifiées ;
    3. si une référence « habitacle vide » existe, ce qui était déjà là est écarté
       (boucles de ceinture, équipement fixe) et ce qui est nouveau sans être reconnu est
       signalé comme « objet non identifié » ;
    4. la caméra thermique vote de son côté (A2 = RGB OU thermique).

En faible lumière, les images sont nettoyées avant d'être montrées aux modèles : rafales
moyennées si la caméra est bruitée, éclaircissement si elle est sombre (care/detection/lumiere.py).
"""
from __future__ import annotations

import time

from .catalogue import INCONNU
from .lumiere import Moyenne, luminosite, nettoyer
from .lumiere import Reglages as Lumiere
from .rendu import annoter


def rafale(source, k: int, attente_s: float = 0.25) -> list:
    """Jusqu'à k images DISTINCTES d'une caméra (une seule si la source n'horodate pas ses images)."""
    f = source.derniere()
    if f is None:
        return []
    images, vu, limite = [f], getattr(source, "stamp", None), time.time() + attente_s
    while vu is not None and len(images) < k and time.time() < limite:
        if source.stamp != vu:
            vu = source.stamp
            f = source.derniere()
            if f is not None:
                images.append(f)
        else:
            time.sleep(0.005)
    return images


def analyser_essai(moteur, verrou_inference, rgb, thermique, reference=None, *, n_images: int = 3,
                   pause_s: float = 0.05, alerte_inconnu: bool = True,
                   lumiere: Lumiere | None = None) -> dict:
    """rgb : liste de Source ; thermique : SourceThermique ou None ; reference : Reference ou None."""
    t0 = time.time()
    n = max(1, int(n_images))
    lum = lumiere or Lumiere()
    observations = {s.id: [] for s in rgb}
    derniere = {s.id: None for s in rgb}        # image donnée aux modèles (éclaircie s'il fait sombre)
    moyennes = {s.id: Moyenne() for s in rgb}   # caméra bruitée : moyenne de toutes les images de l'essai
    luminosites = {}
    hits_th, pix_max, tmax, mesure_th = 0, 0, None, None

    for _ in range(n):
        ids, frames = [], []
        for s in rgb:
            f = s.derniere()
            if f is None:
                continue
            luminosites[s.id] = luminosite(f)
            if luminosites[s.id] >= lum.seuil_noir:
                f, _ = nettoyer(lambda k, s=s: rafale(s, k), f, moyennes[s.id], lum)
            ids.append(s.id)
            frames.append(f)
        if frames:
            with verrou_inference:
                obs = moteur.observer(frames)
            for sid, f, o in zip(ids, frames, obs):
                observations[sid].append(o)
                derniere[sid] = f
        if thermique is not None:
            m = thermique.mesure()
            if m is not None:
                mesure_th = m
                hits_th += int(m["chaud"])
                pix_max = max(pix_max, m["pixels_chauds"])
                if m["tmax"] is not None:
                    tmax = max(tmax or -999, m["tmax"])
        time.sleep(pause_s)

    vivants, objets, cams_vivant, detections, annotees = set(), set(), [], [], []
    nb_zones, inconnu, lumiere_changee = 0, False, False
    for s in rgb:
        image = derniere[s.id]
        if image is None:
            continue
        comparaison = reference.comparer(s.id, image) if reference is not None else None
        zones, utilisable = [], False
        if comparaison is not None:
            utilisable = not comparaison.inutilisable
            lumiere_changee = lumiere_changee or comparaison.inutilisable
            zones = comparaison.zones()
        nouveau = (lambda b, cp=comparaison: cp.part_changee(b) >= reference.p["part_deja_la"]) if utilisable else None
        with verrou_inference:
            c = moteur.conclure(image, observations[s.id], zones, garder=nouveau)
        fixes = []
        if reference is not None and reference.a(s.id):
            fixes = [d for d in c.objets if reference.deja_la(s.id, d, comparaison if utilisable else None)]
            fixes += [d for d in c.vivants if reference.deja_la(s.id, d, None)]   # jamais sur les pixels seuls
            c.objets = [d for d in c.objets if d not in fixes]
            c.vivants = [d for d in c.vivants if d not in fixes]
        nb_zones += len(zones)
        inconnu = inconnu or bool(c.inconnues)
        vivants |= {d.cle for d in c.vivants}
        objets |= {d.cle for d in c.objets}
        if c.vivants:
            cams_vivant.append(s.id)
        detections += [{"camera": s.id, **d.en_dict()} for d in c.detections]
        detections += [{"camera": s.id, "libelle": INCONNU, "categorie": "zone", "confiance": None,
                        "boite": [int(v) for v in z], "sources": ["référence"]} for z in c.inconnues]
        annotees.append(annoter(image, c.detections, fixes, c.inconnues))

    liste_objets = sorted(objets)
    if inconnu and alerte_inconnu:
        liste_objets.append(INCONNU)
    return {
        "vivant_rgb": bool(vivants),
        "vivant_thermique": None if thermique is None else hits_th / n >= 0.5,
        "classes_vivant": sorted(vivants),
        "objets": liste_objets,
        "cameras_vivant": sorted(cams_vivant),
        "detections": detections,
        "zones_nouvelles": nb_zones,
        "reference_utilisee": bool(reference is not None and reference.etat()["active"]),
        "lumiere_changee": lumiere_changee,
        "luminosite": round(min(luminosites.values())) if luminosites else None,   # caméra la plus sombre
        "cameras_aveugles": sorted(sid for sid, v in luminosites.items() if v < lum.seuil_noir),
        "pixels_chauds": pix_max if thermique is not None else None,
        "tmax": None if tmax is None else round(tmax, 1),
        "methode_thermique": mesure_th.get("methode", "") if mesure_th else "",
        "resolution_thermique": mesure_th.get("resolution", "") if mesure_th else "",
        "latence_s": round(time.time() - t0, 2),
        "images_rgb": annotees,
        "image_thermique": thermique.apercu() if thermique is not None else None,
        "image_thermique_brute": thermique.derniere() if thermique is not None else None,
    }
