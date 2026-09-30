# Cockpit Solaire Albi — V2

Dashboard local de suivi énergétique et photovoltaïque de la maison. La V2 conserve l'architecture d'origine — **Excel → génération Python → site HTML statique** — et la fiabilise : corrections de formules, contrôle automatique, projection saisonnalisée, séparation des deux installations photovoltaïques, contexte piscine, lecture énergétique annuelle et documentation des estimations.

## Démarrage rapide

### Consulter le cockpit avec Linky
Double-cliquer sur :

`demarrer-cockpit.cmd`

Le navigateur s'ouvre sur `http://127.0.0.1:8765`. Le petit service Python reste strictement local et permet au navigateur de lire la base SQLite sans jamais recevoir le jeton MyElectricalData. La partie solaire continue à fonctionner hors ligne avec les données déjà générées.

Avant la première synchronisation, copier `config.example.json` sous le nom `config.local.json`, puis renseigner le jeton MyElectricalData et le numéro PDL. Voir `LINKY_SETUP.md`.

Pour tester sans compte Enedis et sans toucher aux données réelles, double-cliquer sur `demarrer-cockpit-demo.cmd`. Le bandeau **Mode TEST** est explicite et sa base `data/energy-demo.db` est séparée.

### Mettre à jour après modification de l'Excel
1. Mettre à jour `KWH.xlsx`.
2. Enregistrer le classeur dans Excel afin de recalculer ses formules.
3. Double-cliquer sur `mettre-a-jour-et-ouvrir.cmd`.

Le processus :
1. crée une sauvegarde de sécurité ;
2. régénère les données énergie ;
3. tente de mettre à jour les données Météo-France ;
4. lance un audit de cohérence ;
5. produit un audit croisé Excel / Linky / météo ;
6. démarre le service local et ouvre le dashboard si tout est correct.

Pour régénérer sans ouverture automatique, utiliser `regenerer-site.cmd`.

## Structure

- `KWH.xlsx` — source de données et calculs historiques.
- `site/` — dashboard autonome (`index.html`, `app.js`, `styles.css`, données générées).
- `tools/build_from_export_site.py` — transforme l'Excel en `site/data.js`.
- `tools/build_weather_from_meteofrance.py` — récupère les données climatiques de la station ALBI / Le Séquestre.
- `tools/audit_cockpit.py` — contrôle ce que le dashboard va réellement afficher.
- `tools/audit_data_sources.py` — rapproche Excel, Linky et météo sans modifier le classeur.
- `tools/linky_core.py` — synchronisation incrémentale MyElectricalData et stockage SQLite.
- `tools/linky_server.py` — serveur local et API Linky de même origine.
- `tools/import_enedis_export.py` — importe un export quotidien officiel dans SQLite en ignorant les valeurs `NA`.
- `tools/repair_load_curve.py` — répare uniquement une période de courbe fine identifiée comme incomplète.
- `data/energy.db` — données Linky réelles locales, créée au premier import.
- `config.local.json` — secrets locaux, volontairement exclus des exports et sauvegardes.
- `reports/diagnostic-latest.md` — dernier rapport d'audit.
- `reports/audit-donnees-latest.md` — état des sources, périodes, écarts et champs restant manuels.
- `DONNEES_CONTROLES.md` — règle stable : source officielle de chaque valeur et formules autorisées.
- `backups/auto/` — sauvegardes automatiques avant régénération (12 dernières conservées).
- `documents/` — contrat et facture EDF OA personnels.
- `PARAMETRES_COCKPIT` dans l'Excel — hypothèses/contextes structurés utilisés par la V2.

Un export Enedis nommé `*_Export_energie_Consommation-Production_*.xlsx`, placé dans le dossier parent du cockpit, est détecté automatiquement par l'audit croisé. L'original reste inchangé et n'est jamais copié dans le site partageable.

Les courbes fines utilisent des bornes API de fin exclusives et des blocs chevauchés d'une journée. La clé SQLite `timestamp_utc` et l'UPSERT rendent ce chevauchement sans doublon. La complétude est contrôlée en temps UTC sur la journée locale Europe/Paris : continuité, durée totale et pas réellement reçu (10, 30 ou 60 minutes), y compris lors des changements d'heure.

## Règle de lecture fondamentale

- **2023** : mise en service du Plug & Play en cours d'année.
- **2024** : année de transition ; installation toiture 3 kWc en fin d'année.
- **2025** : première année complète avec les deux installations ; année repère.
- **2026** : année en cours ; utiliser une projection saisonnalisée, pas une simple règle de trois.

## Ce qui est mesuré / calculé / estimé

