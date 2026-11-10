"""Tekent de pagina's van 240x240 px (donker thema, instelbare accentkleur).

Alles wordt op dubbele grootte (480x480) getekend en daarna verkleind,
zodat randen en lettertypes zacht (anti-aliased) worden.
"""
import io
import math
import os

from PIL import Image, ImageDraw, ImageFont

S = 2  # schaalfactor
W = H = 240 * S

FONT_DIR = os.environ.get("FONT_DIR", os.path.join(os.path.dirname(__file__), "..", "fonts"))

BG = (27, 23, 20)
CARD = (40, 34, 29)
def _hex(waarde, standaard):
    try:
        w = waarde.strip().lstrip("#")
        return tuple(int(w[i:i + 2], 16) for i in (0, 2, 4))
    except (AttributeError, ValueError, IndexError):
        return standaard


# Accentkleur (titels, iconen, stipje); in te stellen met ACCENT_COLOR=FFD71B
ORANJE = _hex(os.environ.get("ACCENT_COLOR", "FFD71B"), (255, 215, 27))
GEEL = (255, 196, 61)
TEKST = (245, 237, 228)
GRIJS = (168, 154, 140)
GROEN = (124, 197, 118)
ROOD = (229, 83, 61)
BLAUW = (96, 170, 235)
WOLK = (205, 200, 196)
WOLK_DONKER = (140, 134, 130)

_fonts = {}


def font(gewicht: str, px: int) -> ImageFont.FreeTypeFont:
    key = (gewicht, px)
    if key not in _fonts:
        _fonts[key] = ImageFont.truetype(os.path.join(FONT_DIR, f"Inter-{gewicht}.otf"), px * S)
    return _fonts[key]


def fit_font(draw, tekst, gewicht, max_px, max_breedte):
    px = max_px
    while px > 10:
        f = font(gewicht, px)
        if draw.textlength(tekst, font=f) <= max_breedte * S:
            return f
        px -= 2
    return font(gewicht, 10)


def tekst_mid(draw, y, tekst, f, kleur):
    """Tekst horizontaal gecentreerd; y in 240-coördinaten (bovenkant)."""
    draw.text((W / 2, y * S), tekst, font=f, fill=kleur, anchor="mt")


def nl_getal(n: int) -> str:
    return f"{n:,}".replace(",", ".")


# ---------- kleine icoontjes (coördinaten in 240-schaal) ----------

def druppel(draw, cx, cy, r, kleur=BLAUW):
    cx, cy, r = cx * S, cy * S, r * S
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=kleur)
    draw.polygon([(cx - r * 0.92, cy - r * 0.35), (cx + r * 0.92, cy - r * 0.35), (cx, cy - r * 2.3)], fill=kleur)


def stip(draw, cx, cy, r, kleur=ORANJE):
    cx, cy, r = cx * S, cy * S, r * S
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=kleur)


def zon(draw, cx, cy, r):
    cx, cy, r = cx * S, cy * S, r * S
    for i in range(8):
        a = i * math.pi / 4
        x1, y1 = cx + math.cos(a) * r * 1.35, cy + math.sin(a) * r * 1.35
        x2, y2 = cx + math.cos(a) * r * 1.8, cy + math.sin(a) * r * 1.8
        draw.line((x1, y1, x2, y2), fill=GEEL, width=int(r * 0.22))
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=GEEL)


def maan(draw, cx, cy, r):
    cx, cy, r = cx * S, cy * S, r * S
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(235, 228, 200))
    o = r * 0.55
    draw.ellipse((cx - r + o, cy - r - o * 0.4, cx + r + o, cy + r - o * 0.4), fill=BG)


def wolk(draw, cx, cy, w, kleur=WOLK):
    """Wolk met middelpunt (cx, cy) en breedte w."""
    cx, cy, w = cx * S, cy * S, w * S
    h = w * 0.5
    basis_y = cy + h * 0.35
    draw.rounded_rectangle((cx - w / 2, basis_y - h * 0.45, cx + w / 2, basis_y + h * 0.15), radius=h * 0.3, fill=kleur)
    r1, r2 = w * 0.22, w * 0.3
    draw.ellipse((cx - w * 0.38 - r1 * 0, basis_y - h * 0.45 - r1 * 1.1, cx - w * 0.38 + r1 * 2, basis_y - h * 0.45 + r1 * 0.9), fill=kleur)
    draw.ellipse((cx - r2 * 0.6, basis_y - h * 0.45 - r2 * 1.35, cx + r2 * 1.4, basis_y - h * 0.45 + r2 * 0.65), fill=kleur)


