# Kid’s Ministry Check-in — Full Design & Implementation Roadmap

This is a complete, developer-friendly design document showing **every moving part**, prioritized implementation order, decisions, and practical workarounds (e.g., **display label content on tablets now; plug Dymo printers later**). Treat this as the single source of truth you can hand to a developer or to an AI (Claude) to start building.

---

## Executive summary (one-paragraph)

Run a fully local check-in system on your Pi-400: tablets run a browser UI that scans QR codes (front camera), posts to the Pi-400 server (FastAPI), and displays a confirm screen. Pi-400 holds a local DB (SQLite), queues WhatsApp notifications (sent via a Playwright-based WhatsApp-Web worker), logs everything, and returns label content to the tablet for volunteers to write on a physical sticker until Dymo printing is implemented. The system is modular so you can add printers, analytics and volunteer accounts later.

---

# 1 — System overview (components & responsibilities)

**Tablets (6 stations)**

- Browser UI only (no native app).

- Camera (front) → QR decode (js library) → POST `/scan`.

- Displays confirmation card + label contents (for manual sticker writing).

- Sends `station_id` and `device_id` with every request.

**Pi-400 (central local server)**

- Runs Docker container(s) with:
  
  - FastAPI backend (API + pages).
  
  - Worker(s): Playwright WhatsApp worker + optional background job processor.

- SQLite DB (local file).

- Optional: CUPS or print stubs later for Dymo integration.

**WhatsApp Web Worker (Playwright, Python)**

- Runs on Pi-400 as long-running headless Chromium.

- Holds a persistent WhatsApp Web session (stored credentials).

- Monitors incoming messages (detect opt-in) and consumes `message_queue` to send outgoing messages.

- Writes results to `logs` and `message_queue` status fields.

**Volunteers/Admin UI (later)**

- Login protected web app for viewing/editing child profiles, medical info, attendance analytics, and manual printing controls.

**Label printing (future)**

- Stubbed today: server returns printable label payload (PNG / JSON) to tablets.

- Later: Android helper app or Pi agent to send Dymo print jobs (OTG USB).

---

# 2 — High level data flow (textual diagram)

1. Tablet camera decodes QR → `POST /api/scan { qr_value, station_id, device_id }`

2. Server looks up `children` by QR:
   
   - FOUND → creates `session` (expires in 40s) and returns child details + `session_id` → Tablet shows confirm card.
   
   - NOT FOUND → server returns `not_registered`; Tablet shows sign-up form route.

3. Tablet “Confirm” → `POST /api/checkin { session_id, station_id, device_id, created_by }`.

4. Server writes `attendance` row, inserts one `message_queue` row per parent with `status='pending'` if `parents.notify_opt_in = true` (else skip). Server inserts `print_queue` stub and returns label payload to tablet to display.

5. WhatsApp Playwright worker polls `message_queue`, sends messages to opted-in parents, updates `message_queue` and `logs`.

6. If parent later sends "Notify me" via WhatsApp, Playwright detects incoming message and sets `parents.notify_opt_in = true`.

---

# 3 — Database schema (finalized)

Use the SQL in the earlier message (DDL included). Key tables:

- `children (id TEXT primary key, first_name, last_name, preferred_name, birthdate, gender, program, photo_uri, notes, created_at, updated_at)`

- `parents (id, child_id -> children.id, full_name, phone, phone_normalized, email, relationship, is_primary, notify_opt_in BOOLEAN, created_at)`

- `medical_info (id, child_id, allergies, medications, medical_notes, emergency_instructions, updated_at)`

- `attendance (id, child_id, checked_in_at, checked_out_at, station_id, device_id, program, created_by, checkin_method, label_printed, printed_at, notes, created_at)`

- `sessions (id, child_id, created_at, expires_at, station_id, status)`

- `message_queue (id, to_phone, parent_id, message_body, template, type, status, attempt_count, last_attempt_at, queued_at, sent_at)`

- `print_queue (id, child_id, station_id, label_payload, status, attempts, created_at)`

- `volunteers (id, username, password_hash, role, full_name, phone, email, created_at)`

