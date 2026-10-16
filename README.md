# Footballanalyzer – lokal oppstart

Start fra denne mappen:

```sh
sh start.sh
```

Åpne http://localhost:8000. Nettsiden og API-et kjører på samme server.
Stopp serveren med Ctrl+C.

## Førstegangsoppsett

Bruk Python 3.10–3.13. Opprett et separat miljø og installer pakkene:

```sh
cd Footballanalyzer-master
python3.10 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cd ..
sh start.sh
```

Bytt `python3.10` med din installerte Python 3.10–3.13 ved behov.
Pakkene er tilpasset den medfølgende modellen, som er lagret med scikit-learn 1.7.2.
Data og modell følger med prosjektet; ingen API-nøkkel er nødvendig.
API-dokumentasjon: http://localhost:8000/docs.

## Ny kampmodell og flere ligaer

API-Football-integrasjonen støtter Premier League (39), La Liga (140), Serie A (135),
Bundesliga (78) og Ligue 1 (61). Nettsiden bruker bare lokale data; sidevisninger og
prediksjoner bruker **ingen** API-spørringer.

1. Legg nøkkelen fra API-Football → Account → My Access i
   `Footballanalyzer-master/.env`: `API_FOOTBALL_KEY=din_nøkkel`.
2. Kjør fra prosjektets ytterste mappe:

```sh
cd Footballanalyzer-master
.venv/bin/python update_football.py
```

Standardimporten prøver sesongene 2022–2026 for de fem ligaene: maksimalt 30
spørringer ved en full førstegangsimport (5 ligaoppslag + 25 sesongoppslag).
Gratisabonnementet kan avvise nyere sesonger. De hoppes over med en tydelig melding;
nettsiden viser den faktiske sesongen og nedlastingstidspunktet. Vi lover ikke tilgang
til inneværende sesong på gratisplanen.

Svar, også avslag på sesongtilgang, mellomlagres i 24 timer. Importen sender høyst én
spørring per 6,1 sekunder, stopper ved HTTP-feil og har ingen automatiske forsøk.
Standardtaket er 35 spørringer per kjøring; den lokale dagsgrensen er 80, med minst
20 spørringer i reserve basert på sist kjente kvote. Bruk i dashboardet eller andre
apper mellom våre oppslag kan ikke telles lokalt; API-ets kvoteoverskrift leses ved
hvert svar. Ingen automatisk oppdateringsjobb er aktivert.

Eksempel for ett sett sesonger og ligaer:

```sh
.venv/bin/python update_football.py --leagues 135 39 --seasons 2023 2024 2025 --max-requests 10
```

Ved senere oppdateringer må alle aktive ligaer og minst deres nyeste importerte
sesong tas med. Importen nekter å fjerne ligaer eller gå tilbake til eldre sesonger.
En vellykket import publiserer modell og lagdata samlet; serveren laster dem inn
uten omstart. Feilet import beholder den aktive modellen. Ligavalg som mangler data
er deaktivert. Den opprinnelige Serie A-modellen brukes fram til ny import finnes.

### Hva modellen faktisk lærer

Den nye modellen trener på hjemmeseier/uavgjort/borteseier fra ferdigspilte kamper,
med ligatilhørighet, mål, poeng, seiersandel og siste fem resultater som inngangsdata.
Statistikk beregnes kun fra tidligere kamper i samme sesong, med fire timers margin
etter avspark. Minst fem kamper per lag kreves. Den bruker ikke sluttabellen som
inngangsdata til tidligere kamper. Topp­scorer og keeper hentes ikke, for å spare kvote.

De første omtrent 80 % av kampene i tid brukes til evalueringens trening, de siste
20 % til validering. Nøyaktighet og log loss sammenlignes med en enkel modell basert
på utfallsfrekvens. Deretter trenes den publiserte modellen på alle tilgjengelige
kamper. Resultatene vises i importloggen og `/api/catalog`. Modellen er eksperimentell;
nettsiden viser en merknad hvis den ikke slår referansen på log loss.

Den gamle CSV-en hadde sesongår i motsatt rekkefølge. Årene er korrigert til
2025, 2024, 2023, 2022 og 2021 i samme rekkefølge som kildene i notebooken.
Originalen er bevart som `serie_a_full_data.original.csv`. Disse sesongtabellene
blandes ikke inn i den nye kampmodellen.

Test uten nettverk/API-kvote:

```sh
cd Footballanalyzer-master
.venv/bin/python -m unittest discover -s tests -v
```
