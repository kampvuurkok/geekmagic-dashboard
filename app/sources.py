"""Gegevensbronnen: weer (Open-Meteo + Buienradar) en phpList."""
import datetime as dt
import logging
import os
from zoneinfo import ZoneInfo

import requests

log = logging.getLogger("sources")
TZ = ZoneInfo(os.environ.get("TZ", "Europe/Amsterdam"))
UA = {"User-Agent": "geekmagic-dashboard/0.1 (prive dashboard)"}

# WMO-weercodes -> (Nederlandse omschrijving, icoontype)
WMO = {
    0: ("Onbewolkt", "clear"),
    1: ("Vrijwel onbewolkt", "clear"),
    2: ("Half bewolkt", "partly"),
    3: ("Bewolkt", "cloud"),
    45: ("Mist", "fog"),
    48: ("Rijpmist", "fog"),
    51: ("Lichte motregen", "drizzle"),
    53: ("Motregen", "drizzle"),
    55: ("Dichte motregen", "drizzle"),
    56: ("IJzel", "drizzle"),
    57: ("IJzel", "drizzle"),
    61: ("Lichte regen", "rain"),
    63: ("Regen", "rain"),
    65: ("Zware regen", "rain"),
    66: ("IJzel", "rain"),
    67: ("IJzel", "rain"),
    71: ("Lichte sneeuw", "snow"),
    73: ("Sneeuw", "snow"),
    75: ("Zware sneeuw", "snow"),
    77: ("Sneeuwkorrels", "snow"),
    80: ("Regenbuien", "rain"),
    81: ("Regenbuien", "rain"),
    82: ("Zware buien", "rain"),
    85: ("Sneeuwbuien", "snow"),
    86: ("Sneeuwbuien", "snow"),
    95: ("Onweer", "thunder"),
    96: ("Onweer met hagel", "thunder"),
    99: ("Onweer met hagel", "thunder"),
}

WINDRICHTING = ["N", "NO", "O", "ZO", "Z", "ZW", "W", "NW"]
BEAUFORT_MS = [0.3, 1.6, 3.4, 5.5, 8.0, 10.8, 13.9, 17.2, 20.8, 24.5, 28.5, 32.7]


def beaufort(ms: float) -> int:
    for bft, grens in enumerate(BEAUFORT_MS):
        if ms < grens:
            return bft
    return 12


