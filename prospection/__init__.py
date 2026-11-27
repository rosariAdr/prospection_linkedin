"""Prospection LinkedIn — bibliothèque du process.

Modules :
    cles      clés de déduplication (contenu, URL, auteur)
    dates     lecture des dates relatives LinkedIn et fenêtrage
    config    chargement et validation du fichier de configuration profil
    dedup     déduplication d'un run contre l'historique
    verify    garde-fous bloquants avant livraison
    workbook  construction du classeur MASTER / DELTA / SUIVI_LEADS
    run       orchestration (prepare → [scoring] → finaliser)
    emplacements  emplacement des données : mode local, ou dossier partagé entre plusieurs PC
    verrou    verrou de run sur le dossier partagé
    poste     contrôle d'un PC avant un run (`poste`)
    migration création du dossier partagé et migration du data/ local (`initialiser-donnees`)
"""
__version__ = "1.0.0"
