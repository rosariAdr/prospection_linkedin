"""Tests fonctionnels de `prospection.run` (PL-10, PL-17).

Chaque test tourne dans un faux dépôt créé dans `tmp_path` (config, JSON d'agents et scored_*.json
fictifs) : jamais dans le dépôt réel, jamais sur `data/` ni sur `runs/`.
"""
import csv
import json
import textwrap

import openpyxl
import pytest

from prospection.run import main
from prospection.workbook import COLS

RUN = "01-01-2030"
RECHERCHE = "https://www.linkedin.com/search/results/content/?keywords=formateur%20data"
CONFIG = textwrap.dedent(
    """
    version: 1
    profil: {nom: "Personne Fictive"}
    blacklist:
      organisations: ["Ecole Interdite"]
      en_observation: ["Ecole Surveillee"]
    scoring: {seuil_conservation: 3, seuil_redaction: 5}
    search_plan:
      lots:
        A: ["formateur data", "intervenant data"]
        B: ["formateur python"]
    """
)
TEXTES = ("reponse_commentaire_linkedin", "note_invitation_200", "note_invitation_300",
          "message_linkedin", "reponse_mail")


@pytest.fixture()
def depot(tmp_path, monkeypatch):
    """Faux dépôt : config fictive et dossier de run vide. Le test s'exécute DANS ce dossier."""
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "config.yaml").write_text(CONFIG, encoding="utf-8")
    (tmp_path / "runs" / RUN).mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _slug(auteur):
    return auteur.lower().replace(" ", "-")


def _post(auteur, score=10, **kw):
    """Une ligne scorée fictive, conforme aux garde-fous."""
    p = {
        "post_extrait": f"Annonce fictive de {auteur}",
        "url_post": f"https://www.linkedin.com/posts/{_slug(auteur)}_activity-0000000000000000001/",
        "url_profil_auteur": f"https://www.linkedin.com/in/{_slug(auteur)}/",
        "auteur": auteur, "date": "3 j", "mail": "", "taux_horaire": "à déterminer",
        "localisation": "IDF", "score_pertinence": score, "mot_cle_recherche": "formateur data",
        "batch": "A", "type_opportunite": "annonce directe", "echeance": "S1 2030",
        "deal_breaker": "", "commentaire_scoring": "+4 intention +3 metier +3 zone",
        "cle_contenu": f"cle-{_slug(auteur)}",
        "reponse_commentaire_linkedin": "Votre annonce m'interesse.",
        "note_invitation_200": "Bonjour, formateur data, votre annonce m'interesse.",
        "note_invitation_300": "Bonjour, ingenieur data et formateur, votre annonce m'interesse.",
        "message_linkedin": "Bonjour,\nVotre annonce m'interesse.\nPersonne Fictive",
        "reponse_mail": "",
    }
    if score <= 5:  # sous le seuil de rédaction : aucun texte
        p.update({c: "" for c in TEXTES})
    p.update(kw)
    return p


def _scored(depot, posts, nom="A"):
    chemin = depot / "runs" / RUN / f"scored_{nom}.json"
    chemin.write_text(json.dumps({"posts": posts}, ensure_ascii=False), encoding="utf-8")


def _auteurs_master(depot):
    wb = openpyxl.load_workbook(depot / "data" / f"prospection_{RUN}.xlsx")
    ws = wb["MASTER"]
    cols = [c.value for c in ws[1]]
    return [dict(zip(cols, r)) for r in ws.iter_rows(min_row=2, values_only=True)]


def _lignes_csv(chemin):
    with open(chemin, encoding="utf-8", newline="") as fh:
        return list(csv.reader(fh))


# --- finaliser : F4 -------------------------------------------------------------


def test_f4_ecarte_une_organisation_blacklistee_quel_que_soit_son_score(depot, capsys):
    _scored(depot, [_post("Ecole Alpha"), _post("Ecole Interdite Paris", score=15)])
    assert main(["finaliser", "--run", RUN]) == 0
    assert [p["auteur"] for p in _auteurs_master(depot)] == ["Ecole Alpha"]
    assert "écarté (F4 blacklist) : Ecole Interdite Paris" in capsys.readouterr().out


