"""Construction du classeur : MASTER + DELTA_<date> + SUIVI_LEADS.

Le classeur sert à la fois de base de données, d'interface de feedback (colonnes validation /
motif) et de CRM léger. Il est reconstruit à chaque run sans écraser les labels déjà saisis.

⚠️ `openpyxl.delete_rows` est peu fiable (283 lignes fantômes constatées) : pour retirer des
lignes, reconstruire l'onglet de zéro plutôt que d'y supprimer en place.

Identité d'une ligne du MASTER (`cles_identite`) : sa `cle_contenu`, son URL (sauf URL de
recherche) et, quand des lignes antérieures sont réinjectées depuis l'historique, une clé de
secours auteur + extrait. Une clé vide n'identifie jamais rien. En mode partagé, une
refinalisation garde aussi les labels saisis dans l'onglet DELTA du run.
"""
from __future__ import annotations

import csv
import errno
import json
import os
import re
from typing import Any

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from .cles import cle_contenu, cle_secours, cle_url, norm
from .dedup import COLONNE_HISTORIQUE, nom_ignore
from .verify import controler

__all__ = [
    "CLE_PROVENANCE", "COLS", "COLS_LEADS", "cles_identite", "construire", "lire_historique_csv",
    "run_du_fichier",
]

# clé interne posée sur chaque ligne antérieure : le run dont elle vient (jamais écrite)
CLE_PROVENANCE = "_run"

COLS = [
    "post_extrait", "url_post", "url_profil_auteur", "auteur", "date", "mail", "taux_horaire",
    "localisation", "score_pertinence", "mot_cle_recherche", "batch", "type_opportunite",
    "echeance", "deal_breaker", "commentaire_scoring", "reponse_commentaire_linkedin",
    "note_invitation_200", "note_invitation_300", "message_linkedin", "reponse_mail",
    "cle_contenu", "validation", "motif",
]
COLS_LEADS = [
    "lead", "organisation", "annonce", "url_post", "contact", "mail", "type_opportunite",
    "echeance", "score", "statut_lead", "reponse_commentaire_linkedin", "note_invitation_200",
    "note_invitation_300", "message_linkedin", "reponse_mail", "notes",
]
STATUTS = "À contacter,Contacté,Relancé,En discussion,RDV/Entretien,Gagné,Perdu/Sans réponse"

WRAP = {
    "post_extrait", "commentaire_scoring", "reponse_commentaire_linkedin", "note_invitation_200",
    "note_invitation_300", "message_linkedin", "reponse_mail", "motif",
}
LARGEURS = {
    "post_extrait": 50, "url_post": 34, "url_profil_auteur": 28, "auteur": 20, "date": 10,
    "mail": 22, "taux_horaire": 12, "localisation": 20, "score_pertinence": 8,
    "mot_cle_recherche": 17, "batch": 13, "type_opportunite": 16, "echeance": 14,
    "deal_breaker": 12, "commentaire_scoring": 45, "reponse_commentaire_linkedin": 45,
    "note_invitation_200": 32, "note_invitation_300": 42, "message_linkedin": 60,
    "reponse_mail": 55, "cle_contenu": 14, "validation": 10, "motif": 26,
}

HDR = PatternFill("solid", fgColor="1F3864")
GOLD = PatternFill("solid", fgColor="BF8F00")
EDIT = PatternFill("solid", fgColor="FFF2CC")
HI = PatternFill("solid", fgColor="C6EFCE")
MID = PatternFill("solid", fgColor="FFEB9C")
_T = Side(style="thin", color="BFBFBF")
BD = Border(left=_T, right=_T, top=_T, bottom=_T)
COL_HUMAIN = ("validation", "motif", "statut_lead")


def _police(**kw: Any) -> Font:
    return Font(name="Arial", size=10, **kw)


def _entete(ws: Any, cols: list[str]) -> None:
    for c, x in enumerate(cols, 1):
        cell = ws.cell(row=1, column=c, value=x)
        cell.font = Font(name="Arial", bold=True, color="FFFFFF", size=10)
        cell.fill = GOLD if x in COL_HUMAIN else HDR
        cell.border = BD
        cell.alignment = Alignment(vertical="center", wrap_text=True)


