#!/usr/bin/env python3
"""Daily Cyber News : génère docs/index.html.

Utilisation :
    python scripts/build.py            # génère l'édition du jour (sauf si déjà faite)
    python scripts/build.py --force    # régénère même si l'édition du jour existe
    python scripts/build.py --stale    # ajoute un bandeau « mise à jour échouée »

Uniquement la bibliothèque standard de Python : rien à installer.
"""
import argparse
import html
import json
import math
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
import avatar  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
DATA = ROOT / "data"
DOCS = ROOT / "docs"
PARIS = ZoneInfo("Europe/Paris")
UA = "Mozilla/5.0 (compatible; DailyCyberNews/1.0)"

JOURS = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
        "août", "septembre", "octobre", "novembre", "décembre"]
MOIS_COURTS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.",
               "août", "sept.", "oct.", "nov.", "déc."]
CRITICITES = {"légère": "c-l", "moyenne": "c-m", "importante": "c-i"}


def log(msg):
    print(msg, flush=True)


# ----------------------------------------------------------------------------
# Utilitaires
# ----------------------------------------------------------------------------
def charger_json(chemin, defaut=None):
    try:
        return json.loads(Path(chemin).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return defaut


def ecrire_json(chemin, contenu):
    Path(chemin).write_text(json.dumps(contenu, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def http_get(url, timeout=25, tentatives=3):
    derniere = None
    for i in range(tentatives):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            derniere = e
            time.sleep(2 * (i + 1))
    raise derniere


def sans_accents(s):
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def cles_titre(titre):
    """Clés de comparaison d'un titre de notion/réflexion : texte principal + sigles entre parenthèses."""
    t = sans_accents(titre.lower())
    entre_parentheses = re.findall(r"\(([^)]*)\)", t)
    principal = re.sub(r"\([^)]*\)", " ", t)
    cles = {re.sub(r"[^a-z0-9]+", "", principal)}
    cles |= {re.sub(r"[^a-z0-9]+", "", p) for p in entre_parentheses}
    return {c for c in cles if len(c) >= 2}


def est_doublon(titre, deja_vus):
    cles = cles_titre(titre)
    for vu in deja_vus:
        for c2 in cles_titre(vu):
            for c1 in cles:
                if c1 == c2:
                    return vu
                if len(c1) >= 9 and len(c2) >= 9 and (c1 in c2 or c2 in c1):
                    return vu
    return None


def txt(s):
    """Texte sûr pour du HTML, avec apostrophes typographiques."""
    return html.escape(str(s).strip(), quote=False).replace("'", "’")


def nettoyer_html(s):
    s = re.sub(r"(?is)<(script|style).*?</\1>", " ", s or "")
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def arrondi(x):
    return int(math.floor(x + 0.5))


# ----------------------------------------------------------------------------
# Flux RSS
# ----------------------------------------------------------------------------
def parse_date(s):
    s = (s or "").strip()
    if not s:
        return None
    d = None
    try:
        d = parsedate_to_datetime(s)
    except Exception:  # noqa: BLE001
        try:
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:  # noqa: BLE001
            return None
    if d is None:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d


def local(tag):
    return tag.split("}")[-1].lower()


def parse_flux(contenu, source):
    try:
        racine = ET.fromstring(contenu)
    except ET.ParseError:
        propre = re.sub(rb"[\x00-\x08\x0b\x0c\x0e-\x1f]", b"", contenu)
        racine = ET.fromstring(propre)
    articles = []
    for el in racine.iter():
        if local(el.tag) not in ("item", "entry"):
            continue
        champs = {}
        lien = ""
        for enfant in el:
            t = local(enfant.tag)
            if t == "link":
                href = enfant.get("href")
                if href and (enfant.get("rel") in (None, "alternate")):
                    lien = lien or href
                elif enfant.text and not lien:
                    lien = enfant.text.strip()
            elif t not in champs:
                champs[t] = "".join(enfant.itertext())
        titre = nettoyer_html(champs.get("title", ""))
        date = parse_date(champs.get("pubdate") or champs.get("published")
                          or champs.get("updated") or champs.get("date"))
        corps = champs.get("encoded") or champs.get("content") or champs.get("description") \
            or champs.get("summary") or ""
        if titre and lien and date:
            articles.append({"source": source, "titre": titre, "url": lien.strip(),
                             "date": date, "extrait": nettoyer_html(corps)[:700]})
    return articles


def collecter_articles(cfg, historique, maintenant):
    depuis = maintenant - timedelta(hours=cfg["fenetre_heures"])
    deja = {n.get("url") for n in historique.get("news", []) if n.get("url")}
    motif_cyber = re.compile(cfg["mots_cles_cyber"], re.I)
    candidats, bilan = [], []
    for src in cfg["sources"]:
        recus, ok = [], False
        for url in src["urls"]:
            try:
                recus += parse_flux(http_get(url), src["nom"])
                ok = True
                if src.get("mode", "first") == "first":
                    break
            except Exception as e:  # noqa: BLE001
                log(f"   ! {src['nom']} : échec sur {url} ({type(e).__name__}: {str(e)[:80]})")
        vus, gardes = set(), []
        for a in sorted(recus, key=lambda x: x["date"], reverse=True):
            if a["url"] in vus or a["url"] in deja:
                continue
            vus.add(a["url"])
            if not (depuis <= a["date"] <= maintenant + timedelta(hours=1)):
                continue
            if src.get("filtre_cyber") and not motif_cyber.search(a["titre"] + " " + a["extrait"]):
                continue
            gardes.append(a)
        gardes = gardes[: cfg["max_candidats_par_source"]]
        candidats += gardes
        bilan.append(f"{src['nom']}: {'OK' if ok else 'ÉCHEC'} ({len(gardes)} article(s) retenu(s))")
    log("Sources : " + " | ".join(bilan))
    candidats.sort(key=lambda x: x["date"], reverse=True)
    for i, a in enumerate(candidats):
        a["id"] = i
    return candidats


# ----------------------------------------------------------------------------
# Météo (Open-Meteo)
# ----------------------------------------------------------------------------
def categorie_ciel(code):
    if code in (95, 96, 99):
        return "orage"
    if 71 <= code <= 77 or code in (85, 86):
        return "neige"
    if 51 <= code <= 67 or 80 <= code <= 82:
        return "pluie"
    if code in (45, 48):
        return "brouillard"
    if code == 3:
        return "couvert"
    if code in (1, 2):
        return "peu nuageux"
    return "dégagé"


def recuperer_meteo(cfg):
    m = cfg["meteo"]
    params = urllib.parse.urlencode({
        "latitude": m["latitude"], "longitude": m["longitude"],
        "hourly": "temperature_2m,precipitation_probability,precipitation,weather_code,visibility,wind_gusts_10m",
        "timezone": "Europe/Paris", "forecast_days": 1, "wind_speed_unit": "kmh",
    })
    data = json.loads(http_get("https://api.open-meteo.com/v1/forecast?" + params, tentatives=4))
    h = data["hourly"]
    heures = {int(t[11:13]): i for i, t in enumerate(h["time"])}

    def val(cle, heure, defaut=0):
        v = h[cle][heures[heure]]
        return defaut if v is None else v

    def plage(a, b):
        return range(a, b + 1)

    temps = {k: arrondi(val("temperature_2m", m["heure_" + k])) for k in ("matin", "midi", "soir")}

    # Ciel de la journée (8 h à 19 h) -> émoji + résumé pour Gemini
    codes_jour = [val("weather_code", hh) for hh in plage(8, 19)]
    cats = [categorie_ciel(c) for c in codes_jour]
    nb = lambda c: cats.count(c)  # noqa: E731
    if nb("orage"):
        emoji, ciel = "⛈️", "orageux"
    elif nb("neige"):
        emoji, ciel = "❄️", "neige"
    elif nb("pluie") >= 4:
        emoji, ciel = "🌧️", "pluvieux"
    elif nb("pluie"):
        emoji, ciel = "🌦️", "quelques averses"
    elif nb("brouillard") >= 3:
        emoji, ciel = "🌫️", "brumeux"
    elif nb("couvert") >= 7:
        emoji, ciel = "☁️", "couvert"
    elif nb("dégagé") + nb("peu nuageux") >= 7 and nb("dégagé") >= 5:
        emoji, ciel = "☀️", "ensoleillé"
    else:
        emoji, ciel = "🌤️", "nuageux avec éclaircies"

    # Conduite : trajets du matin et du soir
    trajets = list(plage(*m["trajet_matin"])) + list(plage(*m["trajet_soir"]))
    codes_t = [val("weather_code", hh) for hh in trajets]
    matin = list(plage(*m["trajet_matin"]))
    t_min_matin = min(val("temperature_2m", hh, 99) for hh in matin)
    vis_min = min(val("visibility", hh, 99999) for hh in matin)
    pluie_max = max(val("precipitation", hh) for hh in trajets)
    rafale_max = max(val("wind_gusts_10m", hh) for hh in trajets)
    if any(c in (56, 57, 66, 67) for c in codes_t):
        voiture = "Attention verglas possible : conduire très prudemment"
    elif any(71 <= c <= 77 or c in (85, 86) for c in codes_t):
        voiture = "Attention neige : conduire très prudemment"
    elif t_min_matin <= m["seuil_gel_celsius"]:
        voiture = "Attention il y a du gel : raclette nécessaire"
    elif any(c in (45, 48) for c in codes_t) or vis_min < 1000:
        voiture = "Attention brouillard : conduire prudemment"
    elif any(c in (65, 82, 95, 96, 99) for c in codes_t) or pluie_max >= 4:
        voiture = "Attention pluie forte : ralentir"
    elif rafale_max >= 65:
        voiture = "Attention vent fort : prudence"
    else:
        voiture = "RAS"

    return {
        "temps": temps,
        "emoji": emoji,
        "ciel": ciel,
        "proba_pluie_max": max(val("precipitation_probability", hh) for hh in plage(7, 19)),
        "pluie_mm": round(sum(val("precipitation", hh) for hh in plage(7, 19)), 1),
        "rafale_max_kmh": arrondi(max(val("wind_gusts_10m", hh) for hh in plage(7, 19))),
        "voiture": voiture,
    }


# ----------------------------------------------------------------------------
# Gemini
# ----------------------------------------------------------------------------
def appeler_gemini(modeles, systeme, utilisateur, cle):
    derniere = "aucun modèle essayé"
    for modele in modeles:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{modele}:generateContent"
        corps = json.dumps({
            "systemInstruction": {"parts": [{"text": systeme}]},
            "contents": [{"role": "user", "parts": [{"text": utilisateur}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.8},
        }).encode("utf-8")
        for essai in range(1, 4):
            try:
                req = urllib.request.Request(
                    url, data=corps, method="POST",
                    headers={"Content-Type": "application/json", "x-goog-api-key": cle})
                with urllib.request.urlopen(req, timeout=180) as r:
                    rep = json.load(r)
                parts = rep["candidates"][0]["content"]["parts"]
                texte = "".join(p.get("text", "") for p in parts if not p.get("thought"))
                if not texte.strip():
                    raise ValueError("réponse vide")
                log(f"Gemini : modèle utilisé = {modele}")
                return texte
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", "replace")[:300].replace("\n", " ")
                derniere = f"{modele} : HTTP {e.code} {detail}"
                log(f"   ! {derniere}")
                quota_nul = "limit: 0" in detail
                if e.code in (429, 500, 502, 503, 504) and essai < 3 and not quota_nul:
                    time.sleep(30 * essai)
                    continue
                break  # modèle suivant
            except Exception as e:  # noqa: BLE001
                derniere = f"{modele} : {type(e).__name__} {str(e)[:120]}"
                log(f"   ! {derniere}")
                time.sleep(10 * essai)
    raise RuntimeError("Gemini injoignable avec tous les modèles. Dernière erreur : " + derniere)


def extraire_json(texte):
    t = texte.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    debut, fin = t.find("{"), t.rfind("}")
    return json.loads(t[debut:fin + 1])


def valider(resultat, candidats, historique):
    """Renvoie (liste d'erreurs, résultat nettoyé)."""
    erreurs = []
    ids = {a["id"] for a in candidats}
    news = []
    vus = set()
    for n in resultat.get("news", []):
        try:
            i = int(n.get("id"))
        except (TypeError, ValueError):
            erreurs.append("une news n'a pas d'id valide")
            continue
        if i not in ids or i in vus:
            erreurs.append(f"id {i} inconnu ou utilisé deux fois")
            continue
        vus.add(i)
        crit = str(n.get("criticite", "")).strip().lower()
        if crit not in CRITICITES:
            erreurs.append(f"criticité invalide pour l'id {i} : « {crit} »")
            continue
        if not all(str(n.get(k, "")).strip() for k in ("titre", "victime", "attaque", "resume")):
            erreurs.append(f"champ vide dans la news id {i}")
            continue
        news.append({**n, "id": i, "criticite": crit})
    if not 3 <= len(news) <= 4:
        erreurs.append(f"il faut 3 ou 4 news valides (reçu {len(news)})")

    notion = resultat.get("notion") or {}
    if not all(str(notion.get(k, "")).strip() for k in ("titre", "definition", "exemple", "dfir")):
        erreurs.append("la notion est incomplète")
    else:
        d = est_doublon(notion["titre"], [x["titre"] for x in historique["notions"]])
        if d:
            erreurs.append(f"la notion « {notion['titre']} » est un doublon de « {d} » : choisis une AUTRE notion")

    philo = resultat.get("philocyber") or {}
    if not all(str(philo.get(k, "")).strip() for k in ("titre", "texte", "label")):
        erreurs.append("la réflexion Philocyber est incomplète")
    else:
        d = est_doublon(philo["label"], [x.get("label", x["titre"]) for x in historique["reflexions"]]) \
            or est_doublon(philo["titre"], [x["titre"] for x in historique["reflexions"]])
        if d:
            erreurs.append(f"la réflexion « {philo['titre']} » est trop proche de « {d} » : choisis un AUTRE thème")

    tenue = resultat.get("tenue")
    if not isinstance(tenue, list) or not tenue:
        erreurs.append("la tenue est absente")
    return erreurs, {**resultat, "news": news}


def rediger(cfg, candidats, meteo, historique, maintenant, cle):
    consigne = (SCRIPTS / "prompt.md").read_text(encoding="utf-8")
    vocab = "\n".join(f"  - {k} : {', '.join(v)}" for k, v in avatar.VOCABULAIRE.items())
    consigne = consigne.replace("{{VOCABULAIRE}}", vocab)

    jour = maintenant.weekday()
    style = "élégant" if jour in (0, 2) else "cool"
    entree = {
        "date": f"{JOURS[jour]} {maintenant.day} {MOIS[maintenant.month - 1]} {maintenant.year}",
        "style_du_jour": style,
        "meteo": ({
            "temperatures": meteo["temps"], "ciel": meteo["ciel"],
            "proba_pluie_max_pct": meteo["proba_pluie_max"], "pluie_mm": meteo["pluie_mm"],
            "rafales_max_kmh": meteo["rafale_max_kmh"],
        } if meteo else "indisponible"),
        "notions_deja_vues": [x["titre"] for x in historique["notions"]],
        "reflexions_deja_vues": [x.get("label", x["titre"]) for x in historique["reflexions"]],
        "news_deja_traitees": [x["titre"] for x in historique["news"]][-60:],
        "articles_candidats": [
            {"id": a["id"], "source": a["source"], "titre": a["titre"],
             "date": a["date"].astimezone(PARIS).strftime("%d/%m %Hh%M"), "extrait": a["extrait"]}
            for a in candidats],
    }
    base = json.dumps(entree, ensure_ascii=False, indent=1)
    correction = ""
    for tentative in range(1, 4):
        log(f"Rédaction (tentative {tentative}/3)…")
        brut = appeler_gemini(cfg["modeles_gemini"], consigne, base + correction, cle)
        try:
            resultat = extraire_json(brut)
        except Exception as e:  # noqa: BLE001
            correction = f"\n\nTa réponse précédente n'était pas un JSON valide ({e}). Réponds uniquement avec le JSON demandé."
            continue
        erreurs, nettoye = valider(resultat, candidats, historique)
        if not erreurs:
            return nettoye
        log("   ! Réponse refusée : " + " ; ".join(erreurs))
        correction = "\n\nCorrige ta réponse précédente, elle a été refusée pour ces raisons : " + " ; ".join(erreurs)
    raise RuntimeError("Gemini n'a pas produit de contenu valide après 3 tentatives.")


# ----------------------------------------------------------------------------
# Génération de la page
# ----------------------------------------------------------------------------
def date_longue(d):
    return f"{JOURS[d.weekday()]} {d.day} {MOIS[d.month - 1]} {d.year}"


def html_meteo(meteo, tenue):
    if not meteo:
        return "<h2>Météo à Rennes</h2>\n<p>Données météo indisponibles ce matin.</p>"
    t = meteo["temps"]
    return (
        f"<h2>Météo à Rennes {meteo['emoji']}</h2>\n"
        '<div class="weather">\n<div class="wtxt">\n'
        f'<div class="temps"><div><b>{t["matin"]}°</b><span>Matin</span></div>'
        f'<div><b>{t["midi"]}°</b><span>Midi</span></div>'
        f'<div><b>{t["soir"]}°</b><span>Soir</span></div></div>\n'
        f'<p class="row"><b>Tenue</b> : {txt(", ".join(tenue))}</p>\n'
        f'<p class="row"><b>Voiture</b> : {txt(meteo["voiture"])}</p>\n'
        "</div>\n" + avatar.dessiner(tenue) + "\n</div>"
    )


def html_news(news, candidats):
    par_id = {a["id"]: a for a in candidats}
    blocs = []
    for n in news:
        a = par_id[n["id"]]
        d = a["date"].astimezone(PARIS)
        source = f"{a['source']}, {d.day} {MOIS_COURTS[d.month - 1]}"
        blocs.append(
            "<article>\n"
            f"<h3>{txt(n['titre'])}</h3>\n"
            f"<dl><dt>Victime</dt><dd>{txt(n['victime'])}</dd>"
            f"<dt>Attaque</dt><dd>{txt(n['attaque'])}</dd>"
            f'<dt>Criticité</dt><dd><span class="crit {CRITICITES[n["criticite"]]}">{n["criticite"]}</span></dd></dl>\n'
            f"<p>{txt(n['resume'])}</p>\n"
            f'<p class="src">{txt(source)}</p>\n'
            "</article>")
    return "\n\n".join(blocs)


def html_journal(historique, limite=40):
    par_date = {}
    for n in historique["notions"]:
        par_date.setdefault(n["date"], {})["notion"] = n["titre"]
    for r in historique["reflexions"]:
        par_date.setdefault(r["date"], {})["reflexion"] = r.get("label", r["titre"])
    lignes = []
    for d in sorted(par_date, reverse=True)[:limite]:
        aaaa, mm, jj = d.split("-")
        e = par_date[d]
        lignes.append(f"<li>{jj}/{mm}/{aaaa} — Notion : {txt(e.get('notion', '—'))} | "
                      f"Réflexion : {txt(e.get('reflexion', '—'))}</li>")
    return "\n".join(lignes)


def construire_page(maintenant, meteo, contenu, candidats, historique):
    modele = (SCRIPTS / "template.html").read_text(encoding="utf-8")
    tenue = avatar.normaliser(contenu.get("tenue")) if meteo else []
    nt, ph = contenu["notion"], contenu["philocyber"]
    remplacements = {
        "{{DATE}}": date_longue(maintenant),
        "{{METEO}}": html_meteo(meteo, tenue),
        "{{NEWS}}": html_news(contenu["news"], candidats),
        "{{NOTION_TITRE}}": txt(nt["titre"]),
        "{{NOTION_DEFINITION}}": txt(nt["definition"]),
        "{{NOTION_EXEMPLE}}": txt(nt["exemple"]),
        "{{NOTION_DFIR}}": txt(nt["dfir"]),
        "{{PHILO_TITRE}}": txt(ph["titre"]),
        "{{PHILO_TEXTE}}": txt(ph["texte"]),
        "{{JOURNAL}}": html_journal(historique),
        "{{MAJ}}": f"{maintenant.day} {MOIS[maintenant.month - 1]} {maintenant.year}",
    }
    page = modele
    for k, v in remplacements.items():
        page = page.replace(k, v)
    return page


def mettre_a_jour_historique(historique, contenu, candidats, maintenant):
    jour = maintenant.strftime("%Y-%m-%d")
    par_id = {a["id"]: a for a in candidats}
    historique["notions"].append({"date": jour, "titre": contenu["notion"]["titre"].strip()})
    historique["reflexions"].append({"date": jour, "titre": contenu["philocyber"]["titre"].strip(),
                                     "label": contenu["philocyber"]["label"].strip()})
    for n in contenu["news"]:
        historique["news"].append({"date": jour, "titre": n["titre"].strip(), "url": par_id[n["id"]]["url"]})
    historique["news"] = historique["news"][-200:]


def sortie_github(cle, valeur):
    chemin = os.environ.get("GITHUB_OUTPUT")
    if chemin:
        with open(chemin, "a", encoding="utf-8") as f:
            f.write(f"{cle}={valeur}\n")


# ----------------------------------------------------------------------------
def mode_bandeau():
    page_path = DOCS / "index.html"
    if not page_path.exists():
        log("Aucune page existante : pas de bandeau à ajouter.")
        return
    page = page_path.read_text(encoding="utf-8")
    bandeau = ('<p class="stale">⚠️ La mise à jour automatique de ce matin a échoué : '
               "c’est l’édition précédente qui est affichée.</p>")
    page = re.sub(r"<!--BANNER-->.*?<!--/BANNER-->", f"<!--BANNER-->{bandeau}<!--/BANNER-->", page, flags=re.S)
    page_path.write_text(page, encoding="utf-8")
    log("Bandeau d'échec ajouté à la page existante.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--stale", action="store_true")
    args = ap.parse_args()

    if args.stale:
        mode_bandeau()
        return 0

    cfg = charger_json(SCRIPTS / "config.json")
    maintenant = datetime.now(PARIS)
    aujourdhui = maintenant.strftime("%Y-%m-%d")
    log(f"Heure à Paris : {maintenant:%Y-%m-%d %H:%M}")

    meta = charger_json(DOCS / "meta.json", {})
    if meta.get("date") == aujourdhui and not args.force:
        log("L'édition du jour existe déjà : rien à faire.")
        sortie_github("generated", "false")
        return 0

    cle = os.environ.get("GEMINI_API_KEY", "").strip()
    if not cle:
        log("ERREUR : le secret GEMINI_API_KEY est vide ou absent (voir le guide, étape « clé API »).")
        return 1

    historique = charger_json(DATA / "history.json", {"notions": [], "reflexions": [], "news": []})
    if args.force:  # on régénère : on retire d'abord l'édition du jour de l'historique
        for cle_h in ("notions", "reflexions", "news"):
            historique[cle_h] = [x for x in historique[cle_h] if x.get("date") != aujourdhui]

    log("Collecte des flux RSS…")
    candidats = collecter_articles(cfg, historique, maintenant)
    if len(candidats) < 5:
        log(f"ERREUR : seulement {len(candidats)} article(s) récupéré(s) ; trop peu pour rédiger l'édition.")
        return 1

    log("Météo…")
    try:
        meteo = recuperer_meteo(cfg)
        log(f"   {meteo['temps']} | {meteo['ciel']} | voiture : {meteo['voiture']}")
    except Exception as e:  # noqa: BLE001
        log(f"   ! Météo indisponible ({type(e).__name__}: {str(e)[:100]}) : la page s'affichera sans météo.")
        meteo = None

    contenu = rediger(cfg, candidats, meteo, historique, maintenant, cle)
    page = construire_page(maintenant, meteo, contenu, candidats, historique)

    mettre_a_jour_historique(historique, contenu, candidats, maintenant)
    # La page est reconstruite avec le journal à jour (pour y inclure l'édition du jour)
    page = construire_page(maintenant, meteo, contenu, candidats, historique)

    DOCS.mkdir(exist_ok=True)
    (DOCS / "index.html").write_text(page, encoding="utf-8")
    ecrire_json(DOCS / "meta.json", {"date": aujourdhui, "genere_le": maintenant.isoformat(timespec="seconds")})
    ecrire_json(DATA / "history.json", historique)
    sortie_github("generated", "true")
    log("Terminé : docs/index.html écrit.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
