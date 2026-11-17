# MMOUi Enel Energia Italy

> **Fork** di [sathia-musso/enelgrid](https://github.com/sathia-musso/enelgrid), creato da Sathia Francesco Musso.
> La versione 2.x è una riscrittura: corregge la corruzione delle statistiche della v1.6.0, il sensore mensile
> e l'ora legale, aggiunge le bollette e modernizza l'integrazione (vedi il [CHANGELOG](CHANGELOG.md)).

Integrazione per Home Assistant che legge dall'area clienti **Enel Energia**:

- i **consumi orari** di energia elettrica, importati come statistiche e pronti per la **dashboard Energia**;
- le **bollette**: ultima bolletta, bolletta precedente e totale ancora da pagare, con emissione, scadenza, periodo e stato.

## Requisiti

Prima di configurare l'integrazione servono:

| Requisito | Dettagli |
|---|---|
| Home Assistant | **2025.11** o successivo, con il `recorder` attivo (lo è di default) |
| HACS | per l'installazione consigliata |
| Account area clienti Enel Energia | **email e password** con cui entri su [enel.it](https://www.enel.it/it/login). Funziona solo l'accesso con email e password, non quello con SPID o con i social |
| Fornitura di energia elettrica Enel Energia | attiva e visibile nell'area clienti dello stesso account |
| **POD** | codice della fornitura, es. `IT001E12345678`: lo trovi in bolletta o nell'area clienti, nei dettagli della fornitura |
| **Numero utente** (numero cliente) | solo cifre, lo trovi in bolletta. Gli zeri iniziali vengono mantenuti |
| Prezzo per kWh | stima per la statistica dei costi: totale della bolletta diviso i kWh consumati. Si può cambiare in seguito dalle opzioni |

Per le **bollette** non serve altro: si usano le stesse credenziali e la fornitura viene riconosciuta dal POD.
Se l'account ha più forniture, ognuna si aggiunge come voce separata dell'integrazione.

## Installazione

### HACS

[![Apri il repository in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=mattiaouiapp&repository=HomeAssistant_HACS_EnelEnergia&category=integration)

1. Premi il pulsante qui sopra, oppure HACS → menu ⋮ → **Repository personalizzati** → aggiungi `https://github.com/mattiaouiapp/HomeAssistant_HACS_EnelEnergia`, categoria **Integrazione**.
2. Cerca **MMOUi Enel Energia Italy** e installala.
3. Riavvia Home Assistant.
4. **Impostazioni → Dispositivi e servizi → Aggiungi integrazione** → cerca **MMOUi Enel Energia Italy** e inserisci i dati dei [requisiti](#requisiti).

### Manuale

1. Copia `custom_components/enelgrid` in `<config>/custom_components/enelgrid`.
2. Riavvia Home Assistant e aggiungi l'integrazione da **Impostazioni → Dispositivi e servizi**.

### Aggiornamento

HACS → **MMOUi Enel Energia Italy** → **Aggiorna**, poi riavvia Home Assistant.
Se HACS non propone l'aggiornamento: menu ⋮ → **Aggiorna informazioni**.

## Primo avvio

- Alla prima configurazione viene importato **tutto lo storico disponibile** su Enel (fino a 4 anni), in background.
- Poi l'integrazione si aggiorna ogni **12 ore**: scarica i consumi dal mese precedente a oggi e l'archivio delle bollette.
- Enel pubblica i consumi con circa **3 giorni di ritardo**: gli ultimi giorni risultano vuoti o parziali.
- Se Home Assistant è rimasto spento, al riavvio vengono recuperati i giorni mancanti (fino a un anno).

## Dashboard Energia

**Impostazioni → Dashboard → Energia** → consumo dalla rete: scegli la statistica `Enel <POD> Consumption` e,
come costo, l'entità che traccia i costi totali `Enel <POD> Cost`.

![Configurazione dashboard Energia](assets/energy_config.jpg)

![Esempio](assets/example.jpg)

## Dashboard pronta "Consumi Enel"

Nel file [`dashboard/consumi-enel.yaml`](dashboard/consumi-enel.yaml) c'è una dashboard completa da copiare:

- **Riepilogo**: consumo dell'ultima settimana, del mese, del mese scorso e dell'anno, costo del mese e dell'anno;
- **Bollette**: ultima bolletta (stato, giorni alla scadenza, emissione, scadenza, periodo, importo) e bolletta precedente;
- **Andamento**: consumo orario, giornaliero e mensile, costo mensile stimato.

Usa solo card standard di Home Assistant, non servono card aggiuntive.

1. Sostituisci ovunque `it001e12345678` con il tuo POD in minuscolo.
2. **Impostazioni → Dashboard → Aggiungi dashboard → Nuova dashboard da zero**, aprila, matita → menu ⋮ →
   **Editor di configurazione grezza**, incolla tutto il file e salva.
   Per aggiungere solo la vista a una dashboard esistente, copia l'elemento sotto `views:`.
3. Se le card delle bollette mostrano "Dati bolletta non ancora disponibili", controlla gli entity id nella pagina
   del dispositivo (vedi [Entità e statistiche](#entità-e-statistiche)): con Home Assistant in italiano sono per
   esempio `sensor.enel_<pod>_ultima_bolletta` invece di `sensor.enel_<pod>_last_bill`.
   Le statistiche `sensor:enelgrid_<pod>_...` e `sensor.enelgrid_<pod>_monthly_consumption` hanno sempre lo stesso nome.

## Bollette

Le bollette arrivano dall'archivio dell'area clienti (le stesse che vedi su enel.it in *Bollette*) e si aggiornano
insieme ai consumi. Se l'archivio non risponde, i consumi continuano ad aggiornarsi: l'errore compare
nell'attributo `error` di *Amount due* e nella diagnostica.

| Sensore | Valore | Attributi |
|---|---|---|
| **Last bill** (ultima bolletta) | importo in € | `issue_date` (emissione), `due_date` (scadenza), `period` (es. `gennaio - febbraio 2025`), `period_start`, `period_end`, `status` (`Da pagare` / `Pagata`), `amount_due` (ancora da pagare), `paid_on`, `overdue` (scaduta), `tv_fee` (canone TV) |
| **Previous bill** (bolletta precedente) | importo in € | come *Last bill* |
| **Amount due** (totale da pagare) | € ancora da pagare | `unpaid_bills` (quante), `next_due_date` (prossima scadenza), `overdue`, `error` |

Esempio di card Markdown per l'ultima bolletta (sostituisci l'entità con la tua):

```yaml
type: markdown
title: Ultima bolletta
content: |-
  {% set b = 'sensor.enel_it001e12345678_last_bill' %}
  {% if states(b) in ['unknown', 'unavailable'] %}
  Dati bolletta non ancora disponibili.
  {% else %}
  ## {{ '🟢' if state_attr(b, 'amount_due') | float(0) == 0 else ('🔴' if state_attr(b, 'overdue') else '🟠') }} {{ state_attr(b, 'status') }}: {{ '%.2f' | format(states(b) | float(0)) }} €

  | | |
  |:--|--:|
  | Emissione | {{ strptime(state_attr(b, 'issue_date'), '%Y-%m-%d').strftime('%d/%m/%Y') }} |
  | Scadenza | {{ strptime(state_attr(b, 'due_date'), '%Y-%m-%d').strftime('%d/%m/%Y') }} |
  | Periodo | {{ state_attr(b, 'period') | capitalize }} |
  {% endif %}
```

Con *Amount due* si possono fare automazioni, per esempio una notifica quando `overdue` diventa `true`.

## Entità e statistiche

| Nome | Tipo | Note |
|---|---|---|
| `sensor:enelgrid_<pod>_consumption` | statistica esterna (kWh) | oraria, da usare nella dashboard Energia |
| `sensor:enelgrid_<pod>_kw_cost` | statistica esterna (EUR) | costo orario stimato |
| Current month consumption | sensore (kWh) | entity id fisso: `sensor.enelgrid_<pod>_monthly_consumption` |
| Previous month consumption | sensore (kWh) | |
| Last available day consumption | sensore (kWh) | attributo `date` |
| Current month estimated cost | sensore (EUR) | attributo `price_per_kwh` |
| Last available data | timestamp diagnostico | attributo `historical_import` |
| Last bill / Previous bill / Amount due | sensori (EUR) | vedi [Bollette](#bollette) |

Gli entity id dei sensori dipendono dal nome del dispositivo (`Enel <POD>`) e dalla lingua di Home Assistant
al momento della configurazione, per esempio `sensor.enel_it001e12345678_last_bill` in inglese o
`sensor.enel_it001e12345678_ultima_bolletta` in italiano. Li trovi nella pagina del dispositivo.
I sensori riassumono l'ultimo download; lo storico vero dei consumi è nelle statistiche.

## Opzioni e diagnostica

- **Opzioni** (Impostazioni → Dispositivi e servizi → MMOUi Enel Energia Italy → **Configura**): prezzo per kWh.
  Si applica dal mese precedente in poi; i costi più vecchi restano invariati.
- **Password cambiata**: Home Assistant chiede da solo di reinserire le credenziali.
- **Diagnostica**: menu ⋮ dell'integrazione → **Scarica diagnostica**. Credenziali, POD e numero utente vengono oscurati.

## Passaggio dall'integrazione originale (1.x)

Il dominio è sempre `enelgrid`, quindi questa integrazione sostituisce l'originale senza perdere configurazione,
statistiche e impostazioni della dashboard Energia. **Non installarle entrambe.**

- La configurazione viene migrata da sola e **le statistiche vengono ricostruite da zero** con tutto lo storico
  Enel, perché la v1.6.0 le rovinava a ogni aggiornamento (salto enorme il primo giorno del mese precedente).
- Il vecchio sensore `enelgrid Daily Import` non esiste più: usa *Last available data*.
- La cartella `/config/enelgrid_debug` non viene più scritta e si può cancellare.

## Limiti

- Enel non offre API pubbliche: l'integrazione usa le stesse chiamate del sito dell'area clienti, che Enel può
  cambiare senza preavviso.
- Solo forniture di energia elettrica Enel Energia; gas e fibra non sono gestiti.

## Crediti e licenza

Integrazione originale di [Sathia Francesco Musso](https://github.com/sathia-musso/enelgrid);
questo fork è mantenuto da [mattiaouiapp](https://github.com/mattiaouiapp). Licenza MIT, vedi [LICENSE](LICENSE).