def _ecrire_ligne(ws: Any, i: int, p: dict[str, Any], seuil_redaction: float) -> None:
    v = [p.get(c, "") for c in COLS]
    for c, x in enumerate(v, 1):
        cell = ws.cell(row=i, column=c, value=x)
        cell.font = _police()
        cell.border = BD
        cell.alignment = Alignment(vertical="top", wrap_text=(COLS[c - 1] in WRAP))
    for nom in ("url_post", "url_profil_auteur"):
        c = COLS.index(nom) + 1
        if v[c - 1]:
            ws.cell(row=i, column=c).hyperlink = v[c - 1]
            ws.cell(row=i, column=c).font = _police(color="0563C1", underline="single")
    sc = ws.cell(row=i, column=COLS.index("score_pertinence") + 1)
    sc.font = _police(bold=True)
    if not p.get("deal_breaker"):
        sc.fill = HI if float(p.get("score_pertinence") or 0) > seuil_redaction else MID
    for nom in ("validation", "motif"):
        ws.cell(row=i, column=COLS.index(nom) + 1).fill = EDIT


def _preparer(posts: list[dict[str, Any]], run: str) -> list[dict[str, Any]]:
    """Normalise les types et garantit une `cle_contenu` sur chaque ligne.

    ⚠️ `cle_contenu` est calculée au harvest, sur le TEXTE BRUT du post, et transportée par
    `a_scorer.json`. Les agents de scoring doivent la recopier telle quelle dans leur sortie.
    Si elle manque, on la recalcule sur le texte encore disponible — et à défaut sur
    `post_extrait`, qui est une reformulation : la ligne sera alors invisible à la
    déduplication du run suivant. On le signale plutôt que de le laisser passer en silence.
    """
    sans_cle = []
    for p in posts:
        try:
            p["score_pertinence"] = float(p.get("score_pertinence") or 0)
        except (TypeError, ValueError):
            p["score_pertinence"] = 0.0
        texte_brut = p.get("texte") or ""
        for k in COLS:
            if k != "score_pertinence":
                p[k] = str(p.get(k) or "")
        p["batch"] = p["batch"] or f"RUN {run}"
        if not p["cle_contenu"]:
            p["cle_contenu"] = cle_contenu(p["auteur"], texte_brut or p["post_extrait"])
            if not texte_brut:
                sans_cle.append(p["auteur"])
    if sans_cle:
        print(
            f"  ⚠ {len(sans_cle)} ligne(s) sans cle_contenu ni texte brut — clé dérivée de "
            f"post_extrait, la déduplication du prochain run les manquera : "
            + ", ".join(sans_cle[:5]) + ("…" if len(sans_cle) > 5 else "")
        )
    posts.sort(key=lambda p: -p["score_pertinence"])
    return posts


