"""Historique en mode partagé : lecture des CSV (BOM, format reconnu, fichiers de travail) et
réinjection au MASTER des lignes des runs antérieurs (`construire(anterieurs=…)`).

Tout se passe dans `tmp_path`, avec des données fictives : jamais `data/`, jamais `runs/`.
"""
import csv
import json

import openpyxl
import pytest

from prospection.cles import norm
from prospection.dedup import Historique, est_csv_historique, nom_ignore
from prospection.workbook import (
    COLS, COLS_LEADS, cles_identite, construire, lire_historique_csv, run_du_fichier,
)

R1, R2, R3 = "01-01-2030", "08-01-2030", "15-01-2030"
RECHERCHE = "https://www.linkedin.com/search/results/content/?keywords=formateur%20data"
COLS_SANS_CLE = [c for c in COLS if c != "cle_contenu"]  # DELTA d'avant la colonne cle_contenu
TEXTES = {
    "reponse_commentaire_linkedin": "Votre annonce m'interesse.",
    "note_invitation_200": "Bonjour, formateur data, votre annonce m'interesse.",
    "note_invitation_300": "Bonjour, ingenieur data et formateur, votre annonce m'interesse.",
    "message_linkedin": "Bonjour,\nVotre annonce m'interesse.\nPersonne Fictive",
}


def _post(auteur, score=4, **kw):
    """Une ligne scorée fictive, conforme aux garde-fous (sous le seuil : aucun texte)."""
    p = {c: "" for c in COLS}
    p.update({
        "post_extrait": f"Annonce fictive de {auteur}",
        "url_post": f"https://lnkd.in/p/{norm(auteur)}1",
        "url_profil_auteur": f"https://www.linkedin.com/in/{norm(auteur)}/",
        "auteur": auteur, "date": "3 j", "score_pertinence": score,
        "commentaire_scoring": "+2 intention +2 metier", "cle_contenu": f"cle-{norm(auteur)}",
    })
    p.update(kw)
    return p


def _ecrire_csv(chemin, cols, lignes, encoding="utf-8"):
    chemin.parent.mkdir(parents=True, exist_ok=True)
    with open(chemin, "w", newline="", encoding=encoding) as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for ligne in lignes:
            w.writerow([ligne.get(c, "") for c in cols])
    return chemin


def _delta(tmp_path, run, lignes, cols=COLS):
    """CSV d'historique `historique/DELTA_<run>.csv`, tel que `finaliser` l'exporte."""
    return _ecrire_csv(tmp_path / "historique" / f"DELTA_{run}.csv", cols, lignes)


def _master(chemin):
    ws = openpyxl.load_workbook(chemin)["MASTER"]
    cols = [c.value for c in ws[1]]
    return [dict(zip(cols, r)) for r in ws.iter_rows(min_row=2, values_only=True)]


def _base(tmp_path, posts, run=R1):
    """Classeur de base produit par un run local ordinaire."""
    chemin = str(tmp_path / f"prospection_{run}.xlsx")
    construire(posts, run=run, sortie=chemin)
    return chemin


# --- lecture des CSV : BOM ----------------------------------------------------------


@pytest.mark.parametrize("stricte", [True, False], ids=["partage", "local"])
def test_un_bom_devant_cle_contenu_ne_masque_pas_la_cle(tmp_path, stricte):
    """Un CSV réenregistré par Excel commence par un BOM : en utf-8 simple, la première colonne
    s'appellerait « \\ufeffcle_contenu » et la clé serait perdue."""
    f = _ecrire_csv(tmp_path / "DELTA_X.csv", ["cle_contenu", "auteur", "url_post", "post_extrait"],
                    [{"cle_contenu": "cle-alpha", "auteur": "Ecole Alpha",
                      "url_post": "https://lnkd.in/p/aaa", "post_extrait": "Annonce"}],
                    encoding="utf-8-sig")
    h = Historique()
    assert h.ajouter_csv(str(f), stricte=stricte) == 1
    assert "cle-alpha" in h.contenus


