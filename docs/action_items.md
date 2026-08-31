# FACT Project — Official Action Items & Roadmap

Based on current infrastructure status and architectural requirements, here is the prioritized roadmap for the development team to prepare the FACT registration system for the upcoming conference.

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
