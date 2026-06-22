# ⬡ Kvitto-appen

Hämtar automatiskt kvitton från Gmail, Outlook/Hotmail och iCloud, känner igen dem med AI och sparar dem som PDF – med månadsrapport klar att skicka till revisorn.

---

## Funktioner

- 📧 Gmail, 📨 Outlook/Hotmail och ☁️ iCloud – alla tre på en gång
- 🤖 Automatisk igenkänning av kvitton, orderbekräftelser och fakturor
- 🧠 Lär sig vilka avsändare som brukar skicka kvitton
- ⚠️ Varnar om en känd avsändare uteblir under månaden
- 📋 Månadsrapport som PDF – klar att mejla till revisorn
- 💾 Exportera enskilda kvitton som PDF
- 📊 Statistik och aktivitetslogg

---

## Installation (Mac)

```bash
cd kvitto-appen
chmod +x install.sh start.sh
./install.sh
```

---

## Konfigurera konton

### Gmail – Google OAuth

1. Gå till [console.cloud.google.com](https://console.cloud.google.com)
2. Skapa projekt → Aktivera **Gmail API**
3. *Credentials → Create → OAuth client ID → Desktop app*
4. Ladda ner JSON och lägg i: `~/.kvitto-appen/gmail_credentials.json`

### Outlook/Hotmail – Azure

1. Gå till [portal.azure.com](s) → *App registrations*
2. New registration – Personal Microsoft accounts, redirect: `http://localhost`
3. *Authentication → Allow public client flows: Ja*
4. *API permissions → Microsoft Graph → Mail.Read*
5. Fyll i Client ID i `~/.kvitto-appen/outlook_config.json`:
```json
{ "client_id": "DITT-ID-HÄR", "tenant_id": "consumers" }
```

### iCloud – App-lösenord

1. Gå till [appleid.apple.com](https://appleid.apple.com)
2. Logga in → *Lösenord & säkerhet → App-lösenord → Skapa*
3. Namnge det "Kvitto-appen" och kopiera lösenordet
4. Fyll i `~/.kvitto-appen/icloud_config.json`:
```json
{ "email": "din@icloud.com", "app_password": "xxxx-xxxx-xxxx-xxxx" }
```
> **Tips:** Du behöver inte konfigurera alla tre – använd bara de du har.

---

## Starta

```bash
./start.sh
```

---

## Månadsrapporten

Under fliken **Månadsrapport** kan du:
- Välja vilken månad rapporten gäller
- Fylla i företagsnamnet (visas i PDF:en)
- Se vilka kända avsändare som saknas denna månad
- Generera en färdig PDF att skicka direkt till revisorn

---

## Hur appen lär sig

- **Automatisk:** Avsändare med konsekvent hög "kvitto-poäng" läggs till automatiskt
- **Manuell:** Klicka "Markera som känd avsändare" i förhandsgranskningen
- **Saknade-varning:** Om en känd avsändare (t.ex. Spotify, Fortnox) inte hört av sig under månaden flaggas det i rapporten

---

*All data lagras lokalt på din Mac. Inget skickas till externa servrar.*

---

## Uppdateringar

Appen kollar automatiskt mot GitHub vid start om det finns en nyare version (jämför `VERSION`-filen mot senaste [release](https://github.com/Cebbas/kvitto-appen/releases)). Finns en uppdatering visas en länk i sidopanelen.

### Släppa en ny version (för utvecklare)

1. Höj versionsnumret i `VERSION` (t.ex. `1.1.0`)
2. Committa och pusha till `main`
3. Tagga och skapa release:
   ```bash
   git tag v1.1.0
   git push origin v1.1.0
   gh release create v1.1.0 --title "v1.1.0" --notes "Vad som är nytt…"
   ```
4. Användare med en äldre version ser uppdateringen i appen nästa gång de startar den.
