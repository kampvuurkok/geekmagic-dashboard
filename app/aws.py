"""Amazon (AWS): problemen met SES en meldingen van AWS Health.

Twee bronnen, allebei alleen lezen:
- SES (rechtstreeks gevraagd): staat verzenden aan, is het account gezond, en zijn de
  domeinen, DKIM en het MAIL FROM-domein (bv. nieuwsbrief.kampvuurkok.nl) in orde.
- AWS Health (optioneel): een EventBridge-regel stuurt alle Health-meldingen naar een
  SQS-wachtrij; de container leest die wachtrij leeg en onthoudt de open meldingen.

Geen boto3 nodig: de aanvragen worden zelf ondertekend (AWS Signature v4).
"""
import datetime as dt
import hashlib
import hmac
import json
import logging
import os
import time
import urllib.parse

import requests

log = logging.getLogger("aws")

MAILFROM_NL = {"PENDING": "wacht op DNS", "FAILED": "mislukt", "TEMPORARY_FAILURE": "MX ontbreekt"}
STATUS_NL = {"PENDING": "wacht op DNS", "FAILED": "mislukt", "TEMPORARY_FAILURE": "tijdelijk mislukt",
             "NOT_STARTED": "niet gestart"}


# ---------------------------------------------------------------- ondertekenen (SigV4)

def _hmac(sleutel, tekst):
    return hmac.new(sleutel, tekst.encode(), hashlib.sha256).digest()


def _aanvraag(cfg, methode, regio, dienst, host, pad="/", body=b"", headers=None, query=None):
    """Ondertekende aanvraag naar AWS. Geeft het JSON-antwoord terug."""
    nu = dt.datetime.now(dt.timezone.utc)
    amzdate, datum = nu.strftime("%Y%m%dT%H%M%SZ"), nu.strftime("%Y%m%d")
    query = query or {}
    qs = "&".join(f"{urllib.parse.quote(k, safe='-_.~')}={urllib.parse.quote(str(v), safe='-_.~')}"
                  for k, v in sorted(query.items()))
    h = {"host": host, "x-amz-date": amzdate, **{k.lower(): v for k, v in (headers or {}).items()}}
    if cfg.get("session_token"):
        h["x-amz-security-token"] = cfg["session_token"]
    getekend = ";".join(sorted(h))
    canoniek = "\n".join([
        methode, urllib.parse.quote(pad, safe="/-_.~"), qs,
        "".join(f"{k}:{h[k].strip()}\n" for k in sorted(h)), getekend,
        hashlib.sha256(body).hexdigest(),
    ])
    scope = f"{datum}/{regio}/{dienst}/aws4_request"
    te_tekenen = "\n".join(["AWS4-HMAC-SHA256", amzdate, scope, hashlib.sha256(canoniek.encode()).hexdigest()])
    k = _hmac(("AWS4" + cfg["secret_key"]).encode(), datum)
    for deel in (regio, dienst, "aws4_request"):
        k = _hmac(k, deel)
    handtekening = hmac.new(k, te_tekenen.encode(), hashlib.sha256).hexdigest()
    h["authorization"] = (f"AWS4-HMAC-SHA256 Credential={cfg['access_key']}/{scope}, "
                          f"SignedHeaders={getekend}, Signature={handtekening}")
    del h["host"]
    url = f"https://{host}{pad}" + (f"?{qs}" if qs else "")
    try:
        r = requests.request(methode, url, data=body or None, headers=h, timeout=20)
    except requests.RequestException as e:
        raise RuntimeError(f"verbinding met AWS ({dienst}) mislukt ({type(e).__name__})") from None
    try:
        j = r.json() if r.content else {}
    except ValueError:
        j = {}
    if r.status_code >= 400:
        bericht = j.get("message") or j.get("Message") or r.text[:150]
        if r.status_code in (401, 403):
            bericht = f"geen toegang ({bericht}) – controleer AWS_ACCESS_KEY_ID/SECRET en de rechten"
        raise RuntimeError(f"{dienst} {r.status_code}: {bericht}")
    return j


# ---------------------------------------------------------------- SES

def _ses(cfg, regio, pad):
    return _aanvraag(cfg, "GET", regio, "ses", f"email.{regio}.amazonaws.com", pad)