- `logs (id, event_type, ref_id, message, payload, created_at)`

**Important columns**: `parents.notify_opt_in` — must be set `TRUE` before sending messages.

---

# 4 — API & Internal interfaces

Even though everything is local, designing stable APIs yields clean separation:

### Public (local) HTTP endpoints the tablets call

(Serve these on `http://pi400.local:8000` or IP)

- `POST /api/scan`  
  Request: `{ "qr_value": "...", "station_id":"ST01","device_id":"tablet-1" }`  
  Response (found): `{ "status":"found", "session_id":"sess_ABC", "child": {...}, "expires_in":40 }`  
  Response (not_found): `{ "status":"not_found", "registration_url":"/register?prefill=..." }`

- `POST /api/checkin`  
  Request: `{ "session_id":"sess_ABC", "station_id":"ST01", "device_id":"tablet-1", "created_by":"vol_jess" }`  
  Response: `{ "status":"ok", "attendance_id":123, "label_payload": { ... } }`

- `POST /api/checkout`  
  Request: `{ "child_id":"abc123", "station_id":"exit-1", "device_id": "tablet-exit" }`  
  Response: `{ "status":"ok", "message":"checked out" }`

- `POST /api/register`  
  Request: child + parents payload (see spec). Returns `child_id` and `qr_png_b64` for vCard.

- `GET /api/child/{id}` → full profile including `parents`, `medical_info`, last N `attendance`.

- `POST /api/mark_opt_in` (admin helper) — not required if Playwright detects incoming message; helpful in manual verification.

- `GET /api/print_payload/{attendance_id}` → returns printable JSON/PNG label for tablet display.

### Internal worker interface (DB-driven)

- All background work reads/writes the DB queues:
  
  - `message_queue` for outgoing WhatsApp.
  
  - `print_queue` for printing when implemented.
  
  - `logs` for diagnostics.

---

# 5 — WhatsApp via Playwright — design details

**Language**: **Python (Playwright)** — recommended.

**Why Python?** You’re running Python for FastAPI; keeping WhatsApp worker in Python reduces context switching and makes DB access simpler.

**Playwright Worker responsibilities**

- Start headless Chromium with persistent storage dir (`user-data-dir`) so you do **one QR scan only at initial setup**. Save the profile folder to disk.

- On start, restore session from disk. If not logged in, open Chromium to `https://web.whatsapp.com` and show QR to operator. Once scanned, worker will proceed.

- Event flows:
  
  - **Incoming messages watcher**: listen for chats, when message matches `Notify me` or any text from unknown parent phone, record the phone and optionally capture sender name to `parents` with `notify_opt_in=True` (or prompt manual confirmation).
  
  - **Outgoing sender**: poll `message_queue` for `status='pending'`, send each message (respecting rate limits), update `message_queue` status to `sent/failed` with attempts and `sent_at`.

- Message templates: build text templates for `checkin`, `checkout`, `request_more_info`. Ensure messages are short and not promotional.

**Robustness**

- Use Playwright’s `wait_for_selector` / retry loops. Wrap sends with try/catch and exponential backoff.

- Respect WhatsApp etiquette: not sending mass cold messages; only to opted-in parents.

- Implement DB hooks: if `attempt_count` > 5 mark as `failed` and alert admin via `logs`.

**Session persistence note**

- Use Playwright’s `persistent` context with a folder like `/home/pi/.whatsapp_session`. This avoids re-scanning each restart.

---

# 6 — Frontend (tablet) UI design & behavior

**Core pages**

- `scanner.html` — camera preview + JS library (html5-qrcode or jsQR).
  
  - On decode: POST `/api/scan`.
  
  - On response `found`: show `confirm.html` UI modal.
  
  - On `not_found`: show `register` link.

- `confirm.html` (modal) — shows child details and parents (phone masked), “Yes, check me in” and “Check another” buttons.
  
  - After pressing Yes: POST `/api/checkin` and show success page.

