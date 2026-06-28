# i-Vent Smart Home — Home Assistant Integracija

![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)
![Quality Scale](https://img.shields.io/badge/Quality_Scale-Platinum-blue)
![HA Version](https://img.shields.io/badge/Home_Assistant-2024.1+-blue.svg)

Integracija po meri za pametne prezračevalne sisteme **i-Vent**. Omogoča popoln nadzor in avtomatizacijo vaših i-Vent ventilatorskih enot neposredno preko lokalnega Home Assistant sistema z uporabo uradnega i-Vent Cloud API-ja.

Zgrajena z mislijo na Platinum HA standarde: ponuja dinamično zaznavanje naprav, strogo tipiziranje in celovito podporo diagnostiki.

---

## Predpogoji

Za povezavo integracije boste potrebovali:
- **i-Vent cloud račun**, ki ga ustvarite in do dostopate na [https://cloud.i-vent.com/](https://cloud.i-vent.com/).
- **API ključ:** Pojdite v nastavitve uporabnika in ustvarite nov API ključ.
- **ID lokacije:** Ko na nadzorni plošči odprete svojo lokacijo, preberite številko/ID iz URL naslova brskalnika (npr. če je URL `https://cloud.i-vent.com/live/123`, je ID lokacije `123`).

---

## Namestitev

### 1. Možnost: Preko HACS (Priporočeno)
1. V Home Assistantu odprite **HACS** > **Integrations**.
2. Kliknite na tri pikice (zgoraj desno) in izberite **Custom repositories**.
3. Vnesite URL tega repozitorija (`https://github.com/JernejHren/ivent-home-assistant`) in kot tip izberite **Integration**.
4. Kliknite **Add** in nato poiščite `i-Vent Smart Home` ter ga namestite.
5. Ponovno zaženite Home Assistant.

### 2. Možnost: Ročna namestitev
1. Kopiraj celotno mapo `custom_components/ivent/` iz tega repozitorija.
2. Prilepi jo v svojo mapo `config/custom_components/` na Home Assistantu.
3. Znova zaženi Home Assistant.

### Konfiguracija
1. Sledite poti: **Settings (Nastavitve)** → **Devices & Services (Naprave in storitve)** → **Add Integration (Dodaj integracijo)**.
2. Poiščite **i-Vent Smart Home**.
3. Vnesite svoj **API ključ** in **ID lokacije**.
4. Po uspešni potrditvi bo integracija dinamično in samodejno uvozila vse vaše skupine, naprave in urnike.

---

## Podprte entitete

Naprave so v i-Vent sistemu razdeljene na "Skupine" (kjer je lahko združenih več naprav) in na "Posamične naprave".

### Kategorija: Skupinska kontrola

| Entiteta | Platforma | Ikona | Razred | Kategorija | Opis |
|----------|-----------|-------|--------|------------|------|
| **Ventilator** | `fan` | 🌀 | - | - | Vklop/izklop skupine ter nastavitev hitrosti in načina (Rekuperacija/Bypass). |
| **Način prezračevanja** | `select` | ♻️ | - | Nastavitve | Izbira načina ventilacije. |
| **Hitrost ventilatorja** | `select` | 💨 | - | Nastavitve | Explicitna kontrola stopnje hitrosti 1 do 3. |
| **Ime skupine** | `text` | 📝 | - | Nastavitve | Omogoča hitro preimenovanje skupine preko UI. |
| **Izbriši skupino** | `button` | 🗑️ | - | Nastavitve | Sproži brisanje te logične skupine iz računa. |
| **LED lučke** | `switch` | 💡 | - | Nastavitve | Vklopi/izklopi statusne LED indikatorje. |
| **Zvočni signali (Buzzer)** | `switch` | 🔊 | - | Nastavitve | Vklopi/izklopi piske ob spremembah naprave. |
| **Nočni način 1 & 2** | `switch` | 🌙 | - | - | Aktivacija tihih in varčnih programov. |
| **Dremež (Snooze)** | `switch` | ⏳ | - | - | Začasno pavziranje prezračevanja. |
| **Boost** | `switch` | 🚀 | - | - | Maksimalna moč prezračevanja za hitro izmenjavo zraka. |

### Kategorija: Posamične NAPRAVE (fizične enote)

| Entiteta | Platforma | Ikona | Razred | Kategorija | Opis |
|----------|-----------|-------|--------|------------|------|
| **Signala (RSSI)** | `sensor` | 📶 | `signal_strength` | Diagnostika | Moč Wi-Fi signala naprave (v dBm). *Onemogočeno privzeto.* |
| **Zadnja sprememba** | `sensor` | ⏱️ | `timestamp` | Diagnostika | Čas UTC zadnje spremembe delovnega načina. *Onemogočeno privzeto.* |
| **Konec posebnega načina** | `sensor` | ⏳ | `timestamp` | Diagnostika | Kdaj preneha veljati trenutni Boost/Dremež. *Onemogočeno privzeto.* |
| **Stanje naprave** | `binary_sensor` | ⚠️ | `problem` | Diagnostika | Zaznava napake (status_esp != 0), npr. čas za menjavo filtrov. |
| **Povezljivost** | `binary_sensor` | 🌐 | `connectivity` | Diagnostika | Stanje oblak spletne povezave s to napravo. |
| **Obratni tok** | `switch` | 🔄 | - | - | Preklopi izmenični ali reverzibilni tok zraka izmenjalnika. |
| **Ime enote** | `text` | 🏷️ | - | Nastavitve | Preimenovanje naprave neposredno iz HA. |
| **Premakni v skupino** | `select` | ➡️ | - | Nastavitve | Premakne fizično enoto iz trenutne v novo skupino. |
| **Urnik** | `switch` | 📅 | - | Nastavitve | Omogoči upravljanje (on/off) posameznih sistemskih urnikov. |

*(Opomba: Senzorji za pretekle in prihodnje časovne diagnoze so privzeto omogočeni med testiranjem, a jih kot nevsiljiv dejavnik lahko preprosto izklopite.)*

---

## Servisi (Services)

Integracija po meri postavlja naslednje `ivent.*` servise, primerne za skripte in kompleksne avtomatizacije. Pri invalidnosti servisi prožijo `ServiceValidationError`.

1. **`ivent.create_group`**
   - **Opis**: Ustvari novo lokalno skupino.
   - **Parametri**: `name` (Ime, npr. "Spalnica").
2. **`ivent.delete_group`**
   - **Opis**: Nežno uniči specifično skupino. Morda premakne naprave drugam.
   - **Parametri**: `group_id` (Celo število).
3. **`ivent.rename_group`**
   - **Opis**: Preimenuje skupino.
   - **Parametri**: `group_id`, `new_name`.
4. **`ivent.rename_device`**
   - **Opis**: Preimenuje golo fizično enoto.
   - **Parametri**: `device_mac`, `new_name`.
5. **`ivent.move_device_to_group`**
   - **Opis**: Fizično napravo premakne iz ene skupine pod dežnik druge skupine.
   - **Parametri**: `device_mac`, `group_id`.

---

## Primeri uporabe & Avtomatizacije

### 1. Avtomatski "Boost" ob povišanem CO2
Pametno povežite senzor kakovosti zraka in prezračevanje na steroidih! Zračimo tja do 30 min in se umirimo.

```yaml
alias: "Prezrači sobo ob slabem zraku"
mode: single
trigger:
  - platform: numeric_state
    entity_id: sensor.dnevna_soba_co2
    above: 1200
action:
  - service: switch.turn_on
    target:
      entity_id: switch.dnevna_soba_boost
```

### 2. Tihi nočni način ko greste spat
Pred spanjem izklopite morebitni Boost in aktivirajte Night 1, hkrati izklopite nadležne LED in piskanje (Buzzer).

```yaml
alias: "Lahko noč - Tihi modus"
trigger:
  - platform: state
    entity_id: input_boolean.house_sleep_mode
    to: "on"
action:
  - service: switch.turn_on
    target:
      entity_id: switch.dnevna_soba_night_mode_1
  - service: switch.turn_off
    target:
      entity_id: 
        - switch.dnevna_soba_led_lights
        - switch.dnevna_soba_buzzer
```

---

## Znane omejitve

- **Brez Push tehnologije**: Sistem uporablja lokalno prožen "Polling", pri katerem preko API-ja poizveduje na vsakih 60 sekund. Morebitne spremembe iz i-Vent mobilne aplikacije bodo morda vidne s kratkim zamikom.
- **Ni uradnega Device Discovery**: Zaradi narave Cloud API-ja trenutno ne more podpreti ZeroConf mDNS ali Bluetooth iskanja. Naprave se odkrijejo *strogo* ob inicializaciji API ključa ali med polling ciklusom ("Dynamic Devices").
- Trenutno ni uradne rešitve **popravil** (Repair Issues); ob tekoči napaki vas aplikacija zgolj obvesti o "Reavtentikaciji" in ponuja potrditev ključev.

---

## Odpravljanje težav

- **"Reauth failed" / Autentikacijske napake (HTTP 401)**: To se pogosto zgodi, če prekličete API ključ na portalu i-Vent ali vnesete napačne podatke. Integracija bo samodejno postavila entitete na `Unavailable` stanje in sprožila vmesnik za ponoven vnos gesla/ključa na nadzorni plošči (Setup Reauthentication Flow).
- **Napaka "Cannot Connect" (HTTP/Timeout)**: Vaš internet je padel ali pa ima i-Vent strežnik začasne izpade. Na integracijski enoti se bodo obdržala stara stanja, posodobitve se pa morda ponovijo kasneje.
- **Diagnostics**: Če naletite na neznan tehnični lapsus - omogočili smo funkcijo "Download Diagnostics". Pod `Settings -> Integrations -> i-Vent` enostavno prenesite datoteko za popravila, zbrani podatki bodo anonimizirani (brez ključev)! 

### Skupnost in Podpora
Za prijavo napak, vprašanj ali izboljšav, vas vljudno vabimo na [Issue Tracker](https://github.com/JernejHren/ivent-home-assistant/issues).
