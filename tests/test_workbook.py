import openpyxl
import pytest

from prospection.workbook import COLS, construire


def _post(auteur, score=10, **kw):
    p = {
        "post_extrait": f"Annonce de {auteur}", "url_post": f"https://lnkd.in/p/{auteur[:3]}",
        "url_profil_auteur": "https://www.linkedin.com/in/x/", "auteur": auteur, "date": "3 j",
        "mail": "", "taux_horaire": "à déterminer", "localisation": "IDF",
        "score_pertinence": score, "mot_cle_recherche": "formateur data", "batch": "",
        "type_opportunite": "annonce directe", "echeance": "S2 2027", "deal_breaker": "",
        "commentaire_scoring": "+4 +3 +2", "cle_contenu": "",
        "reponse_commentaire_linkedin": "Votre annonce m'interesse.",
        "note_invitation_200": "Bonjour, formateur data, votre annonce m'interesse.",
        "note_invitation_300": "Bonjour, ingenieur data et formateur, votre annonce m'interesse.",
        "message_linkedin": "Bonjour,\nVotre annonce m'interesse.\nROSARI Adrian",
        "reponse_mail": "",
    }
    p.update(kw)
    return p


def test_construit_les_trois_onglets(tmp_path):
    out = tmp_path / "p.xlsx"
    stats = construire([_post("Alice"), _post("Bob", 4, **{c: "" for c in (
        "reponse_commentaire_linkedin", "note_invitation_200", "note_invitation_300",
        "message_linkedin")})], run="TEST", sortie=str(out))
    wb = openpyxl.load_workbook(out)
    assert wb.sheetnames[:3] == ["MASTER", "DELTA_TEST", "SUIVI_LEADS"]
    assert stats["delta"] == 2 and stats["nouveaux_leads"] == 1
    assert [c.value for c in wb["MASTER"][1]] == COLS


def test_une_cle_de_contenu_est_ecrite_sur_chaque_ligne(tmp_path):
    out = tmp_path / "p.xlsx"
    construire([_post("Alice")], run="TEST", sortie=str(out))
    wb = openpyxl.load_workbook(out)
    cols = [c.value for c in wb["MASTER"][1]]
    ligne = next(wb["MASTER"].iter_rows(min_row=2, values_only=True))
    assert ligne[cols.index("cle_contenu")]


def test_relancer_le_meme_run_n_ajoute_pas_de_doublon_au_master(tmp_path):
    """Le bug historique : la dédup MASTER par auteur seul."""
    out = str(tmp_path / "p.xlsx")
    construire([_post("Alice")], run="T1", sortie=out)
    stats = construire([_post("Alice")], run="T2", sortie=out, base=out)
    assert stats["ajoutes_master"] == 0
    assert stats["master_total"] == 1


def test_une_deuxieme_annonce_de_la_meme_ecole_entre_bien_au_master(tmp_path):
    out = str(tmp_path / "p.xlsx")
    construire([_post("Ecole X")], run="T1", sortie=out)
    autre = _post("Ecole X", post_extrait="Un tout autre module, Power BI",
                  url_post="https://lnkd.in/p/zzz", cle_contenu="")
    autre["reponse_commentaire_linkedin"] = ""
    autre["note_invitation_200"] = autre["note_invitation_300"] = autre["message_linkedin"] = ""
    autre["score_pertinence"] = 4
    stats = construire([autre], run="T2", sortie=out, base=out)
    assert stats["ajoutes_master"] == 1


def test_le_build_echoue_si_un_garde_fou_saute(tmp_path):
    mauvais = _post("Alice", note_invitation_200="x" * 250)
    with pytest.raises(AssertionError, match="garde-fous"):
        construire([mauvais], run="TEST", sortie=str(tmp_path / "p.xlsx"))


def test_avertit_quand_la_cle_de_contenu_est_perdue_au_scoring(tmp_path, capsys):
    """La clé est calculée au harvest : si le scoring ne la recopie pas, on le dit."""
    construire([_post("Alice")], run="TEST", sortie=str(tmp_path / "p.xlsx"))
    assert "sans cle_contenu" in capsys.readouterr().out


def test_la_cle_du_harvest_est_conservee_telle_quelle(tmp_path):
    out = str(tmp_path / "p.xlsx")
    construire([_post("Alice", cle_contenu="abc123")], run="TEST", sortie=out)
    wb = openpyxl.load_workbook(out)
    cols = [c.value for c in wb["MASTER"][1]]
    ligne = next(wb["MASTER"].iter_rows(min_row=2, values_only=True))
    assert ligne[cols.index("cle_contenu")] == "abc123"
