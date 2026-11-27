"""Tests de `prospection.verrou` (mode partagé) : prise, refus, expiration, pierre tombale.

Les « postes » sont simulés par un monkeypatch de `socket.gethostname`, le compte par celui de
`getpass.getuser`. Tout se passe dans `tmp_path`. Le cas `prepare` sous verrou étranger (code 3)
passe par la ligne de commande : il est testé avec les sous-commandes.
"""
import getpass
import json
import os
import socket
from datetime import datetime, timedelta, timezone

import pytest

from prospection.verrou import VerrouOccupe, _date, etats, liberer, occupants, prendre

RUN = "01-01-2030"
AUTRE_RUN = "02-01-2030"
COMPTE = "compte-fictif-a"


@pytest.fixture()
def poste(monkeypatch):
    """Poste courant « PC-A » ; `poste("PC-B")` simule un autre PC."""
    monkeypatch.setattr(getpass, "getuser", lambda: COMPTE)

    def changer(nom):
        monkeypatch.setattr(socket, "gethostname", lambda: nom)

    changer("PC-A")
    return changer


def _iso(heures_avant=0.0):
    return (datetime.now(timezone.utc) - timedelta(hours=heures_avant)).isoformat(timespec="seconds")


def _poser(dossier, nom="verrou.json", **kw):
    """Écrit un verrou à la main : par défaut pris par PC-B pour RUN, actif il y a une heure."""
    e = {"etat": "pris", "poste": "PC-B", "utilisateur": "compte-fictif-b", "run": RUN,
         "depuis": _iso(1), "activite": _iso(1), "commande": "prepare"}
    e.update(kw)
    (dossier / nom).write_text(json.dumps(e), encoding="utf-8")
    return e


def _lire(dossier, nom="verrou.json"):
    return json.loads((dossier / nom).read_text(encoding="utf-8"))


# --- prise ---------------------------------------------------------------------------------------

def test_prise_sur_un_dossier_sans_verrou(tmp_path, poste):
    c = prendre(str(tmp_path), RUN, "prepare")
    assert _lire(tmp_path) == c
    assert (c["etat"], c["poste"], c["utilisateur"], c["run"], c["commande"]) == (
        "pris", "PC-A", COMPTE, RUN, "prepare"
    )
    assert c["depuis"] == c["activite"] and c["activite"].endswith("+00:00")
    assert _date(c["activite"]).utcoffset() == timedelta(0)
    # écriture atomique : le temporaire a été renommé, pas laissé à côté
    assert not (tmp_path / "verrou.json.tmp").exists()


def test_refus_pour_un_autre_poste_sans_rien_ecrire(tmp_path, poste):
    prendre(str(tmp_path), RUN, "prepare")
    avant = _lire(tmp_path)
    poste("PC-B")
    with pytest.raises(VerrouOccupe) as exc:
        prendre(str(tmp_path), RUN, "prepare")
    message = str(exc.value)
    assert "PC-A" in message and RUN in message and "il y a" in message
    # poste, run et ancienneté, mais jamais le compte de la personne
    assert COMPTE not in message
    assert exc.value.occupants and exc.value.occupants[0]["poste"] == "PC-A"
    assert _lire(tmp_path) == avant


def test_meme_poste_autre_run_refuse(tmp_path, poste):
    prendre(str(tmp_path), RUN, "prepare")
    with pytest.raises(VerrouOccupe, match=RUN):
        prendre(str(tmp_path), AUTRE_RUN, "prepare")
    assert _lire(tmp_path)["run"] == RUN


def test_rafraichissement_garde_depuis_et_avance_activite(tmp_path, poste):
    ancien = _poser(tmp_path, poste="PC-A", depuis=_iso(5), activite=_iso(5))
    c = prendre(str(tmp_path), RUN, "finaliser")
    assert c["depuis"] == ancien["depuis"]
    assert _date(c["activite"]) > _date(ancien["activite"])
    assert c["commande"] == "finaliser"


