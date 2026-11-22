from prospection.cles import cle_contenu, cle_secours, cle_url, corps_du_post, norm


def test_norm_supprime_accents_casse_et_ponctuation():
    assert norm("Sophie R.") == norm("SOPHIE  r") == "sophier"
    assert norm("Guînes & Saint-Omer") == "guinessaintomer"
    assert norm(None) == ""


def test_cle_contenu_stable_malgre_la_mise_en_forme():
    a = cle_contenu("Alice Martin", "Nous recherchons un formateur Python pour nos Master 2.")
    b = cle_contenu("ALICE  MARTIN", "Nous recherchons un formateur Python pour nos Master 2. ")
    assert a == b


def test_cle_contenu_distingue_deux_annonces_du_meme_auteur():
    a = cle_contenu("Alice", "Nous recherchons un formateur Python pour le Master 2 data science")
    b = cle_contenu("Alice", "Nous recherchons un formateur Excel pour le Bachelor gestion RH")
    assert a != b


def _carte(auteur, titre, date, corps):
    """Texte d'une carte tel que le harvester le capture (format de tests/test_dates.py)."""
    return f"Post du fil d’actualité {auteur} • 2e {titre} {date} • Suivre {corps}"


def test_meme_post_a_deux_dates_relatives_donne_la_meme_cle():
    """PL-01 : le même post, capturé à « 3 j » puis à « 1 sem », doit garder la même clé.

    Le lien lnkd.in change à chaque capture : si la clé de contenu change aussi, le post est
    rescoré et la personne risque d'être recontactée.
    """
    corps = "Nous cherchons un intervenant Python pour nos Master 2 à la rentrée."
    a = _carte("Marie Dupont", "Responsable pédagogique", "3 j", corps)
    b = _carte("Marie Dupont", "Responsable pédagogique", "1 sem", corps)
    assert cle_contenu("Marie Dupont", a) == cle_contenu("Marie Dupont", b)
    assert cle_secours(a) == cle_secours(b)


def test_corps_du_post_coupe_apres_le_dernier_horodatage():
    """Le titre peut contenir un motif de date (« depuis 5 ans • ») : c'est le DERNIER qui fait
    foi, comme pour la date (tests/test_dates.py). Sans horodatage, le texte est rendu tel quel."""
    titre = "Consultant depuis 5 ans • Formateur"
    a = _carte("Alice Martin", titre, "19 h", "Recherche intervenant SQL en distanciel.")
    b = _carte("Alice Martin", titre, "2 sem", "Recherche intervenant SQL en distanciel.")
    assert norm(corps_du_post(a)) == norm(corps_du_post(b)) == norm("Suivre Recherche intervenant SQL en distanciel.")
    assert corps_du_post("Recherche intervenant SQL en distanciel.") == "Recherche intervenant SQL en distanciel."


def test_deux_annonces_d_un_auteur_au_titre_long_donnent_deux_cles():
    """PL-01 : un titre long remplissait à lui seul les premiers caractères de la clé, et la
    seconde annonce du même auteur était écartée comme « déjà connue »."""
    titre = (
        "Responsable pédagogique des formations en alternance et de la formation continue, "
        "campus de Lille, Roubaix et Tourcoing"
    )
    a = _carte("Marie Dupont", titre, "3 j", "Nous cherchons un intervenant Python pour le Master 2.")
    b = _carte("Marie Dupont", titre, "3 j", "Nous cherchons un formateur Excel pour le Bachelor RH.")
    assert cle_contenu("Marie Dupont", a) != cle_contenu("Marie Dupont", b)
    assert cle_secours(a) != cle_secours(b)


def test_cle_secours_rattrape_un_repost_par_un_autre_auteur():
    texte = "Le campus recrute un formateur en mathematiques a 50 pourcent pour la rentree"
    repost = _carte("Alice Martin", "Chargée de recrutement", "19 h", texte)
    original = _carte("Marie Dupont", "Responsable pédagogique", "3 j", texte)
    assert cle_secours(repost) == cle_secours(original)
    assert cle_contenu("Auteur A", texte) != cle_contenu("Auteur B", texte)


def test_cle_url_retire_la_query_string():
    assert cle_url("https://lnkd.in/p/abc?utm=x") == "https://lnkd.in/p/abc"
    assert cle_url("https://lnkd.in/p/abc/") == "https://lnkd.in/p/abc"
