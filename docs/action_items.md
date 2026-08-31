# FACT Project — Official Action Items & Roadmap

Based on current infrastructure status and architectural requirements, here is the prioritized roadmap for the development team to prepare the FACT registration system for the upcoming conference.

## 📌 Update (2026-08-31): Eventbrite verified, capacity race fixed, CI actually works now — read this first

If you're a new Claude Code session picking this up, start here — the 2026-08-17 section below is still accurate background on the three-frontend situation, but the "one substantial backend task left" framing in it is now out of date.

**What got done since 2026-08-17:**

1. **Eventbrite integration verified against the real API v3 spec** (the thing the 2026-08-17 update called "the one substantial backend task left"). `registration/payment/eventbrite_client.py`'s `_real_create_discount`/`_real_get_order` were never actually checked against Eventbrite's real docs — they were a documented best guess. Checked them against the real `eventbrite-api-v3-public.apib` spec and found two real mismatches: discount creation is **organization-scoped** (`POST /organizations/{organization_id}/discounts/`), not event-scoped like the code assumed, and the request body must be **JSON nested under `"discount"`**, not form-encoded flat keys. Both fixed; added `EVENTBRITE_ORGANIZATION_ID` setting (`.env` / DO env var, not sensitive) and regression tests that lock in the correct request shape. Order retrieval (`GET /orders/{id}/`, `expand=attendees`) already matched the spec — no change needed there.
   - **Still blocking:** an actual Eventbrite API token + organization ID + event ID for a real (or sandbox) event, to flip `EVENTBRITE_MOCK_MODE` off and prove this end-to-end once. Nobody has provided one yet.
