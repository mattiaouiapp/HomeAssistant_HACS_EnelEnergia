# Home Assistant - enelgrid Integration

This custom integration for Home Assistant retrieves and imports **hourly and daily energy consumption data** from **Enel Italia**, making it available in Home Assistant's **Energy Dashboard**.

## 📋 Features

- 📊 Automatic login using Enel's SAML authentication process.
- 🕒 Imports **hourly** consumption (Enel publishes data with a ~3 day delay) as long-term statistics, ready for the **Energy dashboard**.
- 📚 Imports the **whole available history** (up to 4 years) on first setup.
- 💶 Cost statistic based on a configurable price per kWh (changeable from the integration options).
- 📈 Summary sensors: current month, previous month, last available day, estimated monthly cost, last available data.
- 🔁 Updates every 12 hours, fills gaps if Home Assistant was offline.
- 🔐 Re-authentication flow when the Enel password changes.
- 🩺 Diagnostics download (Settings → Devices & Services → enelgrid → ⋮ → Download diagnostics).

Requires Home Assistant **2025.11** or newer.

## 🛠️ Installation

### Installation via HACS (Recommended)

1. In **HACS**, add this repository as a **Custom Repository** (category *Integration*).
2. Search for **"enelgrid"** and install.
3. Restart Home Assistant.
4. Go to **Settings → Devices & Services → Add Integration** and search for **"enelgrid"**.

### Manual Installation

1. Copy `custom_components/enelgrid` into `config/custom_components/enelgrid`.
2. Restart Home Assistant and add the integration from **Settings → Devices & Services**.

## ⚙️ Configuration

During setup you need:

- **Email** and **Password** of the Enel customer area
- **POD** (e.g. `IT001E12345678`, printed on the bill)
- **User number** (printed on the bill)
- **Price per kWh**: total bill amount divided by the kWh consumed is a reasonable estimate. It can be changed later from the integration options (applied from the previous month onwards).

Then go to **Settings → Dashboards → Energy** and add as grid consumption the statistic
`Enel <POD> Consumption`, with `Enel <POD> Cost` as entity tracking the total costs:

![Energy configuration](assets/energy_config.jpg)

Result:

![Example](assets/example.jpg)

## 📊 Entities and statistics

| Name | Type | Notes |
|---|---|---|
| `sensor:enelgrid_<pod>_consumption` | external statistic (kWh) | hourly, use it in the Energy dashboard |
| `sensor:enelgrid_<pod>_kw_cost` | external statistic (EUR) | hourly cost |
| Current month consumption | sensor (kWh) | entity id kept from v1: `sensor.enelgrid_<pod>_monthly_consumption` |
| Previous month consumption | sensor (kWh) | |
| Last available day consumption | sensor (kWh) | attribute `date` |
| Current month estimated cost | sensor (EUR) | |
| Last available data | diagnostic timestamp | attribute `historical_import` |

The sensors only summarise the latest download: the authoritative history is in the statistics.

## ⬆️ Upgrading from 1.x

The upgrade is automatic. The configuration is migrated (version 5) and **the statistics are rebuilt
from scratch** with the full Enel history, because v1.6.0 corrupted them on every daily update
(the first day of the previous month received a huge jump). The statistic ids do not change, so the
Energy dashboard configuration keeps working.

The old `enelgrid Daily Import` text sensor has been removed (use *Last available data* instead), and
the `/config/enelgrid_debug` folder is no longer written: it can be deleted.

## 🔗 Links

- 📖 [Enel Portal](https://www.enel.it/)
- 📘 [Home Assistant Docs](https://www.home-assistant.io/integrations/)

## 🧑‍💻 Developer

This integration was originally developed by [Sathia Francesco Musso](https://github.com/sathia-musso/enelgrid/).
This repository is a fork with the 2.0.0 rewrite (see [CHANGELOG](CHANGELOG.md)).  
Contributions and feedback are welcome!

---

## 📜 License

This project is licensed under the MIT License.
