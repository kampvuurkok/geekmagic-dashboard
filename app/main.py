"""GeekMagic-dashboard – hoofdlus.

Haalt periodiek gegevens op, tekent pagina's en toont ze om de beurt op de SmallTV.
"""
import datetime as dt
import hashlib
import json
import logging
import os
import time

import aws
import render
import sources
import status
from device import SmallTV

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("main")


def env(naam, standaard=None, cast=str):
    w = os.environ.get(naam, "")
    return cast(w) if w != "" else standaard


CFG = {
    "device": env("DEVICE_HOST", ""),
    "picture_theme": env("PICTURE_THEME", 4, int),
    "page_seconds": env("PAGE_SECONDS", 10, int),
    "dry_run": env("DRY_RUN", "0") == "1",
    "data_dir": env("DATA_DIR", "/data"),
    "newsletter_label": env("NEWSLETTER_LABEL", "leden nieuwsbrief"),
    "status_port": env("STATUS_PORT", 8080, int),
    "pages": [p.strip() for p in env("PAGES", "weer,nieuwsbrief").split(",") if p.strip()],
    "weather": {
        "name": env("WEATHER_NAME", "Weer"),
        "lat": env("WEATHER_LAT", None, float),
        "lon": env("WEATHER_LON", None, float),
        "every": env("WEATHER_MINUTES", 15, int) * 60,
        "rain_every": env("RAIN_MINUTES", 5, int) * 60,
    },
    "phplist": {
        "host": env("PHPLIST_DB_HOST", "phplist-db"),
        "port": env("PHPLIST_DB_PORT", 3306, int),
        "db": env("PHPLIST_DB_NAME", "phplist"),
        "user": env("PHPLIST_DB_USER", "geekmagic"),
        "password": env("PHPLIST_DB_PASSWORD", ""),
        "prefix": env("PHPLIST_TABLE_PREFIX", "phplist_"),
        "list_id": env("PHPLIST_LIST_ID", 1, int),
        "every": env("STATS_MINUTES", 15, int) * 60,
    },
    "unraid": {
        "api_url": env("UNRAID_API_URL", ""),
        "api_key": env("UNRAID_API_KEY", ""),
        "compose_status": env("COMPOSE_STATUS_FILE", "/host/plugins/compose.manager/update-status.json"),
        "plugins_installed": env("PLUGINS_INSTALLED_DIR", "/host/plugins"),
        "plugins_tmp": env("PLUGINS_TMP_DIR", "/host/tmp-plugins"),
        "os_check": env("OS_CHECK_FILE", "/host/unraidcheck/result.json"),
        "every": env("UPDATES_MINUTES", 60, int) * 60,
    },
    "umami": {
        "url": env("UMAMI_URL", ""),
        "website_id": env("UMAMI_WEBSITE_ID", ""),
        "api_key": env("UMAMI_API_KEY", ""),
        "username": env("UMAMI_USERNAME", ""),
        "password": env("UMAMI_PASSWORD", ""),
        "every": env("STATS_MINUTES", 15, int) * 60,
    },
    "google": {
        "api_key": env("GOOGLE_API_KEY", ""),
        "place_id": env("GOOGLE_PLACE_ID", ""),
        "query": env("GOOGLE_PLACE_QUERY", ""),
        "data_dir": env("DATA_DIR", "/data"),
        # rating/aantal valt in de Enterprise-categorie (1.000 gratis per maand): standaard elke 2 uur
        "every": env("GOOGLE_MINUTES", 120, int) * 60,
    },
    "meta": {
        "token": env("META_PAGE_TOKEN", ""),
        "page_id": env("META_PAGE_ID", ""),
        "ig_id": env("META_IG_ID", ""),
        "version": env("META_API_VERSION", "v27.0"),
        "every": env("STATS_MINUTES", 15, int) * 60,
    },
    "wordpress": {
        "host": env("WP_SSH_HOST", ""),
        "port": env("WP_SSH_PORT", 22, int),
        "user": env("WP_SSH_USER", ""),
        "key": env("WP_SSH_KEY", "/data/ssh/id_ed25519"),
        "known_hosts": env("WP_SSH_KNOWN_HOSTS", "/data/ssh/known_hosts"),
        # komma-gescheiden paden t.o.v. de SSH-thuismap, bv. "httpdocs,stegehuis.org"
        "paths": env("WP_PATHS", "auto"),
        "exclude": env("WP_EXCLUDE", ""),
        "labels": dict(x.split("=", 1) for x in env("WP_LABELS", "").split(",") if "=" in x),
        "every": env("WORDPRESS_MINUTES", 240, int) * 60,
    },
    "aws": {
        "access_key": env("AWS_ACCESS_KEY_ID", ""),
        "secret_key": env("AWS_SECRET_ACCESS_KEY", ""),
        "session_token": env("AWS_SESSION_TOKEN", ""),
        # regio's waar SES gebruikt wordt (Stockholm = eu-north-1)
        "regions": [r.strip() for r in env("AWS_SES_REGIONS", "eu-north-1").split(",") if r.strip()],
        "exclude": [x.strip() for x in env("AWS_SES_EXCLUDE", "").split(",") if x.strip()],
        "emails": env("AWS_SES_EMAILS", "0") == "1",  # ook losse e-mailadressen controleren
        # optioneel: SQS-wachtrij waar een EventBridge-regel de AWS Health-meldingen in zet
        "queue_url": env("AWS_HEALTH_QUEUE_URL", ""),
        "health_days": env("AWS_HEALTH_DAYS", 7, int),
        "data_dir": env("DATA_DIR", "/data"),
        "every": env("AWS_MINUTES", 60, int) * 60,
    },
}

