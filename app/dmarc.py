"""DMARC en SMTP TLS: problemen uit de database van parsedmarc (PostgreSQL).

Alleen lezen. Telt als probleem:
- mail namens je eigen domein die DMARC niet haalt (per domein en afzender),
  vanaf DMARC_MIN_FAIL berichten in de laatste DMARC_DAYS dagen;
- mislukte TLS-verbindingen naar je mailservers (SMTP TLS-rapporten);
- geen nieuwe rapporten meer sinds DMARC_STALE_DAYS dagen (dan is de koppeling stuk).

Rood (ernstig): TLS-fouten, of een domein waarvan een groot deel van de mail DMARC niet haalt
(dan gaat er waarschijnlijk iets mis met je eigen verzending).
"""
import datetime as dt
import logging

log = logging.getLogger("dmarc")

SQL_LAATSTE = "SELECT max(end_date) FROM dmarc_aggregate_report"

# per domein (From-header) en afzender: hoeveel berichten haalden DMARC niet
SQL_FOUTEN = """
SELECT lower(COALESCE(r.header_from, rpt.domain)) AS domein,
       COALESCE(NULLIF(r.source_base_domain, ''), NULLIF(r.source_reverse_dns, ''),
                host(r.source_ip_address)) AS bron,
       SUM(r.message_count)::int AS aantal
FROM dmarc_aggregate_record r
JOIN dmarc_aggregate_report rpt ON rpt.id = r.report_id
WHERE rpt.end_date > now() - make_interval(days => :dagen)
  AND NOT COALESCE(r.dmarc_passed, COALESCE(r.spf_aligned, false) OR COALESCE(r.dkim_aligned, false))
GROUP BY 1, 2
ORDER BY 3 DESC
"""

# totalen per domein, voor het foutpercentage
SQL_TOTALEN = """
SELECT lower(COALESCE(r.header_from, rpt.domain)) AS domein,
       SUM(r.message_count)::int AS totaal,
       SUM(CASE WHEN NOT COALESCE(r.dmarc_passed, COALESCE(r.spf_aligned, false)
                                   OR COALESCE(r.dkim_aligned, false))
                THEN r.message_count ELSE 0 END)::int AS fout
FROM dmarc_aggregate_record r
JOIN dmarc_aggregate_report rpt ON rpt.id = r.report_id
WHERE rpt.end_date > now() - make_interval(days => :dagen)
GROUP BY 1
"""

SQL_TLS = """
SELECT lower(p.policy_domain) AS domein,
       SUM(COALESCE(p.failed_session_count, 0))::int AS mislukt,
       SUM(COALESCE(p.successful_session_count, 0))::int AS gelukt
FROM smtp_tls_policy p
JOIN smtp_tls_report t ON t.id = p.report_id
WHERE t.end_date > now() - make_interval(days => :dagen)
GROUP BY 1
"""


def _verbinden(cfg):
    import pg8000.native  # pas hier, zodat de rest zonder deze bron kan draaien

    return pg8000.native.Connection(
        user=cfg["user"], password=cfg["password"], host=cfg["host"], port=cfg["port"],
        database=cfg["db"], timeout=20,
    )


def _geen_tabel(e) -> bool:
    """Tabellen bestaan pas nadat parsedmarc het eerste rapport heeft opgeslagen."""
    args = getattr(e, "args", None)
    return bool(args) and isinstance(args[0], dict) and args[0].get("C") == "42P01"


def _kort(bron: str) -> str:
    return (bron or "?").removeprefix("mail.")[:28]


def fetch_dmarc(cfg: dict) -> dict:
    import pg8000.exceptions

    res = {"problems": [], "total": 0, "urgent": False, "domains": {}, "tls": {},
           "last_report": None, "failing": []}
    try:
        conn = _verbinden(cfg)
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"database van parsedmarc niet bereikbaar ({type(e).__name__}: {str(e)[:120]})") from None
    try:
        try:
            laatste = conn.run(SQL_LAATSTE)[0][0]
            fouten = conn.run(SQL_FOUTEN, dagen=cfg["days"])
            totalen = conn.run(SQL_TOTALEN, dagen=cfg["days"])
        except pg8000.exceptions.DatabaseError as e:
            if _geen_tabel(e):
                res["note"] = "nog geen rapporten verwerkt"
                return res
            raise
        try:
            tls = conn.run(SQL_TLS, dagen=cfg["days"])
        except pg8000.exceptions.DatabaseError as e:
            if not _geen_tabel(e):
                raise
            tls = []
    finally:
        conn.close()

    negeer = {x.lower() for x in cfg.get("ignore", ())}
    problemen = []

    if laatste is not None:
        res["last_report"] = laatste.astimezone().strftime("%d-%m %H:%M")
        oud = dt.datetime.now(dt.timezone.utc) - laatste
        if oud > dt.timedelta(days=cfg["stale_days"]):
            problemen.append((f"geen rapporten sinds {laatste.astimezone():%d-%m}", False))

    for domein, totaal, fout in totalen:
        res["domains"][domein] = {"totaal": totaal, "fout": fout}

    for domein, bron, aantal in fouten:
        res["failing"].append({"domein": domein, "bron": bron, "aantal": aantal})
        if aantal < cfg["min_fail"] or (bron or "").lower() in negeer or domein in negeer:
            continue
        t = res["domains"].get(domein, {})
        aandeel = (t.get("fout", 0) / t["totaal"]) if t.get("totaal") else 0
        ernstig = aandeel >= cfg["urgent_share"]
        problemen.append((f"{domein}: {aantal}× fout ({_kort(bron)})", ernstig))

    for domein, mislukt, gelukt in tls:
        res["tls"][domein] = {"mislukt": mislukt, "gelukt": gelukt}
        if mislukt and domein not in negeer:
            problemen.append((f"TLS {domein}: {mislukt} mislukt", True))

    res["total"] = len(problemen)
    res["urgent"] = any(e for _, e in problemen)
    res["problems"] = problemen
    return res