def test_un_bom_devant_auteur_ne_fait_pas_ignorer_le_fichier(tmp_path):
    f = _ecrire_csv(tmp_path / "DELTA_X.csv", ["auteur", "post_extrait", "url_post", "cle_contenu"],
                    [{"auteur": "Ecole Alpha", "post_extrait": "Annonce",
                      "url_post": "https://lnkd.in/p/aaa", "cle_contenu": "cle-alpha"}],
                    encoding="utf-8-sig")
    h = Historique()
    assert h.ajouter_csv(str(f), stricte=True) == 1
    assert h.ignores == []
    assert norm("Ecole Alpha") in h.auteurs
    assert est_csv_historique(str(f)) is True
    lignes = lire_historique_csv(str(f))
    assert lignes is not None
    assert [x["auteur"] for x in lignes] == ["Ecole Alpha"]


# --- lecture des CSV : format reconnu -----------------------------------------------


def _suivi_leads(tmp_path):
    return _ecrire_csv(tmp_path / "SUIVI_LEADS.csv", COLS_LEADS, [{
        "lead": "Ecole Alpha [R]", "organisation": "Ecole Alpha", "statut_lead": "Contacté",
        "url_post": "https://www.linkedin.com/posts/ecole-alpha_activity-1/",
    }])


def test_un_export_suivi_leads_est_ignore_et_liste_en_lecture_stricte(tmp_path):
    f = _suivi_leads(tmp_path)
    h = Historique()
    assert h.ajouter_csv(str(f), stricte=True) == 0
    assert "https://www.linkedin.com/posts/ecole-alpha_activity-1" not in h.urls
    assert h.ignores == [str(f)]
    assert est_csv_historique(str(f)) is False
    assert lire_historique_csv(str(f)) is None


def test_en_mode_local_suivi_leads_est_lu_comme_avant(tmp_path):
    """Mode local inchangé : sans lecture stricte, SUIVI_LEADS apporte toujours ses URL."""
    f = _suivi_leads(tmp_path)
    h = Historique()
    assert h.ajouter_csv(str(f)) == 1
    assert "https://www.linkedin.com/posts/ecole-alpha_activity-1" in h.urls
    assert h.ignores == []


# --- lecture : fichiers de travail ----------------------------------------------------


@pytest.mark.parametrize("stricte", [True, False], ids=["partage", "local"])
@pytest.mark.parametrize("nom", ["~$MASTER.csv", f"DELTA_{R1}.csv.tmp"])
def test_les_fichiers_de_travail_ne_sont_jamais_lus(tmp_path, nom, stricte):
    f = _ecrire_csv(tmp_path / nom, COLS, [_post("Ecole Fantome", cle_contenu="cle-fantome")])
    assert nom_ignore(str(f))
    h = Historique()
    assert h.ajouter_csv(str(f), stricte=stricte) == 0
    assert "cle-fantome" not in h.contenus
    assert h.ignores == [str(f)]
    assert lire_historique_csv(str(f)) is None
    assert est_csv_historique(str(f)) is False


def test_un_classeur_ouvert_dans_excel_ne_fait_pas_echouer_la_lecture(tmp_path):
    """Excel dépose `~$<classeur>` à côté d'un classeur ouvert : ce n'est pas un classeur."""
    f = tmp_path / f"~$prospection_{R1}.xlsx"
    f.write_bytes(b"\x04anon" + b" " * 50)  # contenu d'un verrou d'Excel : pas un zip
    h = Historique()
    assert h.ajouter_xlsx(str(f)) == 0
    assert h.ignores == [str(f)]


def test_un_json_inacheve_n_est_pas_lu(tmp_path):
    f = tmp_path / "A.json.tmp"
    f.write_text(json.dumps({"candidats": [{"auteur": "Ecole Fantome", "texte": "x"}]}),
                 encoding="utf-8")
    h = Historique()
    assert h.ajouter_run(str(f)) == 0
    assert h.contenus == set()
    assert (h.cles_json, h.json_lus, h.ignores) == (0, 0, [str(f)])