def test_verrou_expire_repris_avec_avertissement(tmp_path, poste, capsys):
    ancien = _poser(tmp_path, depuis=_iso(13), activite=_iso(13))
    c = prendre(str(tmp_path), RUN, "prepare")
    assert c["poste"] == "PC-A" and c["depuis"] != ancien["depuis"]
    err = capsys.readouterr().err
    assert "expiré" in err and "PC-B" in err


def test_le_ttl_est_parametrable(tmp_path, poste):
    _poser(tmp_path, activite=_iso(13))
    with pytest.raises(VerrouOccupe):
        prendre(str(tmp_path), RUN, "prepare", ttl_heures=24)
    _poser(tmp_path, activite=_iso(11))
    with pytest.raises(VerrouOccupe):
        prendre(str(tmp_path), RUN, "prepare")


@pytest.mark.parametrize(
    "contenu",
    [
        "{pas du json",
        "[]",
        "",
        json.dumps({"etat": "pris", "poste": "PC-B", "run": RUN, "depuis": "2030-01-01T10:00:00",
                    "activite": "2030-01-01T10:00:00"}),  # sans fuseau
        json.dumps({"etat": "pris", "poste": "PC-B", "run": RUN, "depuis": "2030-01-01T10:00:00+00:00"}),
        json.dumps({"etat": "libre", "poste": "PC-B", "depuis": "hier", "activite": "hier"}),
        json.dumps({"etat": "libre", "poste": "PC-B", "depuis": 12, "activite": 12}),
        json.dumps({"etat": "inconnu", "poste": "PC-B", "depuis": "2030-01-01T10:00:00+00:00",
                    "activite": "2030-01-01T10:00:00+00:00"}),
    ],
    ids=["json-invalide", "liste", "vide", "sans-fuseau", "sans-activite", "date-invalide",
         "date-nombre", "etat-inconnu"],
)
def test_verrou_corrompu_compte_comme_occupe(tmp_path, poste, contenu):
    (tmp_path / "verrou.json").write_text(contenu, encoding="utf-8")
    assert etats(str(tmp_path)) == [
        {"etat": "pris", "poste": "?", "corrompu": True, "fichier": "verrou.json"}
    ]
    with pytest.raises(VerrouOccupe, match="illisible"):
        prendre(str(tmp_path), RUN, "prepare")


def test_une_date_en_z_est_comprise_sous_toutes_les_versions():
    assert _date("2030-01-01T10:00:00Z") == datetime(2030, 1, 1, 10, tzinfo=timezone.utc)


def test_copie_en_conflit_tenue_par_un_autre_poste(tmp_path, poste):
    _poser(tmp_path, etat="libre", poste="PC-A")
    _poser(tmp_path, "verrou (1).json")
    with pytest.raises(VerrouOccupe, match=r"verrou \(1\)\.json"):
        prendre(str(tmp_path), RUN, "prepare")


def test_un_temporaire_abandonne_n_est_pas_un_verrou(tmp_path, poste):
    (tmp_path / "verrou.json.tmp").write_text("{pas du json", encoding="utf-8")
    assert etats(str(tmp_path)) == []
    prendre(str(tmp_path), RUN, "prepare")


def test_occupants_ne_change_rien(tmp_path, poste):
    _poser(tmp_path)
    avant = (tmp_path / "verrou.json").read_text(encoding="utf-8")
    assert [e["poste"] for e in occupants(str(tmp_path), RUN)] == ["PC-B"]
    assert (tmp_path / "verrou.json").read_text(encoding="utf-8") == avant
    poste("PC-B")
    assert occupants(str(tmp_path), RUN) == []


def test_prise_sur_expire_neutralise_la_copie_en_conflit(tmp_path, poste):
    # une copie expirée d'un autre poste reçoit une pierre tombale : sinon `liberer` la
    # refuserait en fin de run
    _poser(tmp_path, "verrou (1).json", activite=_iso(13))
    prendre(str(tmp_path), RUN, "prepare")
    assert _lire(tmp_path, "verrou (1).json")["etat"] == "libre"
    assert sorted(liberer(str(tmp_path), RUN)) == ["verrou.json"]


