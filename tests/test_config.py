import textwrap

import pytest

from prospection.config import CheminConfigIntrouvable, charger

MINIMALE = textwrap.dedent(
    """
    version: 1
    profil: {nom: "Test Personne"}
    blacklist:
      organisations: ["ORGA-X"]
      en_observation: ["Orga-Obs"]
    scoring: {seuil_conservation: 3, seuil_redaction: 5}
    search_plan:
      lots:
        A: ["formateur data", "intervenant data"]
        B: ["formateur python"]
    """
)


@pytest.fixture()
def cfg(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "config.yaml").write_text(MINIMALE, encoding="utf-8")
    return charger(racine=str(tmp_path))


def test_seuils(cfg):
    assert cfg.conserver(3) and not cfg.conserver(2.9)
    # seuil de rédaction STRICTEMENT supérieur : 5 ne déclenche pas
    assert cfg.rediger_messages(5.1) and not cfg.rediger_messages(5)


def test_blacklist_insensible_a_la_casse_et_aux_variantes(cfg):
    assert cfg.est_blacklistee("Orga-x")
    assert cfg.est_blacklistee("Marie Dupont — ORGA-X")   # forme du cas du 03/09 : « auteur — organisation »
    assert not cfg.est_blacklistee("Orga-Y")


def test_observation(cfg):
    assert cfg.est_en_observation("Orga-Obs") and not cfg.est_en_observation("Ecole Gamma")


def test_mots_cles_et_lots(cfg):
    assert cfg.mots_cles == ["formateur data", "intervenant data", "formateur python"]
    lots = cfg.lots(2)
    assert [len(x) for x in lots] == [2, 1]


def test_config_absente(tmp_path):
    with pytest.raises(CheminConfigIntrouvable):
        charger(racine=str(tmp_path))


def test_section_manquante(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "config.yaml").write_text("version: 1\nprofil: {}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="manquantes"):
        charger(racine=str(tmp_path))