def weericoon(draw, soort, cx, cy, maat):
    """Tekent een weericoon in een vak van 'maat' breed rond (cx, cy)."""
    m = maat
    if soort == "clear":
        zon(draw, cx, cy, m * 0.26)
    elif soort == "clear_night":
        maan(draw, cx, cy, m * 0.32)
    elif soort in ("partly", "partly_night"):
        if soort == "partly":
            zon(draw, cx - m * 0.14, cy - m * 0.14, m * 0.2)
        else:
            maan(draw, cx - m * 0.14, cy - m * 0.16, m * 0.22)
        wolk(draw, cx + m * 0.06, cy + m * 0.08, m * 0.7)
    elif soort == "cloud":
        wolk(draw, cx + m * 0.12, cy - m * 0.12, m * 0.55, WOLK_DONKER)
        wolk(draw, cx - m * 0.04, cy + m * 0.05, m * 0.75)
    elif soort == "fog":
        wolk(draw, cx, cy - m * 0.12, m * 0.7)
        for i in range(3):
            y = (cy + m * 0.18 + i * m * 0.1) * S
            draw.line(((cx - m * 0.35) * S, y, (cx + m * 0.35) * S, y), fill=GRIJS, width=int(m * 0.045 * S))
    elif soort in ("drizzle", "rain", "thunder", "snow"):
        wolk(draw, cx, cy - m * 0.14, m * 0.75)
        if soort == "snow":
            for dx, dy in ((-0.2, 0.25), (0.0, 0.33), (0.2, 0.25)):
                stip(draw, cx + dx * m, cy + dy * m, m * 0.045, TEKST)
        elif soort == "thunder":
            x, y = cx * S, (cy + m * 0.1) * S
            u = m * S
            draw.polygon([(x + u * 0.05, y), (x - u * 0.1, y + u * 0.2), (x + u * 0.0, y + u * 0.2),
                          (x - u * 0.08, y + u * 0.38), (x + u * 0.14, y + u * 0.14), (x + u * 0.03, y + u * 0.14),
                          (x + u * 0.12, y)], fill=GEEL)
        else:
            n = 2 if soort == "drizzle" else 3
            for i in range(n):
                dx = (i - (n - 1) / 2) * m * 0.2
                druppel(draw, cx + dx, cy + m * 0.32, m * (0.045 if soort == "drizzle" else 0.06))
    else:
        wolk(draw, cx, cy, m * 0.75)


def icoon_mensen(draw, cx, cy, m, kleur=ORANJE):
    """Twee hoofd-en-schouder-figuurtjes: 'volgers/leden'."""
    for dx, schaal, k in ((m * 0.18, 0.8, tuple(int(c * 0.6) for c in kleur)), (-m * 0.08, 1.0, kleur)):
        x, r = (cx + dx) * S, m * 0.16 * schaal * S
        y = (cy - m * 0.12) * S
        draw.ellipse((x - r, y - r, x + r, y + r), fill=k)
        bw, bh = m * 0.34 * schaal * S, m * 0.3 * schaal * S
        draw.pieslice((x - bw, y + r * 1.2, x + bw, y + r * 1.2 + bh * 2), 180, 360, fill=k)


def icoon_envelop(draw, cx, cy, m, kleur=ORANJE):
    x0, y0, x1, y1 = (cx - m * 0.4) * S, (cy - m * 0.26) * S, (cx + m * 0.4) * S, (cy + m * 0.26) * S
    w = max(2, int(m * 0.06 * S))
    draw.rounded_rectangle((x0, y0, x1, y1), radius=m * 0.05 * S, outline=kleur, width=w)
    draw.line((x0 + w, y0 + w, cx * S, cy * S + w, x1 - w, y0 + w), fill=kleur, width=w, joint="curve")


def icoon_play(draw, cx, cy, m, kleur=ORANJE):
    x0, y0, x1, y1 = (cx - m * 0.42) * S, (cy - m * 0.3) * S, (cx + m * 0.42) * S, (cy + m * 0.3) * S
    draw.rounded_rectangle((x0, y0, x1, y1), radius=m * 0.12 * S, fill=kleur)
    t = m * 0.13 * S
    draw.polygon([(cx * S - t * 0.8, cy * S - t), (cx * S - t * 0.8, cy * S + t), (cx * S + t * 1.1, cy * S)], fill=BG)


