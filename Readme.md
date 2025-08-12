# **i-Vent Smart Home integracija za Home Assistant**

Ta integracija omogoča nadzor in avtomatizacijo prezračevalnih sistemov i-Vent Smart Home znotraj Home Assistanta. Deluje preko uradnega i-Vent Cloud API-ja.

## **Funkcionalnosti**

* **Nadzor ventilatorja:** Vklop in izklop posameznih skupin.  
* **Upravljanje s hitrostjo:** Izbira med stopnjami 1, 2 in 3\.  
* **Načini delovanja:** Ločena stikala za Boost, Nočni način in Dremež.  
* **Način prezračevanja:** Preklop med Rekuperacijo (zimski način) in Prezračevanjem (Bypass \- letni način).  
* **Dodatne kontrole:** Stikala za LED lučke, zvočne signale in obratni tok zraka za posamezne enote.  
* **Senzorji:** Spremljanje moči Wi-Fi signala (RSSI) in stanja naprave (opozorila za napake ali čiščenje filtrov) za vsako enoto.  
* **Upravljanje z urniki:** Vklop in izklop obstoječih urnikov, nastavljenih v i-Vent aplikaciji.  
* **Administrativne funkcije:** Preimenovanje, brisanje in ustvarjanje skupin ter premikanje enot neposredno iz Home Assistanta.


## **Namestitev**

### **Preko HACS (Priporočeno)**

1. Pojdite v HACS \> Integracije.  
2. Kliknite na tri pike v zgornjem desnem kotu in izberite "Custom repositories".  
3. V polje "Repository" vnesite [https://github.com/JernejHren/ivent-home-assistant](https://github.com/JernejHren/ivent-home-assistant) in za kategorijo izberite "Integration".  
4. Kliknite "Add".  
5. Poiščite "i-Vent Smart Home" na seznamu integracij in kliknite "Install".  
6. Ponovno zaženite Home Assistant.

### **Ročna namestitev**

1. Prenesite zadnjo različico iz [strani z objavami](https://github.com/JernejHren/ivent-home-assistant/releases).  
2. Razširite arhiv in mapo custom\_components/ivent/ prekopirajte v mapo config/custom\_components/ vaše Home Assistant namestitve.  
3. Ponovno zaženite Home Assistant.

## **Konfiguracija**

1. Pojdite v **Nastavitve \> Naprave in storitve**.  
2. Kliknite **Dodaj integracijo** in poiščite **"i-Vent Smart Home"**.  
3. Vnesite **API ključ** in **ID lokacije**, ki ju dobite v [i-Vent spletnem vmesniku](https://cloud.i-vent.com/) pod Nastavitve \> Ključi.  
4. Integracija bo samodejno odkrila vse vaše naprave in skupine.

## **Licenca**

Ta projekt je licenciran pod licenco Apache 2.0. Za podrobnosti si oglejte datoteko [LICENSE](https://www.google.com/search?q=LICENSE).
