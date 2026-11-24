"""Analyse d'un essai et façade Detecteur, avec un moteur factice (ni modèle ni caméra)."""
import threading

import numpy as np

from care.detection.catalogue import INCONNU
from care.detection.classifieur import agreger, recadrer
from care.detection.essai import analyser_essai
from care.detection.identification import Detection
from care.detection.moteurs import Conclusion, MoteurHistorique, creer
from care.reference import Reference


class Source:
    def __init__(self, sid, image=None):
        self.id, self.image = sid, np.zeros((480, 640, 3), np.uint8) if image is None else image

    def derniere(self):
        return self.image.copy()


class MoteurFactice:
    """Conclut ce qu'on lui a dit de conclure, caméra par caméra."""

    def __init__(self, par_camera):
        self.par_camera, self.observees, self.filtres = par_camera, 0, {}

    def observer(self, images, facteur_conf=1.0):
        self.observees += len(images)
        return [int(i[0, 0, 0]) for i in images]            # la « caméra » est codée dans l'image

    def conclure(self, image, observations, zones=(), garder=None):
        cam = f"rgb{observations[-1]}"
        self.filtres[cam] = garder
        c = self.par_camera.get(cam, Conclusion())
        return Conclusion(list(c.vivants), list(c.objets), [list(z) for z in zones] if c.inconnues else [])


def sources(n=2):
    return [Source(f"rgb{i}", np.full((480, 640, 3), i, np.uint8)) for i in range(n)]


def analyser(moteur, **kw):
    return analyser_essai(moteur, threading.Lock(), kw.pop("rgb", sources()), kw.pop("thermique", None),
                          kw.pop("reference", None), pause_s=0, **kw)


def test_resultat_agrege_les_cameras():
    m = MoteurFactice({"rgb0": Conclusion(objets=[Detection("clés", "valeur", 0.9, [1, 2, 30, 40], ("yoloe", "clip"))]),
                       "rgb1": Conclusion(vivants=[Detection("bébé", "vivant", 0.8, [0, 0, 100, 100], ("entraîné",))],
                                          objets=[Detection("téléphone", "valeur", 0.7, [5, 5, 50, 50])])})
    r = analyser(m, n_images=3)
    assert m.observees == 6                                   # 3 images × 2 caméras
    assert r["objets"] == ["clés", "téléphone"] and r["classes_vivant"] == ["bébé"]
    assert r["vivant_rgb"] is True and r["cameras_vivant"] == ["rgb1"] and r["vivant_thermique"] is None
    vus = {(d["camera"], d["libelle"]) for d in r["detections"]}
    assert vus == {("rgb0", "clés"), ("rgb1", "bébé"), ("rgb1", "téléphone")}
    assert r["detections"][0]["confiance"] == 0.9 and len(r["images_rgb"]) == 2
    assert r["reference_utilisee"] is False and r["zones_nouvelles"] == 0


def test_habitacle_vide_rien_a_signaler():
    r = analyser(MoteurFactice({}))
    assert r["objets"] == [] and r["classes_vivant"] == [] and r["vivant_rgb"] is False


def test_camera_sans_image_ignoree():
    class Morte(Source):
        def derniere(self):
            return None
    r = analyser(MoteurFactice({}), rgb=[Morte("rgb0"), sources(2)[1]])
    assert len(r["images_rgb"]) == 1


class Thermique:
    def __init__(self, chaud):
        self.chaud = chaud

    def mesure(self):
        return {"chaud": self.chaud, "pixels_chauds": 140 if self.chaud else 2, "tmax": 35.0 if self.chaud else None}

    def apercu(self):
        return "<image thermique>"


def test_thermique_vote_a_part():
    r = analyser(MoteurFactice({}), thermique=Thermique(True))
    assert r["vivant_thermique"] is True and r["vivant_rgb"] is False
    assert r["pixels_chauds"] == 140 and r["tmax"] == 35.0
    assert analyser(MoteurFactice({}), thermique=Thermique(False))["vivant_thermique"] is False


def camera0(image):
    """Marque l'image comme venant de rgb0 pour le moteur factice (un pixel)."""
    image = image.copy()
    image[0, 0] = 0
    return image


def reference(tmp_path, images):
    ref = Reference(str(tmp_path), None)
    ref.images = images
    ref.detections = {sid: [] for sid in images}
    return ref