- `success.html` — green confirmation and **label preview area**: show text + vCard QR + printable preview image. **Also** show "Print label" (no actual printing for now) and "Return to scanner" button. Auto-redirect to scanner after 30–40s.

- `register.html` — full form for first-time sign up (child info + one or two parents). On submit call `/api/register` which creates child, creates first attendance row, returns `qr_png_b64` for the vCard to show, and a button “I have sent message” (opt-in flow).

**Label UI (temporary manual printing)**

- Present label payload clearly with max-sized font for `Child Name`, `Age`, parent name(s) and phone(s), and QR image for vCard. Volunteers write this on sticky label.

**UX considerations**

- Debounce scans (ignore duplicates for N seconds).

- Use loud beep or haptic/visual feedback on successful scan.

- For speed: minimal animations; keep flows 2 taps max after scan.

---

# 7 — Implementation roadmap (prioritized tasks)

Break the project into **phases**. Each phase has clear deliverables.

### Phase 0 — Prep & hardware

- Reserve Pi-400 and set up Raspberry Pi OS; Docker installed.

- Buy or procure 6 tablets (Android recommended) and USB-C OTG cables (for later).

- Prepare Wi-Fi network — assign static DHCP reservations for Pi-400 and tablets (recommended).

- Create a folder on Pi-400 for Playwright session persistence.

**Deliverable:** Pi-400 reachable at `pi-400.local`.

---

### Phase 1 — Core local backend & tablet UI (no WhatsApp, no printing)

**Goal:** Fully functional local check-in flow with session confirm UI and DB logging; display label payload for manual writing.

Tasks:

1. Create repo skeleton (FastAPI, SQLAlchemy or raw sqlite access, templates/static).

2. Implement DB schema (DDL + migration script).

3. Implement endpoints: `/api/scan`, `/api/checkin`, `/api/register`, `/api/child/{id}`, `/api/print_payload/{id}`.

4. Implement `sessions` lifecycle (generate session token, expiry 40s).

5. Implement `message_queue` and `print_queue` insert logic (no worker yet).

6. Build minimal tablet UI: `scanner.html`, `confirm.html`, `register.html` using `html5-qrcode` and simple CSS. Include auto-redirect timer.

7. Add logging to `logs` table for all events.

8. Unit tests for key endpoints.

**Deliverable:** Tablets can scan & confirm. Attendance rows persist. Label payload displayed on tablet. Volunteers can manually write stickers.

---

### Phase 2 — WhatsApp Web worker (Playwright) — opt-in & messaging

**Goal:** Send/receive WhatsApp messages locally using Playwright.

Tasks:

1. Implement a Playwright worker (Python) that:
   
   - Loads `web.whatsapp.com` with persistent context.
   
   - If session not authenticated, provides instructions to operator to scan QR (show on Pi-400 monitor or via VNC).

2. Implement incoming message handler:
   
   - Monitor new messages.
   
   - If message content suggests opt-in (e.g., contains “notify” or any predefined text), find matching parent record by phone or create a parent record and set `notify_opt_in = True`.

3. Implement outgoing message sender:
   
   - Poll `message_queue` for `status='pending'` and send messages to `to_phone`.
   
   - Update queue entries with `sent/failed`.

4. Implement rate limiting and retry logic; write to `logs`.

5. Add admin page to view `message_queue` and `logs`.

**Deliverable:** System sends check-in/check-out messages to opted-in parents; incoming messages mark parents as opted in.

---

### Phase 3 — First-time opt-in flow & "2nd check-in" trigger

**Goal:** Implement the special first-time and second-signin behaviors.

Tasks:

1. On `/api/register` return `qr_png_b64` (vCard). Tablet displays QR & button "I have sent a message".

2. Implement `POST /api/confirm_optin` or check directly from Playwright incoming messages.

3. When registration is completed and opt-in verified: immediately queue a check-in WhatsApp message and mark attendance. If not verified, mark attendance but don’t send message.

4. Implement "2nd check-in" detection: on checkin, count previous attendance rows for that child; if `count == 1` (i.e. this is 2nd checkin overall), then queue `request_more_info` message (only if parent opted in).

