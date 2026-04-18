# ⚡ Coût électricité

🇬🇧 [Read in English](README.md)

Une intégration personnalisée [Home Assistant](https://www.home-assistant.io/) pour suivre la consommation et le coût d'électricité **par appareil et par tarif** — avec des prix en temps réel lus depuis vos entités `input_number` existantes.

---

## Fonctionnalités

- **Multi-tarifs** — définissez autant de tarifs que nécessaire (ex : HC, HP, Weekend)
- **Prix dynamiques** — les prix sont lus depuis des entités `input_number` ; modifier un prix met à jour tous les coûts instantanément
- **Compteurs d'énergie par appareil** — chaque appareil surveillé dispose de son propre compteur kWh par tarif, qui n'accumule que lorsque ce tarif est actif
- **Sélecteur de tarif global** — une seule entité `select` bascule tous les compteurs simultanément
- **Capteurs de coût en temps réel** — le coût se met à jour instantanément à chaque accumulation (push direct, zéro délai)
- **Reset manuel** — appelez l'action `electricity_cost.reset` directement sur un compteur, sans configuration supplémentaire
- **Reset automatisé** *(optionnel)* — configurez une entité de reset (`switch`, `input_boolean` ou `binary_sensor`) ; un passage OFF→ON remet les compteurs à zéro automatiquement
- **Persistance au redémarrage** — toutes les valeurs accumulées survivent aux redémarrages via `RestoreEntity`
- **Registre d'appareils propre** — chaque appareil surveillé apparaît dans la liste HA avec toutes ses entités regroupées
- **Ajout et suppression d'appareils** — gérez vos appareils à tout moment depuis le menu ⚙ de l'intégration

---

## Comment ça fonctionne

```
┌────────────────────────────────────────────────────┐
│                  Electricity Cost                  │
│                                                    │
│       select.electricity_cost_active_tariff        │ ← vous contrôlez ça 
│                   (HC / HP / …)                    │
│                         │                          │
│     ┌───────────────────▼────────────────────┐     │
│     │               Lave-linge               │     │
│     │                                        │     │
│     │      sensor.lave_linge_energie_hc      │     │ ← compteur kWh
│     │      sensor.lave_linge_energie_hp      │     │ ← compteur kWh
│     │                                        │     │
│     │      sensor.lave_linge_cout_hc         │     │ ← € = kWh × prix
│     │      sensor.lave_linge_cout_hp         │     │ ← € = kWh × prix
│     └────────────────────────────────────────┘     │
└────────────────────────────────────────────────────┘
```

Chaque compteur n'accumule des kWh que lorsque son tarif correspond au tarif actif. Changer le sélecteur global bascule instantanément quel compteur est actif.

---

## Prérequis

- Home Assistant **2023.4** ou plus récent (testé sur **2026.4**)
- [HACS](https://hacs.xyz/) installé
- Une entité `input_number` par tarif pour stocker le prix en €/kWh
- Une entité `sensor` avec `device_class: energy` par appareil à surveiller

---

## Installation via HACS

> Vous n'avez pas encore HACS ? [Installez HACS ici](https://hacs.xyz/docs/use/download/download/).

1. Ouvrez HACS dans la barre latérale de Home Assistant
2. Cliquez sur le menu **⋮** (en haut à droite) → **Dépôts personnalisés**
3. Collez l'URL de votre dépôt et sélectionnez la catégorie **Intégration**
4. Cliquez sur **Ajouter**
5. Recherchez **Electricity Cost** dans HACS → **Télécharger**
6. Redémarrez Home Assistant

---

## Installation manuelle

1. Copiez le dossier `electricity_cost` dans `/config/custom_components/`
2. Redémarrez Home Assistant

---

## Configuration

### Étape 1 — Créer les entités de prix

Créez un `input_number` par tarif (**Paramètres → Entrées → Créer une entrée → Nombre**) :

| Entrée | Unité | Exemple |
|---|---|---|
| `input_number.prix_hc` | €/kWh | 0.2068 |
| `input_number.prix_hp` | €/kWh | 0.2530 |

Ou via `configuration.yaml` :

```yaml
input_number:
  prix_hc:
    name: "Prix HC"
    initial: 0.2068
    min: 0
    max: 2
    step: 0.0001
    unit_of_measurement: "€/kWh"
    mode: box

  prix_hp:
    name: "Prix HP"
    initial: 0.2530
    min: 0
    max: 2
    step: 0.0001
    unit_of_measurement: "€/kWh"
    mode: box
```

### Étape 2 — Configurer l'intégration

1. Allez dans **Paramètres → Appareils et services → + Ajouter une intégration**
2. Recherchez **Electricity Cost**
3. **Étape 1 — Tarifs :** entrez les noms de vos tarifs séparés par des virgules :
   ```
   HC, HP
   ```
4. **Étape 2 — Entités de prix :** sélectionnez le `input_number` correspondant à chaque tarif

### Étape 3 — Ajouter un appareil

1. Allez dans **Paramètres → Appareils et services → Electricity Cost → ⚙ Configurer**
2. Choisissez **Ajouter un appareil**
3. Renseignez :

| Champ | Requis | Description |
|---|---|---|
| Nom de l'appareil | ✅ | Nom d'affichage, ex. `Lave-linge` |
| Capteur de consommation | ✅ | Un `sensor` avec `device_class: energy` |
| Entité de reset | ❌ | Un `switch` ou `binary_sensor` — son passage à ON déclenche un reset |

---

## Entités créées

### Globales (une par intégration)

| Entité | Description |
|---|---|
| `select.electricity_cost_active_tariff` | Tarif actif — le changer bascule tous les compteurs d'un coup |

### Par appareil (exemple : "Lave-linge", tarifs HC / HP)

| Entité | Description |
|---|---|
| `sensor.lave_linge_energie_hc` | kWh accumulés sur le tarif HC |
| `sensor.lave_linge_energie_hp` | kWh accumulés sur le tarif HP |
| `sensor.lave_linge_cout_hc` | Coût en € pour le tarif HC (temps réel) |
| `sensor.lave_linge_cout_hp` | Coût en € pour le tarif HP (temps réel) |

---

## Automations

### Basculement de tarif sur horaire (exemple EDF HC/HP)

```yaml
automation:
  - alias: "Passage en HC (22h)"
    triggers:
      - trigger: time
        at: "22:00:00"
    actions:
      - action: select.select_option
        target:
          entity_id: select.electricity_cost_active_tariff
        data:
          option: HC

  - alias: "Passage en HP (6h)"
    triggers:
      - trigger: time
        at: "06:00:00"
    actions:
      - action: select.select_option
        target:
          entity_id: select.electricity_cost_active_tariff
        data:
          option: HP
```

### Reset des compteurs d'un appareil

Appel direct via l'action `electricity_cost.reset` — aucune configuration préalable requise :

```yaml
action: electricity_cost.reset
target:
  entity_id:
    - sensor.lave_linge_energie_hc
    - sensor.lave_linge_energie_hp
```

Vous pouvez aussi cibler un seul compteur, ou tous les compteurs d'un appareil en une seule action. Fonctionne directement depuis **Outils de développement → Actions** dans Home Assistant.

> Le reset via entité (OFF→ON) reste disponible comme alternative automatisée (voir section [Configuration](#configuration)).

---

## Exemple de tableau de bord

```yaml
type: vertical-stack
cards:
  - type: entities
    title: Tarif actif
    entities:
      - entity: select.electricity_cost_active_tariff
      - entity: input_number.prix_hc
      - entity: input_number.prix_hp

  - type: entities
    title: Lave-linge
    entities:
      - entity: sensor.lave_linge_hc_energy
        name: "Énergie HC (kWh)"
      - entity: sensor.lave_linge_hp_energy
        name: "Énergie HP (kWh)"
      - entity: sensor.lave_linge_hc_cost
        name: "Coût HC (€)"
      - entity: sensor.lave_linge_hp_cost
        name: "Coût HP (€)"
```

---

## Supprimer un appareil

1. **Paramètres → Appareils et services → Electricity Cost → ⚙ Configurer**
2. Choisissez **Supprimer un appareil**
3. Sélectionnez l'appareil — toutes ses entités sont supprimées du registre automatiquement

---

## Publier des mises à jour (mainteneurs)

1. Incrémentez `version` dans `manifest.json`
2. Créez une GitHub Release avec le tag `v1.x.x`
3. HACS notifie les utilisateurs de la mise à jour automatiquement

Astuce : avec le GitHub Action ci-dessous, `git tag v1.1.0 && git push --tags` suffit.

```yaml
# .github/workflows/release.yml
name: Release
on:
  push:
    tags: ["v*"]
jobs:
  release:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: softprops/action-gh-release@v1
```

---

## Licence

MIT

---

## Mention IA

Ce projet a été développé avec l'assistance d'outils IA.
