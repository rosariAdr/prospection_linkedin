"""Prospection LinkedIn — bibliothèque du process.

Modules :
    cles      clés de déduplication (contenu, URL, auteur)
    dates     lecture des dates relatives LinkedIn et fenêtrage
    config    chargement et validation du fichier de configuration profil
    dedup     déduplication d'un run contre l'historique
    verify    garde-fous bloquants avant livraison
    workbook  construction du classeur MASTER / DELTA / SUIVI_LEADS
    run       orchestration (prepare → [scoring] → finaliser)
"""
__version__ = "1.0.0"