def test_f4_une_organisation_en_observation_est_signalee_au_commentaire(depot):
    _scored(depot, [_post("Ecole Surveillee")])
    assert main(["finaliser", "--run", RUN]) == 0
    (ligne,) = _auteurs_master(depot)
    assert ligne["commentaire_scoring"].startswith("⚠ organisation EN OBSERVATION (F4)")
    assert ligne["commentaire_scoring"].endswith("+4 intention +3 metier +3 zone")


def test_le_prefixe_en_observation_ne_masque_pas_un_score_non_trace(depot, capsys):
    """L'avertissement F4 est ajouté au commentaire : il ne doit pas tenir lieu de détail du calcul."""
    _scored(depot, [_post("Ecole Surveillee", commentaire_scoring="")])
    assert main(["finaliser", "--run", RUN]) == 2
    assert "commentaire_scoring vide" in capsys.readouterr().err


# --- finaliser : seuil de conservation --------------------------------------------


def test_les_lignes_sous_le_seuil_de_conservation_sont_retirees_du_livrable(depot, capsys):
    _scored(depot, [_post("Ecole Alpha"), _post("Ecole Beta", score=2), _post("Ecole Gamma", score=3)])
    assert main(["finaliser", "--run", RUN]) == 0
    assert sorted(p["auteur"] for p in _auteurs_master(depot)) == ["Ecole Alpha", "Ecole Gamma"]
    assert "1 ligne(s) sous le seuil de conservation" in capsys.readouterr().out


# --- finaliser : garde-fous bloquants ---------------------------------------------


@pytest.mark.parametrize("defaut", [
    {"note_invitation_200": "x" * 250},
    {"url_post": RECHERCHE},
    {"url_post": ""},
    {"commentaire_scoring": ""},
], ids=["note-trop-longue", "url-de-recherche", "permalien-vide", "score-non-trace"])
def test_un_garde_fou_en_echec_renvoie_2_sans_rien_ecrire(depot, capsys, defaut):
    _scored(depot, [_post("Ecole Alpha", **defaut)])
    assert main(["finaliser", "--run", RUN]) == 2
    assert "GARDE-FOUS EN ÉCHEC" in capsys.readouterr().err
    assert list((depot / "data").iterdir()) == [depot / "data" / "config.yaml"]


# --- finaliser : archive CSV ------------------------------------------------------


def test_les_csv_d_archive_sont_exportes(depot):
    _scored(depot, [_post("Ecole Alpha"), _post("Ecole Beta", score=4)])
    assert main(["finaliser", "--run", RUN]) == 0
    master = _lignes_csv(depot / "data" / "MASTER.csv")
    delta = _lignes_csv(depot / "data" / f"DELTA_{RUN}.csv")
    leads = _lignes_csv(depot / "data" / "SUIVI_LEADS.csv")
    assert master[0] == COLS and delta[0] == COLS
    assert sorted(r[COLS.index("auteur")] for r in master[1:]) == ["Ecole Alpha", "Ecole Beta"]
    assert len(delta) == 3
    assert [r[1] for r in leads[1:]] == ["Ecole Alpha"]  # seul le lead rédigé entre au suivi


def test_relancer_finaliser_reecrit_les_csv_sans_les_dupliquer(depot):
    _scored(depot, [_post("Ecole Alpha")])
    base = str(depot / "data" / f"prospection_{RUN}.xlsx")
    assert main(["finaliser", "--run", RUN]) == 0
    assert main(["finaliser", "--run", RUN, "--base", base]) == 0
    master = _lignes_csv(depot / "data" / "MASTER.csv")
    assert len(master) == 2 and master[0] == COLS


def test_sans_csv_n_exporte_aucun_csv(depot):
    _scored(depot, [_post("Ecole Alpha")])
    assert main(["finaliser", "--run", RUN, "--sans-csv"]) == 0
    assert (depot / "data" / f"prospection_{RUN}.xlsx").exists()
    assert sorted(p.name for p in (depot / "data").glob("*.csv")) == []


# --- prepare : reprise d'un run interrompu (PL-17) --------------------------------


def _candidat(auteur, mot_cle):
    return {"mot_cle": mot_cle, "auteur": auteur, "profil": "",
            "url_post": f"https://www.linkedin.com/posts/{_slug(auteur)}_activity-0000000000000000002/",
            "date_rel": "3 j", "texte": f"{auteur} recherche un formateur ({mot_cle}), annonce fictive."}


