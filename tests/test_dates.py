import pytest

from prospection.dates import dans_fenetre, extraire_du_texte_carte, parse_date_relative


@pytest.mark.parametrize(
    "valeur,jours",
    [("19 h", 0), ("45 min", 0), ("3 j", 3), ("1 sem", 7), ("2 sem", 14), ("1 mois", 30), ("1 an", 365)],
)
def test_parse_date_relative(valeur, jours):
    assert parse_date_relative(valeur) == jours


def test_date_illisible_ou_vide_renvoie_none():
    assert parse_date_relative("") is None
    assert parse_date_relative("hier") is None


def test_date_illisible_conserve_le_post():
    """Règle de sûreté : on ne perd jamais un post à cause d'une date qu'on ne sait pas lire."""
    assert dans_fenetre("", 21) is True
    assert dans_fenetre(None, 7) is True


def test_fenetre():
    assert dans_fenetre("3 sem", 21) is True
    assert dans_fenetre("4 sem", 21) is False
    assert dans_fenetre("1 mois", 21) is False


def test_extraction_ignore_les_nombres_du_corps_du_post():
    """Le bug historique : « 3 ans d'expérience » pris pour l'horodatage du post."""
    carte = (
        "Post du fil d’actualité Marie Dupont • 2e Responsable pédagogique 3 j • Suivre "
        "Nous cherchons un intervenant avec 3 ans d'expérience minimum et 1 500 heures de cours."
    )
    assert extraire_du_texte_carte(carte) == "3 j"


def test_extraction_prend_la_derniere_occurrence():
    carte = "Auteur • 2e Consultant depuis 5 ans • 19 h • Suivre Le texte du post."
    assert extraire_du_texte_carte(carte) == "19 h"