def kort(regel: str) -> str:
    """'naam 1.0 → 1.1' wordt 'naam → 1.1' (past beter op het schermpje)."""
    delen = regel.split(" ")
    if len(delen) == 4 and delen[2] == "→":
        return f"{delen[0]} → {delen[3]}"
    return regel


def bestandsnaam(pg: str) -> str:
    """Vaste namen voor de vaste pagina's, korte afgeleide namen voor de updatetegels."""
    if pg in BESTANDEN:
        return BESTANDEN[pg]
    slug = "".join(c if c.isalnum() else "-" for c in pg.split(":", 1)[-1].lower()).strip("-")
    return f"dash_9_{slug[:18]}.jpg"


BESTANDEN = {"weer": "dash_1_weer.jpg", "nieuwsbrief": "dash_4_nieuwsbrief.jpg", "website": "dash_6_website.jpg", "instagram": "dash_2_instagram.jpg", "facebook": "dash_3_facebook.jpg", "google": "dash_5_google.jpg", "updates": "dash_9_updates.jpg"}


class State:
    """Bewaart de waarde aan het begin van de dag, voor '+N vandaag'."""

    def __init__(self, pad):
        self.pad = pad
        try:
            with open(pad) as f:
                self.d = json.load(f)
        except (OSError, ValueError):
            self.d = {}

    def delta(self, sleutel, waarde, vandaag):
        rec = self.d.get(sleutel)
        if not rec or rec.get("date") != vandaag:
            # nieuwe dag: begin bij de laatste waarde van gisteren (of de huidige)
            basis = rec["last"] if rec else waarde
            rec = {"date": vandaag, "base": basis}
        if rec.get("last") != waarde or self.d.get(sleutel) is not rec:
            rec["last"] = waarde
            self.d[sleutel] = rec
            self._save()
        return waarde - rec["base"]

    def _save(self):
        tmp = self.pad + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.d, f)
        os.replace(tmp, self.pad)


class Bron:
    """Een gegevensbron met eigen interval en laatst-gelukte-tijd."""

    def __init__(self, naam, functie, interval):
        self.naam, self.functie, self.interval = naam, functie, interval
        self.waarde = None
        self.bijgewerkt = None  # datetime van laatste succes
        self.volgende = 0.0
        self.fout = None

    def misschien_ophalen(self, nu):
        if nu < self.volgende:
            return False
        try:
            self.waarde = self.functie()
            self.bijgewerkt = dt.datetime.now(sources.TZ)
            self.volgende = nu + self.interval
            self.fout = None
            log.info("%s bijgewerkt: %s", self.naam, self.waarde)
            return True
        except Exception as e:  # noqa: BLE001 – een kapotte bron mag de rest niet stoppen
            self.fout = str(e)[:200]
            log.warning("%s ophalen mislukt: %s", self.naam, e)
            # nog nooit gelukt (bv. netwerk nog niet klaar na herstart): snel opnieuw
            self.volgende = nu + (30 if self.waarde is None else min(self.interval, 120))
            return False

    def status(self):
        if not self.bijgewerkt:
            return {"updated": None, "stale": False}
        oud = (dt.datetime.now(sources.TZ) - self.bijgewerkt).total_seconds() > self.interval * 4
        return {"updated": f"{self.bijgewerkt:%H:%M}", "stale": oud}


