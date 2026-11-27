"""Configuration commune des tests.

Garde : sur un PC passé en mode partagé (docs/10), la variable `PROSPECTION_DONNEES` est posée
pour l'utilisateur. Sans cette fixture, elle ferait basculer en mode partagé tous les tests écrits
pour le mode local, et pourrait les faire lire ou écrire dans le vrai dossier de données. Elle est
donc retirée de l'environnement de chaque test ; un test du mode partagé la pose lui-même
(`monkeypatch.setenv`) ou passe `--donnees`.
"""
import pytest


@pytest.fixture(autouse=True)
def _sans_variable_donnees(monkeypatch):
    monkeypatch.delenv("PROSPECTION_DONNEES", raising=False)