2. **Fixed IT Bugs FACT 2024 #6 ("why are we over capacity")** — the real cause: all three workshop-registration paths (`delegate_me` PUT, `delegates` POST, `register_facilitator` PUT) did a capacity `SELECT` followed by a separate `INSERT` with no locking, so two concurrent requests could both pass the capacity check before either wrote — a classic TOCTOU race, worse the closer a workshop gets to full. Fixed with `select_for_update()` on the relevant `Workshop` rows inside one transaction spanning the check and the write, locked in pk order across all three call sites to avoid deadlocks. Found and fixed a second latent bug in the same code: `register_facilitator`'s same-session duplicate check compared a workshop's primary key against a set of session numbers — could never actually fire.
3. **Cross-checked the "IT Bugs FACT 2024" list (8 items) against current code:** #3 (agenda edit needing building/room) and #7 (Eventbrite paid but no account — this session's earlier `claim_order` purchase-first flow) were already fixed. #4/#5/#6 (capacity checks) — see above. #1, #2, #8 (stale login session, workshop-rename showing stale data, networking showing under wrong sessions) all look like **frontend caching/display bugs** — nothing in the backend models or views explains them; needs someone with frontend access to actually chase.
4. **Fixed a crash**: `fact_admin/agenda/views.py`'s single-item agenda create endpoint did `int(session_num)` unconditionally — crashed with an uncaught `TypeError` any time `session_num` was omitted (it's documented as optional; the bulk-upload path already guarded this correctly, the single-item one didn't).
5. **CI pipeline fixed — and this is a big one.** `gh run list` on this repo (and the 2025 repo it was copied from) shows **every single CI run in either repo's history as a failure**. Root cause: none of the six secrets `.github/workflows/django.yml` references (`DEVELOPMENT_MODE`, `SECRET_KEY`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `RESET_PASSWORD_URL`, `ACCOUNT_SETUP_URL`) were ever configured in this repo's GitHub secrets — `gh secret list` returned none. `DEVELOPMENT_MODE` resolving to an empty string sent `settings.py` down the "expects a real Postgres `DATABASE_URL`" branch, which crashed before Django even finished loading — before a single test ran. Fixed by verifying against an actual CI-equivalent local run (not just reasoning about it) and using GitHub Actions' `secrets.X || 'fallback'` pattern for every env var that's read with no code-level default (`EMAIL_HOST_USER`, `RESET_PASSWORD_URL`, and `ACCOUNT_SET_UP_URL` — the workflow had this one misspelled `ACCOUNT_SETUP_URL`, missing the second underscore, so even a correctly-named secret wouldn't have been read). **Confirmed green on GitHub for the first time** (run `33419171724`). CI does not need any real secrets configured to pass — the fallback values are CI-only placeholders. Real secrets can still be added for extra realism; they're optional, not required, and only affect what GitHub Actions sees (see the email/credentials note below — DigitalOcean has its own, completely separate env var store).
6. **Confirmed the "import data" and "export rosters" ask is already fully built**, backend and frontend both: `workshops/bulk/`, `locations/bulk/`, `schools/bulk/`, `agenda-items/bulk/` are all working Excel-upload admin endpoints, wired to drag-and-drop upload pages in `fact-frontend-2026`'s `src/app/admin/`. `sheets/delegates/` and `sheets/locations/` exports are wired to download buttons on the admin dashboard already. Nothing to build here.

**Email configuration — how it actually works, since this came up:**

- GitHub Actions secrets and DigitalOcean App Platform environment variables are **two completely separate stores**. Configuring a value in one has zero effect on the other. GitHub secrets only affect what CI sees when running tests (and CI doesn't need real values — see above). To make the *live* deployed backend send real emails, the values need to go into DO's App Platform dashboard (Settings → App-Level Environment Variables), not GitHub.
- `EMAIL_HOST_USER` / `EMAIL_HOST_PASSWORD` are a Gmail account's address and app password, used as the FACT no-reply sender. The 2025 repo has all six of these already configured as GitHub secrets (confirmed via screenshot of its repo settings) — but GitHub secrets can't be read back out by anyone, including via the API, so those values have to be re-entered by hand from wherever they're actually known (a password manager, or DO's dashboard if the 2025 app is still deployed there and its env vars are still visible).
- `RESET_PASSWORD_URL` and `ACCOUNT_SET_UP_URL` (note: the code reads `ACCOUNT_SET_UP_URL` with two underscores — double-check this when entering it, since the old workflow file had it misspelled) are the frontend URLs these emails link to. Worth double-checking they point at `fact-frontend-2026`'s actual routes, not a stale 2025 path, before they go into DO.

**Admin page — designed, not yet built.** The one genuinely missing piece from the "day-of registration + import + export" ask (import/export both already exist, see above): an admin-only endpoint + frontend page for creating a delegate account in person, on the day of the conference. Agreed design, not yet implemented:
- **Backend:** new `POST fact-admin/delegates/day-of/` in `fact_admin/actions/views.py`, `FACTAdmin`-gated. Takes name/email/pronouns/year/school + an Eventbrite order ID (the door sale) + optional 3 workshop picks. Reuses `_create_delegate_account` (already extracted and shared by `create_delegate`/`claim_order`) for the account, and the same order-verification logic as `claim_order` to set `payment_status`/`ticket_type` — so a day-of delegate is trustworthy the same way an online one is. Must **not** call `login()` — that would swap the admin's own session for the new delegate's. Whether day-of registration should be able to bypass Eventbrite entirely (mark paid directly, e.g. for comped tickets) is **still an open question** — the design defaults to requiring a real Eventbrite order ID as the safe option, and that's additive to change later, not a rewrite.
- Since this would be a third copy of the capacity-locked workshop-registration logic (see bug #6 fix above), extract that into one shared helper reused by `delegate_me`, `delegates`, and this new endpoint.
- **Frontend** (`fact-frontend-2026`): new `admin/day-of/page.tsx` + a `useCreateDayOfDelegate` hook, reusing the existing `useSchools`/`useWorkshops` hooks (same ones the public registration wizard uses). One new link in `admin/components/Navbar.tsx`.

**Admin privilege promotion — needs a decision, a few options on the table:**

Right now the *only* way to grant `FACTAdmin` group membership is logging into Django's raw `/admin/` panel and assigning the group by hand (Phase 3 below) — no in-product way for an existing admin to promote someone else, and no self-service path at all. Worth deciding before this becomes a yearly bottleneck for handing off to the next IT chair. Options, not mutually exclusive:

1. **Domain-based auto-grant** — anyone signing up with a `@psauiuc.org` email gets auto-added to `FACTAdmin`. Zero manual work, but risky as the *sole* gate: depends on knowing `@psauiuc.org` addresses are actually restricted to people who should have admin (not just any PSA-UIUC member), and there's currently no signup path that even checks admin status at account-creation time — this would be new trust-boundary logic, not a small tweak.
2. **Manual promotion via Django `/admin/`** — what exists today. Zero new code, but requires Django-admin/superuser access, which likely means only the current dev has it — doesn't scale to a clean year-to-year handoff between IT chairs.
3. **In-product promotion endpoint** — an existing `FACTAdmin` can promote another registered user (by email) to `FACTAdmin` from inside the actual `fact_admin` frontend, no raw Django admin needed. This is the actual UX gap. Should probably be logged/audited given it grants the most powerful role in the system, and could use option 1's domain check as a soft warning (not a hard gate — a nudge, since the domain alone isn't a reliable enough signal to fully trust).

Recommendation if it needs one: build option 3, keep option 2 as the break-glass fallback, and skip a hard-gated version of option 1 — use it at most as a warning in option 3's UI ("this email isn't @psauiuc.org, are you sure?").

**Still open, unchanged from before:** the mentioned Eventbrite API key hasn't actually been located/provided yet — needed to flip `EVENTBRITE_MOCK_MODE` off for a real end-to-end test. Frontend CI/CD (no GitHub Actions at all in `fact-frontend-2026`; Vercel's own Git integration is the only thing gating deploys, via whatever `next build` itself catches) — deferred, not started.