def icoon_wereld(draw, cx, cy, m, kleur=ORANJE):
    r = m * 0.36 * S
    x, y = cx * S, cy * S
    w = max(2, int(m * 0.05 * S))
    draw.ellipse((x - r, y - r, x + r, y + r), outline=kleur, width=w)
    draw.ellipse((x - r * 0.45, y - r, x + r * 0.45, y + r), outline=kleur, width=w)
    draw.line((x - r, y, x + r, y), fill=kleur, width=w)


def icoon_foto(draw, cx, cy, m, kleur=ORANJE):
    """Fotolijstje met bergje en zonnetje."""
    w = max(2, int(m * 0.06 * S))
    x0, y0, x1, y1 = (cx - m * 0.42) * S, (cy - m * 0.32) * S, (cx + m * 0.42) * S, (cy + m * 0.32) * S
    draw.rounded_rectangle((x0, y0, x1, y1), radius=m * 0.08 * S, outline=kleur, width=w)
    draw.polygon([(x0 + w * 2, y1 - w * 2), ((cx - m * 0.12) * S, (cy - m * 0.04) * S),
                  ((cx + m * 0.04) * S, (cy + m * 0.12) * S), ((cx + m * 0.16) * S, (cy + m * 0.02) * S),
                  (x1 - w * 2, y1 - w * 2)], fill=kleur)
    r = m * 0.07 * S
    zx, zy = (cx + m * 0.2) * S, (cy - m * 0.14) * S
    draw.ellipse((zx - r, zy - r, zx + r, zy + r), fill=kleur)


def icoon_duim(draw, cx, cy, m, kleur=ORANJE):
    """Duim omhoog."""
    u = m * S
    x, y = cx * S, cy * S
    # mouw
    draw.rounded_rectangle((x - u * 0.42, y - u * 0.05, x - u * 0.24, y + u * 0.36), radius=u * 0.03, fill=kleur)
    # hand
    draw.rounded_rectangle((x - u * 0.2, y - u * 0.08, x + u * 0.34, y + u * 0.36), radius=u * 0.09, fill=kleur)
    # duim
    draw.polygon([(x - u * 0.2, y - u * 0.04), (x - u * 0.04, y - u * 0.36), (x + u * 0.06, y - u * 0.38),
                  (x + u * 0.1, y - u * 0.3), (x + u * 0.04, y - u * 0.06)], fill=kleur)
    draw.ellipse((x - u * 0.02, y - u * 0.43, x + u * 0.12, y - u * 0.29), fill=kleur)
    # vingerlijnen
    for i in range(1, 4):
        yy = y - u * 0.08 + i * u * 0.11
        draw.line((x + u * 0.12, yy, x + u * 0.34, yy), fill=BG, width=max(2, int(u * 0.025)))


ICONEN = {"foto": icoon_foto, "duim": icoon_duim, "mensen": icoon_mensen, "envelop": icoon_envelop, "play": icoon_play, "wereld": icoon_wereld}


# ---------- pagina-onderdelen ----------

def kop(draw, titel, status):
    """Titelbalk bovenaan met statusicoontjes rechts."""
    draw.text((14 * S, 12 * S), titel.upper(), font=font("SemiBold", 13), fill=ORANJE, anchor="lt")
    x = 226
    if status.get("updates"):
        stip(draw, x - 5, 19, 5, ROOD if status.get("updates_urgent") else ORANJE)
        x -= 18
    if status.get("drop"):
        druppel(draw, x - 5, 21, 4.5)


def voet(draw, status):
    tijd = status.get("updated")
    if not tijd:
        tekst, kleur = "nog geen gegevens", GRIJS
    elif status.get("stale"):
        tekst, kleur = f"verouderd · {tijd}", ROOD
    else:
        tekst, kleur = f"bijgewerkt {tijd}", GRIJS
    tekst_mid(draw, 218, tekst, font("Medium", 11), kleur)


def nieuw_canvas():
    img = Image.new("RGB", (W, H), BG)
    return img, ImageDraw.Draw(img)


