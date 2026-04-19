# ⚡ Electricity Cost

🇫🇷 [Lire en français](README_FR.md)

A [Home Assistant](https://www.home-assistant.io/) custom integration to track electricity consumption and cost **per device and per tariff** — with real-time pricing from your existing `input_number` entities.

---

## Features

- **Multi-tariff support** — define as many tariffs as you need (e.g. Off-Peak, Peak, Weekend)
- **Live pricing** — prices are read from `input_number` entities; updating a price instantly updates all related costs
- **Per-device energy metering** — each monitored device gets its own kWh counter per tariff, accumulating only when that tariff is active
- **Global tariff selector** — one `select` entity switches all device meters simultaneously
- **Real-time cost sensors** — cost updates instantly as energy accumulates (direct push, zero polling delay)
- **Manual reset** — call the `electricity_cost.reset` action directly on any meter entity, no extra configuration needed
- **Automated reset** *(optional)* — link a `switch`, `input_boolean`, or `binary_sensor`; an OFF→ON transition resets the meters automatically
- **Persistent across restarts** — all accumulated values survive Home Assistant restarts via `RestoreEntity`
- **Clean device registry** — each monitored device appears in the HA device list with all its entities grouped underneath
- **Add and remove devices** — manage devices at any time from the integration's ⚙ settings menu

---

## How it works

```
┌────────────────────────────────────────────────────┐
│                  Electricity Cost                  │
│                                                    │
│       select.electricity_cost_active_tariff        │ ← you control this
│               (Off-Peak / Peak / …)                │
│                         │                          │
│     ┌───────────────────▼────────────────────┐     │
│     │            Washing Machine             │     │
│     │                                        │     │
│     │ sensor.washing_machine_off_peak_energy │     │ ← kWh counter 
│     │ sensor.washing_machine_peak_energy     │     │ ← kWh counter
│     │                                        │     │
│     │ sensor.washing_machine_off_peak_cost   │     │ ← € = kWh × price
│     │ sensor.washing_machine_peak_cost       │     │ ← € = kWh × price
│     └────────────────────────────────────────┘     │
└────────────────────────────────────────────────────┘
```

Each energy meter only accumulates kWh when its tariff matches the active one. Switching the global selector instantly changes which meter counts.

---

## Requirements

- Home Assistant **2023.4** or later (tested on **2026.4**)
- [HACS](https://hacs.xyz/) installed
- One `input_number` entity per tariff holding the price in €/kWh
- One `sensor` entity with `device_class: energy` per device to monitor

---

## Installation via HACS

> Don't have HACS yet? [Install HACS here](https://hacs.xyz/docs/use/download/download/).

1. Open HACS in your Home Assistant sidebar
2. Click the **⋮** menu (top right) → **Custom repositories**
3. Paste your repository URL and select category **Integration**
4. Click **Add**
5. Search for **Electricity Cost** in HACS → **Download**
6. Restart Home Assistant

---

## Manual installation

1. Copy the `electricity_cost` folder into `/config/custom_components/`
2. Restart Home Assistant

---

## Configuration

### Step 1 — Create price entities

Create one `input_number` per tariff (**Settings → Helpers → Create helper → Number**):

| Helper | Unit | Example |
|---|---|---|
| `input_number.price_off_peak` | €/kWh | 0.2068 |
| `input_number.price_peak` | €/kWh | 0.2530 |

Or via `configuration.yaml`:

```yaml
input_number:
  price_off_peak:
    name: "Price Off-Peak"
    initial: 0.2068
    min: 0
    max: 2
    step: 0.0001
    unit_of_measurement: "€/kWh"
    mode: box

  price_peak:
    name: "Price Peak"
    initial: 0.2530
    min: 0
    max: 2
    step: 0.0001
    unit_of_measurement: "€/kWh"
    mode: box
```

### Step 2 — Add the integration

1. Go to **Settings → Devices & services → + Add integration**
2. Search for **Electricity Cost**
3. **Step 1 — Tariffs:** enter your tariff names, comma-separated:
   ```
   Off-Peak, Peak
   ```
4. **Step 2 — Price entities:** select the `input_number` for each tariff

### Step 3 — Add a device

1. Go to **Settings → Devices & services → Electricity Cost → ⚙ Configure**
2. Choose **Add a device**
3. Fill in:

| Field | Required | Description |
|---|---|---|
| Device name | ✅ | Display name, e.g. `Washing Machine` |
| Energy sensor | ✅ | A `sensor` with `device_class: energy` |
| Reset entity | ❌ | A `switch` or `binary_sensor` — turns ON triggers a full meter reset |

---

## Entities created

### Global (one per integration)

| Entity | Description |
|---|---|
| `select.electricity_cost_active_tariff` | Active tariff — changing it switches all meters at once |

### Per device (example: "Washing Machine", tariffs Off-Peak / Peak)

| Entity | Description |
|---|---|
| `sensor.washing_machine_off_peak_energy` | kWh accumulated on Off-Peak |
| `sensor.washing_machine_peak_energy` | kWh accumulated on Peak |
| `sensor.washing_machine_off_peak_cost` | Cost in € for Off-Peak (live) |
| `sensor.washing_machine_peak_cost` | Cost in € for Peak (live) |

---

## Automations

### Schedule-based tariff switching (EDF HC/HP example)

```yaml
automation:
  - alias: "Switch to Off-Peak (10 PM)"
    triggers:
      - trigger: time
        at: "22:00:00"
    actions:
      - action: select.select_option
        target:
          entity_id: select.electricity_cost_active_tariff
        data:
          option: Off-Peak

  - alias: "Switch to Peak (6 AM)"
    triggers:
      - trigger: time
        at: "06:00:00"
    actions:
      - action: select.select_option
        target:
          entity_id: select.electricity_cost_active_tariff
        data:
          option: Peak
```

### Meter reset

Call the `electricity_cost.reset` action directly — no prior configuration needed:

```yaml
action: electricity_cost.reset
target:
  entity_id:
    - sensor.washing_machine_energy_off_peak
    - sensor.washing_machine_energy_peak
```

You can target a single meter or all meters for a device at once. Works directly from **Developer Tools → Actions** in Home Assistant.

> The reset via entity (OFF→ON) is still available as an automated alternative (see [Configuration](#configuration)).

---

## Dashboard example

```yaml
type: vertical-stack
cards:
  - type: entities
    title: Active tariff
    entities:
      - entity: select.electricity_cost_active_tariff
      - entity: input_number.price_off_peak
      - entity: input_number.price_peak

  - type: entities
    title: Washing Machine
    entities:
      - entity: sensor.washing_machine_off_peak_energy
        name: "Energy Off-Peak (kWh)"
      - entity: sensor.washing_machine_peak_energy
        name: "Energy Peak (kWh)"
      - entity: sensor.washing_machine_off_peak_cost
        name: "Cost Off-Peak (€)"
      - entity: sensor.washing_machine_peak_cost
        name: "Cost Peak (€)"
```

---

## Removing a device

1. **Settings → Devices & services → Electricity Cost → ⚙ Configure**
2. Choose **Remove a device**
3. Select the device — all its entities are removed from the registry automatically

---

## Publishing updates (maintainers)

1. Bump `version` in `manifest.json`
2. Push a tag — the release is created automatically:
   ```
   git tag 1.2.0 && git push --tags
   ```
3. HACS notifies users of the update automatically

The release workflow is defined in [`.github/workflows/release.yml`](.github/workflows/release.yml).

---

## License

MIT

---

## AI notice

This project was developed with the assistance of AI tools.
