"""Verrou de run sur le dossier de données partagé (mode partagé seulement).

Plusieurs PC partagent le même dossier de données. Le verrou évite qu'un PC lance ou finalise un
run pendant qu'un autre en a un en cours : `lots --run`, `prepare` et `finaliser` le prennent (ou
le rafraîchissent), `finaliser` le libère après succès.

⚠️ Honnêteté : un fichier sur un Drive n'est PAS un verrou distribué. Le Drive synchronise avec
retard, et deux PC qui prennent le verrou à la même seconde le prendront tous les deux (le Drive
en fera une copie en conflit, `verrou (1).json`). Le verrou couvre l'OUBLI — lancer un run sur le
PC B alors que le PC A n'a pas fini —, pas la course à la seconde.

Le fichier `verrou.json` :

    {"etat": "pris"|"libre", "poste": "<nom du PC>", "utilisateur": "<compte, sinon ?>",
     "run": "...", "depuis": "<ISO UTC +00:00>", "activite": "<ISO UTC +00:00>", "commande": "..."}

- Tous les `verrou*.json` sont lus, copies en conflit comprises : une copie tenue par un autre
  poste bloque comme l'original.
- Un fichier illisible, ou une date absente, invalide ou sans fuseau, compte pour un verrou pris
  par un poste inconnu (`corrompu`) : dans le doute, occupé.
- Libérer RÉÉCRIT le verrou avec `"etat": "libre"` (pierre tombale) au lieu de le supprimer :
  sur un Drive, un fichier supprimé peut revenir à la synchronisation suivante.
- Chaque écriture passe par un temporaire dans le même dossier, puis `os.replace`.
"""
from __future__ import annotations

import fnmatch
import getpass
import json
import os
import socket
import sys
from datetime import datetime, timedelta, timezone
from typing import Any

__all__ = ["NOM", "TTL_HEURES", "VerrouOccupe", "etats", "occupants", "prendre", "liberer", "decrire"]

NOM = "verrou.json"
MOTIF = "verrou*.json"
TTL_HEURES = 12
CHAMPS_DATE = ("depuis", "activite")


class VerrouOccupe(RuntimeError):
    """Le verrou est tenu par un autre poste, par un autre run, ou il est illisible."""

    def __init__(self, message: str, occupants: list[dict[str, Any]] | None = None) -> None:
        super().__init__(message)
        self.occupants = occupants or []


# --- lecture ---------------------------------------------------------------------------------

def etats(dossier: str) -> list[dict[str, Any]]:
    """Lit tous les `verrou*.json` du dossier, copies en conflit comprises.

    Chaque état porte en plus `fichier` (le nom du fichier lu). Un état illisible vaut
    `{"etat": "pris", "poste": "?", "corrompu": True}`. `verrou.json` vient en premier.
    """
    noms = sorted(
        (n for n in os.listdir(dossier) if fnmatch.fnmatchcase(n.lower(), MOTIF)),
        key=lambda n: (n.lower() != NOM, n),
    )
    return [_lire(os.path.join(dossier, n)) for n in noms]


def _lire(chemin: str) -> dict[str, Any]:
    corrompu = {"etat": "pris", "poste": "?", "corrompu": True, "fichier": os.path.basename(chemin)}
    try:
        # utf-8-sig : un verrou réenregistré par le Bloc-notes porte un BOM
        with open(chemin, encoding="utf-8-sig") as fh:
            d = json.load(fh)
    except (OSError, ValueError):  # absent hors connexion, JSON ou encodage invalides
        return corrompu
    try:
        if d["etat"] not in ("pris", "libre"):
            raise ValueError(d["etat"])
        for k in CHAMPS_DATE:
            _date(d[k])
    except (ValueError, TypeError, KeyError):
        return corrompu
    return {**d, "fichier": os.path.basename(chemin)}


def _date(valeur: Any) -> datetime:
    """Date ISO avec fuseau. Lève ValueError sans fuseau, TypeError si ce n'est pas un texte."""
    if not isinstance(valeur, str):
        raise TypeError(f"date attendue en texte ISO : {valeur!r}")
    # « Z » n'est compris par fromisoformat qu'à partir de Python 3.11
    t = valeur[:-1] + "+00:00" if valeur.endswith("Z") else valeur
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError(f"date sans fuseau : {valeur!r}")
    return dt


def _maintenant() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def _poste() -> str:
    return socket.gethostname()


def _utilisateur() -> str:
    try:
        return getpass.getuser() or "?"
    except Exception:  # pas de compte lisible (OSError, KeyError, ImportError selon la plateforme)
        return "?"


# --- classement ------------------------------------------------------------------------------