def _preparer_anterieurs(lignes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalisation propre aux lignes réinjectées depuis l'historique.

    Types et colonnes `COLS` seulement : ni recalcul de clé (celle d'origine fait foi, même
    absente), ni tri par score (l'ordre chronologique reçu est conservé), ni avertissement
    « sans clé ». `batch` vide devient `RUN <run>`, le run étant la clé interne `_run` posée par
    l'appelant. Les lignes sont copiées : `_run` et les colonnes hors `COLS` ne vont pas plus loin.
    """
    out = []
    for ligne in lignes:
        p: dict[str, Any] = {k: str(ligne.get(k) or "") for k in COLS if k != "score_pertinence"}
        try:
            p["score_pertinence"] = float(ligne.get("score_pertinence") or 0)
        except (TypeError, ValueError):
            p["score_pertinence"] = 0.0
        run = str(ligne.get(CLE_PROVENANCE) or "")
        if not p["batch"] and run:
            p["batch"] = f"RUN {run}"
        out.append(p)
    return out


def cles_identite(ligne: dict[str, Any], secours: bool = True) -> set[tuple[str, str]]:
    """Clés d'identité NON VIDES d'une ligne du MASTER, étiquetées par sorte.

    Une ligne est déjà présente si l'une de ses clés est connue :
      - `cle_contenu` ;
      - l'URL normalisée (sans query), sauf une URL de recherche (`search/results` dans son
        chemin) : elles se réduisent toutes à la même clé et écarteraient en silence les
        annonces suivantes. Seul le chemin compte : un permalien suivi de
        `?trk=search/results` reste une clé, comme avant en mode local ;
      - avec `secours`, `norm(auteur) | norm(post_extrait)[:90]`, seulement si les deux côtés
        sont non vides : elle rattrape un DELTA sans `cle_contenu` dont le lien `lnkd.in` a changé.

    Une clé vide n'est jamais rendue : elle n'est donc ni ajoutée aux ensembles, ni comparée.
    """
    cles: set[tuple[str, str]] = set()
    k = str(ligne.get("cle_contenu") or "")
    if k:
        cles.add(("contenu", k))
    u = cle_url(ligne.get("url_post"))
    if u and "search/results" not in u:
        cles.add(("url", u))
    if secours:
        a, t = norm(ligne.get("auteur")), norm(ligne.get("post_extrait"))[:90]
        if a and t:
            cles.add(("secours", a + "|" + t))
    return cles


def construire(
    posts: list[dict[str, Any]],
    run: str,
    sortie: str,
    base: str | None = None,
    seuil_redaction: float = 5.0,
    anterieurs: list[dict[str, Any]] | None = None,
) -> dict[str, int]:
    """Écrit le classeur. Lève AssertionError si un garde-fou saute.

    `anterieurs` (mode partagé) : lignes d'historique des runs antérieurs, dans l'ordre
    chronologique, chacune avec sa clé interne `_run` (voir `lire_historique_csv`). Celles qui
    manquent au MASTER y sont réinjectées, avant le run courant, et comptées dans
    `reinjectees`. Elles ne passent ni par `controler()` ni par F4 ici : l'appelant les filtre
    (F4) avant. Elles n'entrent ni au DELTA ni au SUIVI_LEADS. Dans ce mode seulement :
      - la clé de secours auteur + extrait est active ;
      - une `base` fournie mais introuvable lève FileNotFoundError : jamais de repli sur un
        classeur vide, qui perdrait les labels et les leads ;
      - une refinalisation (la base porte déjà l'onglet `DELTA_<run>`) reporte dans le nouvel
        onglet les `validation` et `motif` saisis dans l'ancien, ligne retrouvée par ses clés
        d'identité.

    Sans `anterieurs` (mode local), le résultat est celui d'avant : mêmes lignes, mêmes
    statistiques, sans `reinjectees`.
    """
    posts = _preparer(posts, run)

    anomalies = controler(posts, seuil_redaction=seuil_redaction)
    if anomalies:
        raise AssertionError("garde-fous : " + " | ".join(str(a) for a in anomalies))
    partage = anterieurs is not None
    anciens = _preparer_anterieurs(anterieurs) if partage else []

    if base and os.path.exists(base):
        wb = openpyxl.load_workbook(base)
    elif base and partage:
        raise FileNotFoundError(errno.ENOENT, "classeur de base introuvable", base)
    else:
        wb = openpyxl.Workbook()
    if "Sheet" in wb.sheetnames and wb["Sheet"].max_row == 1:
        del wb["Sheet"]
    for nom, cols in (("MASTER", COLS), ("SUIVI_LEADS", COLS_LEADS)):
        if nom not in wb.sheetnames:
            _entete(wb.create_sheet(nom), cols)

    # --- DELTA ---------------------------------------------------------------
    sh = f"DELTA_{run}"
    labels: dict[tuple[str, str], dict[str, Any]] = {}
    if sh in wb.sheetnames:
        if partage:  # refinalisation : les labels saisis dans l'onglet DELTA sont gardés
            labels = _labels_onglet(wb[sh])
        del wb[sh]
    ws = wb.create_sheet(sh, 1)
    _entete(ws, COLS)
    for i, p in enumerate(posts, 2):
        _ecrire_ligne(ws, i, p, seuil_redaction)
        _reporter_labels(ws, i, p, labels)
    _finir_onglet(ws, COLS, "validation", '"OUI,NON"')

    # --- MASTER : n'ajouter que ce qui n'y est pas déjà ----------------------
    m = wb["MASTER"]
    cols_m = [c.value for c in m[1]]
    if cols_m != COLS:  # classeur d'une version antérieure : on migre l'en-tête
        _migrer_entete(m, cols_m)
    secours = partage
    connues: set[tuple[str, str]] = set()
    for r in m.iter_rows(min_row=2, values_only=True):
        connues |= cles_identite(dict(zip(COLS, r)), secours=secours)

    # lignes antérieures manquantes, dans l'ordre chronologique reçu ; les labels de la base ne
    # sont pas touchés, on ne fait qu'ajouter
    reinjectees = sans_identite = 0
    for p in anciens:
        cles = cles_identite(p)
        if not cles:  # jamais reconnaissable : réinjectée, elle reviendrait à chaque run
            sans_identite += 1
            continue
        if cles & connues:
            continue
        _ecrire_ligne(m, m.max_row + 1, p, seuil_redaction)
        connues |= cles
        reinjectees += 1
    if sans_identite:
        print(
            f"  ⚠ {sans_identite} ligne(s) d'historique sans aucune clé (ni cle_contenu, ni URL, "
            "ni auteur et extrait) : non réinjectée(s), elles reviendraient à chaque run"
        )

    ajoutes = 0
    for p in posts:
        cles = cles_identite(p, secours=secours)
        if cles & connues:
            continue
        _ecrire_ligne(m, m.max_row + 1, p, seuil_redaction)
        # mode local : comme avant, seule la cle_contenu d'une ligne écrite compte pour la suite
        connues |= cles if secours else {c for c in cles if c[0] == "contenu"}
        ajoutes += 1
    _finir_onglet(m, COLS, "validation", '"OUI,NON"')

    # --- SUIVI_LEADS ---------------------------------------------------------
    sl = wb["SUIVI_LEADS"]
    hl = [c.value for c in sl[1]]
    i_org = hl.index("organisation")
    deja_org = {norm(r[i_org]) for r in sl.iter_rows(min_row=2, values_only=True) if r[i_org]}
    leads = [
        p for p in posts
        if p["reponse_commentaire_linkedin"] and norm(p["auteur"]) not in deja_org
    ]
    i_url = hl.index("url_post")
    for i, p in enumerate(leads, sl.max_row + 1):
        v = [
            f"{p['auteur']} [{run}]", p["auteur"], p["post_extrait"][:300], p["url_post"],
            f"{p['auteur']} — {p['url_profil_auteur']}", p["mail"], p["type_opportunite"],
            p["echeance"], p["score_pertinence"], "À contacter",
            p["reponse_commentaire_linkedin"], p["note_invitation_200"],
            p["note_invitation_300"], p["message_linkedin"], p["reponse_mail"],
            f"Run {run} | " + p["commentaire_scoring"][:200],
        ]
        for c, x in enumerate(v, 1):
            cell = sl.cell(row=i, column=c, value=x)
            cell.font = _police()
            cell.border = BD
            cell.alignment = Alignment(
                vertical="top", wrap_text=(hl[c - 1] not in ("score", "statut_lead", "mail"))
            )
        if p["url_post"]:
            sl.cell(row=i, column=i_url + 1).hyperlink = p["url_post"]
            sl.cell(row=i, column=i_url + 1).font = _police(color="0563C1", underline="single")
        sl.cell(row=i, column=hl.index("statut_lead") + 1).fill = EDIT
    _finir_onglet(sl, hl, "statut_lead", f'"{STATUTS}"')

    ordre = ["MASTER", sh, "SUIVI_LEADS"]
    wb._sheets = [wb[s] for s in ordre + [x for x in wb.sheetnames if x not in ordre]]
    wb.save(sortie)
    stats = {
        "delta": len(posts), "ajoutes_master": ajoutes, "nouveaux_leads": len(leads),
        "master_total": m.max_row - 1, "leads_total": sl.max_row - 1,
    }
    if partage:  # 0 en régime normal : un autre nombre est un signal
        stats["reinjectees"] = reinjectees
    return stats


LABELS_DELTA = ("validation", "motif")


def _labels_onglet(ws: Any) -> dict[tuple[str, str], dict[str, Any]]:
    """Labels humains (`validation`, `motif`) d'un onglet au format `COLS`, par clé d'identité.

    Les colonnes se lisent à leur en-tête : un onglet d'une version antérieure garde ses labels.
    Une ligne sans label n'apporte rien ; à clé égale, la première ligne l'emporte.
    """
    lignes = ws.iter_rows(values_only=True)
    cols = ["" if c is None else str(c) for c in next(lignes, ())]
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for r in lignes:
        ligne = dict(zip(cols, r))
        lab = {c: ligne[c] for c in LABELS_DELTA if ligne.get(c) not in (None, "")}
        if lab:
            for k in cles_identite(ligne):
                out.setdefault(k, lab)
    return out


def _reporter_labels(
    ws: Any, i: int, p: dict[str, Any], labels: dict[tuple[str, str], dict[str, Any]]
) -> None:
    """Reporte sur la ligne `i` les labels de l'ancienne ligne de même identité (contenu, puis
    URL, puis secours). Un label déjà porté par la ligne scorée l'emporte."""
    if not labels:
        return
    cles = cles_identite(p)
    for sorte in ("contenu", "url", "secours"):
        lab = next((labels[k] for k in cles if k[0] == sorte and k in labels), None)
        if lab:
            for c, v in lab.items():
                if not p.get(c):
                    ws.cell(row=i, column=COLS.index(c) + 1, value=v)
            return


def _finir_onglet(ws: Any, cols: list[str], col_liste: str, formule: str) -> None:
    for c, x in enumerate(cols, 1):
        ws.column_dimensions[get_column_letter(c)].width = LARGEURS.get(x, 18)
    ws.freeze_panes = "A2"
    derniere = max(ws.max_row, 2)
    ws.auto_filter.ref = f"A1:{get_column_letter(len(cols))}{derniere}"
    if col_liste in cols:
        dv = DataValidation(type="list", formula1=formule, allow_blank=True)
        ws.add_data_validation(dv)
        lettre = get_column_letter(cols.index(col_liste) + 1)
        dv.add(f"{lettre}2:{lettre}{derniere}")


def _migrer_entete(ws: Any, cols_actuelles: list[str]) -> None:
    """Ajoute les colonnes manquantes à un classeur produit par une version antérieure."""
    for manquante in [c for c in COLS if c not in cols_actuelles]:
        i = COLS.index(manquante) + 1
        ws.insert_cols(i)
        cell = ws.cell(row=1, column=i, value=manquante)
        cell.font = Font(name="Arial", bold=True, color="FFFFFF", size=10)
        cell.fill = GOLD if manquante in COL_HUMAIN else HDR
        cell.border = BD


def charger_posts(chemin: str) -> list[dict[str, Any]]:
    with open(chemin, encoding="utf-8") as fh:
        d = json.load(fh)
    return d["posts"] if isinstance(d, dict) and "posts" in d else d


def run_du_fichier(chemin: str) -> str | None:
    """Run tiré du nom `DELTA_<run>.csv`, ou None (MASTER migré, autre nom)."""
    m = re.fullmatch(r"DELTA_(.+)\.csv", os.path.basename(chemin), re.IGNORECASE)
    return m.group(1) if m else None


def lire_historique_csv(chemin: str, run: str | None = None) -> list[dict[str, Any]] | None:
    """Lignes d'un CSV d'historique au format `COLS` (MASTER, DELTA), pour `construire(anterieurs=…)`.

    Lecture en `utf-8-sig` : un CSV réenregistré par Excel commence par un BOM, qui collerait
    au nom de la première colonne. Le fichier est reconnu à sa colonne `auteur` (présente dans
    `COLS`, absente de `COLS_LEADS`). Renvoie None pour un fichier non reconnu ou un fichier de
    travail (`~$…`, `….tmp`) : à l'appelant de le signaler.

    Chaque ligne porte la clé interne `_run` : `run` s'il est fourni, sinon le run tiré du nom
    `DELTA_<run>.csv`, sinon "". Un fichier illisible lève son exception : jamais de repli
    silencieux.
    """
    if nom_ignore(chemin):
        return None
    with open(chemin, encoding="utf-8-sig", newline="") as fh:
        lecteur = csv.DictReader(fh, restval="")
        if COLONNE_HISTORIQUE not in (lecteur.fieldnames or []):
            return None
        provenance = run if run is not None else (run_du_fichier(chemin) or "")
        lignes: list[dict[str, Any]] = []
        for r in lecteur:
            r.pop(None, None)  # cellules au-delà de l'en-tête
            r[CLE_PROVENANCE] = provenance
            lignes.append(r)
    return lignes
