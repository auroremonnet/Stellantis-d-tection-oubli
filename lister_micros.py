"""Liste les index des périphériques d'entrée pour config.json."""
import sounddevice as sd


for index, appareil in enumerate(sd.query_devices()):
    if appareil["max_input_channels"] > 0:
        print(f"{index}: {appareil['name']} ({appareil['max_input_channels']} canaux, "
              f"{int(appareil['default_samplerate'])} Hz)")