def test_un_fichier_illisible_leve_son_exception(tmp_path):
    """Jamais de repli silencieux : l'appelant doit pouvoir bloquer en nommant le fichier."""
    f = tmp_path / "DELTA_X.csv"
    f.write_bytes("auteur,post_extrait\nÉcole Alpha,Annonce\n".encode("latin-1"))
    with pytest.raises(UnicodeDecodeError):
        Historique().ajouter_csv(str(f), stricte=True)
    with pytest.raises(UnicodeDecodeError):
        lire_historique_csv(str(f))


# --- clés recalculées depuis des JSON bruts ---------------------------------------------


def test_les_cles_recalculees_depuis_des_json_bruts_sont_comptees_a_part(tmp_path):
    delta = _delta(tmp_path, R1, [_post("Ecole Alpha")])
    lot = tmp_path / "runs" / R1 / "A.json"
    lot.parent.mkdir(parents=True)
    lot.write_text(json.dumps({"candidats": [
        {"auteur": "Ecole Beta", "texte": "Recherche un formateur Python, annonce fictive.",
         "url_post": "https://lnkd.in/p/bbb"},
        {"auteur": "Ecole Gamma", "texte": "Recherche un intervenant SQL, annonce fictive.",
         "url_post": "https://lnkd.in/p/ccc"},
    ]}), encoding="utf-8")
    h = Historique()
    h.ajouter_csv(str(delta), stricte=True)
    assert (h.cles_json, h.json_lus) == (0, 0)
    assert h.ajouter_run(str(lot)) == 2
    h.ajouter_run(str(tmp_path / "runs" / R1 / "absent.json"))
    assert (h.cles_json, h.json_lus) == (2, 1)
    assert len(h.contenus) == 3


# --- identité d'une ligne du MASTER ---------------------------------------------------


def test_une_cle_vide_n_identifie_jamais_rien():
    vide = {"cle_contenu": "", "url_post": "", "auteur": "", "post_extrait": ""}
    assert cles_identite(vide) == set()
    assert cles_identite({**vide, "auteur": "Ecole Alpha"}) == set()
    assert cles_identite({**vide, "post_extrait": "Annonce fictive"}) == set()
    assert cles_identite({**vide, "url_post": "?"}) == set()


def test_une_url_de_recherche_n_identifie_pas_une_ligne():
    assert cles_identite({"url_post": RECHERCHE}) == set()


def test_un_permalien_suivi_d_une_query_search_results_identifie_sa_ligne():
    """Seul le chemin compte : `?trk=search/results` derrière un permalien n'en fait pas une
    URL de recherche."""
    url = "https://www.linkedin.com/posts/org-un_activity-0000000000000000001/?trk=search/results"
    for secours in (True, False):
        assert cles_identite({"url_post": url}, secours=secours) == {
            ("url", "https://www.linkedin.com/posts/org-un_activity-0000000000000000001")}


def test_la_cle_de_secours_demande_l_auteur_et_l_extrait_et_le_mode_partage():
    ligne = {"cle_contenu": "cle-alpha", "url_post": "https://lnkd.in/p/aaa/",
             "auteur": "Ecole Alpha", "post_extrait": "Annonce fictive"}
    assert cles_identite(ligne) == {
        ("contenu", "cle-alpha"), ("url", "https://lnkd.in/p/aaa"),
        ("secours", "ecolealpha|annoncefictive"),
    }
    assert ("secours", "ecolealpha|annoncefictive") not in cles_identite(ligne, secours=False)


# --- construire(anterieurs=…) -----------------------------------------------------------


def test_sans_anterieurs_les_statistiques_sont_celles_d_avant(tmp_path):
    stats = construire([_post("Ecole Alpha")], run=R1, sortie=str(tmp_path / "p.xlsx"))
    assert "reinjectees" not in stats
    stats = construire([_post("Ecole Alpha")], run=R1, sortie=str(tmp_path / "p.xlsx"),
                       anterieurs=[])
    assert stats["reinjectees"] == 0