def fetch_weather(lat: float, lon: float) -> dict:
    r = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,weather_code,wind_speed_10m,wind_direction_10m,is_day",
            "daily": "temperature_2m_max,temperature_2m_min",
            "wind_speed_unit": "ms",
            "timezone": "Europe/Amsterdam",
            "forecast_days": 1,
        },
        headers=UA,
        timeout=15,
    )
    r.raise_for_status()
    j = r.json()
    cur, daily = j["current"], j["daily"]
    code = int(cur["weather_code"])
    tekst, icoon = WMO.get(code, ("Onbekend", "cloud"))
    if icoon in ("clear", "partly") and not cur.get("is_day", 1):
        icoon += "_night"
    return {
        "temp": cur["temperature_2m"],
        "code": code,
        "text": tekst,
        "icon": icoon,
        "wind_bft": beaufort(cur["wind_speed_10m"]),
        "wind_dir": WINDRICHTING[int((cur["wind_direction_10m"] + 22.5) % 360 // 45)],
        "tmin": daily["temperature_2m_min"][0],
        "tmax": daily["temperature_2m_max"][0],
    }


def fetch_rain(lat: float, lon: float) -> dict:
    """Buienradar-regenverwachting, 2 uur vooruit in stappen van 5 minuten.

    Elke regel is 'waarde|HH:MM'; neerslag in mm/u = 10 ** ((waarde - 109) / 32).
    """
    r = requests.get(
        "https://gpsgadget.buienradar.nl/data/raintext",
        params={"lat": f"{lat:.2f}", "lon": f"{lon:.2f}"},
        headers=UA,
        timeout=15,
    )
    r.raise_for_status()
    now = dt.datetime.now(TZ)
    reeks = []
    for regel in r.text.strip().splitlines():
        try:
            waarde, tijd = regel.strip().split("|")
            hh, mm = map(int, tijd.split(":"))
        except ValueError:
            continue
        t = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if t < now - dt.timedelta(hours=1):  # over middernacht heen
            t += dt.timedelta(days=1)
        mmu = 10 ** ((int(waarde) - 109) / 32) if int(waarde) > 0 else 0.0
        reeks.append((t, mmu >= 0.1))
    if not reeks:
        raise ValueError("lege regenverwachting")
    return samenvatting_regen(reeks, now)


def samenvatting_regen(reeks, now) -> dict:
    """Maakt van een reeks (tijd, regent) een korte regel en de druppel-vlag."""
    if reeks[0][1]:
        droog = next((t for t, nat in reeks if not nat), None)
        regel = f"Regen tot {droog:%H:%M}" if droog else "Regen, komende 2 uur"
        return {"line": regel, "drop": True}
    eerste = next((t for t, nat in reeks if nat), None)
    if eerste is None:
        return {"line": "Komende 2 uur droog", "drop": False}
    minuten = max(0, int((eerste - now).total_seconds() // 60))
    if minuten <= 60:
        return {"line": f"Regen over {minuten} min" if minuten > 2 else "Regen begint nu", "drop": True}
    return {"line": f"Droog tot {eerste:%H:%M}", "drop": False}


def fetch_phplist(cfg: dict) -> int:
    import pymysql  # pas hier, zodat de rest zonder database kan draaien

    p = cfg["prefix"]
    sql = (
        f"SELECT COUNT(*) FROM {p}listuser lu "
        f"JOIN {p}user_user u ON u.id = lu.userid "
        "WHERE lu.listid = %s AND u.confirmed = 1 AND u.blacklisted = 0"
    )
    conn = pymysql.connect(
        host=cfg["host"],
        port=cfg["port"],
        user=cfg["user"],
        password=cfg["password"],
        database=cfg["db"],
        connect_timeout=10,
        read_timeout=10,
    )
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (cfg["list_id"],))
            return int(cur.fetchone()[0])
    finally:
        conn.close()


# ---------------------------------------------------------------- Unraid-updates

def _versie_tuple(v: str):
    import re
    return tuple(int(x) for x in re.findall(r"\d+", v or ""))


def _plg_versie(pad: str, fouten=None):
    """Leest de versie uit een .plg-bestand (ENTITY of PLUGIN-attribuut)."""
    import re
    try:
        with open(pad, encoding="utf-8", errors="replace") as f:
            kop = f.read(8192)
    except FileNotFoundError:
        return None
    except OSError as e:
        if fouten is not None:
            fouten.append(f"plugin: {e}")
        return None
    entity = re.search(r'<!ENTITY\s+version\s+"([^"]+)"', kop)
    attr = re.search(r'<PLUGIN\b[^>]*\sversion="([^"]+)"', kop, flags=re.S)
    if attr and not attr.group(1).startswith("&"):
        return attr.group(1)
    return entity.group(1) if entity else None


def fetch_unraid_updates(cfg: dict) -> dict:
    """Telt beschikbare updates; elk onderdeel faalt los van de rest.

    Resultaat: {"docker": [...], "compose": [...], "plugins": [...], "os": "7.x" of None, "errors": [...]}
    """
    import glob
    import json

    res = {"docker": [], "compose": [], "plugins": [], "os": None, "errors": []}
    compose_namen = set()

    # Compose Manager: eigen updatecheck per container (vastgepinde containers tellen niet mee)
    try:
        with open(cfg["compose_status"]) as f:
            data = json.load(f)
        for project, p in data.items():
            for c in p.get("containers", []):
                compose_namen.add(c.get("name"))
                if c.get("hasUpdate") and not c.get("isPinned"):
                    res["compose"].append(f"{project}/{c.get('name')}")
    except (OSError, ValueError, AttributeError) as e:
        res["errors"].append(f"compose: {e}")

    # Gewone dockers via de Unraid API
    if cfg.get("api_url") and cfg.get("api_key"):
        try:
            r = requests.post(
                cfg["api_url"],
                json={"query": "{ docker { containers { names isUpdateAvailable } } }"},
                headers={"x-api-key": cfg["api_key"], **UA},
                timeout=20,
            )
            r.raise_for_status()
            for c in r.json()["data"]["docker"]["containers"]:
                naam = (c.get("names") or ["?"])[0].lstrip("/")
                if c.get("isUpdateAvailable") and naam not in compose_namen:
                    res["docker"].append(naam)
        except (requests.RequestException, ValueError, KeyError, TypeError) as e:
            res["errors"].append(f"api: {e}")

    # Plugins: nieuwste versie (in /tmp/plugins na de check) tegen geïnstalleerde versie
    for nieuw in glob.glob(f"{cfg['plugins_tmp']}/*.plg"):
        naam = nieuw.rsplit("/", 1)[-1]
        if naam == "unRAIDServer.plg":
            continue
        v_nieuw = _plg_versie(nieuw, res["errors"])
        v_oud = _plg_versie(f"{cfg['plugins_installed']}/{naam}", res["errors"])
        if v_nieuw and v_oud and _versie_tuple(v_nieuw) > _versie_tuple(v_oud):
            res["plugins"].append(f"{naam[:-4]} {v_oud} → {v_nieuw}")

    if not glob.glob(f"{cfg['plugins_tmp']}/*.plg"):
        res["errors"].append("plugins: geen bestanden in /tmp/plugins (nog geen updatecheck gedraaid?)")

    # Unraid OS
    try:
        with open(cfg["os_check"]) as f:
            os_res = json.load(f)
        if os_res.get("isNewer"):
            res["os"] = os_res.get("version") or "nieuw"
    except FileNotFoundError:
        pass
    except (OSError, ValueError) as e:
        res["errors"].append(f"os: {e}")

    res["total"] = len(res["docker"]) + len(res["compose"]) + len(res["plugins"]) + (1 if res["os"] else 0)
    return res


# ---------------------------------------------------------------- WordPress-updates

def fetch_wordpress_updates(cfg: dict) -> dict:
    """Vraagt via SSH + WP-CLI per site de beschikbare updates op.

    Eén SSH-verbinding voor alle sites. Resultaat:
    {"core": ["site 6.8 → 6.9"], "plugins": [...], "themes": [...], "errors": [...], "total": n}
    """
    import json
    import shlex
    import subprocess

    res = {"core": [], "plugins": [], "themes": [], "errors": []}
    paden = [p.strip() for p in cfg["paths"].split(",") if p.strip()]
    stukken = []
    for pad in paden:
        q = shlex.quote(pad)
        # --skip-plugins/--skip-themes: plugins niet inladen, zodat een plugin die een nieuwere
        # PHP vraagt dan de PHP van de commandoregel de check niet laat crashen.
        wp = f"wp --path={q} --skip-plugins --skip-themes"
        stukken.append(
            f"echo; echo '@@SITE {pad}'; "
            f"echo '@@core'; {wp} core check-update --format=json 2>&1; "
            f"echo; echo '@@plugins'; {wp} plugin list --update=available --fields=name,version,update_version --format=json 2>&1; "
            f"echo; echo '@@themes'; {wp} theme list --update=available --fields=name,version,update_version --format=json 2>&1; echo"
        )
    opdracht = [
        "ssh", "-i", cfg["key"], "-p", str(cfg["port"]),
        "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", f"UserKnownHostsFile={cfg['known_hosts']}",
        "-o", "ConnectTimeout=20",
        "-o", "LogLevel=ERROR",
        f"{cfg['user']}@{cfg['host']}",
        "; ".join(stukken),
    ]
    p = subprocess.run(opdracht, capture_output=True, text=True, timeout=180)
    if p.returncode != 0 and "@@SITE" not in p.stdout:
        raise RuntimeError(f"ssh mislukt ({p.returncode}): {p.stderr.strip()[:200]}")

    site, soort, buffer = None, None, []

    def verwerk():
        if not site or not soort:
            return
        tekst = "\n".join(buffer).strip()
        label = site.rstrip("/").split("/")[-1]
        label = cfg["labels"].get(site, label)
        try:
            data = json.loads(tekst or "[]")
        except ValueError:
            res["errors"].append(f"{label} {soort}: {tekst[:120]}")
            return
        for item in data:
            if soort == "core":
                res["core"].append(f"{label} → {item.get('version')}")
            else:
                res[soort].append(f"{label}: {item.get('name')} {item.get('version')} → {item.get('update_version')}")

    for regel in p.stdout.splitlines():
        regel = regel.rstrip()
        if regel.startswith("@@SITE "):
            verwerk()
            site, soort, buffer = regel[7:], None, []
        elif regel in ("@@core", "@@plugins", "@@themes"):
            verwerk()
            soort, buffer = regel[2:], []
        else:
            buffer.append(regel)
    verwerk()

    # alleen versies van de kern tellen één keer per site
    res["total"] = len(res["core"]) + len(res["plugins"]) + len(res["themes"])
    return res


# ---------------------------------------------------------------- Umami (websitebezoekers)

def _umami_headers(cfg: dict, vorm: int = 0) -> dict:
    """API-sleutel als die er is (twee schrijfwijzen), anders inloggen met gebruikersnaam/wachtwoord."""
    if cfg.get("api_key"):
        if vorm == 0:
            return {"x-umami-api-key": cfg["api_key"], **UA}
        return {"Authorization": f"Bearer {cfg['api_key']}", **UA}
    r = requests.post(
        cfg["url"].rstrip("/") + "/api/auth/login",
        json={"username": cfg["username"], "password": cfg["password"]},
        headers=UA,
        timeout=15,
    )
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['token']}", **UA}


def _waarde(v):
    """Umami v2 geeft {'value': n, 'prev': m}, v3 geeft gewoon n."""
    if isinstance(v, dict):
        return int(v.get("value") or 0)
    return int(v or 0)


def fetch_umami(cfg: dict) -> dict:
    basis = cfg["url"].rstrip("/") + f"/api/websites/{cfg['website_id']}"
    nu = dt.datetime.now(TZ)
    middernacht = nu.replace(hour=0, minute=0, second=0, microsecond=0)
    params = {"startAt": int(middernacht.timestamp() * 1000), "endAt": int(nu.timestamp() * 1000)}
    # zelf gehoste Umami-versies verschillen in hoe een API-sleutel mee moet; probeer beide
    vormen = [cfg.get("vorm", 0), 1 - cfg.get("vorm", 0)] if cfg.get("api_key") else [0]
    for vorm in vormen:
        kop = _umami_headers(cfg, vorm)
        r = requests.get(basis + "/stats", params=params, headers=kop, timeout=15)
        if r.status_code != 401:
            cfg["vorm"] = vorm
            break
    r.raise_for_status()
    s = r.json()
    actief = None
    try:
        a = requests.get(basis + "/active", headers=kop, timeout=15)
        a.raise_for_status()
        j = a.json()
        actief = _waarde(j.get("visitors", j.get("x")) if isinstance(j, dict) else j)
    except (requests.RequestException, ValueError, TypeError):
        pass
    return {"visitors": _waarde(s.get("visitors")), "pageviews": _waarde(s.get("pageviews")), "active": actief}


# ---------------------------------------------------------------- Meta (Facebook + Instagram)

def fetch_meta(cfg: dict) -> dict:
    """Volgers van de Facebook-pagina en het gekoppelde Instagram-account (één pagina-token)."""
    basis = f"https://graph.facebook.com/{cfg['version']}"
    res = {"facebook": None, "instagram": None, "errors": []}

    def get(pad, velden):
        try:
            r = requests.get(f"{basis}/{pad}", params={"fields": velden, "access_token": cfg["token"]},
                             headers=UA, timeout=20)
            j = r.json()
        except (requests.RequestException, ValueError) as e:
            # requests zet de volledige URL (met token) in de foutmelding: nooit doorgeven
            raise RuntimeError(f"verbinding met Meta mislukt ({type(e).__name__})") from None
        if "error" in j:
            fout = j["error"]
            if fout.get("code") == 190:
                raise RuntimeError("pagina-token verlopen of ongeldig: maak een nieuw token aan "
                                   "(zie README, Meta) en zet het in META_PAGE_TOKEN")
            # nooit de token loggen: alleen type en bericht
            raise RuntimeError(f"{fout.get('type')}: {fout.get('message')}")
        return j

    try:
        p = get(cfg["page_id"], "followers_count,fan_count,instagram_business_account")
        res["facebook"] = int(p.get("followers_count") or p.get("fan_count") or 0)
        ig_id = cfg.get("ig_id") or (p.get("instagram_business_account") or {}).get("id")
    except (requests.RequestException, RuntimeError, ValueError) as e:
        res["errors"].append(f"facebook: {e}")
        ig_id = cfg.get("ig_id")
    if ig_id:
        try:
            res["instagram"] = int(get(ig_id, "followers_count").get("followers_count") or 0)
        except (requests.RequestException, RuntimeError, ValueError) as e:
            res["errors"].append(f"instagram: {e}")
    if res["facebook"] is None and res["instagram"] is None:
        raise RuntimeError("; ".join(res["errors"]) or "geen gegevens")
    return res


# ---------------------------------------------------------------- Google-reviews (Places API New)

def _google_place_id(cfg: dict) -> str:
    """Place ID uit de instellingen, of eenmalig opzoeken met een zoekterm en bewaren."""
    import json
    import os

    if cfg.get("place_id"):
        return cfg["place_id"]
    pad = os.path.join(cfg["data_dir"], "google_place.json")
    try:
        with open(pad) as f:
            opgeslagen = json.load(f)
        if opgeslagen.get("query") == cfg["query"]:
            return opgeslagen["id"]
    except (OSError, ValueError, KeyError):
        pass
    if not cfg.get("query"):
        raise RuntimeError("GOOGLE_PLACE_ID of GOOGLE_PLACE_QUERY ontbreekt")
    # alleen het ID opvragen houdt deze zoekactie in de goedkoopste categorie
    r = requests.post(
        "https://places.googleapis.com/v1/places:searchText",
        json={"textQuery": cfg["query"], "languageCode": "nl"},
        headers={"X-Goog-Api-Key": cfg["api_key"], "X-Goog-FieldMask": "places.id", **UA},
        timeout=20,
    )
    r.raise_for_status()
    plaatsen = r.json().get("places") or []
    if not plaatsen:
        raise RuntimeError(f"geen Google-plaats gevonden voor '{cfg['query']}'")
    pid = plaatsen[0]["id"]
    with open(pad, "w") as f:
        json.dump({"query": cfg["query"], "id": pid}, f)
    return pid


def fetch_google(cfg: dict) -> dict:
    pid = _google_place_id(cfg)
    r = requests.get(
        f"https://places.googleapis.com/v1/places/{pid}",
        headers={"X-Goog-Api-Key": cfg["api_key"], "X-Goog-FieldMask": "displayName,rating,userRatingCount", **UA},
        timeout=20,
    )
    if r.status_code >= 400:
        try:
            fout = r.json().get("error", {}).get("message", "")
        except ValueError:
            fout = r.text[:120]
        raise RuntimeError(f"{r.status_code}: {fout}")
    j = r.json()
    return {
        "name": (j.get("displayName") or {}).get("text"),
        "rating": float(j.get("rating") or 0),
        "count": int(j.get("userRatingCount") or 0),
    }