def main():
    os.makedirs(CFG["data_dir"], exist_ok=True)
    state = State(os.path.join(CFG["data_dir"], "state.json"))
    preview_dir = os.path.join(CFG["data_dir"], "preview")
    os.makedirs(preview_dir, exist_ok=True)

    w, p = CFG["weather"], CFG["phplist"]
    bronnen = {
        "weer": Bron("weer", lambda: sources.fetch_weather(w["lat"], w["lon"]), w["every"]),
        "regen": Bron("regen", lambda: sources.fetch_rain(w["lat"], w["lon"]), w["rain_every"]),
        "nieuwsbrief": Bron("nieuwsbrief", lambda: sources.fetch_phplist(p), p["every"]),
        "google": Bron("google", lambda: sources.fetch_google(CFG["google"]), CFG["google"]["every"]),
        "meta": Bron("meta", lambda: sources.fetch_meta(CFG["meta"]), CFG["meta"]["every"]),
        "website": Bron("website", lambda: sources.fetch_umami(CFG["umami"]), CFG["umami"]["every"]),
        "updates": Bron("updates", lambda: sources.fetch_unraid_updates(CFG["unraid"]), CFG["unraid"]["every"]),
        "wordpress": Bron("wordpress", lambda: sources.fetch_wordpress_updates(CFG["wordpress"]),
                          CFG["wordpress"]["every"]),
        "aws": Bron("aws", lambda: aws.fetch_aws(CFG["aws"]), CFG["aws"]["every"]),
    }

    go = CFG["google"]
    if not (go["api_key"] and (go["place_id"] or go["query"])):
        if "google" in CFG["pages"]:
            log.warning("GOOGLE_API_KEY en GOOGLE_PLACE_ID/GOOGLE_PLACE_QUERY nodig: Google-pagina uit")
        CFG["pages"] = [pg for pg in CFG["pages"] if pg != "google"]
        del bronnen["google"]
    me = CFG["meta"]
    if not (me["token"] and me["page_id"]):
        if {"instagram", "facebook"} & set(CFG["pages"]):
            log.warning("META_PAGE_TOKEN/META_PAGE_ID niet ingesteld: Instagram- en Facebook-pagina uit")
        CFG["pages"] = [pg for pg in CFG["pages"] if pg not in ("instagram", "facebook")]
        del bronnen["meta"]
    um = CFG["umami"]
    if not (um["url"] and um["website_id"] and (um["api_key"] or (um["username"] and um["password"]))):
        if "website" in CFG["pages"]:
            log.warning("UMAMI_URL/UMAMI_WEBSITE_ID/inloggegevens niet compleet: websitepagina uit")
        CFG["pages"] = [pg for pg in CFG["pages"] if pg != "website"]
        del bronnen["website"]
    if not CFG["dry_run"] and not CFG["device"]:
        raise SystemExit("DEVICE_HOST is niet ingesteld (IP-adres van het scherm)")
    if w["lat"] is None or w["lon"] is None:
        if "weer" in CFG["pages"]:
            log.warning("WEATHER_LAT/WEATHER_LON niet ingesteld: weerpagina uit")
        CFG["pages"] = [pg for pg in CFG["pages"] if pg != "weer"]
        del bronnen["weer"], bronnen["regen"]
    tv = None if CFG["dry_run"] else SmallTV(CFG["device"], CFG["picture_theme"])
    actief = [pg for pg in CFG["pages"] if pg in BESTANDEN and pg != "updates"]
    updates_aan = "updates" in CFG["pages"]
    if not updates_aan:
        del bronnen["updates"]
    if not updates_aan or not (CFG["wordpress"]["host"] and CFG["wordpress"]["user"]):
        del bronnen["wordpress"]
    ak = CFG["aws"]
    if "aws" not in CFG["pages"] or not (ak["access_key"] and ak["secret_key"]):
        if "aws" in CFG["pages"]:
            log.warning("AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY niet ingesteld: Amazon-tegel uit")
        del bronnen["aws"]
    if not actief:
        raise SystemExit("PAGES bevat geen bekende pagina's")
    log.info("start; pagina's: %s; scherm: %s", actief, "DRY_RUN" if tv is None else CFG["device"])
    if CFG["status_port"]:
        status.start(CFG["status_port"])
        status.zet("gestart", dt.datetime.now(sources.TZ).strftime("%d-%m %H:%M"))
        log.info("statuspagina op poort %s", CFG["status_port"])

    geupload = {}  # bestandsnaam -> hash van wat er op het scherm staat
    opgeruimd = False
    index = 0
    while True:
        nu = time.time()
        for b in bronnen.values():
            b.misschien_ophalen(nu)

        status.zet("bronnen", {
            n: {"waarde": b.waarde, "bijgewerkt": f"{b.bijgewerkt:%d-%m %H:%M}" if b.bijgewerkt else None,
                "stale": b.status()["stale"], "fout": b.fout}
            for n, b in bronnen.items()
        })
        status.zet("updates", bronnen["updates"].waarde if "updates" in bronnen else None)
        status.zet("wordpress", bronnen["wordpress"].waarde if "wordpress" in bronnen else None)
        status.zet("aws", bronnen["aws"].waarde if "aws" in bronnen else None)
        regen = bronnen["regen"].waarde if "regen" in bronnen else None
        upd = bronnen["updates"].waarde if updates_aan else None
        wp = bronnen["wordpress"].waarde if "wordpress" in bronnen else None
        if upd is not None or wp is not None:
            upd = dict(upd or {"docker": [], "compose": [], "plugins": [], "os": None, "total": 0})
            upd["wp"] = wp
            upd["total"] = (upd.get("total") or 0) + (wp["total"] if wp else 0)
        algemeen = {"drop": bool(regen and regen["drop"]),
                    "updates": bool(upd and upd["total"]),
                    "updates_urgent": bool(upd and (upd["os"] or (wp and wp["core"])))}
        am = bronnen["aws"].waarde if "aws" in bronnen else None
        if am and am["total"]:
            # Amazon-problemen tellen mee voor het stipje (rood als het ernstig is)
            algemeen["updates"] = True
            algemeen["updates_urgent"] = algemeen["updates_urgent"] or am["urgent"]

        beelden = {}
        if "weer" in actief:
            st = {**algemeen, **bronnen["weer"].status()}
            beelden["weer"] = render.pagina_weer(w["name"], bronnen["weer"].waarde, regen, st)
        if "nieuwsbrief" in actief:
            b = bronnen["nieuwsbrief"]
            delta = None
            if b.waarde is not None and b.bijgewerkt:
                delta = state.delta("nieuwsbrief", b.waarde, b.bijgewerkt.date().isoformat())
            st = {**algemeen, **b.status()}
            beelden["nieuwsbrief"] = render.pagina_getal("Nieuwsbrief", "envelop", b.waarde, delta,
                                                         CFG["newsletter_label"], st)

        for soort, titel, icoon, kleur in (("instagram", "Instagram", "camera", render.INSTA_KLEUR),
                                           ("facebook", "Facebook", "duim", render.FACEBOOK_KLEUR)):
            if soort in actief:
                b = bronnen["meta"]
                n = b.waarde.get(soort) if b.waarde else None
                delta = None
                if n is not None and b.bijgewerkt:
                    delta = state.delta(soort, n, b.bijgewerkt.date().isoformat())
                beelden[soort] = render.pagina_getal(titel, icoon, n, delta, "volgers",
                                                     {**algemeen, **b.status()}, icoonkleur=kleur)
        if "google" in actief:
            b = bronnen["google"]
            g = b.waarde
            nieuw = None
            if g and b.bijgewerkt:
                nieuw = max(0, state.delta("google_reviews", g["count"], b.bijgewerkt.date().isoformat()))
            beelden["google"] = render.pagina_score("Google", g["rating"] if g else None,
                                                    g["count"] if g else None, nieuw,
                                                    {**algemeen, **b.status()})
        if "website" in actief:
            b = bronnen["website"]
            v = b.waarde
            extra = None
            if v:
                extra = f"{render.nl_getal(v['pageviews'])} weergaven"
                if v.get("active") is not None:
                    extra += f" · {v['active']} nu online"
            beelden["website"] = render.pagina_getal("Website", "wereld", v["visitors"] if v else None, None,
                                                     "bezoekers vandaag", {**algemeen, **b.status()}, extra=extra)
        # updatetegels: één voor Unraid, en één per WordPress-site met updates
        tegels = []
        u = bronnen["updates"].waarde if "updates" in bronnen else None
        if u and u.get("total"):
            regels = []
            if u.get("os"):
                regels.append((f"Unraid → {u['os']}", render.ROOD))
            regels += [(f"Docker: {n}", render.ORANJE) for n in u.get("docker", [])]
            regels += [(f"Compose: {n.split('/')[-1]}", render.ORANJE) for n in u.get("compose", [])]
            regels += [(f"Plugin: {kort(n)}", render.ORANJE) for n in u.get("plugins", [])]
            st = {**algemeen, **bronnen["updates"].status()}
            n = u["total"]
            beelden["upd:unraid"] = render.pagina_lijst("Unraid", regels, st,
                                                        onderkop=f"{n} update{'s' if n != 1 else ''} klaar")
            tegels.append("upd:unraid")
        if wp:
            st = {**algemeen, **bronnen["wordpress"].status()}
            for site, info in sorted((wp.get("sites") or {}).items()):
                regels = []
                if info.get("core"):
                    regels.append((f"WordPress → {info['core']}", render.ROOD))
                regels += [(kort(p), render.ORANJE) for p in info.get("plugins", [])]
                regels += [(f"Thema: {kort(t)}", render.ORANJE) for t in info.get("themes", [])]
                if info.get("error"):
                    regels.append(("controle mislukt", render.ROOD))
                if regels:
                    n = len(regels)
                    pg = f"upd:{site}"
                    beelden[pg] = render.pagina_lijst(site, regels, st,
                                                      onderkop=f"{n} update{'s' if n != 1 else ''} klaar")
                    tegels.append(pg)
        # Amazon-tegel: alleen als er een probleem is
        if am and am["total"]:
            regels = [(t, render.ROOD if e else render.ORANJE) for t, e in am["problems"]]
            n = am["total"]
            beelden["upd:amazon"] = render.pagina_lijst("Amazon", regels, {**algemeen, **bronnen["aws"].status()},
                                                        onderkop=f"{n} probleem" + ("en" if n != 1 else ""))
            tegels.insert(0, "upd:amazon")
        rotatie = actief + tegels
        if not rotatie:
            rotatie = list(beelden) or ["weer"]

        try:
            if tv and not opgeruimd:
                tv.select_picture_app()
                tv.cleanup({bestandsnaam(pg) for pg in beelden})
                geupload.clear()
                opgeruimd = True

            # pagina's die niet meer nodig zijn (bv. updates = 0) van het scherm halen,
            # anders bladert de firmware er zelf nog langs
            nodig = {bestandsnaam(pg) for pg in beelden}
            for naam in [n for n in geupload if n not in nodig]:
                if tv:
                    tv.delete(naam)
                    log.info("%s van het scherm gehaald", naam)
                del geupload[naam]

            for pg, data in beelden.items():
                naam = bestandsnaam(pg)
                h = hashlib.sha1(data).hexdigest()
                if geupload.get(naam) == h:
                    continue
                with open(os.path.join(preview_dir, naam), "wb") as f:
                    f.write(data)
                if tv:
                    tv.delete(naam)  # eerst weg, zodat de upload het oude bestand zeker vervangt
                    tv.upload(naam, data)
                    log.info("%s geüpload (%d bytes)", naam, len(data))
                geupload[naam] = h

            pagina = rotatie[index % len(rotatie)]
            if tv:
                tv.show(bestandsnaam(pagina))
            index += 1
        except ConnectionError as e:
            log.warning("scherm niet bereikbaar: %s – opnieuw over 30 s", e)
            opgeruimd = False  # na een herstart van het scherm opnieuw instellen
            time.sleep(30)
            continue

        time.sleep(CFG["page_seconds"])


if __name__ == "__main__":
    main()
