# 02 — Configuration du profil
### C'est LE fichier à remplir. Tout le reste du kit est générique.

> `cp templates/config-profil.example.yaml data/config.yaml`, puis le remplir.
> `data/` est gitignoré : ce fichier ne quitte jamais la machine.
> Ne pas chercher à faire parfait : le POC et les labels corrigeront.

## 1. Profil de la personne

Les champs sont décrits dans le template. Deux d'entre eux méritent un soin particulier :

- **`COMPETENCES`** sert de filtre : une annonce exigeant un outil absent de cette liste est
  rejetée automatiquement (F2). Une liste trop large produit des faux positifs coûteux.
- **`EXPERIENCE_CIBLE`** (les écoles/clients où la personne est déjà intervenue) est l'argument
  principal de tous les messages. Sans elle, les messages sonnent creux.

## 2. Construction du search plan

Un mot-clé = **`<rôle recherché>` + `<domaine/outil>`**.

1. Lister les **rôles** employés par les recruteurs du secteur.
   *Enseignement FR* : `formateur`, `intervenant`, `enseignant`, `vacataire`, `professeur`.
   *Freelance tech* : `freelance`, `consultant`, `prestataire`, `expert`, `mission`.
2. Lister les **domaines et outils**, avec synonymes et acronymes
   (`intelligence artificielle` ET `IA` ET `machine learning` ET `ML`).
3. Croiser, puis **grouper en 4 à 6 lots thématiques** pour exécuter et analyser lot par lot.
4. Viser **40 à 50 mots-clés**. Au-delà, le rendement marginal s'effondre.

> Mesuré sur le cas réel : **13 des 45 mots-clés n'ont rien produit** en hebdomadaire. Mieux vaut
> 25 mots-clés bien choisis, enrichis mensuellement par la découverte, que 50 au jugé.

## 3. Calibrer la grille

La grille vit dans `data/config.yaml` (section `scoring`) ; `03-scoring-et-regles.md` §3 explique ce que chaque critère capture. Les trois réglages à faire en
priorité, parce qu'ils sont les plus spécifiques au profil :

| Réglage | Question à poser |
|---|---|
| `REMUNERATION_SEUIL` | À partir de quel taux l'opportunité devient franchement intéressante ? |
| Bonus distanciel | Le distanciel change-t-il la donne géographique, ou pas du tout ? |
| Malus segment | Y a-t-il un niveau/public qui est accepté « par défaut » mais jamais avec plaisir ? |

Le troisième est le plus souvent oublié, et c'est celui qui produit le plus de frustration :
sur le cas réel, le BTS a dû passer de 0 à **−3** une fois l'emploi du temps mieux rempli.
**Un critère de scoring peut dépendre du moment de l'année** — le relire à chaque run complet.