**Deliverable:** Fully functional opt-in UX and second-visit follow-up.

---

### Phase 4 — Volunteer admin UI & analytics

**Goal:** Provide volunteers with secure login, child profile editing (add medical info), attendance reports and search.

Tasks:

1. Implement `/auth/login` with password hashing (bcrypt). Seed a volunteer user.

2. Admin UI pages: child search, child profile edit (medical info), attendance history, simple graphs (attendance counts per week).

3. Protect medical info behind roles (`volunteer`, `manager`).

**Deliverable:** Volunteers can manage child records and see attendance analytics.

---

### Phase 5 — Printing integration with Dymo (deferred)

**Goal:** Use Dymo LabelWriter at each station to print sticker from tablet.

Options to implement:

- **A. Tablet helper app (Android)** — tablet receives label payload, sends to USB-OTG Dymo via Dymo Android SDK or custom service.

- **B. Pi agent per station** — lightweight Raspberry Pi connected to printer via USB and reachable from central server.

- **C. Central server USB hosting** — connect all printers to Pi-400 via USB hubs (not recommended: fragility/USB bus limits).

**Deliverable (preferred)**: Option A — Android helper app that listens on `localhost` (e.g. `http://127.0.0.1:4000/print`) for POSTed label payloads, then prints silently via Dymo SDK. The server returns label payload to tablet, the browser POSTs to `localhost:4000/print` and helper prints.

---

# 8 — Message templates (examples)

**Check-in (text)**

```
Hi {parent_first}, {child_name} has been checked in to {program} at {time}. We will message you here if any issues.
```

**Check-out (text)**

```
Hi {parent_first}, {child_name} has been checked out at {time}. Thank you.
```

**Request more info (2nd visit)**

```
Hi {parent_first}, thanks for bringing {child_name} regularly. Would you please reply with any allergies, medications or special instructions we should know? Reply here or press the link: {info_link}
```

**Opt-in prompt (QR instructions shown on tablet)**

```
Please save our number and send the message "Notify me" via WhatsApp to receive automatic check-in & check-out alerts for your child.
```

---

# 9 — Security, privacy & compliance

- **Local only**: all data stored locally on Pi-400 unless you choose cloud backups. This reduces exposure.

- **Phone numbers**: store normalized E.164. Do not log or transmit emails/numbers to third parties.

- **Access control**: volunteer accounts (bcrypt hashed passwords). Only volunteers with a role can view medical info.

- **Data retention**: implement retention rules (e.g., purge logs older than X years) if required by policy.

- **Backups**: nightly DB dump to a USB drive or a secure cloud bucket (encrypted). Keep at least 7 daily backups.

---

# 10 — Operational notes & monitoring

- Playwright headless Chromium may occasionally need manual QR re-scan — keep a simple admin panel to show Playwright status (connected / waiting for QR / last-send time / queued messages).

- Add a simple health endpoint `GET /api/heartbeat` returning server and Playwright status.

- Logs should include timestamps and event types. Expose last 100 `logs` in admin UI.

- Implement basic alerting: if `message_queue` has `pending` items older than X minutes, show warning in admin UI.

---

# 11 — Hardware & network checklist

**Hardware**

- Pi-400 (host) with Docker. (You already have this.)

