# Kontrolni seznam: test lokalnega načina na pravi lokaciji (veja `dev`)

Cilj: preveriti, kar so doslej dokazali samo lažna naprava in skripte. Vse korake delaj po vrsti, zabeleži izid (OK / napaka + zapis iz dnevnika). Pri napaki je najdragocenejši zapis `debug` dnevnika in prenos *Diagnostics*.

## 0. Priprava (pred prvim zagonom)

- [ ] **Varnostna kopija / posnetek HA.** Vnos se pri nalaganju migrira na verzijo 4 (`mode=cloud`). Starejša integracija (0.2.6 ali prej) takšnega vnosa **ne naloži več** (HA ne podpira "nižanja" verzije vnosa). Vrnitev je možna samo z obnovitvijo kopije ali z brisanjem in ponovno dodajo vnosa.
- [ ] **Ustavi `ivent_udp_probe.py` (`watch`)**, če še teče na HA strežniku (Advanced SSH & Web Terminal). Drži vrata UDP 1028 in bi zmotil integracijo (naprava odgovarja samo na izvorna vrata 1028).
- [ ] HA in enote so v istem podomrežju; HA ni v Docker `bridge` omrežju (HAOS ali `network_mode: host` je v redu).
- [ ] Vklopi dnevnik:
  ```yaml
  logger:
    logs:
      custom_components.ivent: debug
  ```
- [ ] Namesti `dev` posnetek (`custom_components/ivent/`) in znova zaženi HA. Obstoječi oblačni vnos mora ostati nespremenjen in delovati (isti `entity_id`-ji, stanje kot prej).

## 1. Samo lokalno: dodajanje

Dodaj **novo** integracijo v načinu *Samo lokalno* (ali preklopi obstoječi vnos z *Rekonfiguracijo*, glej 5.).

- [ ] Vsa tri polja prazna: odkrivanje najde Master v ~8 s (IP, MAC, ID lokacije se izpolnijo sami, vnos se ustvari).
- [ ] Če odkrivanje ne uspe: sporočilo `discovery_failed`; ročni vnos IP + MAC + ID lokacije uspe.
- [ ] Napačen MAC ali ID lokacije: ustrezno sporočilo (`invalid_mac`, `invalid_location_id`), obrazec ostane odprt.
- [ ] Samo IP vnesen: odkrivanje se omeji na ta IP.
- [ ] Po dodajanju: vse tri skupine (Dnevna, Tilen, "iVent") in vse naprave so prikazane; imena, hitrosti in načini se ujemajo z uradno aplikacijo.
- [ ] `binary_sensor` filtra pokaže isto kot aplikacija (`statusEsp` bit 1024), `rssi` je smiseln.
- [ ] Ni nobene napake v dnevniku; v nastavitvah *Naprave in storitve* ni urnikov (v lokalnem načinu jih ni), brez opozorila vsako minuto.

## 2. Samo lokalno: ukazi (vsak preveri na enoti IN v uradni aplikaciji)

Po vsakem koraku se vrni v prvotno stanje.

- [ ] Hitrost 1 → 2 → 3 na eni skupini (isti način).
- [ ] Preklop rekuperacija ↔ bypass na isti hitrosti.
- [ ] Posebni načini: Boost, Dremež (Snooze), Nočni 1, Nočni 2; po izklopu se vrne prejšnja hitrost.
- [ ] Izklop skupine in ponovni vklop (ventilatorji se za nekaj sekund ustavijo).
- [ ] LED način skupine (Dnevna): vklop/izklop. Zvočno opozorilo (`buzzerMode`): vklop in izklop (ni še bil preizkušen).
- [ ] Preimenovanje naprave in vrnitev (ime je UTF-8, poskusi tudi šumnike).
- [ ] **Skupina "iVent" (vse naprave):** ukaz (npr. Boost ali hitrost) se izvede na *obeh* pravih skupinah, vsaka obdrži svoj način in hitrost.
  - **Potrjeno (10. 10.):** deluje pravilno. Opomba: integracija zapiše ukaz tudi v samo skupino "iVent" (da je prikaz usklajen), uradna aplikacija pa tega *ne dela* (pošlje samo dva ukaza, na pravi skupini). Preveri, da zapis v skupino 1 nič ne pokvari (npr. da naprave ne reagirajo dvakrat, da v aplikaciji ni čudnega stanja) in zapiši vedenje; če je sporno, se zapis v skupino 1 lokalno izpusti.
- [ ] *Obrni smer ventilatorja* (`reverseFlow`) na eni napravi: fizično obrne smer pretoka; vrni nazaj.

## 3. Push in osveževanje