def naar_jpg(img) -> bytes:
    klein = img.resize((240, 240), Image.LANCZOS)
    buf = io.BytesIO()
    # baseline (niet progressive): de decoder in het schermpje kan geen progressive JPG
    klein.save(buf, "JPEG", quality=90, progressive=False, optimize=False, subsampling=0)
    return buf.getvalue()


# ---------- pagina's ----------

def pagina_getal(titel, icoon, waarde, delta, onderschrift, status, extra=None) -> bytes:
    img, d = nieuw_canvas()
    kop(d, titel, status)
    ICONEN[icoon](d, 120, 66, 56)
    tekst = nl_getal(waarde) if isinstance(waarde, int) else "–"
    tekst_mid(d, 102, tekst, fit_font(d, tekst, "Bold", 62, 212), TEKST)
    tekst_mid(d, 166, onderschrift, font("Medium", 13), GRIJS)
    if extra:
        tekst_mid(d, 186, extra, font("Medium", 12), GRIJS)
    elif delta is not None:
        if delta > 0:
            dt, kleur = f"+{nl_getal(delta)} vandaag", GROEN
        elif delta < 0:
            dt, kleur = f"−{nl_getal(-delta)} vandaag", ROOD
        else:
            dt, kleur = "± 0 vandaag", GRIJS
        tekst_mid(d, 186, dt, font("SemiBold", 14), kleur)
    voet(d, status)
    return naar_jpg(img)


def pagina_weer(plaats, w, regen, status) -> bytes:
    img, d = nieuw_canvas()
    kop(d, plaats, status)
    if not w:
        tekst_mid(d, 100, "–", font("Bold", 60), TEKST)
        voet(d, status)
        return naar_jpg(img)
    weericoon(d, w["icon"], 66, 82, 92)
    temp = f"{round(w['temp'])}°"
    d.text((178 * S, 82 * S), temp, font=fit_font(d, temp, "Bold", 54, 110), fill=TEKST, anchor="mm")
    tekst_mid(d, 134, w["text"], fit_font(d, w["text"], "SemiBold", 17, 220), TEKST)
    regel = f"min {round(w['tmin'])}° · max {round(w['tmax'])}° · {w['wind_bft']} Bft {w['wind_dir']}"
    tekst_mid(d, 158, regel, fit_font(d, regel, "Medium", 13, 224), GRIJS)
    if regen:
        kleur = BLAUW if regen["drop"] else GROEN
        tekst_mid(d, 182, regen["line"], font("SemiBold", 14), kleur)
    voet(d, status)
    return naar_jpg(img)


def pagina_updates(u, status) -> bytes:
    """Overzicht van beschikbare updates; Unraid OS in rood."""
    img, d = nieuw_canvas()
    kop(d, "Updates", status)
    if not u:
        tekst_mid(d, 100, "–", font("Bold", 60), TEKST)
        voet(d, status)
        return naar_jpg(img)
    totaal = u.get("total", 0)
    urgent = u.get("os") or (u.get("wp") and u["wp"].get("core"))
    kleur = ROOD if urgent else (ORANJE if totaal else GROEN)
    tekst_mid(d, 36, str(totaal) if totaal else "✓", font("Bold", 52), kleur)
    tekst_mid(d, 96, "updates klaar" if totaal != 1 else "update klaar", font("Medium", 13), GRIJS)
    wp = u.get("wp")
    rijen = [
        ("Dockers", len(u.get("docker", []))),
        ("Compose", len(u.get("compose", []))),
        ("Plugins", len(u.get("plugins", []))),
    ]
    if wp is not None:
        rijen.append(("WordPress", wp["total"]))
    y = 122 if wp is None else 114
    f_l, f_w = font("Medium", 14), font("SemiBold", 14)
    for label, n in rijen:
        d.text((40 * S, y * S), label, font=f_l, fill=GRIJS if n == 0 else TEKST, anchor="lt")
        rood = label == "WordPress" and wp and wp.get("core")
        d.text((200 * S, y * S), str(n), font=f_w, fill=GRIJS if n == 0 else (ROOD if rood else ORANJE), anchor="rt")
        y += 19
    d.text((40 * S, y * S), "Unraid", font=f_l, fill=ROOD if u.get("os") else GRIJS, anchor="lt")
    d.text((200 * S, y * S), u["os"] if u.get("os") else "actueel", font=f_w,
           fill=ROOD if u.get("os") else GRIJS, anchor="rt")
    voet(d, status)
    return naar_jpg(img)
