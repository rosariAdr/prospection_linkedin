# 05 — Les cinq textes générés par opportunité

## Déclencheur
Score > seuil de rédaction **et** aucun filtre déclenché → les 5 textes sont produits.
Seule exception : `reponse_mail` n'existe que si une adresse figure dans le post.
Le seuil est `scoring.seuil_redaction`, dans la config dont `prepare` affiche le chemin absolu.
Les textes vont dans `<dossier du run>/scored_<LOT>.json`, au dossier affiché par la même
commande (`10-run-recurrent.md` §4).

---

## 1. `reponse_commentaire_linkedin` — commentaire public sous le post
- **Aucune salutation, aucun prénom, aucun nom.** On répond sous leur post : ils savent à qui on
  s'adresse, et un « Bonjour Prénom » sonne artificiel en commentaire public.
- 2 à 3 phrases : accroche liée au besoin précis → preuve (terrain + enseignement) → CTA.
- **Ne jamais écrire le téléphone ni l'adresse mail dans un commentaire public** (spam, robots).
  Renvoyer vers le profil, ou annoncer l'envoi d'une invitation.

## 2. `note_invitation_200` — note d'invitation, compte gratuit
- **200 caractères maximum, espaces compris.** À vérifier par script : c'est bloquant.
- Commence par `Bonjour Monsieur <NOM DE FAMILLE>,` — jamais le prénom.
- À 200 caractères il faut choisir : salutation + qui je suis en 4-5 mots + le besoin visé + une
  invitation courte à échanger. Pas de coordonnées, pas de liste d'outils.

## 3. `note_invitation_300` — note d'invitation, compte Premium
- **300 caractères maximum.** Mêmes règles de salutation.
- La marge sert à préciser la stack ou une preuve (écoles, clients), pas à rallonger les formules.

## 4. `message_linkedin` — message direct
- **10 lignes maximum.** Doit fonctionner en InMail direct **et** après acceptation d'invitation :
  donc jamais « suite à votre acceptation », jamais de connexion supposée.
- Structure : accroche sur le besoin → profil en 2-3 lignes (terrain + enseignement + stack utile
  à CETTE annonce) → disponibilité → clôture.
- **Toujours terminer par le bloc de contact** : « Je vous joins mon CV » ET les coordonnées, pour
  que la personne choisisse son canal.
- Signature : le nom seul.

## 5. `reponse_mail` — e-mail (seulement si une adresse figure dans le post)
`Objet : …` + ligne vide + salutation + 4-5 paragraphes courts séparés par une ligne vide + **une**
question ouverte + signature. Longueur cible **150 à 220 mots**.

---

## Règle de civilité — ne jamais deviner

N'employer `Monsieur` / `Madame` **que si le prénom lève toute ambiguïté**. Sinon `Bonjour,` seul :
- prénom épicène (Camille, Dominique, Claude, Alix, Sacha…) ;
- contexte non francophone ;
- contact = page entreprise ou adresse générique (`contact@`, `recrutement@`) ;
- nom affiché en initiales ou incomplet.

> Une civilité erronée coûte plus cher qu'une salutation neutre. `Bonjour,` est toujours correct.

**Extraction du nom de famille** : dernier mot du nom affiché, remis en capitalisation normale
(`CLAIRE DURAND` → `Madame Durand`). Attention aux profils qui inversent nom et prénom.

---

## Variantes selon le type d'opportunité

| Type | Angle du message |
|---|---|
| `annonce directe` | Candidature ciblée sur le besoin exact |
| `réseau / vivier` | Demande de référencement : « rejoindre votre réseau d'intervenants » |
| `à qualifier` | Poser la question bloquante (distanciel, conditions) **avant** de candidater |

**Une seule candidature par organisation**, même si plusieurs posts sont détectés.

---

## Extraire le style réel de la personne

Un message générique se repère immédiatement. La méthode qui a fonctionné : **lire 4 à 6 mails de
candidature réellement envoyés** (boîte d'envoi) et en extraire la structure, les formules
récurrentes, la signature, la longueur. Pas un pastiche : un gabarit.

Ce qui a été extrait sur le cas réel, à titre d'exemple de ce qu'il faut chercher :
- objet qui **nomme le rôle exact tel qu'écrit dans l'annonce**, pas une formule générique ;
- §1 objet direct, §2 preuve la plus proche du besoin, §3 élargissement, §4 CV + une question +
  téléphone dans le corps, §5 clôture ;
- signature = `NOM Prénom` seul, jamais de bloc titre/mail/LinkedIn ;
- ton affirmatif (« Je suis sûr qu'après la lecture de mon CV, mon profil vous intéressera »).

---

## Contrôle qualité avant livraison (script obligatoire)

```python
err = []
for p in posts:
    if len(p["note_invitation_200"]) > 200: err.append((p["auteur"], "n200", len(p["note_invitation_200"])))
    if len(p["note_invitation_300"]) > 300: err.append((p["auteur"], "n300", len(p["note_invitation_300"])))
    if p["message_linkedin"] and p["message_linkedin"].count("\n") + 1 > 10: err.append((p["auteur"], "lignes"))
    c = p["reponse_commentaire_linkedin"]
    if re.match(r"^\s*(Bonjour|Bonsoir|Madame|Monsieur)", c): err.append((p["auteur"], "salutation"))
    if "@" in c or re.search(r"0\d[\s.]?\d{2}", c): err.append((p["auteur"], "coordonnees publiques"))
assert not err, err
```

- [ ] Aucune compétence mentionnée hors du profil
- [ ] Le nom de la structure et l'intitulé exact du besoin repris tels quels
- [ ] Une seule candidature par organisation
