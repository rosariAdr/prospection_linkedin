from prospection.cles import cle_contenu, cle_secours, cle_url, norm


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


def test_cle_secours_rattrape_un_repost_par_un_autre_auteur():
    texte = "Le campus recrute un formateur en mathematiques a 50 pourcent pour la rentree"
    assert cle_secours(texte) == cle_secours(texte)
    assert cle_contenu("Auteur A", texte) != cle_contenu("Auteur B", texte)


def test_cle_url_retire_la_query_string():
    assert cle_url("https://lnkd.in/p/abc?utm=x") == "https://lnkd.in/p/abc"
    assert cle_url("https://lnkd.in/p/abc/") == "https://lnkd.in/p/abc"