def _lot(depot, nom, traites, non_traites, candidats):
    d = {"batch": nom, "date_run": "2030-01-01", "filtre": "past-week",
         "mots_cles_traites": traites, "mots_cles_non_traites": non_traites,
         "nb_candidats": len(candidats), "candidats": candidats, "rejetes": []}
    (depot / "runs" / RUN / f"{nom}.json").write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")


def _rapport(depot):
    return json.loads((depot / "runs" / RUN / "rapport_prepare.json").read_text(encoding="utf-8"))


def test_prepare_signale_un_run_incomplet(depot, capsys):
    _lot(depot, "A", ["formateur data"], ["intervenant data", "formateur python"],
         [_candidat("Ecole Alpha", "formateur data")])
    assert main(["prepare", "--run", RUN]) == 0
    rap = _rapport(depot)
    assert rap["run_incomplet"] is True
    assert rap["mots_cles_non_traites"] == ["intervenant data", "formateur python"]
    assert "RUN INCOMPLET" in capsys.readouterr().err


def test_un_mot_cle_non_traite_n_est_pas_compte_sans_resultat(depot):
    """Le bug : un mot-clé jamais cherché passait pour stérile, et la doc invite à le retirer."""
    _lot(depot, "A", ["formateur data", "intervenant data"], ["formateur python"],
         [_candidat("Ecole Alpha", "formateur data")])
    assert main(["prepare", "--run", RUN]) == 0
    assert _rapport(depot)["mots_cles_sans_resultat"] == ["intervenant data"]


def test_une_reprise_dans_un_second_lot_complete_le_run(depot, capsys):
    _lot(depot, "A", ["formateur data"], ["intervenant data", "formateur python"],
         [_candidat("Ecole Alpha", "formateur data")])
    _lot(depot, "A2", ["intervenant data", "formateur python"], [],
         [_candidat("Ecole Beta", "formateur python")])
    assert main(["prepare", "--run", RUN]) == 0
    rap = _rapport(depot)
    assert rap["run_incomplet"] is False
    assert rap["mots_cles_non_traites"] == []
    assert rap["mots_cles_sans_resultat"] == ["intervenant data"]
    assert "RUN INCOMPLET" not in capsys.readouterr().err


def test_un_mot_cle_non_traite_ecrit_avec_une_autre_casse_est_reconnu(depot):
    _lot(depot, "A", ["formateur data", "intervenant data"], ["Formateur Python"],
         [_candidat("Ecole Alpha", "formateur data")])
    assert main(["prepare", "--run", RUN]) == 0
    rap = _rapport(depot)
    assert rap["mots_cles_sans_resultat"] == ["intervenant data"]
    assert rap["run_incomplet"] is True


def test_une_reprise_avec_une_autre_casse_complete_le_run(depot):
    _lot(depot, "A", ["formateur data"], ["intervenant data", "formateur python"],
         [_candidat("Ecole Alpha", "formateur data")])
    _lot(depot, "A2", ["Intervenant Data", "Formateur Python"], [], [])
    assert main(["prepare", "--run", RUN]) == 0
    assert _rapport(depot)["mots_cles_non_traites"] == []


def test_un_mot_cle_productif_ecrit_avec_une_autre_casse_n_est_pas_sans_resultat(depot):
    _lot(depot, "A", ["formateur data", "intervenant data", "formateur python"], [],
         [_candidat("Ecole Alpha", "Intervenant Data")])
    assert main(["prepare", "--run", RUN]) == 0
    assert _rapport(depot)["mots_cles_sans_resultat"] == ["formateur data", "formateur python"]


def test_un_mot_cle_non_traite_ecrit_comme_texte_et_non_comme_liste(depot):
    """Un agent qui écrit une chaîne au lieu d'une liste ne doit pas produire une liste de lettres."""
    _lot(depot, "A", ["formateur data", "intervenant data"], "formateur python",
         [_candidat("Ecole Alpha", "formateur data")])
    assert main(["prepare", "--run", RUN]) == 0
    rap = _rapport(depot)
    assert rap["mots_cles_non_traites"] == ["formateur python"]
    assert rap["mots_cles_sans_resultat"] == ["intervenant data"]