- 6 x Android tablets (8–10") — front camera quality adequate.

- 6 x OTG USB-C cables (for future Dymo printing).

- Dymo LabelWriter 450 ×6 (you already have).

- Optional: small monitor for Pi-400 admin (or VNC headless).

**Network**

- Local LAN with stable Wi-Fi and DHCP reservations.

- Set Pi-400 to a static IP or reserve via router (e.g., `192.168.0.46`).

- Ensure tablets can reach Pi-400 via hostname or IP.

---

# 12 — Developer deliverables (what to code first)

**Sprint 1 (MVP)**

1. Repo skeleton + Dockerfile + docker-compose (FastAPI + worker placeholder).

2. DB schema + migration.

3. Endpoints `/api/scan`, `/api/checkin`, `/api/register` (logic, DB writes).

4. Minimal tablet UI (`scanner.html`, `confirm.html`, `register.html`) with `html5-qrcode`.

5. Unit tests for API flows.

6. Logging to `logs` table.

**Sprint 2**

1. Implement `message_queue` insert logic on checkin.

2. Build Playwright worker skeleton with session persistence and manual admin QR flow (operator scans once).

3. Outgoing message send logic with DB updates (mock first, then connect Playwright send).

**Sprint 3**

1. Incoming message watcher and opt-in marking.

2. First-time opt-in button flow (tablet displays vCard and “I have sent a message” action).

3. 2nd check-in trigger and `request_more_info` queueing.

**Sprint 4**

1. Admin UI for volunteer logins, child edit, medical info input.

2. Analytics endpoints and basic charts (attendance counts).

**Sprint 5**

1. Print integration (Android helper app or Pi agent).

2. Harden logging, backup, and monitoring.

---

# 13 — Testing & QA plan

- **Unit tests**: API endpoints (`/api/scan`, `/api/checkin`, `/api/register`), DB transactions.

- **Integration tests**: simulate tablet flow (scan → confirm → checkin) and assert DB `attendance` row + `message_queue` rows created.

- **Load test**: simulate 6 concurrent tablets scanning at peak (e.g., 100 kids in 15 minutes). Confirm DB and worker keep up.

- **Manual QA**: run real tablet through flows, first-time registration, opt-in, and mock WhatsApp sends.

- **Failure modes**: test offline tablet (cache scan locally), Playwright disconnected (worker offline), DB locked.

---

# 14 — Implementation notes for Claude / developer prompt

When giving this to an AI coder, include these specifics:

- Language & frameworks: **FastAPI (Python)**, SQLAlchemy or `databases` library for async DB, **Playwright (Python)** for WhatsApp worker; `html5-qrcode` in frontend.

- Use environment variables for config:
  
  - `DB_PATH=/data/attendance.db`
  
  - `STATION_TOKENS` (authorized station tokens)
  
  - `PLAYWRIGHT_USER_DATA_DIR=/home/pi/.whatsapp_session`
  
  - `WORKER_POLL_INTERVAL=2` etc.

- Docker: one container runs FastAPI; worker runs in the same container or separate container (recommended separate for resilience).

- Provide `schema.sql` and a DB init script.

- Provide sample curl commands for `/api/scan` and `/api/checkin`.

- Stub printer logic in `printer.py` with TODOs.

---

# 15 — Sample curl commands (quick test)

**Scan**

```bash
curl -X POST http://pi-400.local:8000/api/scan \
  -H "Content-Type: application/json" \
  -d '{"qr_value":"abc123hex","station_id":"entrance-a","device_id":"tablet-01"}'
```

**Confirm checkin**

```bash
curl -X POST http://pi-400.local:8000/api/checkin \
  -H "Content-Type: application/json" \
  -d '{"session_id":"sess_6f7e","station_id":"entrance-a","device_id":"tablet-01","created_by":"vol_amy"}'
```

---

# 16 — Risks & mitigation

- **WhatsApp Web changes**: Playwright may need occasional updates. Keep Playwright pinned and have a quick admin flow to rescan QR and restart the worker.

- **Single Pi failure**: Pi-400 is single point of failure. Mitigate with nightly DB backups and optionally a standby Pi.

- **High volume**: If 100 kids in 15 min → ensure DB writes are lightweight (batch inserts are unnecessary but avoid blocking code); Playwright worker should run in separate process.

- **Dymo printing fragility**: integrating USB printing across many devices can be messy — prefer Android helper per tablet for local USB OTG printing.

---

# 17 — Next immediate actions (what you should do now)

1. Confirm tablet hardware list & buy tablets.

2. Prepare Pi-400: OS update, Docker install, allocate folder for Playwright session.

3. Create repository skeleton and implement **Phase 1** (API + tablet UI).

4. Build one tablet test flow and verify DB entries for 10–20 dummy kids.

5. Once Phase 1 is stable, implement Playwright worker skeleton and run an initial WhatsApp login.


