# nexus_core — noyau de contrôle Nexus (étape 4 de DEPLOIEMENT-VPS-CLAUDE)

Registre de budget, revue indépendante, approbation, envoi et audit, en PostgreSQL 16.
**Aucune dépense, aucun envoi réel, aucun appel à un fournisseur** : le code n'ouvre ni SMTP ni API payante.
Il fournit les garde-fous que les futurs adaptateurs (n8n, Hermes, transport e-mail) devront traverser.

## Ce qui est garanti (et testé)
- **Budget** : 300 € au total, 60 € de réserve intouchable, 240 € consommables, recherche 60 € dont 30 € par cycle de 15 jours (ancrage 2026-10-04, calcul serveur). Mois de Paris. Coût inconnu ou nul : refus. Réservation atomique et idempotente. Coût réel tardif conservé, jamais écrêté, et peut bloquer le mois d'origine. Alertes à 80 % et 100 %, une seule fois chacune.
- **Qui peut quoi** : les rôles applicatifs n'ont aucun droit sur les tables, seulement sur des fonctions. L'identité vient de la session authentifiée (`session_user`), jamais d'un paramètre. Le rédacteur ne peut ni relire, ni approuver, ni envoyer. Le relecteur ne peut pas rédiger. Seul le fondateur approuve. Seul le transport réserve et marque l'envoi.
- **Texte figé** : le contenu d'un message est immuable (déclencheur) ; corriger crée une nouvelle version (2 corrections au plus, puis pause). L'approbation est liée au hash exact du texte, à une durée (1 à 168 h) et au budget de transport, réservé au moment d'approuver.
- **Opposition** : normalisée (casse, espaces), vérifiée à la création, à l'approbation, à la réservation d'envoi et juste avant l'envoi (`precheck_before_send`). Elle libère le budget réservé.
- **Envoi** : bail avec expiration, un seul preneur par message, quota quotidien d'e-mails (jour de Paris), reprise sur échec, `mark_sent` idempotent. Sans transport, rien ne part et une alerte est levée une seule fois.
- **Audit** : chaîne de hachage ; modification, suppression et troncature refusées. Toute altération faite en désactivant les protections est détectée par `verify_audit_chain()`.
- **Restauration** : un `pg_dump` restauré conserve soldes, chaîne d'audit et droits (test).

## Limites à connaître
- **Un verrou global** (7001) sérialise toutes les mutations. Simple et sans interblocage ; à revoir au-delà de quelques opérations par seconde.
- **L'audit n'est pas inviolable face à un administrateur** : il détecte l'altération, il ne l'empêche pas. Il faut ancrer régulièrement la dernière empreinte hors de la machine (non fait ici).
- **Fenêtre résiduelle** entre `precheck_before_send` et l'envoi SMTP réel : la base ne peut pas la fermer. Elle se réduit en appelant `precheck` au dernier moment.
- **Pas d'authentification forte** (MFA, certificats), pas de réseau, pas de chiffrement des sauvegardes : à traiter aux étapes suivantes. Les mots de passe ou certificats des rôles se configurent hors de ce dépôt.
- Les coûts sont en centimes d'euro. Le périmètre fiscal (TVA, provision) n'est pas modélisé ici.
- Testé sur PostgreSQL 16 uniquement. Ce n'est pas une preuve de viabilité commerciale.

## Lancer les tests
```
pip install -r nexus_core/requirements.txt
python -m pytest nexus_core/tests -q
```
Les tests démarrent un cluster PostgreSQL temporaire (binaire `PG_BIN`, par défaut `/usr/lib/postgresql/16/bin`, exécuté via l'utilisateur `postgres`) et une base neuve par test.

## Installer sur une base réelle (quand le déploiement sera autorisé)
1. Superutilisateur : `bootstrap.sql` (rôles `nexus_*`), puis créer la base `nexus_core` propriétaire `nexus_owner`.
2. `nexus_owner` : `schema.sql`, puis `seed_principals.sql`.
3. Définir mots de passe ou certificats des rôles dans `pg_hba.conf` et un gestionnaire de secrets. Ne rien versionner.
