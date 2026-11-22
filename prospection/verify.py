"""Garde-fous bloquants avant livraison.

Ces contrôles ont chacun attrapé une erreur réelle en production. Ils échouent le build :
un livrable qui ne passe pas n'est pas livré.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

__all__ = ["Anomalie", "controler", "controler_classeur", "LIMITES"]

LIMITES = {"note_invitation_200": 200, "note_invitation_300": 300, "message_linkedin_lignes": 10}

_SALUTATION = re.compile(r"^\s*(Bonjour|Bonsoir|Madame|Monsieur|Chère?|Cher)", re.I)
_MAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
# Téléphone FR : 0X suivi de 8 chiffres, séparateurs optionnels. Exige les 10 chiffres pour
# ne pas confondre avec un volume horaire ou une date. Format international : +33 ou 0033, puis
# le numéro sans son 0, avec un « (0) » toléré (+33 6 …, +33600000000, +33 (0)6 …).
_TEL = re.compile(
    r"\b0\d(?:[\s.\-]?\d{2}){4}\b"
    r"|(?:\+|\b00)33[\s.\-]?(?:\(0\)[\s.\-]?)?[1-9](?:[\s.\-]?\d{2}){4}\b"
)
_CHAMPS_TEXTE = (
    "reponse_commentaire_linkedin",
    "note_invitation_200",
    "note_invitation_300",
    "message_linkedin",
    "reponse_mail",
)


@dataclass
class Anomalie:
    auteur: str
    regle: str
    detail: str = ""

    def __str__(self) -> str:
        return f"{self.auteur} — {self.regle}" + (f" ({self.detail})" if self.detail else "")


def controler(posts: Iterable[dict[str, Any]], seuil_redaction: float | None = None) -> list[Anomalie]:
    """Contrôle une liste de lignes scorées. Renvoie la liste des anomalies (vide = OK).

    Chaque ligne reçue est une ligne CONSERVÉE (le retrait sous seuil a lieu avant) : elle doit
    porter le permalien du post et, si son score est positif, le détail de son calcul.
    """
    err: list[Anomalie] = []
    organisations: dict[str, str] = {}

    for p in posts:
        a = str(p.get("auteur") or "?")

        # permalien : jamais vide, jamais l'URL de recherche (elles se réduisent toutes à la
        # même cle_url, et une seule suffirait à écarter en silence les annonces suivantes)
        url = str(p.get("url_post") or "").strip()
        if not url:
            err.append(Anomalie(a, "permalien manquant (url_post vide)"))
        elif "search/results" in url:
            err.append(Anomalie(a, "URL de recherche au lieu d'un permalien"))

        # chaque score est tracé : un score positif sans le détail de son calcul est refusé
        try:
            score = float(p.get("score_pertinence") or 0)
        except (TypeError, ValueError):
            score = 0.0
        if score > 0 and not str(p.get("commentaire_scoring") or "").strip():
            err.append(Anomalie(a, "commentaire_scoring vide alors que le score est positif",
                                f"score {score}"))

        n200 = str(p.get("note_invitation_200") or "")
        n300 = str(p.get("note_invitation_300") or "")
        msg = str(p.get("message_linkedin") or "")
        com = str(p.get("reponse_commentaire_linkedin") or "")
        mail = str(p.get("reponse_mail") or "")

        # longueurs
        if len(n200) > LIMITES["note_invitation_200"]:
            err.append(Anomalie(a, "note_invitation_200 trop longue", f"{len(n200)} car."))
        if len(n300) > LIMITES["note_invitation_300"]:
            err.append(Anomalie(a, "note_invitation_300 trop longue", f"{len(n300)} car."))
        if msg:
            lignes = msg.count("\n") + 1
            if lignes > LIMITES["message_linkedin_lignes"]:
                err.append(Anomalie(a, "message_linkedin trop long", f"{lignes} lignes"))

        # commentaire public : ni salutation, ni coordonnées
        if _SALUTATION.match(com):
            err.append(Anomalie(a, "commentaire public commence par une salutation"))
        if _MAIL.search(com):
            err.append(Anomalie(a, "adresse mail dans un commentaire public"))
        if _TEL.search(com):
            err.append(Anomalie(a, "téléphone dans un commentaire public"))

        # cohérence mail : un corps de mail sans adresse dans le post n'a pas de destinataire
        if mail and not str(p.get("mail") or "").strip():
            err.append(Anomalie(a, "reponse_mail rédigée alors qu'aucune adresse ne figure au post"))

        # cohérence seuil : des textes sous le seuil, ou aucun texte au-dessus
        if seuil_redaction is not None and p.get("score_pertinence") is not None:
            a_des_textes = any(str(p.get(c) or "").strip() for c in _CHAMPS_TEXTE)
            if score > seuil_redaction and not a_des_textes and not p.get("doublon_de"):
                err.append(Anomalie(a, "aucun message rédigé alors que le score dépasse le seuil",
                                    f"score {score}"))
            if score <= seuil_redaction and a_des_textes:
                err.append(Anomalie(a, "messages rédigés sous le seuil", f"score {score}"))

        # une seule candidature par organisation
        from .cles import norm

        org = norm(a)
        if org and any(str(p.get(c) or "").strip() for c in _CHAMPS_TEXTE):
            if org in organisations:
                err.append(Anomalie(a, "deuxième candidature pour la même organisation",
                                    f"déjà : {organisations[org]}"))
            else:
                organisations[org] = a

    return err


def controler_classeur(chemin: str, onglet: str = "MASTER") -> list[Anomalie]:
    """Relit un classeur produit et rejoue les contrôles, plus ceux propres au fichier."""
    import openpyxl

    wb = openpyxl.load_workbook(chemin)
    ws = wb[onglet]
    cols = [c.value for c in ws[1]]
    posts = [dict(zip(cols, r)) for r in ws.iter_rows(min_row=2, values_only=True)]
    err = controler(posts)

    vues: set[str] = set()
    for p in posts:
        k = str(p.get("cle_contenu") or "")
        if k:
            if k in vues:
                err.append(Anomalie(str(p.get("auteur")), "doublon de cle_contenu dans le classeur"))
            vues.add(k)
    return err