def test_la_cle_de_secours_ne_joue_pas_en_mode_local(tmp_path):
    """Mode local : même résultat qu'avant, la clé auteur + extrait n'existe pas."""
    base = _base(tmp_path, [_post("Ecole Alpha")])
    meme_extrait = dict(cle_contenu="cle-autre", url_post="https://lnkd.in/p/zzz")
    stats = construire([_post("Ecole Alpha", **meme_extrait)], run=R2,
                       sortie=str(tmp_path / "local.xlsx"), base=base)
    assert stats["ajoutes_master"] == 1
    stats = construire([_post("Ecole Alpha", **meme_extrait)], run=R2,
                       sortie=str(tmp_path / "partage.xlsx"), base=base, anterieurs=[])
    assert stats["ajoutes_master"] == 0


def test_mode_local_une_url_ecrite_pendant_le_run_ne_masque_pas_la_suivante(tmp_path):
    """Mode local, comme avant : une ligne écrite au MASTER n'ajoute que sa `cle_contenu` aux clés
    connues. Deux annonces du même permalien mais de contenus différents entrent toutes deux."""
    url = "https://www.linkedin.com/posts/ecole-un_activity-0000000000000000001/"
    stats = construire([_post("Ecole Alpha", cle_contenu="k1", url_post=url),
                        _post("Ecole Alpha", cle_contenu="k2", url_post=url,
                              post_extrait="Un second module, SQL")],
                       run=R1, sortie=str(tmp_path / "local.xlsx"))
    assert (stats["ajoutes_master"], stats["master_total"]) == (2, 2)


def test_mode_local_un_permalien_a_query_search_results_reste_une_cle(tmp_path):
    """Mode local, comme avant : la base fournit la `cle_url` de chaque ligne, query comprise. Un
    permalien suivi de `?trk=search/results` n'est pas une URL de recherche : le même post, avec
    une `cle_contenu` d'avant le correctif #3, est reconnu et n'entre pas une seconde fois."""
    permalien = "https://www.linkedin.com/posts/org-un_activity-0000000000000000001/"
    base = _base(tmp_path, [_post("Ecole Alpha", cle_contenu="cle-ancienne", url_post=permalien)])
    wb = openpyxl.load_workbook(base)
    wb["MASTER"].cell(row=2, column=COLS.index("url_post") + 1,
                      value=permalien + "?trk=search/results")
    wb.save(base)
    stats = construire([_post("Ecole Alpha", cle_contenu="cle-nouvelle", url_post=permalien)],
                       run=R2, sortie=str(tmp_path / "local.xlsx"), base=base)
    assert (stats["ajoutes_master"], stats["master_total"]) == (0, 1)


def test_une_base_introuvable_n_est_jamais_remplacee_par_un_classeur_vide(tmp_path):
    """Mode partagé (`anterieurs` fourni) : une base disparue lève FileNotFoundError, rien n'est
    écrit. Le mode local reste celui d'avant : une base absente donne un classeur neuf."""
    absente = str(tmp_path / "absente.xlsx")
    sortie = tmp_path / "p.xlsx"
    with pytest.raises(FileNotFoundError):
        construire([_post("Ecole Alpha")], run=R2, sortie=str(sortie), base=absente,
                   anterieurs=[])
    assert not sortie.exists()
    stats = construire([_post("Ecole Alpha")], run=R2, sortie=str(sortie), base=absente)
    assert stats["master_total"] == 1


def test_en_mode_local_l_onglet_delta_est_recree_comme_avant(tmp_path):
    """Invariance du mode local : refinaliser avec `--base` sur le classeur du run recrée l'onglet
    DELTA à vide, comme avant. Le report des labels du DELTA est propre au mode partagé."""
    base = _base(tmp_path, [_post("Ecole Alpha")])
    wb = openpyxl.load_workbook(base)
    wb[f"DELTA_{R1}"].cell(row=2, column=COLS.index("validation") + 1, value="NON")
    wb.save(base)
    sortie = str(tmp_path / "relance.xlsx")
    construire([_post("Ecole Alpha")], run=R1, sortie=sortie, base=base)
    ws = openpyxl.load_workbook(sortie)[f"DELTA_{R1}"]
    assert [r[COLS.index("validation")] for r in ws.iter_rows(min_row=2, values_only=True)] == [None]
    construire([_post("Ecole Alpha")], run=R1, sortie=sortie, base=base, anterieurs=[])
    ws = openpyxl.load_workbook(sortie)[f"DELTA_{R1}"]
    assert [r[COLS.index("validation")] for r in ws.iter_rows(min_row=2, values_only=True)] == ["NON"]


