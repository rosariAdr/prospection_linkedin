from prospection.verify import controler


def _ligne(**kw):
    base = {
        "auteur": "Alice Martin", "score_pertinence": 10, "mail": "",
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
