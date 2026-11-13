# 🎓 UPF Schedule Sync & Auditor

[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Playwright](https://img.shields.io/badge/Playwright-Headless-2EAD33?logo=playwright&logoColor=white)](https://playwright.dev/)
[![Google Calendar API](https://img.shields.io/badge/Google%20Calendar-API%20v3-4285F4?logo=googlecalendar&logoColor=white)](https://developers.google.com/calendar)
[![Telegram Bot API](https://img.shields.io/badge/Telegram-Notifications-26A5E4?logo=telegram&logoColor=white)](https://core.telegram.org/bots/api)
[![GitHub Actions](https://img.shields.io/badge/GitHub%20Actions-Automated-2088FF?logo=githubactions&logoColor=white)](https://github.com/features/actions)

Servei autònom en Python que audita l'horari oficial de la **Universitat Pompeu Fabra (Campus Global / Secretaria Virtual)** mitjançant **Playwright headless**, el compara setmana a setmana amb el teu **Google Calendar**, aplica les actualitzacions automàticament i t'avisa a l'instant per **Telegram** quan hi ha canvis.

Pensat per funcionar **100% gratis i sense servidor propi** orquestrat amb **GitHub Actions** — llest per fer-ne un *fork* o utilitzar-lo com a plantilla.

---

## ✨ Funcionalitats principals

* **📅 Auditoria setmanal intel·ligent (feiners vs. cap de setmana):**
  * **De dilluns a divendres:** audita tota la setmana en curs (de dilluns a diumenge) per detectar canvis d'última hora.
  * **Dissabtes i diumenges:** canvia automàticament el focus a la **setmana vinent**, preparant l'horari abans que comenci la setmana.
  * També admet auditories manuals per a qualsevol setmana concreta (`--date YYYY-MM-DD`) i mode de prova sense escriptura (`--dry-run`).

* **🔍 Motor de comparació avançat (`diff_engine.py`):**
  * 🕒 **Reprogramacions (`TIME_CHANGE`):** detecta si una classe s'ha mogut de dia o franja horària dins la mateixa setmana, respectant la tipologia (*Teoria*, *Seminari*, *Pràctiques*) per evitar duplicats o falses cancel·lacions.
  * ✅ **Reactivacions (`RESTORED`):** si una classe marcada prèviament com `[CANCEL·LADA]` torna a aparèixer a l'horari oficial, retira automàticament l'etiqueta i la confirma.
  * ⚠️ **Canvis d'aula (`ROOM_CHANGE`):** normalitza formats (p. ex. `Aula 52.019` vs. `52.019`) i actualitza la ubicació de l'esdeveniment.
  * ➕ **Noves sessions (`NEW_SESSION`):** crea automàticament noves classes o recuperacions afegides al portal.
  * ❌ **Cancel·lacions (`CANCELLED`):** afegeix el prefix `[CANCEL·LADA]` al títol de l'esdeveniment en lloc d'esborrar-lo, conservant-ne la traçabilitat.
  * ⏱️ **Tolerància horària de ±15 minuts** i neteja automàtica de codis d'assignatura (p. ex. `23974 - ...`) per a un *matching* fiable.

* **🏫 Extracció d'aules ocultes a les observacions:**
  * Quan la Secretaria Virtual mostra un marcador genèric com `"Sense aules assignades"` o `"Pendent d'assignar"`, l'extractor analitza el camp d'observacions/comentaris amb expressions regulars per recuperar automàticament l'aula real (p. ex. `Aula 52.019`, `Lab 54.004`, `Aula Magna`, etc.).

* **🎨 Integració intel·ligent amb Google Calendar:**
  * **Herència automàtica de colors:** abans de crear un nou esdeveniment, cerca el `colorId` d'esdeveniments existents de la mateixa assignatura (en memòria cau o via Google Calendar API) perquè les noves classes mantinguin exactament el teu codi de colors.
  * **Visibilitat pública:** els nous esdeveniments es creen amb `visibility: "public"` per facilitar calendaris compartits o subscripcions.

* **🎛️ Filtratge configurable de grups (`SUBJECT_GROUP_FILTERS`):**
  * Algunes assignatures de la UPF exposen tots els grups de seminari i pràctiques al calendari general. Pots configurar per variable d'entorn quins grups t'interessen per assignatura (p. ex. `23962:S201,P201`) sense tocar el codi, mantenint sempre les sessions de teoria.

* **📲 Notificacions estructurades a Telegram:**
  * Només t'envia un resum en HTML agrupat per tipus de canvi quan realment hi ha discrepàncies accionables.

---

## 🏗️ Arquitectura i Flux d'Execució

```text
GitHub Actions (Cron diari / Manual)
        │
        ▼
[1] auth.py ─────────────► Login headless a UPF (Playwright) + intercepció Ajax FullCalendar
        │
        ▼
[2] scraper.py ──────────► Normalització, extracció d'aules a observacions i filtre de grups
        │
        ▼
[3] calendar_manager.py ─► Lectura d'esdeveniments de la setmana a Google Calendar
        │
        ▼
[4] diff_engine.py ──────► Detecció de TIME_CHANGE, ROOM_CHANGE, RESTORED, NEW_SESSION, CANCELLED
        │
        ▼
[5] calendar_manager.py ─► Actualització d'esdeveniments (amb visibilitat pública i colorId)
    & notifier.py          + Alerta immediata per Telegram
```

### Estructura del repositori

```text
.
├── .github/workflows/
│   └── schedule_sync.yml    # Workflow programat i execució manual (GitHub Actions)
├── src/
│   ├── auth.py              # Login SSO headless amb Playwright i intercepció de xarxa
│   ├── scraper.py           # Parsing FullCalendar, extracció d'aules i filtre de grups
│   ├── calendar_manager.py  # Client Google Calendar API v3 (colors i visibilitat)
│   ├── diff_engine.py       # Motor de comparació setmanal i resolució de canvis
│   ├── notifier.py          # Formatació HTML i enviament d'alertes via Telegram Bot API
│   ├── models.py            # Esquemes Pydantic (ClassSession, CalendarEvent, DiffResult)
│   ├── config.py            # Configuració tipada via pydantic-settings
│   └── main.py              # Orquestrador CLI (--date, --dry-run)
├── tests/                   # Bateria de proves unitàries amb pytest i respx
├── requirements.txt
└── .env.example             # Plantilla de configuració
```

---

## 🚀 Posada en marxa (com a plantilla)

### 1. Prepara els serveis externs

#### Google Cloud Service Account
1. Accedeix a [Google Cloud Console](https://console.cloud.google.com/) i crea o selecciona un projecte.
2. Activa la **Google Calendar API**.
3. A **IAM & Admin > Service Accounts**, crea una Service Account (p. ex. `upf-sync-bot`) i genera una clau en format **JSON**.
4. Obre [Google Calendar](https://calendar.google.com/), entra a la configuració del teu calendari d'universitat i comparteix-lo amb el correu de la Service Account (`...@...iam.gserviceaccount.com`) amb permisos de **"Fer canvis en els esdeveniments"**.

#### Bot de Telegram
1. Obre Telegram, cerca `@BotFather`, executa `/newbot` i desa el `TELEGRAM_BOT_TOKEN`.
2. Inicia una conversa amb el teu bot prement **Start**.
3. Consulta `@userinfobot` per obtenir el teu `TELEGRAM_CHAT_ID` numèric.

### 2. Configura els Secrets i Variables a GitHub

Al teu repositori, ves a **Settings > Secrets and variables > Actions**:

#### Secrets (`Repository secrets`)
| Secret | Descripció | Exemple |
|---|---|---|
| `UNI_USERNAME` | Identificador d'accés al portal UPF | `12345678A` |
| `UNI_PASSWORD` | Contrasenya del Campus Global / Matrícula | `LaTevaContrasenya` |
| `GOOGLE_SERVICE_ACCOUNT_KEY` | Contingut JSON (o Base64) de la Service Account | `{"type": "service_account", ...}` |
| `GOOGLE_CALENDAR_ID` | ID del calendari de Google | `xxxx@group.calendar.google.com` |
| `TELEGRAM_BOT_TOKEN` | Token del bot de Telegram | `123456789:ABCdef...` |
| `TELEGRAM_CHAT_ID` | ID del xat on rebre les alertes | `987654321` |

#### Variables opcionals (`Repository variables`)
| Variable | Descripció | Exemple |
|---|---|---|
| `SUBJECT_GROUP_FILTERS` | Filtra seminaris/pràctiques per codi o nom d'assignatura | `23962:S201,P201` |

> **Format de `SUBJECT_GROUP_FILTERS`:** admet múltiples assignatures separades per `;` (`23962:S201,P201;Comunicació Tècnica en Anglès:201`) o bé format JSON (`{"23962": ["S201", "P201"]}`). Si es deixa buit, s'inclouen totes les sessions.

---

## 💻 Execució en local i tests

```bash
# 1. Crear entorn virtual i instal·lar dependències
python -m venv .venv
source .venv/bin/activate  # A Windows: .venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium

# 2. Configurar variables d'entorn locals
cp .env.example .env

# 3. Executar en mode prova (recomanat per validar configuració)
python -m src.main --dry-run

# 4. Auditar una setmana concreta
python -m src.main --date 2026-10-15

# 5. Executar la bateria de tests unitaris
pytest -v
```

---

## ⏰ Automatització i Privadesa

* El workflow [schedule_sync.yml](.github/workflows/schedule_sync.yml) s'executa automàticament un cop al dia (`0 13 * * *` UTC, equivalent a les **15:00 CEST** / **14:00 CET** a Catalunya) i es pot llançar manualment des de la pestanya **Actions** amb paràmetres opcionals (`target_date`, `dry_run`).
* **Privadesa en repositoris públics:** aquest template **no puja artifacts ni traces de Playwright** a GitHub Actions en cas d'error, evitant qualsevol exposició accidental de captures o sessions en execucions públiques. Si fas un fork públic, mantén totes les credencials exclusivament dins de **GitHub Secrets** (o utilitza un repositori privat per a les teves execucions diàries personals).
