# data/ — contenu non versionné

Ce dossier reçoit **les données réelles** : configuration de profil, classeurs, exports CSV,
historique. Tout son contenu est exclu de git par `.gitignore`, à l'exception de ce fichier.

Pourquoi : les posts collectés contiennent des noms, des profils et des adresses de **personnes
tierces** (responsables pédagogiques, recruteurs) qui n'ont pas consenti à figurer dans un dépôt
public, et la configuration de profil contient les coordonnées personnelles de l'utilisateur.

## Mise en route
```bash
cp templates/config-profil.example.yaml data/config.yaml
# puis remplir data/config.yaml
```

## Fichiers attendus ici
| Fichier | Rôle |
|---|---|
| `config.yaml` | configuration du profil — source unique de vérité |
| `prospection_<date>.xlsx` | classeur produit par `python -m prospection.run finaliser` |
| `MASTER.csv`, `SUIVI_LEADS.csv` | archives CSV, relues par la déduplication |

Ne jamais forcer l'ajout d'un fichier de ce dossier (`git add -f`) : la règle du `.gitignore`
est la seule protection avant un push.
