import openpyxl
import pytest

from prospection.verify import controler, controler_classeur

PERMALIEN = "https://www.linkedin.com/feed/update/urn:li:activity:0000000000000000001/"
RECHERCHE = "https://www.linkedin.com/search/results/content/?keywords=formateur%20data"


def _ligne(**kw):
    base = {
        "auteur": "Alice Martin", "score_pertinence": 10, "mail": "",
        "url_post": PERMALIEN, "commentaire_scoring": "+4 intention +3 metier +3 zone",
        "reponse_commentaire_linkedin": "Votre recherche m'interesse, je forme a Python.",
        "note_invitation_200": "Bonjour Madame Martin, formateur Python, votre annonce m'interesse.",
        "note_invitation_300": "Bonjour Madame Martin, ingenieur data et formateur Python.",
        "message_linkedin": "Bonjour Madame Martin,\nVotre annonce m'interesse.\nROSARI Adrian",
        "reponse_mail": "",
    }
    base.update(kw)
    return base


def test_ligne_conforme_ne_leve_rien():
    assert controler([_ligne()], seuil_redaction=5) == []


def test_note_invitation_trop_longue():
    err = controler([_ligne(note_invitation_200="x" * 201)])
    assert any("note_invitation_200" in a.regle for a in err)


def test_message_linkedin_de_plus_de_dix_lignes():
    err = controler([_ligne(message_linkedin="ligne\n" * 11)])
    assert any("message_linkedin" in a.regle for a in err)


def test_commentaire_public_ne_doit_pas_commencer_par_une_salutation():
    err = controler([_ligne(reponse_commentaire_linkedin="Bonjour Madame, votre annonce...")])
    assert any("salutation" in a.regle for a in err)


def test_pas_de_coordonnees_dans_un_commentaire_public():
    err = controler([_ligne(reponse_commentaire_linkedin="Ecrivez-moi a moi@example.com")])
    assert any("mail" in a.regle for a in err)
    err = controler([_ligne(reponse_commentaire_linkedin="Appelez-moi au 06.00.00.00.00")])
    assert any("telephone" in a.regle.replace("é", "e") for a in err)


def test_un_volume_horaire_n_est_pas_pris_pour_un_telephone():
    assert controler([_ligne(reponse_commentaire_linkedin="Le module fait 021 22 heures au total.")]) == []


def test_mail_redige_sans_adresse_dans_le_post():
    err = controler([_ligne(reponse_mail="Objet : Candidature\n\nBonjour,")])
    assert any("aucune adresse" in a.regle for a in err)


def test_messages_manquants_au_dessus_du_seuil():
    vide = {c: "" for c in ("reponse_commentaire_linkedin", "note_invitation_200",
                            "note_invitation_300", "message_linkedin", "reponse_mail")}
    err = controler([_ligne(score_pertinence=9, **vide)], seuil_redaction=5)
    assert any("aucun message" in a.regle for a in err)


def test_messages_rediges_sous_le_seuil():
    err = controler([_ligne(score_pertinence=4)], seuil_redaction=5)
    assert any("sous le seuil" in a.regle for a in err)


def test_deux_candidatures_pour_la_meme_organisation():
    err = controler([_ligne(), _ligne()], seuil_redaction=5)
    assert any("même organisation" in a.regle for a in err)


# --- permalien et score tracé (PL-06) -----------------------------------------


def test_url_post_vide_est_bloquee():
    err = controler([_ligne(url_post="")], seuil_redaction=5)
    assert any("permalien manquant" in a.regle for a in err)


def test_url_de_recherche_au_lieu_du_permalien_est_bloquee():
    err = controler([_ligne(url_post=RECHERCHE)], seuil_redaction=5)
    assert any("URL de recherche" in a.regle for a in err)


def test_url_post_vide_est_bloquee_meme_sans_message():
    """La règle vaut pour toute ligne conservée, pas seulement pour les leads rédigés."""
    vide = {c: "" for c in ("reponse_commentaire_linkedin", "note_invitation_200",
                            "note_invitation_300", "message_linkedin", "reponse_mail")}
    err = controler([_ligne(score_pertinence=4, url_post="", **vide)], seuil_redaction=5)
    assert any("permalien manquant" in a.regle for a in err)


def test_commentaire_scoring_vide_avec_un_score_positif_est_bloque():
    err = controler([_ligne(commentaire_scoring="  ")], seuil_redaction=5)
    assert any("commentaire_scoring" in a.regle for a in err)


def test_un_score_nul_n_exige_pas_de_commentaire_de_scoring():
    vide = {c: "" for c in ("reponse_commentaire_linkedin", "note_invitation_200",
                            "note_invitation_300", "message_linkedin", "reponse_mail")}
    err = controler([_ligne(score_pertinence=0, commentaire_scoring="", **vide)], seuil_redaction=5)
    assert not any("commentaire_scoring" in a.regle for a in err)


def test_controler_classeur_signale_une_seule_fois_l_url_de_recherche(tmp_path):
    chemin = tmp_path / "classeur.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "MASTER"
    ligne = _ligne(url_post=RECHERCHE)
    cols = list(ligne)
    ws.append(cols)
    ws.append([ligne[c] for c in cols])
    wb.save(chemin)
    err = controler_classeur(str(chemin))
    assert [a.regle for a in err].count("URL de recherche au lieu d'un permalien") == 1


# --- téléphone au format international (PL-18) --------------------------------


@pytest.mark.parametrize("numero", [
    "+33 6 00 00 00 00",
    "+33600000000",
    "+33 (0)6 00 00 00 00",
    "+33.6.00.00.00.00",
    "0033 6 00 00 00 00",
])
def test_telephone_au_format_international_dans_un_commentaire_public(numero):
    err = controler([_ligne(reponse_commentaire_linkedin=f"Appelez-moi au {numero}")])
    assert any("telephone" in a.regle.replace("é", "e") for a in err)
