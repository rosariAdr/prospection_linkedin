# data/ — contenu non versionné

En mode local, ce dossier reçoit **les données réelles** : configuration de profil, classeurs,
exports CSV, historique. Tout son contenu est exclu de git par `.gitignore`, à l'exception de ce
fichier.

Pourquoi : les posts collectés contiennent des noms, des profils et des adresses de **personnes
tierces** (responsables pédagogiques, recruteurs) qui n'ont pas consenti à figurer dans un dépôt
public, et la configuration de profil contient les coordonnées personnelles de l'utilisateur.

## Mode local ou partagé

- **Mode local** (par défaut) : les données sont ici, et les runs dans `runs/` à la racine du
  dépôt.
- **Mode partagé** (plusieurs PC) : les données vivent dans un dossier hors du dépôt, synchronisé
  entre les PC, par exemple `G:\Mon Drive\prospection\donnees`. Il est désigné par `--donnees`
  ou par la variable `PROSPECTION_DONNEES`. Un dossier situé dans le dépôt, ou dans n'importe
  quel arbre git, est refusé.

Chaque commande annonce son mode en première ligne : `données : local — …` ou
`données : partagé — …`.

Le passage au mode partagé se fait une fois, avec
`python -m prospection.run initialiser-donnees --vers <dossier>`. La commande copie la config,
les CSV d'historique, les JSON de `runs/` et le dernier classeur, sans rien déplacer ni écraser,
puis dépose ici `MIGRE_VERS_PARTAGE.txt`. Dès lors, le mode local s'arrête (code 2) au lieu de
lire un `data/` périmé, et les fichiers restés ici ne sont plus lus. Mode opératoire :
[`docs/10-run-recurrent.md`](../docs/10-run-recurrent.md) §7.

## Mise en route (mode local)
```bash
cp templates/config-profil.example.yaml data/config.yaml
# puis remplir data/config.yaml
```

## Fichiers attendus ici (mode local)
| Fichier | Rôle |
|---|---|
| `config.yaml` | configuration du profil — source unique de vérité |
| `prospection_<date>.xlsx` | classeur produit par `python -m prospection.run finaliser` |
| `MASTER.csv`, `SUIVI_LEADS.csv` | archives CSV, relues par la déduplication |
| `MIGRE_VERS_PARTAGE.txt` | déposé par `initialiser-donnees` : les données ont migré |

## Dossier de données partagé
| Élément | Rôle |
|---|---|
| `config.yaml` | configuration du profil — source unique de vérité |
| `historique/` | `DELTA_<run>.csv` écrits par `finaliser`, et le MASTER migré. Ajout seul |
| `runs/<run>/` | JSON des agents, `a_scorer.json`, `scored_*.json` |
| `classeurs/` | `prospection_<run>.xlsx`. Les labels se saisissent dans le plus récent |
| `verrou.json` | verrou de run : un seul poste travaille à la fois |
| `.prospection-donnees` | marqueur du dossier, posé par `initialiser-donnees` |

Ne jamais forcer l'ajout d'un fichier de ce dossier (`git add -f`) : la règle du `.gitignore`
est la seule protection avant un push. La porte (`tests/test_anti_fuite.py`) refuse aussi les
fichiers d'un dossier partagé copié par erreur dans le dépôt.
