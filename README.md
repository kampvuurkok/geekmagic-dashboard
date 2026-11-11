# GeekMagic-dashboard

Dashboard voor een **GeekMagic SmallTV-PRO** (standaardfirmware). Een kleine container op Unraid maakt pagina's van 240×240 pixels en zet ze om de beurt op het schermpje.

## Pagina's

- **Weer** – temperatuur, min/max, wind en regen de komende 2 uur (Open-Meteo + Buienradar, geen sleutel nodig)
- **Instagram** en **Facebook** – volgers, met de groei van vandaag (Meta Graph API, één pagina-token)
- **Google** – gemiddelde score, aantal reviews en hoeveel er vandaag bij zijn gekomen (Places API New)
- **Nieuwsbrief** – aantal bevestigde leden van een phpList-lijst, met de groei van vandaag
- **Website** – bezoekers en weergaven van vandaag, en wie er nu online is (Umami)
- **Updatetegels** – alleen als er iets klaarstaat: één tegel **Unraid** en één tegel per **WordPress-site** (met de sitenaam als titel), met per regel wat er bijgewerkt moet worden. Bronnen: dockers (Unraid API), compose-containers (Compose Manager; vastgepinde tellen niet mee), plugins, Unraid zelf en WordPress-sites (kern, plugins, thema's via SSH + WP-CLI)

- **Recepten** – alleen als bezoekers labels hebben voorgesteld die boven de drempel uitkomen (plugin *Kampvuurkok receptsuggesties*), met per regel recept en voorstel; allergenen in rood

Op elke pagina:
- een **stipje** als er updates klaarstaan (rood bij een update van Unraid of de WordPress-kern)
- een **druppeltje** als er binnen een uur regen komt
- de **tijd van de laatste verversing** (rood als die te oud is)

## Installeren op Unraid (Compose-pagina)

1. **Compose** → **Add New Stack**, naam `geekmagic-dashboard`, Compose Source: *Project folder*.
2. **Edit Stack → Compose File**: plak de inhoud van [`docker-compose.yml`](docker-compose.yml).
3. **Edit Stack → ENV File**: plak [`.env.example`](.env.example) en vul je eigen waarden in.
4. **Compose Up**.

Het image wordt automatisch gebouwd door GitHub bij elke wijziging en staat op `ghcr.io/kampvuurkok/geekmagic-dashboard:latest`.

## Bijwerken

Klik op de Compose-pagina bij de stack op **Update** (of *Pull* + *Compose Up*). Er wordt niets op de server gebouwd.

## Wat de container mag lezen

Alle mappen van de host zijn alleen-lezen; er staan geen poorten open.

| Map op Unraid | Waarvoor |
|---|---|
| `/boot/config/plugins` | geïnstalleerde pluginversies en de updatestatus van Compose Manager |
| `/tmp/plugins` | nieuwste pluginversies (Unraids eigen updatecheck) |
| `/tmp/unraidcheck` | updatecheck voor Unraid zelf |
| `/mnt/user/appdata/geekmagic-dashboard/data` | eigen gegevens (lezen en schrijven): dagstand, preview-plaatjes, SSH-sleutel |

De container draait als root, maar zonder extra rechten (`cap_drop: ALL`, `no-new-privileges`). Dat is nodig omdat `/boot` op Unraid alleen voor root leesbaar is.

Het dashboard telt wat Unraid en Compose Manager zelf gevonden hebben. Staat hun automatische updatecheck uit, dan ziet het dashboard ook niets nieuws.

## Voorbereiding per onderdeel

- **phpList**: maak een MySQL-gebruiker die alleen mag lezen:
  `CREATE USER 'geekmagic'@'%' IDENTIFIED BY '...'; GRANT SELECT ON phplist.* TO 'geekmagic'@'%';`
- **Meta**: maak een app op developers.facebook.com, haal in de Graph API Explorer een gebruikerstoken op met `pages_show_list`, `pages_read_engagement`, `instagram_basic`, verleng hem in de Access Token Debugger, en vraag met die token `me/accounts` op: de `access_token` van je pagina verloopt niet.
- **Google**: zet in een Google Cloud-project de *Places API (New)* aan, maak een API-sleutel die alleen die API mag gebruiken en stel een dagquotum in (bv. 40 aanvragen per dag) als harde grens. Score en aantal vallen in de Enterprise-categorie met 1.000 gratis aanvragen per maand.
- **Umami**: website-ID staat in de adresbalk bij de website (`/websites/<id>`); maak een API-sleutel onder *Settings → API keys*, of gebruik een gebruiker met alleen leesrechten.
- **Unraid API**: *Settings → Management Access → API Keys*, rol **Viewer**.
- **WordPress**: maak een SSH-sleutel in de datamap en zet hem bij je hosting:
  `ssh-keygen -t ed25519 -N "" -f /mnt/user/appdata/geekmagic-dashboard/data/ssh/id_ed25519`
  `ssh-copy-id -i /mnt/user/appdata/geekmagic-dashboard/data/ssh/id_ed25519.pub gebruiker@host`

## Statuspagina

Op `http://<unraid-ip>:8099` staat een pagina met de details achter het schermpje: de laatste waarde per bron, alle updates met namen (per WordPress-site, per container, per plugin) en eventuele fouten. Ververst elke minuut. `/json` geeft hetzelfde als JSON. Alleen bedoeld voor je eigen netwerk.

## WordPress-sites

Met `WP_PATHS=auto` zoekt het dashboard bij elke check zelf alle WordPress-installaties in de SSH-thuismap (tot vier mappen diep; back-ups en `wp-content` worden overgeslagen). Nieuwe sites doen vanzelf mee, verwijderde verdwijnen vanzelf. Uitsluiten met `WP_EXCLUDE=site.nl/staging`.

## Controleren

```
docker logs geekmagic-dashboard 2>&1 | grep bijgewerkt | tail -5
```
Een lege lijst bij `errors` betekent dat alles leesbaar is. Met `DRY_RUN=1` gaat er niets naar het scherm en komen de plaatjes in `data/preview`.

## Techniek

- Python 3.12, Pillow, requests, PyMySQL; lettertype Inter (SIL Open Font License, zie `fonts/`).
- Het scherm wordt aangestuurd via zijn eigen webinterface (`/doUpload`, `/set?img=`, `/delete`). Pagina's die niet nodig zijn worden van het scherm gehaald, omdat de firmware anders zelf door alle plaatjes bladert.