def test_echec_d_ecriture_nettoie_le_temporaire(tmp_path, poste, monkeypatch):
    avant = _poser(tmp_path, etat="libre", poste="PC-A")

    def refus(*_):
        raise PermissionError("fichier verrouillé par la synchronisation")

    monkeypatch.setattr(os, "replace", refus)
    with pytest.raises(PermissionError):
        prendre(str(tmp_path), RUN, "prepare")
    assert not (tmp_path / "verrou.json.tmp").exists()
    assert _lire(tmp_path) == avant


# --- libération ----------------------------------------------------------------------------------

def test_liberer_ecrit_une_pierre_tombale(tmp_path, poste):
    prendre(str(tmp_path), RUN, "prepare")
    assert liberer(str(tmp_path), RUN) == ["verrou.json"]
    # réécrit, pas supprimé : sur un Drive, un fichier supprimé peut revenir
    assert (tmp_path / "verrou.json").exists()
    e = _lire(tmp_path)
    assert e["etat"] == "libre" and e["run"] == RUN and e["commande"] == "liberer"
    poste("PC-B")
    assert prendre(str(tmp_path), AUTRE_RUN, "prepare")["poste"] == "PC-B"


def test_liberer_passe_aussi_les_copies_de_ce_poste_en_libre(tmp_path, poste):
    _poser(tmp_path, poste="PC-A")
    _poser(tmp_path, "verrou (1).json", poste="PC-A")
    assert sorted(liberer(str(tmp_path))) == ["verrou (1).json", "verrou.json"]
    assert {e["etat"] for e in etats(str(tmp_path))} == {"libre"}


def test_liberer_sans_verrou_ne_fait_rien(tmp_path, poste):
    assert liberer(str(tmp_path)) == []
    assert etats(str(tmp_path)) == []


def test_refus_de_liberer_le_verrou_d_un_autre(tmp_path, poste):
    prendre(str(tmp_path), RUN, "prepare")
    avant = _lire(tmp_path)
    poste("PC-B")
    with pytest.raises(VerrouOccupe, match="PC-A"):
        liberer(str(tmp_path), RUN)
    assert _lire(tmp_path) == avant


def test_refus_de_liberer_un_autre_run_de_ce_poste(tmp_path, poste):
    prendre(str(tmp_path), RUN, "prepare")
    with pytest.raises(VerrouOccupe):
        liberer(str(tmp_path), AUTRE_RUN)
    assert _lire(tmp_path)["etat"] == "pris"


def test_liberer_est_tout_ou_rien(tmp_path, poste):
    # notre verrou et une copie d'un autre poste : rien n'est libéré, pas même le nôtre
    _poser(tmp_path, poste="PC-A")
    _poser(tmp_path, "verrou (1).json")
    with pytest.raises(VerrouOccupe):
        liberer(str(tmp_path), RUN)
    assert _lire(tmp_path)["etat"] == "pris"


# --- forcer --------------------------------------------------------------------------------------

def test_forcer_la_prise(tmp_path, poste, capsys):
    _poser(tmp_path)
    c = prendre(str(tmp_path), RUN, "prepare", forcer=True)
    assert c["poste"] == "PC-A" and _lire(tmp_path)["poste"] == "PC-A"
    assert "forcé" in capsys.readouterr().err


def test_forcer_la_prise_sur_un_verrou_corrompu(tmp_path, poste):
    (tmp_path / "verrou.json").write_text("{pas du json", encoding="utf-8")
    assert prendre(str(tmp_path), RUN, "prepare", forcer=True)["poste"] == "PC-A"
    assert etats(str(tmp_path))[0]["etat"] == "pris"


def test_forcer_la_liberation(tmp_path, poste, capsys):
    _poser(tmp_path)
    assert liberer(str(tmp_path), RUN, forcer=True) == ["verrou.json"]
    assert _lire(tmp_path)["etat"] == "libre"
    assert "de force" in capsys.readouterr().err
