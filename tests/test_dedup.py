from prospection.dedup import Historique, dedupliquer


def _post(auteur, texte, date="3 j", url=""):
    return {"auteur": auteur, "texte": texte, "date_rel": date, "url_post": url, "mot_cle": "kw"}


def test_ecarte_les_doublons_internes_malgre_des_url_differentes():
    """Cas réel : LinkedIn renvoie un lnkd.in/p/XXXX différent à chaque capture."""
    t = "Nous recherchons un formateur Python pour nos Master 2 a Paris."
    cands = [_post("Alice", t, url="https://lnkd.in/p/aaa"),
             _post("Alice", t, url="https://lnkd.in/p/bbb"),
             _post("Bob", "Recherche intervenant SQL en distanciel.")]
    gardes, rap = dedupliquer(cands)
    assert rap.doublons_internes == 1
    assert len(gardes) == 2


def test_ecarte_ce_qui_est_deja_dans_l_historique():
    t = "Recherche formateur en mathematiques pour la rentree."
    hist = Historique()
    gardes, _ = dedupliquer([_post("Ecole X", t)])
    hist.contenus.add(gardes[0]["cle_contenu"])
    gardes2, rap = dedupliquer([_post("Ecole X", t)], hist)
    assert rap.deja_connus == 1
    assert gardes2 == []


def test_filtre_par_fenetre_temporelle():
    cands = [_post("A", "texte a", date="3 j"), _post("B", "texte b", date="2 mois")]
    gardes, rap = dedupliquer(cands, jours_max=21)
    assert rap.hors_fenetre == 1
    assert [g["auteur"] for g in gardes] == ["A"]


def test_signale_mais_ne_supprime_pas_un_doublon_d_organisation():
    """Une école qui publie une DEUXIÈME annonce ne doit pas disparaître en silence."""
    hist = Historique(auteurs={"ecolex"})
    gardes, rap = dedupliquer([_post("Ecole X", "Une toute autre annonce, module Power BI.")], hist)
    assert len(gardes) == 1
    assert gardes[0]["deja_en_suivi"] is True
    assert rap.meme_organisation == ["Ecole X"]


def test_la_cle_de_contenu_est_posee_sur_les_lignes_gardees():
    gardes, _ = dedupliquer([_post("A", "un texte de post")])
    assert gardes[0]["cle_contenu"] and gardes[0]["cle_secours"]
