"""Construction du classeur : MASTER + DELTA_<date> + SUIVI_LEADS.

Le classeur sert à la fois de base de données, d'interface de feedback (colonnes validation /
motif) et de CRM léger. Il est reconstruit à chaque run sans écraser les labels déjà saisis.

⚠️ `openpyxl.delete_rows` est peu fiable (283 lignes fantômes constatées) : pour retirer des
lignes, reconstruire l'onglet de zéro plutôt que d'y supprimer en place.
"""
from __future__ import annotations

import json
import os
from typing import Any

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from .cles import cle_contenu, cle_secours, cle_url, norm
from .verify import controler

__all__ = ["COLS", "COLS_LEADS", "construire"]

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


def construire(
    posts: list[dict[str, Any]],
    run: str,
    sortie: str,
    base: str | None = None,
    seuil_redaction: float = 5.0,
) -> dict[str, int]:
    """Écrit le classeur. Lève AssertionError si un garde-fou saute."""
    posts = _preparer(posts, run)

    anomalies = controler(posts, seuil_redaction=seuil_redaction)
    if anomalies:
        raise AssertionError("garde-fous : " + " | ".join(str(a) for a in anomalies))

    wb = openpyxl.load_workbook(base) if base and os.path.exists(base) else openpyxl.Workbook()
    if "Sheet" in wb.sheetnames and wb["Sheet"].max_row == 1:
        del wb["Sheet"]
    for nom, cols in (("MASTER", COLS), ("SUIVI_LEADS", COLS_LEADS)):
        if nom not in wb.sheetnames:
            _entete(wb.create_sheet(nom), cols)

    # --- DELTA ---------------------------------------------------------------
    sh = f"DELTA_{run}"
    if sh in wb.sheetnames:
        del wb[sh]
    ws = wb.create_sheet(sh, 1)
    _entete(ws, COLS)
    for i, p in enumerate(posts, 2):
        _ecrire_ligne(ws, i, p, seuil_redaction)
    _finir_onglet(ws, COLS, "validation", '"OUI,NON"')

    # --- MASTER : n'ajouter que ce qui n'y est pas déjà ----------------------
    m = wb["MASTER"]
    cols_m = [c.value for c in m[1]]
    if cols_m != COLS:  # classeur d'une version antérieure : on migre l'en-tête
        _migrer_entete(m, cols_m)
    deja_contenu, deja_url = set(), set()
    i_k, i_u = COLS.index("cle_contenu"), COLS.index("url_post")
    for r in m.iter_rows(min_row=2, values_only=True):
        if r[i_k]:
            deja_contenu.add(str(r[i_k]))
        if r[i_u]:
            deja_url.add(cle_url(r[i_u]))
    ajoutes = 0
    for p in posts:
        if p["cle_contenu"] in deja_contenu:
            continue
        if p["url_post"] and cle_url(p["url_post"]) in deja_url:
            continue
        _ecrire_ligne(m, m.max_row + 1, p, seuil_redaction)
        deja_contenu.add(p["cle_contenu"])
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
    return {
        "delta": len(posts), "ajoutes_master": ajoutes, "nouveaux_leads": len(leads),
        "master_total": m.max_row - 1, "leads_total": sl.max_row - 1,
    }


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