def _classer(
    lus: list[dict[str, Any]], poste: str, run: str, ttl_heures: float, maintenant: datetime
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Répartit les états lus en (bloquants, expirés, nôtres). Les états libres sont ignorés."""
    bloquants, expires, notres = [], [], []
    ttl = timedelta(hours=ttl_heures)
    for e in lus:
        if e.get("corrompu"):
            bloquants.append(e)
        elif e["etat"] == "libre":
            continue
        elif e.get("poste") == poste and e.get("run") == run:
            notres.append(e)
        elif maintenant - _date(e["activite"]) > ttl:
            expires.append(e)
        else:
            bloquants.append(e)
    return bloquants, expires, notres


def occupants(dossier: str, run: str, ttl_heures: float = TTL_HEURES) -> list[dict[str, Any]]:
    """États qui empêchent CE poste de prendre le verrou pour `run`, sans rien écrire.

    Pris par un autre poste ou par un autre run de ce poste, non expiré, ou illisible.
    """
    return _classer(etats(dossier), _poste(), run, ttl_heures, _maintenant())[0]


def _anciennete(e: dict[str, Any], maintenant: datetime) -> str:
    try:
        delta = maintenant - _date(e["activite"])
    except (ValueError, TypeError, KeyError):
        return "inconnue"
    minutes = max(0, int(delta.total_seconds() // 60))  # horloge d'un autre PC en avance : 0
    j, reste = divmod(minutes, 24 * 60)
    h, m = divmod(reste, 60)
    if j:
        return f"il y a {j} j {h} h"
    if h:
        return f"il y a {h} h {m:02d}"
    return f"il y a {m} min"


def decrire(e: dict[str, Any], maintenant: datetime | None = None) -> str:
    """Une ligne lisible pour un état : poste, run, ancienneté de l'activité, fichier.

    Jamais l'utilisateur : la ligne peut finir dans une capture ou un message.
    """
    maintenant = maintenant or _maintenant()
    fichier = e.get("fichier", NOM)
    if e.get("corrompu"):
        return f"verrou illisible ou invalide ({fichier}) : considéré comme occupé"
    return (
        f"{e.get('etat')} — poste {e.get('poste') or '?'}, run {e.get('run') or '?'}, "
        f"dernière activité {_anciennete(e, maintenant)} ({fichier})"
    )


# --- écriture --------------------------------------------------------------------------------

def _ecrire(dossier: str, contenu: dict[str, Any], nom: str = NOM) -> None:
    """Écriture atomique : `<nom>.tmp` dans le même dossier, puis `os.replace`."""
    cible = os.path.join(dossier, nom)
    tmp = cible + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(contenu, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, cible)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def _pierre_tombale(poste: str, run: str, maintenant: datetime, commande: str) -> dict[str, Any]:
    return {
        "etat": "libre", "poste": poste, "utilisateur": _utilisateur(), "run": run,
        "depuis": _iso(maintenant), "activite": _iso(maintenant), "commande": commande,
    }


def prendre(
    dossier: str, run: str, commande: str, ttl_heures: float = TTL_HEURES, forcer: bool = False
) -> dict[str, Any]:
    """Prend le verrou pour `run` à ce poste, ou le rafraîchit s'il est déjà le nôtre.

    Libre, expiré (`activite` plus vieille que le TTL) ou tenu par ce poste pour ce même run :
    on écrit `pris` et on rafraîchit `activite`. Sinon `VerrouOccupe`, sauf `forcer`.
    Renvoie le contenu écrit.

    Les copies en conflit dépassées (expirées, ou forcées) reçoivent une pierre tombale : sinon
    elles avertiraient à chaque prise, et `liberer` les refuserait en fin de run.
    """
    poste, maintenant = _poste(), _maintenant()
    bloquants, expires, notres = _classer(etats(dossier), poste, run, ttl_heures, maintenant)
    if bloquants and not forcer:
        lignes = "\n".join(f"  {decrire(e, maintenant)}" for e in bloquants)
        raise VerrouOccupe(
            "verrou occupé : un autre run est en cours, ou le verrou est illisible.\n"
            f"{lignes}\n"
            "Attendre la fin de ce run (et que le Drive soit à jour). S'il est abandonné : "
            "`python -m prospection.run verrou liberer --forcer`, ou relancer avec --forcer.",
            bloquants,
        )
    for e in expires:
        print(f"AVERTISSEMENT : verrou expiré (TTL {ttl_heures:g} h) repris : {decrire(e, maintenant)}",
              file=sys.stderr)
    for e in bloquants:
        print(f"AVERTISSEMENT : verrou forcé : {decrire(e, maintenant)}", file=sys.stderr)
    # un rafraîchissement garde la date de prise du verrou ; une prise neuve la remet à zéro
    depuis = next((e["depuis"] for e in notres), None) or _iso(maintenant)
    contenu = {
        "etat": "pris", "poste": poste, "utilisateur": _utilisateur(), "run": run,
        "depuis": depuis, "activite": _iso(maintenant), "commande": commande,
    }
    _ecrire(dossier, contenu)
    for e in expires + bloquants:
        if e["fichier"].lower() != NOM:
            _ecrire(dossier, _pierre_tombale(poste, e.get("run") or run, maintenant, "prendre"),
                    nom=e["fichier"])
    return contenu


def liberer(dossier: str, run: str | None = None, forcer: bool = False) -> list[str]:
    """Passe en `libre` le verrou et ses copies de conflit tenus par CE poste.

    Avec `run`, seuls les verrous de ce run sont les nôtres. Un verrou pris par un autre poste
    (ou par un autre run, ou illisible) lève `VerrouOccupe` sans rien écrire, sauf `forcer`.
    Renvoie les noms des fichiers réécrits (vide si rien n'était pris).
    """
    poste, maintenant = _poste(), _maintenant()
    a_liberer, etrangers = [], []
    for e in etats(dossier):
        if not e.get("corrompu") and e["etat"] == "libre":
            continue
        if not e.get("corrompu") and e.get("poste") == poste and run in (None, e.get("run")):
            a_liberer.append(e)
        else:
            etrangers.append(e)
    if etrangers and not forcer:
        lignes = "\n".join(f"  {decrire(e, maintenant)}" for e in etrangers)
        raise VerrouOccupe(
            "verrou tenu par un autre poste ou un autre run : rien n'est libéré.\n"
            f"{lignes}\n"
            "S'il est abandonné : `python -m prospection.run verrou liberer --forcer`.",
            etrangers,
        )
    for e in etrangers:
        print(f"AVERTISSEMENT : verrou libéré de force : {decrire(e, maintenant)}", file=sys.stderr)
    ecrits = []
    for e in a_liberer + etrangers:
        _ecrire(dossier, _pierre_tombale(poste, e.get("run") or run or "", maintenant, "liberer"),
                nom=e["fichier"])
        ecrits.append(e["fichier"])
    return ecrits
