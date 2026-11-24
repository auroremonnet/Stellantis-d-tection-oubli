from care.peripheriques import resoudre

PC_VOITURE = [  # PC portable dans la voiture : webcam intégrée + 4 USB identiques + thermique
    {"index": 0, "nom": "Integrated Webcam"},
    {"index": 1, "nom": "USB Camera"},
    {"index": 2, "nom": "PureThermal (fw:v1.3.0)"},
    {"index": 3, "nom": "USB Camera"},
    {"index": 4, "nom": "USB Camera"},
    {"index": 5, "nom": "USB Camera"},
]
TH = {"id": "thermal", "index": "auto", "label": "Thermique", "active": True}


def rgb(*index):
    return [{"id": f"rgb{i}", "index": x, "label": f"Cam {i}"} for i, x in enumerate(index)]


def test_auto_ecarte_la_webcam_et_la_thermique():
    r, th = resoudre(rgb("auto", "auto", "auto", "auto"), TH, PC_VOITURE)
    assert [c["source"] for c in r] == [1, 3, 4, 5]
    assert th["source"] == 2
    assert not any(c["probleme"] for c in r + [th])


def test_pas_assez_de_cameras_sans_prendre_la_webcam():
    r, _ = resoudre(rgb("auto", "auto"), None, PC_VOITURE[:2])
    assert r[0]["source"] == 1
    assert r[1]["source"] is None and "pas assez" in r[1]["probleme"]


def test_index_fixe_sur_la_webcam_signale():
    r, _ = resoudre(rgb(0), None, PC_VOITURE)
    assert r[0]["source"] == 0 and "webcam" in r[0]["probleme"]


def test_index_fixe_prioritaire_sur_auto():
    r, _ = resoudre(rgb("auto", 1), None, PC_VOITURE)
    assert r[1]["source"] == 1 and r[0]["source"] == 3


def test_nom_attendu_qui_ne_correspond_plus():
    cams = [{"id": "rgb0", "index": 2, "nom": "USB Camera", "label": "AG"}]
    r, _ = resoudre(cams, None, PC_VOITURE)
    assert "index ont bougé" in r[0]["probleme"]


def test_par_nom_et_url():
    cams = [{"id": "a", "nom": "usb camera", "label": "A"}, {"id": "b", "nom": "USB Camera", "label": "B"},
            {"id": "c", "url": "rtsp://192.168.1.20/stream", "label": "C"}]
    r, _ = resoudre(cams, None, PC_VOITURE)
    assert [c["source"] for c in r] == [1, 3, "rtsp://192.168.1.20/stream"]


def test_noms_illisibles_retombe_sur_les_index_apres_la_webcam():
    r, th = resoudre(rgb("auto", "auto", "auto", "auto"), TH, None)
    assert [c["source"] for c in r] == [1, 2, 3, 4] and th["source"] == 5
    assert "supposé" in r[0]["probleme"]
    r, _ = resoudre(rgb(2, "auto"), None, None)
    assert r[0]["source"] == 2 and not r[0]["probleme"] and r[1]["source"] == 1


def test_webcam_1080p_fhd_du_pc_ecartee():
    """Le PC du banc : sa webcam s'appelle « 1080p FHD Camera » (index 4)."""
    import json
    from pathlib import Path
    cfg = json.loads(Path(__file__).parent.parent.joinpath("config.json").read_text("utf-8"))
    banc = [{"index": 0, "nom": "UVC Camera"}, {"index": 1, "nom": "USB Camera"},
            {"index": 2, "nom": "USB Camera"}, {"index": 3, "nom": "USB Camera"},
            {"index": 4, "nom": "1080p FHD Camera"}, {"index": 5, "nom": "USB Camera"}]
    th = {"id": "thermal", "index": 0, "nom": "UVC Camera", "label": "Thermique", "active": True}
    r, t = resoudre(rgb("auto", "auto", "auto", "auto"), th, banc, cfg["cameras"])
    assert [c["source"] for c in r] == [1, 2, 3, 5] and t["source"] == 0
    r, _ = resoudre(rgb(4), None, banc, cfg["cameras"])
    assert "webcam du PC" in r[0]["probleme"]