def test_un_delta_sans_cle_contenu_aux_liens_lnkd_in_changes_ne_double_rien(tmp_path):
    """La base contient déjà ces lignes ; le DELTA d'origine n'a pas de colonne cle_contenu et
    ses liens `lnkd.in` diffèrent tous de ceux du MASTER."""
    base = _base(tmp_path, [_post("Ecole Alpha"), _post("Ecole Beta")])
    delta = _delta(tmp_path, R1, [
        _post("Ecole Alpha", url_post="https://lnkd.in/p/ecolealpha2"),
        _post("Ecole Beta", url_post="https://lnkd.in/p/ecolebeta2"),
    ], cols=COLS_SANS_CLE)
    sortie = str(tmp_path / f"prospection_{R2}.xlsx")
    stats = construire([_post("Ecole Gamma")], run=R2, sortie=sortie, base=base,
                       anterieurs=lire_historique_csv(str(delta)))
    assert stats["reinjectees"] == 0
    assert stats["master_total"] == 3
    assert [x["auteur"] for x in _master(sortie)] == ["Ecole Alpha", "Ecole Beta", "Ecole Gamma"]


def test_plusieurs_anterieurs_sans_cle_ne_se_masquent_pas(tmp_path):
    """Aucune ligne sautée à tort : des cle_contenu et des URL vides ne sont pas des clés."""
    delta = _delta(tmp_path, R1, [
        _post("Ecole Alpha", cle_contenu="", url_post=""),
        _post("Ecole Beta", cle_contenu="", url_post=""),
        _post("Ecole Alpha", cle_contenu="", url_post="", post_extrait="Un autre module, SQL"),
    ])
    sortie = str(tmp_path / f"prospection_{R2}.xlsx")
    stats = construire([_post("Ecole Gamma")], run=R2, sortie=sortie,
                       anterieurs=lire_historique_csv(str(delta)))
    assert stats["reinjectees"] == 3
    assert [x["auteur"] for x in _master(sortie)] == [
        "Ecole Alpha", "Ecole Beta", "Ecole Alpha", "Ecole Gamma"]


def test_des_anterieurs_a_l_url_de_recherche_ne_se_masquent_pas(tmp_path):
    """Avant le correctif #1, des lignes portaient l'URL de recherche : elle n'identifie rien."""
    delta = _delta(tmp_path, R1, [
        _post("Ecole Alpha", cle_contenu="", url_post=RECHERCHE),
        _post("Ecole Beta", cle_contenu="", url_post=RECHERCHE),
    ])
    stats = construire([_post("Ecole Gamma")], run=R2, sortie=str(tmp_path / "p.xlsx"),
                       anterieurs=lire_historique_csv(str(delta)))
    assert stats["reinjectees"] == 2


def test_une_ligne_sans_aucune_cle_n_est_pas_reinjectee(tmp_path, capsys):
    """Elle ne pourrait jamais être reconnue : réinjectée, elle reviendrait à chaque run."""
    vide = {c: "" for c in COLS}
    stats = construire([_post("Ecole Gamma")], run=R2, sortie=str(tmp_path / "p.xlsx"),
                       anterieurs=[vide, _post("Ecole Alpha")])
    assert stats["reinjectees"] == 1
    assert "1 ligne(s) d'historique sans aucune clé" in capsys.readouterr().out


def test_reinjectees_compte_exactement_et_l_ordre_chronologique_est_conserve(tmp_path):
    base = _base(tmp_path, [_post("Ecole Alpha")])
    d1 = _delta(tmp_path, R1, [_post("Ecole Alpha"), _post("Ecole Beta", score=2)])
    d2 = _delta(tmp_path, R2, [
        _post("Ecole Beta", score=2, url_post="https://lnkd.in/p/ecolebeta2"),  # déjà réinjectée
        _post("Ecole Gamma", score=9, cle_contenu=""),
    ])
    anterieurs = lire_historique_csv(str(d1)) + lire_historique_csv(str(d2))
    sortie = str(tmp_path / f"prospection_{R3}.xlsx")
    stats = construire([_post("Ecole Delta")], run=R3, sortie=sortie, base=base,
                       anterieurs=anterieurs)
    assert (stats["reinjectees"], stats["ajoutes_master"], stats["master_total"]) == (2, 1, 4)
    # ni tri par score (Gamma 9 viendrait avant Beta 2), ni mélange avec le run courant
    assert [x["auteur"] for x in _master(sortie)] == [
        "Ecole Alpha", "Ecole Beta", "Ecole Gamma", "Ecole Delta"]


