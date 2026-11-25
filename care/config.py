"""Lecture de la configuration, commune au dashboard et aux outils."""
import json
import os


def charger_config(racine):
    """config.json, puis réglages propres au poste, hors dépôt (le dépôt est public) :
    config.local.json est ignoré par git et fusionné section par section par-dessus."""
    with open(os.path.join(racine, "config.json"), encoding="utf-8") as fh:
        cfg = json.load(fh)
    local = os.path.join(racine, "config.local.json")
    if os.path.exists(local):
        with open(local, encoding="utf-8") as fh:
            for k, v in json.load(fh).items():
                cfg[k] = {**cfg.get(k, {}), **v} if isinstance(v, dict) else v
    return cfg


def modifier_config_locale(racine, modifications):
    """Fusionne des réglages dans config.local.json sans toucher aux autres (topic ntfy…)."""
    local = os.path.join(racine, "config.local.json")
    actuel = {}
    if os.path.exists(local):
        with open(local, encoding="utf-8") as fh:
            actuel = json.load(fh)
    for k, v in modifications.items():
        actuel[k] = {**actuel.get(k, {}), **v} if isinstance(v, dict) else v
    with open(local, "w", encoding="utf-8") as fh:
        json.dump(actuel, fh, ensure_ascii=False, indent=2)
    return local