def check_ses(cfg, regio):
    """Lijst problemen [(tekst, ernstig)] en details voor de statuspagina."""
    problemen, details = [], {"regio": regio, "identiteiten": {}}
    acc = _ses(cfg, regio, "/v2/email/account")
    details["verzenden"] = acc.get("SendingEnabled")
    details["account"] = acc.get("EnforcementStatus")
    details["productie"] = acc.get("ProductionAccessEnabled")
    if acc.get("SendingEnabled") is False:
        problemen.append(("SES: verzenden staat uit", True))
    if acc.get("EnforcementStatus") and acc["EnforcementStatus"] != "HEALTHY":
        problemen.append((f"SES-account: {acc['EnforcementStatus']}", True))

    ids, token = [], None
    while True:
        j = _aanvraag(cfg, "GET", regio, "ses", f"email.{regio}.amazonaws.com", "/v2/email/identities",
                      query={"NextToken": token} if token else None)
        ids += [i["IdentityName"] for i in j.get("EmailIdentities", [])
                if i.get("IdentityType") == "DOMAIN" or cfg.get("emails")]
        token = j.get("NextToken")
        if not token:
            break

    for naam in ids:
        if naam in cfg.get("exclude", ()):
            continue
        i = _ses(cfg, regio, f"/v2/email/identities/{urllib.parse.quote(naam, safe='')}")
        mf = i.get("MailFromAttributes") or {}
        dkim = i.get("DkimAttributes") or {}
        d = {"verificatie": i.get("VerificationStatus"),
             "dkim": dkim.get("Status") if dkim.get("SigningEnabled") else "uit",
             "mail_from": mf.get("MailFromDomain"), "mail_from_status": mf.get("MailFromDomainStatus")}
        details["identiteiten"][naam] = d
        st = i.get("VerificationStatus")
        if st and st != "SUCCESS":
            problemen.append((f"{naam}: {STATUS_NL.get(st, st)}", st != "PENDING"))
        if dkim.get("SigningEnabled") and dkim.get("Status") not in (None, "SUCCESS"):
            problemen.append((f"DKIM {naam}: {STATUS_NL.get(dkim['Status'], dkim['Status'])}",
                              dkim["Status"] != "PENDING"))
        ms = mf.get("MailFromDomainStatus")
        if mf.get("MailFromDomain") and ms and ms != "SUCCESS":
            # kort, want het schermpje is smal: 'nieuwsbrief: MX ontbreekt'
            sub = mf["MailFromDomain"].removesuffix("." + naam) if naam in mf["MailFromDomain"] else mf["MailFromDomain"]
            problemen.append((f"{sub}: {MAILFROM_NL.get(ms, ms)}", ms != "PENDING"))
    return problemen, details


# ---------------------------------------------------------------- AWS Health via SQS

def _sqs(cfg, regio, actie, data):
    return _aanvraag(cfg, "POST", regio, "sqs", f"sqs.{regio}.amazonaws.com", "/",
                     body=json.dumps(data).encode(),
                     headers={"content-type": "application/x-amz-json-1.0",
                              "x-amz-target": f"AmazonSQS.{actie}"})


def _health_bestand(cfg):
    return os.path.join(cfg["data_dir"], "aws_health.json")