---

## 📌 Update (2026-08-17): Registration Pipeline Plan — read this first

Everything below this section was written earlier and is now partly out of date — Shibboleth login and the Eventbrite promo-code *code* both got built since then (see "what's actually done" below). This section is the current, accurate picture. If you're a new Claude Code session picking this up, start here.

**Where things stand, in plain terms:**

We have three separate frontend attempts and one backend, none of them fully connected to each other yet:

1. **The real backend** (this repo) — already knows how to create accounts, let people pick workshops, run the admin tools, and log delegates in through UIUC's official login system (Shibboleth). It also has code that's *supposed* to create a free one-time discount code on Eventbrite once a UIUC student logs in — but that code has never actually been tested against the real Eventbrite service, only a fake pretend version of it.
2. **A 2025 version of the website** (`fact-website-frontend` repo, the working one from last year) — this is the only frontend that ever actually talked to the backend for real: creating accounts, letting people register for workshops, taking payment through Eventbrite. It's old, it doesn't know about UIUC login or promo codes (those didn't exist yet), and it has the site's old visual design, not the new one.
3. **A brand-new visual design** (`fact-frontend-2026` repo) — this is just the *look* of the new site. Pages, colors, layout, images. It doesn't talk to the backend at all — no login, no signup, no payment, nothing works, it's a mockup.

**The plan: take #2's working guts, put #3's new look on it, and build the missing UIUC/promo-code piece for real.**

### Backend goals, in order

There is really only **one substantial backend task left** — everything else the backend needs to do, it can already do.

1. **Confirm the Eventbrite discount-code feature actually works.** The code that's supposed to create a real one-time-use discount code on Eventbrite (`registration/payment/eventbrite_client.py`) has only ever run in a "pretend" test mode — it has never made one real request to Eventbrite. Before this can go live:
   - Look up Eventbrite's real, current API documentation for creating discount codes and looking up orders.
   - Double check the code is asking for the right information in the right format (the person who wrote it left a note admitting the exact field names were a best guess, never verified).
   - Get a real Eventbrite account/API key for a test event, turn off the "pretend" mode, and try it for real — create a code, make sure it actually works at checkout, make sure the backend can look up the order afterward.
   - Only after that works, get the real credentials for the actual FACT 2026 event.

That's it for the backend. Everything else — creating accounts, signing up for workshops, admin tools, the UIUC login itself — already works and doesn't need backend changes.

### Frontend goals, in order

The frontend needs the most work, because none of the three existing frontends do everything. Start from the 2025 site (option #2 above) — it's the only one that actually works with the backend.

1. **Fix a small existing bug**: when someone signs up, the field for their school name doesn't match what the backend expects, so it silently gets lost. One-line fix.
2. **Actually confirm payment before letting someone finish registering.** Right now the 2025 site's registration form doesn't tell the backend anything about the Eventbrite payment at all — it just assumes payment happened and lets the person in. The backend already has a proper endpoint to verify a purchase really happened on Eventbrite (`POST /registration/verify-payment/`) — the frontend just needs to actually call it after checkout, before finishing registration. This is the actual fix for the "anyone could get in for free" problem from last year.
3. **Build the UIUC login button and the free-ticket flow.** This doesn't exist anywhere yet. Add a "Log in with UIUC" option that sends the person through Shibboleth, and once they're verified, request their one-time discount code from the backend and feed it into the Eventbrite payment popup automatically so it's a free ticket for them. (This step depends on backend goal #1 above actually working first — no point wiring up a discount code that doesn't work.)
4. **Give the 2025 site the new 2026 look.** Don't just copy the new design's files in directly — the two versions of the site are built differently under the hood and the styles would clash. Instead, pull just the *values* (colors, fonts, spacing) from the new design and use them to restyle each page of the 2025 site, using the new design as the visual reference. Some pages in the new design (like the vendor/palenke page) don't have an equivalent in the old site yet and need a decision on where they go.
5. **Point everything at the real backend and test the whole thing end to end** — sign up, log in with UIUC, get the free code, pay on Eventbrite, get confirmed, pick workshops, see your dashboard — before turning off any "pretend" modes in the real, live version of the site.

---

## 🟢 Phase 1: Infrastructure & Bug Fixes (Immediate Priority)

Good news: The DigitalOcean account is already set up, the PostgreSQL database is intact, and the `.env` file is being provided.

- [ ] **Restore DigitalOcean Deployment:** Ensure the App Platform is pulling from the `main` branch and the provided `.env` variables are properly loaded into the DigitalOcean dashboard.
- [ ] **Fix Email Configuration Bug:** In the backend code, fix the inconsistency where `os.getenv` is used in one file but `env()` is used everywhere else. This prevents silent email failures.
- [ ] **Fix HTTP Link Bug:** Update the `ACCOUNT_SET_UP_URL` configuration to use `https://` instead of `http://` so facilitator setup links are secure.

## 🔒 Phase 2: Security & Eventbrite Integration (High Priority)

The current registration flow has a critical security flaw where it blindly trusts a frontend boolean variable. This must be fixed to prevent unauthorized free registrations.

- [ ] **Implement Shibboleth (UIUC Verification):** 
  - Reach out to UIUC Tech Services to register the app as an official Service Provider.
  - Install the necessary SAML libraries (e.g., `python3-saml`) and build the Shibboleth SSO login flow.
- [ ] **Dynamic Eventbrite Promo Codes (Backend):**
  - When Shibboleth verifies a student, the backend must call the Eventbrite Discounts API.
  - Generate a 100% off, single-use promo code formatted as `UIUC_<netid>_<random>`.
  - Pass this code to the frontend to be automatically and secretly injected into the Eventbrite widget.
- [ ] **Secure Eventbrite Verification (Backend):** Update the `POST /registration/delegates/` endpoint. For non-UIUC students, the backend must require an Eventbrite `order_id` and query the Eventbrite API to verify it is paid and valid before creating the account in the database.

## ⚙️ Phase 3: Admin Features & Database Management (Medium Priority)

The system needs proper tools for coordinators to manage the conference lifecycle and clean up old data.

- [ ] **Build Database Cleanup Function:** Create a secure endpoint (or Django management command) that deletes all old `User` accounts that haven't logged in for 2+ years (excluding FACTAdmin accounts). Because of the database structure, this will automatically cascade and delete their old delegate profiles and workshop registrations, wiping the slate clean for the new year.
- [ ] **Build Mass Email Feature:** Convert the existing `sendupdate.py` script logic into a usable API endpoint so admins can send announcements to all registered delegates.
- [ ] **Admin Roles & Privileges Setup:** Ensure coordinators are properly set up with admin access.
  - Log into the developer-level Django `/admin/` panel, create accounts for the coordinators, and assign them to the `FACTAdmin` group.
  - This grants them privileges to view the full database, globally edit records, and manually create users (bypassing the standard registration flow).
- [ ] **Frontend Admin Dashboard UI:** Ensure the frontend React admin pages are actually connected to the existing backend endpoints (`/fact-admin/notifications/`, `/fact-admin/agenda-items/`, `/fact-admin/summary/`) so coordinators have a user-friendly dashboard to work in.

## 📊 Phase 4: Data Upload Workflow (Pre-Conference)

Once the system is live and the database is cleaned up, the admin team must upload the new year's data in this exact, strict order:

1. **Upload Locations:** Bulk import the Excel file of rooms and capacities.
2. **Upload Schools:** Bulk import the Excel file of allowed universities.
3. **Upload Workshops:** Bulk import the Excel file of workshops and facilitators (this automatically assigns rooms and emails setup links to facilitators).
4. **Upload Agenda:** Bulk import the conference day schedule.