**Mesuré ou issu des sources :** consommation réseau quotidienne, productions PV disponibles, coûts, injection annuelle, données météo, facture EDF OA. Les données Linky importées ajoutent la consommation soutirée et l'injection réseau mesurées ; l'injection Linky ne doit pas être confondue avec la production photovoltaïque totale.

**Calculé :** autoconsommation annuelle, besoin électrique réel de la maison, autonomie électrique, bilan énergétique annuel, rendement spécifique kWh/kWc, amortissement.

**Estimé :** répartition mensuelle injection/autoconsommation tant qu'une injection mensuelle réelle n'est pas importée ; projection de l'année en cours ; équivalence énergétique entre production P&P et pompe piscine.

Voir `GUIDE_LECTURE.md` pour les définitions détaillées et `CHANGELOG_V2.md` pour les corrections.

## Confidentialité

Le dossier complet contient des documents EDF OA personnels. Pour partager le dashboard sans ces pièces, lancer :

`creer-version-partageable.cmd`

Un ZIP est alors créé dans `exports/` sans `KWH.xlsx`, sans configuration, sans base ni relevés Linky, sans documents EDF, sans backups et sans scripts de travail.

## APsystems — intégration parallèle (12 septembre 2026)

APsystems est intégré au **même serveur** `tools/linky_server.py`. Excel G/H reste
la référence historique ; aucune valeur Excel, Linky, météo ou formule n'est remplacée.
Sans configuration APsystems, le cockpit continue à fonctionner normalement.

### Activation privée

Ajouter les paramètres de `config.example.json` dans `config.local.json`, **sans
remplacer les paramètres Linky existants** : `APSYSTEMS_APP_ID`,
`APSYSTEMS_APP_SECRET`, `APSYSTEMS_SID` (SID du système EMA),
`APSYSTEMS_BASE_URL` (`https://api.apsystemsema.com:9282`, seul hôte autorisé).
L'ancien nom `APSYSTEMS_SYSTEM_ID` reste accepté pour préserver les configurations.
Ne jamais coller ces identifiants dans le navigateur, un rapport ou une capture.
Redémarrer le cockpit après modification de la configuration.

**Correction du 20/09/2026, exemple APsystems Support :** le timestamp est
`str(int(time.time()))`, en **secondes**, le nonce `str(uuid.uuid4()).replace('-', '')`,
et `requestPath = url.split('/')[-1]` (le SID pour `/details/{SID}`). La signature
est HMAC-SHA256, UTF-8, Base64 standard. L'ancien paramètre
`APSYSTEMS_TIMESTAMP_UNIT` est désormais ignoré : il ne peut plus réactiver les
millisecondes. La configuration locale a été alignée sur `seconds`.
Les essais mock ne nécessitent aucun véritable identifiant.

Diagnostic minimal : `python tools/test_apsystems_connection.py`. Chaque exécution
effectue au plus **un** appel `/details`, sans retry, sans historique ni snapshot,
et comptabilise la tentative dans SQLite. L'affichage masque APP ID/SID, nonce
et signature ; le JSON utile est décrit par ses types, sans exposer ses valeurs
privées ni `authorization_code`. Ne pas relancer en boucle.

Le test du 20/09/2026 a renvoyé HTTP 200, JSON `{"code":2004}` malgré cette
correction. La suite de l'intégration réelle est arrêtée conformément au patch
demandé. Voir `reports/patch-apsystems-support-2026-09-20.md` et le diagnostic
masqué associé. Aucun test réel de synchronisation n'a été effectué ce jour-là.

Après découverte, consulter « Équipements et contrôle API ↔ Excel ». Renseigner
`APSYSTEMS_ECU_MAPPING`, par exemple `{"ECU_FICTIF_TOITURE":"MAIN"}`.
MAIN = totalité de la toiture (colonne H), PLUG = totalité du Plug & Play (colonne G).
Plusieurs ECU peuvent appartenir à une même installation et sont alors additionnés.
Vérifier que cette association couvre **tous** les panneaux de l'installation :
le logiciel ne peut pas le déduire d'un identifiant. Si un ECU mélange les deux
installations, ne pas l'associer : le mapping par micro-onduleur reste à développer.
Un seul SID est pris en charge dans cette première phase.

### Collecte, quota et fonctionnement hors ligne

- Cumuls système : jour, mois, année, durée de vie, en kWh.
- Équipements détectés et état de communication global, sans conserver le code
  d'autorisation de partage renvoyé par l'API.