def _health_laden(cfg):
    try:
        with open(_health_bestand(cfg)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _health_bewaren(cfg, meldingen):
    pad = _health_bestand(cfg)
    with open(pad + ".tmp", "w") as f:
        json.dump(meldingen, f, ensure_ascii=False, indent=1)
    os.replace(pad + ".tmp", pad)


def lees_health(cfg):
    """Haalt nieuwe Health-meldingen uit de wachtrij en geeft de open meldingen terug."""
    url = cfg["queue_url"]
    regio = urllib.parse.urlparse(url).hostname.split(".")[1]
    meldingen = _health_laden(cfg)
    for _ in range(10):  # max. 100 berichten per keer
        j = _sqs(cfg, regio, "ReceiveMessage", {"QueueUrl": url, "MaxNumberOfMessages": 10,
                                                 "WaitTimeSeconds": 0, "VisibilityTimeout": 60})
        berichten = j.get("Messages") or []
        if not berichten:
            break
        for m in berichten:
            try:
                ev = json.loads(m["Body"])
                det = ev.get("detail") or {}
                arn = det.get("eventArn") or m["MessageId"]
                if det.get("statusCode") == "closed":
                    meldingen.pop(arn, None)
                else:
                    oms = next((x.get("latestDescription") for x in det.get("eventDescription") or []
                                if x.get("language", "en_US").startswith("en")), "")
                    meldingen[arn] = {
                        "dienst": det.get("service") or ev.get("source", "AWS"),
                        "code": det.get("eventTypeCode", ""),
                        "soort": det.get("eventTypeCategory", ""),
                        "status": det.get("statusCode", ""),
                        "regio": ev.get("region", ""),
                        "begin": det.get("startTime") or ev.get("time"),
                        "ontvangen": time.time(),
                        "omschrijving": (oms or "")[:600],
                    }
                    log.info("AWS Health: %s %s", det.get("service"), det.get("eventTypeCode"))
            except (ValueError, KeyError, TypeError) as e:
                log.warning("AWS Health: onleesbaar bericht overgeslagen (%s)", e)
            _sqs(cfg, regio, "DeleteMessage", {"QueueUrl": url, "ReceiptHandle": m["ReceiptHandle"]})
    # meldingen die nooit 'closed' worden (zoals accountmeldingen) na een tijd vergeten
    grens = time.time() - cfg["health_days"] * 86400
    meldingen = {k: v for k, v in meldingen.items() if v.get("ontvangen", 0) >= grens}
    _health_bewaren(cfg, meldingen)
    return meldingen


def _leesbaar(code: str) -> str:
    """'AWS_SES_CMF_SUCCESS_TO_TEMPORARY_FAILURE' -> 'cmf success to temporary failure'."""
    delen = code.split("_")
    if len(delen) > 2 and delen[0] == "AWS":
        delen = delen[2:]
    onderwerp = {"CMF": "MAIL FROM", "DKIM": "DKIM"}.get(delen[0])
    if onderwerp and "TO" in delen:
        # bv. CMF_SUCCESS_TO_TEMPORARY_FAILURE -> 'MAIL FROM: temporary failure'
        return f"{onderwerp}: " + " ".join(delen[delen.index("TO") + 1:]).lower()
    return " ".join(delen).lower()


# ---------------------------------------------------------------- samen

def fetch_aws(cfg: dict) -> dict:
    res = {"problems": [], "total": 0, "urgent": False, "ses": {}, "health": {}, "errors": []}
    for regio in cfg["regions"]:
        try:
            p, d = check_ses(cfg, regio)
            res["problems"] += p
            res["ses"][regio] = d
        except RuntimeError as e:
            res["errors"].append(f"SES {regio}: {e}")
    if cfg.get("queue_url"):
        try:
            res["health"] = lees_health(cfg)
        except RuntimeError as e:
            res["errors"].append(f"Health: {e}")
            res["health"] = _health_laden(cfg)
        ses_ok = {r for r in cfg["regions"] if r in res["ses"]}
        for m in res["health"].values():
            # SES-meldingen over domeinen/DKIM/MAIL FROM controleert de SES-check zelf al, en die
            # verdwijnt meteen als het opgelost is; de Health-melding zou nog dagen blijven staan
            if (m.get("dienst") == "SES" and m.get("regio") in ses_ok
                    and any(x in m.get("code", "") for x in ("CMF", "DKIM", "VERIFICATION", "IDENTITY"))):
                continue
            res["problems"].append((f"{m['dienst']}: {_leesbaar(m['code'])}", m.get("soort") == "issue"))
    if len(res["errors"]) == len(cfg["regions"]) + (1 if cfg.get("queue_url") else 0):
        raise RuntimeError("; ".join(res["errors"]))
    # dubbele regels (Health en SES melden vaak hetzelfde) maar één keer
    gezien, uniek = set(), []
    for tekst, ernstig in res["problems"]:
        if tekst not in gezien:
            gezien.add(tekst)
            uniek.append((tekst, ernstig))
    res["problems"] = uniek
    res["total"] = len(uniek)
    res["urgent"] = any(e for _, e in uniek)
    return res