def test_reference_ecarte_ce_qui_etait_deja_la(tmp_path):
    """Boucle de ceinture nommée « clés » : détectée, mais sur des pixels inchangés."""
    vide = np.full((480, 640, 3), 160, np.uint8)
    scene = vide.copy()
    scene[200:260, 300:420] = 20                               # un téléphone posé
    m = MoteurFactice({"rgb0": Conclusion(objets=[Detection("clés", "valeur", 0.9, [50, 50, 90, 90]),
                                                  Detection("téléphone", "valeur", 0.9, [300, 200, 420, 260])])})
    r = analyser(m, rgb=[Source("rgb0", camera0(scene))], reference=reference(tmp_path, {"rgb0": vide}))
    assert r["objets"] == ["téléphone"] and r["reference_utilisee"] and r["zones_nouvelles"] == 1
    garder = m.filtres["rgb0"]                                 # le moteur ne nomme que ce qui a changé
    assert garder([300, 200, 420, 260]) and not garder([50, 50, 90, 90])


def test_zone_non_identifiee_signalee_selon_le_reglage(tmp_path):
    vide = np.full((480, 640, 3), 160, np.uint8)
    scene = vide.copy()
    scene[200:260, 300:420] = 20
    ref = reference(tmp_path, {"rgb0": vide})
    m = MoteurFactice({"rgb0": Conclusion(inconnues=[[0, 0, 1, 1]])})
    assert analyser(m, rgb=[Source("rgb0", camera0(scene))], reference=ref)["objets"] == [INCONNU]
    assert analyser(m, rgb=[Source("rgb0", camera0(scene))], reference=ref, alerte_inconnu=False)["objets"] == []


def test_lumiere_changee_pas_de_filtre_par_les_pixels(tmp_path):
    """Référence inutilisable : on ne filtre plus sur les pixels, seulement sur les
    détections déjà vues au même endroit sur la référence."""
    vide = np.full((480, 640, 3), 160, np.uint8)
    scene = vide.copy()
    scene[:, :420] = 15                                        # les deux tiers de l'image ont changé
    ref = reference(tmp_path, {"rgb0": vide})
    ref.detections["rgb0"] = [("clés", 0.4, [50, 50, 90, 90])]
    m = MoteurFactice({"rgb0": Conclusion(objets=[Detection("clés", "valeur", 0.9, [52, 50, 91, 92]),
                                                  Detection("lunettes", "valeur", 0.9, [300, 200, 420, 260])])})
    r = analyser(m, rgb=[Source("rgb0", camera0(scene))], reference=ref)
    assert r["lumiere_changee"] and r["objets"] == ["lunettes"] and m.filtres["rgb0"] is None


def test_etre_vivant_jamais_ecarte_sur_les_seuls_pixels(tmp_path):
    vide = np.full((480, 640, 3), 160, np.uint8)
    m = MoteurFactice({"rgb0": Conclusion(vivants=[Detection("bébé", "vivant", 0.9, [100, 100, 300, 300])])})
    r = analyser(m, rgb=[Source("rgb0", camera0(vide))], reference=reference(tmp_path, {"rgb0": vide}))
    assert r["classes_vivant"] == ["bébé"]


def test_recadrage_carre_sans_deformation_et_agregation():
    img = np.zeros((480, 640, 3), np.uint8)
    img[100:140, 200:400] = 255
    c = recadrer(img, [200, 100, 400, 140], marge=0.0)
    assert c.shape[0] == c.shape[1] and (c[0, 0] == 127).all() and c[c.shape[0] // 2, c.shape[1] // 2, 0] == 255
    assert recadrer(img, [700, 700, 710, 710]).shape == (8, 8, 3)        # boîte hors image
    assert agreger([0.2, 0.3, 0.5], ["clés", "clés", "_fond"]) == {"clés": 0.5, "_fond": 0.5}


def test_choix_du_moteur_et_reglages_historiques():
    assert creer({"detection": {}}).nom == "care"
    m = creer({"detection": {"moteur": "hybride", "historique": {"confiance_objet": 0.4}}})
    assert isinstance(m, MoteurHistorique) and m.conf_objet == 0.4 and m.libelle("car key") == "clés de voiture"
    assert creer({"detection": {"moteur": "yoloe", "confiance_objet": 0.3}}).conf_objet == 0.3   # ancienne config
    try:
        creer({"detection": {"moteur": "magique"}})
    except ValueError as e:
        assert "magique" in str(e)
    else:
        raise AssertionError("moteur inconnu accepté")


def test_vote_des_moteurs_historiques():
    m = creer({"detection": {"moteur": "yoloe"}, "ratio_presence": 0.5})
    tel = {"nom": "cell phone", "type": "valeur", "conf": 0.6, "boite": [0, 0, 50, 50], "source": "yoloe"}
    reflet = {"nom": "watch", "type": "valeur", "conf": 0.3, "boite": [90, 90, 99, 99], "source": "yoloe"}
    c = m.conclure(None, [[tel], [tel], [tel, reflet]])
    assert [d.cle for d in c.objets] == ["téléphone"] and c.objets[0].extra["nom"] == "cell phone"
