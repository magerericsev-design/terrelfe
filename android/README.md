# Cockpit Solaire pour Android

Version Android autonome : l’interface existante et son moteur Python sont embarqués dans la même application avec Chaquopy. Aucun PC ni serveur distant personnel n’est nécessaire.

## Utilisation prévue

- Android 8.0 ou plus récent, téléphone 64 bits (ARM64). La variante x86_64 sert aux émulateurs.
- Consultation hors ligne des données et graphiques fournis.
- Les mises à jour Linky/APsystems nécessitent Internet et vos droits d’accès API.
- **Réglages** : saisir le jeton MyElectricalData, le PDL et/ou les trois identifiants APsystems. Ils restent dans le stockage privé de l’application. La configuration Windows n’est jamais incluse dans l’APK.
- **Excel** : sélectionner le classeur KWH.xlsx avec les mêmes feuilles et colonnes que l’original. Enregistrer/recalculer les formules dans Excel avant import : openpyxl ne les recalcule pas.
- **Météo ↻** : actualisation manuelle des données de Météo-France.
- Les boutons Linky/APsystems du tableau de bord actualisent leurs propres mesures. APsystems reste manuel pour respecter le quota ; le refus API 2004 mentionné dans le programme d’origine ne peut pas être corrigé par le portage Android.
- L’import Excel actualise la référence historique. Les mesures API restent séparées, conformément aux calculs d’origine.

Le paquet contient vos historiques énergétiques et données d’installation : il est destiné à votre usage personnel. Il ne contient pas `config.local.json`, les logs, les sauvegardes ZIP ou les exécutables Windows. La désinstallation efface les données et réglages stockés sur le téléphone. Les mises à jour de l’APK conservent les données locales.

## Compiler

Prérequis : JDK 21, Python 3.12, SDK Android 35, Build Tools 35.0.0. Gradle 8.9 est fourni via le wrapper avec contrôle SHA-256.

Depuis la racine du dépôt :

```sh
python3 android/tools/prepare_assets.py
python3 -m pip install openpyxl==3.1.5 tzdata==2025.2
python3 android/tests/test_backend.py
cd android
./gradlew --no-daemon :app:assembleDebug
```

`ANDROID_HOME` doit pointer vers le SDK, ou `android/local.properties` doit contenir `sdk.dir=/chemin/du/sdk`. Sur le cloud sous `/workspace`, `bash android/tools/setup_cloud.sh` prépare les outils, teste le moteur et lance la compilation. Les outils sont conservés hors du dépôt dans `/workspace/android-tools`.

APK compilé : `android/app/build/outputs/apk/debug/app-debug.apk`. Une copie à installer est disponible dans `android/apk/Cockpit-Solaire-0.1.apk`. C’est un APK de développement, signé par la clé de test de la machine de compilation, sans publication Play Store. La clé de test est conservée dans `android/.local/debug.keystore` (exclue de Git). Conservez-la pour pouvoir installer les prochaines versions sans désinstaller l’application.

Autre possibilité : dans GitHub, ouvrir **Actions → APK Android → Run workflow**. Après succès, télécharger l’artefact **Cockpit-Solaire-Android**, décompresser le ZIP puis transférer l’APK sur le téléphone. Ce workflow est manuel ; il n’a pas été lancé pendant la préparation.

## État des vérifications

- Cinq tests d’intégration du moteur passés : historique SQLite, ressources, exclusion des fichiers privés, protection des mutations et réglages/import Excel.
- Sept pages vérifiées dans Chromium avec un écran tactile de 393 × 851, sans erreur JavaScript ni débordement horizontal.
- Compilation APK réussie et reproduite avec `tools/setup_cloud.sh`. Signature APK v2 vérifiée, deux architectures embarquées : ARM64 et x86_64. Absence des valeurs des jetons API vérifiée dans le paquet. La configuration réseau nécessaire et les instructions réutilisables sont enregistrées dans le brouillon cloud.
- Installation sur Android, lancement du Python embarqué sur appareil, actualisation météo réelle et appels aux comptes Linky/APsystems restent à vérifier. Aucun appel réel aux comptes n’a été effectué.

Les sources et fichiers du programme Windows restent inchangés. `tools/prepare_assets.py` prépare une copie avec les chemins `assets/` rétablis et une feuille de style mobile supplémentaire.