- [ ] Spremeni hitrost/način v **uradni aplikaciji**: sprememba je v HA vidna v ~1–2 s (ne šele po minuti). V dnevniku: `Push: group … -> …`.
- [ ] V dnevniku je ob zagonu `Master advert received`, nato `Poll interval … -> 0:02:00` (push deluje). 
- [ ] Spremeni stanje v aplikaciji *dvakrat zapored hitro*: HA konča v pravilnem končnem stanju.
- [ ] Spremeni ukaz iz HA: entiteta se spremeni takoj (optimistično), brez utripanja nazaj na staro vrednost.

## 4. Odpornost

- [ ] **Brez interneta** (prekini WAN na usmerjevalniku): lokalno upravljanje deluje nespremenjeno (naprave se odzovejo takoj).
- [ ] **Master izklopljen** (začasno): entitete postanejo `unavailable`, v dnevniku timeout; po vrnitvi Masterja se vse samo povrne brez ročnega posega. Po vrnitvi se utegne pojaviti `Location Master se je spremenil` (`becameMaster`).
- [ ] **Ponovni zagon HA**: vnos se naloži brez napake (vrata 1028 so prosta).
- [ ] **Dve instanci**: če poskusiš dodati drugo lokalno lokacijo, vnos zavrne (`single_local_entry`).
- [ ] Hkratna uporaba uradne aplikacije na telefonu in HA: obe vidita iste spremembe, nobena ne ostane brez odziva.

## 5. Preklapljanje načinov (Rekonfiguracija)

Vsakič: število in `entity_id`-ji entitet ostanejo isti (brez podvojenih entitet), `unique_id` se ne spremeni.

- [ ] Oblak → Samo lokalno.
- [ ] Samo lokalno → Kombinirano (vpiši API ključ).
- [ ] Kombinirano → Samo oblak.
- [ ] Pri preverjanju lokalne povezave med rekonfiguracijo delujoč vnos za nekaj sekund izgine (začasno se sprosti vrata 1028); ob napaki se vnos spet naloži sam.

## 6. Kombinirano

- [ ] Stikala urnikov (vklop/izklop posameznega urnika) so vidna in delujejo (gredo prek oblaka; vsebine urnikov — čas, dnevi, akcija — integracija ne ureja ne v oblaku ne lokalno). Stanje in ukazi gredo lokalno (preveri z WAN prekinjenim: ukazi delujejo, stikala urnikov ne).
- [ ] *Ustvari skupino* in *izbriši skupino* (servisa) delujeta (prek oblaka).
- [ ] Rezerva: Master nedosegljiv + internet na voljo → ukaz gre prek oblaka (dnevnik: `Master ni dosegljiv, ukaz … gre prek oblaka`).
- [ ] Možnost *Stanje iz oblaka, ko Master ni dosegljiv* (nastavitve vnosa) vklopljena: ob izpadu Masterja entitete ostanejo na zadnjem znanem stanju iz oblaka; izklopljena: postanejo `unavailable`.

- [ ] *Samo oblak*: polje ID lokacije je obvezno (obrazca brez njega ni mogoče oddati); z vnesenim ID-jem se poveže. Naslov vnosa je "i-Vent Cloud" (ID lokacije ni v naslovu).
- [ ] *Kombinirano* z API ključem in praznim ID-jem lokacije: ID določi lokalno odkrivanje, oblak se preveri z njim.
- [ ] Po konfiguraciji je v dnevniku (že na ravni INFO) vrstica `Setting up i-Vent in … mode` in v lokalnih načinih `Listening for local i-Vent push messages`. Brez `debug` se podrobnosti pusha ne izpisujejo.
- [ ] V dnevniku HA ni opozoril o zastarelem `via_device` (HA 2026.x) in `async_get_device`.

## 7. Znane neznanke (previdno, z vrnitvijo v prejšnje stanje)

- [ ] **Premik naprave v drugo skupino** (`group_id` v `ModifyDevice`, kodiran kot fixed32; ni preizkušen): poskusi z eno napravo; če naprava vrne napako, zapiši `ErrorCode` iz dnevnika. Vrni napravo v prvotno skupino (v uradni aplikaciji, če HA ne uspe).
- [ ] Brisanje skupine lokalno (`delete`): ne preizkušaj na skupini, ki jo potrebuješ; najprej ustvari preizkusno skupino prek oblaka.
- [ ] "Najdi napravo" (Beacon) še nima entitete v integraciji.

## 8. Če kaj odpove: kaj zbrati

1. `debug` dnevnik od zagona do napake.
2. *Download diagnostics* (ID lokacije in MAC sta skrita).
3. Zajem paketov na HA strežniku: `tcpdump -i any -n -w ivent.pcap udp port 1028` (pazi: vsebuje ID lokacije v čistopisu; ne objavljaj ga javno brez anonimizacije, glej `tools/sanitize_capture.py`).
4. Verzija firmwarea naprav (`espFwNumber`) in model enote.
