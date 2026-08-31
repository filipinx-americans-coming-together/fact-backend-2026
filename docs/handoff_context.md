# FACT Registration Backend — Developer Handoff Context

This document serves as the master context file for the FACT registration backend. It summarizes a deep-dive architectural audit, the critical flaws discovered, the technical reasoning behind the proposed solutions, and explicit instructions for implementing Shibboleth (SAML) SSO.

---

## 1. What We Audited & Discovered
We audited the Django codebase to understand how data flows and what the previous development team left unfinished.
- **The "Faked" Emails:** The `settings.py` file uses Django's `locmem` email backend during tests. This means emails run successfully in the code without crashing, but they don't actually send to real inboxes unless it is deployed to production.
- **Data Upload Flow:** All core data (Locations, Schools, Workshops) must be uploaded via Excel sheets in a strict order by an admin. 
- **Missing Admin Features:** The backend has endpoints for Admin tools (Agenda, Notifications, feature flags), but the **Reset Database** function to wipe old accounts was never implemented. Furthermore, the frontend dashboard to use these endpoints appears unfinished.

## 2. Architectural Flaws & Our Reasoned Solutions

### Flaw A: The Eventbrite Payment Loophole
**The Problem:** The current registration flow blindly trusts the frontend. When a user pays on Eventbrite, the React frontend flips a boolean to `true` and submits the form. Anyone can bypass this by inspecting the page, allowing them to register without paying.
**The Solution:** The backend `POST /registration/delegates/` endpoint must be rewritten to accept an Eventbrite `order_id`. The backend must server-to-server query the Eventbrite API to verify the ticket is paid and ensure that specific `order_id` hasn't been used by another delegate.

### Flaw B: Verifying UIUC Students for Free Tickets
**The Problem:** UIUC students get free tickets. Relying on shared "100% off" Eventbrite promo codes is insecure because students share them with non-UIUC friends.
**The Solution:** UIUC students bypass Eventbrite entirely on the frontend. Instead, they authenticate via **Shibboleth (UIUC's official SSO)**. Once verified, the backend generates a single-use, 100% off promo code (e.g., `UIUC_jsmith2_X9B`) via the Eventbrite Discounts API, and secretly injects it into the checkout widget so Eventbrite can still track the auditorium capacity accurately.

## 3. UIUC Shibboleth Implementation Context
*(Note to future developers or AI agents reading this: Do not follow the official UIUC IT documentation that suggests installing the native `shibd` daemon.)*

Because this application is hosted on **DigitalOcean App Platform**, you do not have root OS access to install background C++ daemons like `shibd`. 
**The Technical Plan:**
1. Use a Python-native SAML library (e.g., `python3-saml` or `django-saml2-auth`).
2. Add an `Aptfile` to the repository root containing `libxmlsec1-dev` and `pkg-config` so DigitalOcean installs the necessary C-bindings for the Python SAML library to compile.
3. Build the Django endpoints (`/saml/login`, `/saml/acs/`, `/saml/metadata/`).
4. Generate self-signed SSL certs locally to sign the SAML requests.
5. Provide the generated XML Metadata to the project admin so they can register the app as a Service Provider on the UIUC iTrust Federation Registry.

## 4. Local Testing & Infrastructure
- The `.env` file should not be committed to GitHub.
- Developers should use `DEVELOPMENT_MODE=True` in their local `.env` file. This tells Django to ignore DigitalOcean and PostgreSQL, and instead spin up a free, local `db.sqlite3` file for testing.
- The entire Shibboleth login flow and Eventbrite dynamic API generation can and should be tested locally before paying to spin up the DigitalOcean production server.

## 5. Next Steps
Please refer to the `action_items.md` roadmap for the step-by-step checklist of what to build first.
