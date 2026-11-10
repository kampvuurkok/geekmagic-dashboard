"""Aansturing van de GeekMagic SmallTV-PRO (firmware V3.3.x) via zijn eigen webinterface.

Het schermpje is traag en kan maar weinig verbindingen tegelijk aan:
alle verzoeken gaan daarom één voor één, met een korte pauze ertussen.
"""
import logging
import re
import time

import requests

log = logging.getLogger("device")


class SmallTV:
    def __init__(self, host: str, picture_theme: int = 4, timeout: float = 15):
        self.base = f"http://{host}"
        self.picture_theme = picture_theme
        self.timeout = timeout
        self.s = requests.Session()

    def _get(self, path: str, **params):
        for poging in range(3):
            try:
                r = self.s.get(self.base + path, params=params, timeout=self.timeout)
                r.raise_for_status()
                time.sleep(0.3)
                return r
            except requests.RequestException as e:
                log.warning("GET %s mislukt (poging %d): %s", path, poging + 1, e)
                time.sleep(2)
        raise ConnectionError(f"scherm reageert niet op {path}")

    def list_images(self) -> list[str]:
        html = self._get("/filelist", dir="/image/").text
        # het scherm geeft een HTML-tabel terug; haal de tags weg en pak de bestandsnamen
        tekst = re.sub(r"<[^>]+>", " ", html)
        return sorted(set(re.findall(r"[\w.\-]+\.(?:jpe?g|gif)\b", tekst, flags=re.I)))

    def delete(self, naam: str):
        self._get("/delete", file="/image/" + naam)

    def upload(self, naam: str, data: bytes):
        # zelfde vorm als de eigen webinterface: veld 'file', dir niet gecodeerd (getest 10-11-2026)
        url = self.base + "/doUpload?dir=/image/"
        for poging in range(3):
            try:
                r = self.s.post(url, files={"file": (naam, data, "image/jpeg")}, timeout=self.timeout * 2)
                r.raise_for_status()
                time.sleep(0.5)
                return
            except requests.RequestException as e:
                log.warning("upload %s mislukt (poging %d): %s", naam, poging + 1, e)
                time.sleep(3)
        raise ConnectionError(f"upload van {naam} mislukt")

    def show(self, naam: str):
        self._get("/set", img="/image/" + naam)

    def select_picture_app(self):
        self._get("/set", theme=str(self.picture_theme))

    def cleanup(self, behouden: set[str]):
        """Verwijdert alles in /image/ wat niet van het dashboard is."""
        for naam in self.list_images():
            if naam not in behouden:
                log.info("verwijder %s van het scherm", naam)
                self.delete(naam)