- Journées par ECU : mois courant, et clôture du mois précédent durant les sept
  premiers jours du mois. Lecture au plus une fois par jour ; pas de rechargement
  automatique des années anciennes. Un historique antérieur ou un long arrêt
  nécessitera une évolution dédiée, pas une modification silencieuse d'Excel.
- Courbe ECU `minutely` : puissance W et énergie kWh conservées séparément.
  L'API fournit une heure locale sans offset : les points ambigus aux changements
  d'heure sont exclus, jamais alignés de force sur Linky. L'énergie de ces points
  n'est pas utilisée pour de nouveaux calculs d'autoconsommation.
- Puissance « actuelle » uniquement si mesure de moins de 20 minutes ; sinon `--`.
  Une production du jour en cours n'est jamais comparée à une journée Excel close.

**Patch support du 20/09/2026 : synchronisation manuelle uniquement.**
`APSYSTEMS_AUTO_SYNC` reste `false` ; le loader force le mode manuel et le callback
automatique est inactif, même si une ancienne configuration contient `true`.
L'ancien calcul de créneaux reste disponible pour une évolution future testée,
mais aucun polling externe n'est activé. Le bouton existant n'est pas une preuve
de connexion réussie : ne pas le relancer tant que le refus 2004 n'est pas résolu.
Un cycle ordinaire coûte `1 + N` appels pour N ECU. Le premier ajoute la découverte,
l'état système et `N` lectures mensuelles (et éventuellement `N` clôtures).
Chaque nouvelle journée ajoute un appel d'état système et `N` lectures mensuelles.
Pour deux ECU : 7 appels au premier cycle hors clôture, puis 3 par cycle ordinaire ;
ancien budget théorique planifié `124 × 3 + 32 × 2 + 33 = 469` appels/mois
(31 jours). Cette estimation ne décrit plus un planning actif.

Le compteur SQLite enregistre **chaque tentative HTTP avant émission**, erreurs
comprises, sans retry automatique. Limites locales : 700 appels automatiques et
900 appels totaux par mois, sur le forfait annoncé de 1 000. Ce compteur est une
estimation locale : les appels d'autres applications ne sont pas connus. Un échec
avant émission après réservation peut surestimer le compteur, jamais le minorer.

Les données acquises restent en SQLite après erreur. `site/apsystems-data.js`
conserve un snapshot privé pour l'ouverture sans serveur (aucun APP ID/secret).
Ne pas partager ce fichier brut : il contient des identifiants d'équipements et
des relevés. Le script d'export public le remplace par un état neutre et exclut
aussi son fichier temporaire. `logs/apsystems.log` utilise une rotation et ne
contient ni réponse brute, ni identifiant, ni secret, ni signature.

### Vérification

```text
python -m unittest discover -s tests -v
node tests/test_apsystems_ui.cjs
node --check site/app.js
demarrer-cockpit.cmd
```

Routes ajoutées : `GET /api/apsystems/status`, `GET /api/apsystems/daily`,
`GET /api/apsystems/power-curve`, `POST /api/apsystems/sync` (JSON même origine).
Les routes de données acceptent `start` et `end` au format AAAA-MM-JJ ; pour la
courbe, les bornes sont des dates UTC. Aucun identifiant secret n'est renvoyé.
La migration ne crée que quatre tables `apsystems_*` au premier accès configuré.

Documentation de référence : [APsystems OpenAPI End User, v1.8 du 18/07/2025](https://file.apsystemsema.com:8083/apsystems/resource/openapi/Apsystems_OpenAPI_User_Manual_End_User_EN.pdf),
consultée le 12/09/2026. Authentification HMAC-SHA256 puis Base64, signature du
dernier segment de chemin selon §2.2. Endpoints utilisés :

```text
GET https://api.apsystemsema.com:9282/user/api/v2/systems/details/{sid}
GET https://api.apsystemsema.com:9282/user/api/v2/systems/inverters/{sid}
GET https://api.apsystemsema.com:9282/user/api/v2/systems/summary/{sid}
GET https://api.apsystemsema.com:9282/user/api/v2/systems/{sid}/devices/ecu/energy/{eid}
    energy_level=daily&date_range=AAAA-MM
    energy_level=minutely&date_range=AAAA-MM-JJ
```

Restent à valider sur le compte réel : droits des endpoints,
SID, ECU virtuels éventuels, mapping, délais de remontée, complétude des agrégats,
quota partagé et comportement réel aux changements d'heure. Le manuel ne garantit
pas qu'un agrégat journalier non nul prouve l'absence d'une coupure de communication.
La comparaison porte donc sur les journées closes renseignées, pas sur une
certification de chaque intervalle de mesure.