def test_le_batch_vide_est_deduit_du_nom_du_fichier(tmp_path):
    assert run_du_fichier(str(tmp_path / "historique" / f"DELTA_{R1}.csv")) == R1
    assert run_du_fichier(str(tmp_path / "MASTER.csv")) is None
    delta = _delta(tmp_path, R1, [_post("Ecole Alpha"), _post("Ecole Beta", batch="B")])
    sortie = str(tmp_path / f"prospection_{R2}.xlsx")
    construire([_post("Ecole Gamma")], run=R2, sortie=sortie,
               anterieurs=lire_historique_csv(str(delta)))
    lignes = _master(sortie)
    assert [x["batch"] for x in lignes] == [f"RUN {R1}", "B", f"RUN {R2}"]
    assert list(lignes[0]) == COLS  # la provenance interne `_run` n'est pas écrite


def test_un_run_fourni_par_l_appelant_l_emporte_sur_le_nom(tmp_path):
    master = _ecrire_csv(tmp_path / "MASTER.csv", COLS, [_post("Ecole Alpha")])
    assert lire_historique_csv(str(master))[0]["_run"] == ""
    assert lire_historique_csv(str(master), run=R1)[0]["_run"] == R1


def test_les_labels_de_la_base_restent_intacts(tmp_path):
    base = _base(tmp_path, [_post("Ecole Alpha", score=10, **TEXTES)])
    wb = openpyxl.load_workbook(base)
    wb["MASTER"].cell(row=2, column=COLS.index("validation") + 1, value="NON")
    wb["MASTER"].cell(row=2, column=COLS.index("motif") + 1, value="hors zone")
    wb["SUIVI_LEADS"].cell(row=2, column=COLS_LEADS.index("statut_lead") + 1, value="Contacté")
    wb.save(base)
    delta = _delta(tmp_path, R1, [_post("Ecole Alpha", score=10, **TEXTES),
                                  _post("Ecole Beta")])
    sortie = str(tmp_path / f"prospection_{R2}.xlsx")
    stats = construire([_post("Ecole Gamma")], run=R2, sortie=sortie, base=base,
                       anterieurs=lire_historique_csv(str(delta)))
    assert stats["reinjectees"] == 1
    alpha = [x for x in _master(sortie) if x["auteur"] == "Ecole Alpha"]
    assert [(x["validation"], x["motif"]) for x in alpha] == [("NON", "hors zone")]
    ws = openpyxl.load_workbook(sortie)["SUIVI_LEADS"]
    assert [(r[1], r[COLS_LEADS.index("statut_lead")])
            for r in ws.iter_rows(min_row=2, values_only=True)] == [("Ecole Alpha", "Contacté")]


def test_un_anterieur_n_entre_ni_au_delta_ni_au_suivi_leads(tmp_path):
    """Un lead réinjecté recevrait le statut « À contacter » à tort."""
    delta = _delta(tmp_path, R1, [_post("Ecole Alpha", score=10, **TEXTES)])
    sortie = str(tmp_path / f"prospection_{R2}.xlsx")
    stats = construire([_post("Ecole Gamma")], run=R2, sortie=sortie,
                       anterieurs=lire_historique_csv(str(delta)))
    assert (stats["reinjectees"], stats["delta"], stats["nouveaux_leads"]) == (1, 1, 0)
    wb = openpyxl.load_workbook(sortie)
    assert [r[COLS.index("auteur")] for r in wb[f"DELTA_{R2}"].iter_rows(
        min_row=2, values_only=True)] == ["Ecole Gamma"]
    assert list(wb["SUIVI_LEADS"].iter_rows(min_row=2, values_only=True)) == []
