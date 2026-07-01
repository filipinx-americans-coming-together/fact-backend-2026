# FACT 2026 — Summer Engineering Roadmap
#### Technical Product Manager's Plan of Action

> **Scope:** ~12 weeks, late June → mid-September 2026
> **Goal 1:** Launch the redesigned FACT public website (minus registration) by the week of August 24, 2026.
> **Goal 2:** Launch the full registration system with UIUC Shibboleth authentication and Eventbrite payments by mid-September 2026.
> **Ground rule:** Each phase must pass its validation steps before the next phase begins.

---

## At-a-Glance Timeline

```
JUNE/JULY            JULY/AUGUST                  AUGUST                       SEPTEMBER
└───────────┬────────┴────────────┬───────────────┴────────────┬───────────────┴────────┘
  Phase 1     Phase 2              Phase 3                      Phase 4 & 5
  Weeks 1–2   Weeks 3–6            Weeks 7–9                    Weeks 10–12
  Foundation  Frontend restyling   Shibboleth & Payments        Reg Flow & Hardening
  & Cleanup   & Public Website     Public Website Launch        Registration Opens
              (Target: Aug 24)     (Target: Aug 24)             (Target: Mid-Sept)
```

---

## Phase 1 — Foundation & Low-Hanging Fruit
### Weeks 1–2 · June 26 – July 9

> **Spirit of this phase:** Fix safety vulnerabilities, clean up code smells, and improve query performance first to establish a clean and robust codebase.

---

### 🎯 Milestone 1.1 — Security Triage (Week 1, Days 1–2) ✅
**"Fix what could hurt us before we touch anything else"**

**Core Objectives:**
1. Remove all debug `console.log` / `print()` statements that leak sensitive data
2. Eliminate all `@csrf_exempt` decorators from mutating endpoints
3. Wrap all multi-step database writes in `transaction.atomic()`

**Target Files:**
| File | What to Change | Status |
|---|---|---|
| [`src/util/fetchWithCredentials.ts`](file:///c:/Users/megan/fact-website-frontend/src/util/fetchWithCredentials.ts) | Remove `console.log("cooke", document.cookie)` — L22 | ✅ Completed |
| [`src/hooks/api/useVerifyEmail.ts`](file:///c:/Users/megan/fact-website-frontend/src/hooks/api/useVerifyEmail.ts) | Remove `console.log(email, code)` — L6 | ✅ Completed |
| [`src/hooks/api/useAdminLogin.ts`](file:///c:/Users/megan/fact-website-frontend/src/hooks/api/useAdminLogin.ts) | Remove `console.log(response)` — L16 | ✅ Completed |
| [`registration/workshop/views.py`](file:///c:/Users/megan/fact-website-backend/registration/workshop/views.py) | Remove `@csrf_exempt` from `workshops_bulk` — L76 | ✅ Completed |
| [`registration/school/views.py`](file:///c:/Users/megan/fact-website-backend/registration/school/views.py) | Remove `@csrf_exempt` from `schools_bulk` — L72 | ✅ Completed |
| [`registration/location/views.py`](file:///c:/Users/megan/fact-website-backend/registration/location/views.py) | Remove `@csrf_exempt` from `locations_bulk` — L138 | ✅ Completed |
| [`fact_admin/actions/views.py`](file:///c:/Users/megan/fact-website-backend/fact_admin/actions/views.py) | Remove `@csrf_exempt` from `send_facilitator_links` — L254 | ✅ Completed |
| [`fact_admin/agenda/views.py`](file:///c:/Users/megan/fact-website-backend/fact_admin/agenda/views.py) | Remove `@csrf_exempt` from `agenda_items_bulk` — L110 | ✅ Completed |
| [`registration/delegate/views.py`](file:///c:/Users/megan/fact-website-backend/registration/delegate/views.py) | Wrap `create_delegate` and `delegates` POST in `transaction.atomic()` | ✅ Completed |

---

### 🎯 Milestone 1.2 — Code Smell Cleanup (Week 1, Days 3–5)
**"Make the codebase readable for every future IT chair"**

**Core Objectives:**
1. Replace all 25 bare `except:` clauses with specific exception types
2. Delete all commented-out dead code blocks
3. Do a project-wide `console.log` and `print()` sweep for the remaining ~30 non-sensitive debug statements

**Target Files:**
| File | Count |
|---|---|
| [`registration/delegate/views.py`](file:///c:/Users/megan/fact-website-backend/registration/delegate/views.py) | 8 bare excepts — highest priority |
| [`registration/facilitator/views.py`](file:///c:/Users/megan/fact-website-backend/registration/facilitator/views.py) | 7 bare excepts |
| [`registration/workshop/views.py`](file:///c:/Users/megan/fact-website-backend/registration/workshop/views.py) | 3 bare excepts |
| [`registration/management/commands/matchworkshoplocations.py`](file:///c:/Users/megan/fact-website-backend/registration/management/commands/matchworkshoplocations.py) | Delete L178–L222 (old algorithm, 45 lines) |
| [`src/app/page.tsx`](file:///c:/Users/megan/fact-website-frontend/src/app/page.tsx) | Delete L69–L113 (entire old homepage, commented out) |
| [`src/app/admin/components/DangerZone.tsx`](file:///c:/Users/megan/fact-website-frontend/src/app/admin/components/DangerZone.tsx) | Delete L16–L27 and L79–L91 |
| `src/hooks/api/*.ts` (all hooks) | Remove remaining `console.log("isSuccess", ...)` lines |

**Validation Steps:**
- [ ] Run `python manage.py test` — all tests still pass
- [ ] Run `npm run lint` in frontend — no new lint errors introduced
- [ ] Manually trigger each error path (wrong password, bad email, etc.) — confirm error responses still return the correct status codes and messages

---

### 🎯 Milestone 1.3 — Performance Quick Win (Week 2)
**"Fix the N+1 query before high-traffic registration"**

**Core Objectives:**
1. Annotate registration counts directly onto the workshops queryset (eliminates 30 extra API calls on page load)
2. Refactor `delegate_sheet` export to use `select_related` / `prefetch_related` (eliminates ~900 queries per export)
3. Extract the shared API response parser into a reusable utility

**Target Files:**
| File | Change |
|---|---|
| [`registration/workshop/views.py`](file:///c:/Users/megan/fact-website-backend/registration/workshop/views.py) | Add `annotate(registration_count=Count('registration'))` to `workshops()` GET |
| [`src/hooks/api/useWorkshops.ts`](file:///c:/Users/megan/fact-website-frontend/src/hooks/api/useWorkshops.ts) | Remove `useQueries` block (L98–L115); read `registrationCount` from the single response |
| [`fact_admin/actions/views.py`](file:///c:/Users/megan/fact-website-backend/fact_admin/actions/views.py) | Refactor `delegate_sheet` to use `.select_related('user', 'school').prefetch_related('registration_set__workshop')` |
| `src/util/parseApiResponse.ts` | **[NEW]** Create shared response parser utility |
| `src/hooks/api/useCreateAccount.ts`, `useRegister.ts`, `useUpdateUser.ts` (+ 12 others) | Replace copy-pasted error-handling block with `parseApiResponse()` call |

**Validation Steps:**
- [ ] Open browser DevTools → Network tab on `/my-fact/workshops` — confirm **1 request** instead of 31
- [ ] Open Admin → download Delegate sheet — confirm it still exports correctly and is noticeably faster

---

## Phase 2 — Frontend Restyling & Core Website
### Weeks 3–6 · July 10 – August 6

> **Spirit of this phase:** Overhaul the visual styling, apply the new FACT 2026 design system, and implement all non-registration public pages. This builds the foundational UI so we can ship the website (minus registration) on schedule.

---

### 🎯 Milestone 2.1 — Design Token System & Base Styling (Week 3)
**"Establish the visual language before touching components"**

**Core Objectives:**
1. Define FACT 2026 color palette, typography scale, and spacing system as CSS custom properties
2. Set up Google Fonts (e.g. Outfit for headings, Inter for body text)
3. Set up responsive base layouts

**Target Files:**
| File | Change |
|---|---|
| [`src/app/globals.css`](file:///c:/Users/megan/fact-website-frontend/src/app/globals.css) | Define CSS custom variables (`--color-primary`, `--font-heading`, `--radius-card`, etc.) |
| [`src/app/layout.tsx`](file:///c:/Users/megan/fact-website-frontend/src/app/layout.tsx) | Integrate fonts and standard meta tags |
| `src/styles/tokens.css` | **[NEW]** Isolate typography and color palettes for clean reference |

---

### 🎯 Milestone 2.2 — Core Component Library Update (Week 4)
**"Rebuild shared UI components to use the design system"**

**Core Objectives:**
1. Redesign buttons, form fields, cards, and modal components using design tokens
2. Modernize the global header `Navbar` and `Footer`
3. Centralize input states (focus, disabled, error styling)

**Target Files:**
| File | Change |
|---|---|
| [`src/components/ui/`](file:///c:/Users/megan/fact-website-frontend/src/components/ui) | Apply tokens to: `Select`, `TextInput`, `LinkButton`, `InteractiveButton` |
| [`src/components/navigation/Navbar.tsx`](file:///c:/Users/megan/fact-website-frontend/src/components/navigation/Navbar.tsx) | Style nav elements with Outfit and modern transparency effects |
| [`src/components/formatting/PageFooter.tsx`](file:///c:/Users/megan/fact-website-frontend/src/components/formatting) | Update layout and typography |

---

### 🎯 Milestone 2.3 — Public Website Restyling (Weeks 5–6)
**"Assemble and polish public-facing sections of the site"**

**Core Objectives:**
1. Restyle public pages: Homepage, About, Team, and FAQ
2. Redesign the public Workshop Catalog so delegates can view workshop descriptions and facilitators before registering
3. Enable static builds and configure routing for public-only pages

**Target Files:**
| File | Change |
|---|---|
| `src/app/page.tsx` | Redesign the landing page with Outfit headings, smooth transitions, and premium graphics |
| `src/app/about/page.tsx`, `faq/page.tsx`, `team/page.tsx` | Restyle text blocks and structure using semantic HTML elements |
| `src/app/workshops/page.tsx` & `[slug]/page.tsx` | Redesign list layout and single-workshop view using card components |

**Validation Steps:**
- [ ] Visually verify responsive formatting on mobile (375px), tablet (768px), and desktop (1280px)
- [ ] Confirm Lighthouse scores for Public landing page are Performance ≥ 85, Accessibility ≥ 90

---

## Phase 3 — Shibboleth SSO & Eventbrite Integration
### Weeks 7–9 · August 7 – August 27

> **Spirit of this phase:** Integrate identity management and external payments. The primary goal is UIUC Shibboleth Single Sign-On (SSO) and the Eventbrite payment bridge.

---

### 🎯 Milestone 3.1 — Shibboleth SSO Integration (Weeks 7–8)
**"Authenticate UIUC students when purchasing tickets and registering"**

**Core Objectives:**
1. Set up Shibboleth authentication middleware in Django to read identity headers forwarded by Nginx/Apache (EPPN, Email, First Name, Last Name)
2. Support custom user accounts: auto-create user accounts for UIUC students authenticated via Shibboleth, and maintain standard password logins for non-UIUC delegates
3. Connect Next.js login buttons to Shibboleth login endpoints and handle callback redirections

**Target Files:**
| File | Change |
|---|---|
| [`fact_registration_backend/settings.py`](file:///c:/Users/megan/fact-website-backend/fact_registration_backend/settings.py) | Configure `RemoteUserBackend` / custom Shibboleth authentication backend |
| [`registration/delegate/views.py`](file:///c:/Users/megan/fact-website-backend/registration/delegate/views.py) | **[NEW]** `shibboleth_login()` and callback handlers; map headers to User/Delegate fields |
| [`registration/urls.py`](file:///c:/Users/megan/fact-website-backend/registration/urls.py) | Add `shibboleth/login/` and authentication routes |
| `src/app/my-fact/login/page.tsx` | **[NEW]** Add "Sign in with UIUC NetID" SSO option |

**Validation Steps:**
- [ ] Mock header values (e.g., `HTTP_SHIB_EPPN`) in local dev to confirm Django's remote user backend automatically initializes user records
- [ ] Verify that UIUC-authenticated accounts bypass standard password creation steps but still successfully generate a `Delegate` record

---

### 🎯 Milestone 3.2 — Eventbrite Payment Bridge (Weeks 8–9)
**"Integrate ticket purchases and verify paid status automatically"**

**Core Objectives:**
1. Integrate Eventbrite client-side payment actions inside the purchase section
2. Add fields to track payments: `payment_status`, `eventbrite_order_id`, and `ticket_type` to `Delegate` model
3. Build the Eventbrite webhook endpoint with HMAC signature verification to set status to `paid` once a ticket is bought

**Target Files:**
| File | Change |
|---|---|
| [`registration/models.py`](file:///c:/Users/megan/fact-website-backend/registration/models.py) | Add payment attributes to `Delegate` model |
| `registration/delegate/views.py` | Add `record_payment_intent()` view |
| `fact_admin/webhook/views.py` | **[NEW]** `eventbrite_webhook()` — receive webhook, verify signature, and update the associated Delegate's payment status |
| [`fact_registration_backend/settings.py`](file:///c:/Users/megan/fact-website-backend/fact_registration_backend/settings.py) | Configure `EVENTBRITE_API_KEY` and `EVENTBRITE_WEBHOOK_SECRET` |

---

### 🚀 Public Website Launch (Target: Week of August 24)
* **Goal:** Deploy the public-facing pages (Homepage, About, Team, FAQ, and Workshop Listing) to production.
* **Scope:** Registration routes will be locked down or hidden with a placeholder ("Registration Opens Mid-September") so students can browse workshops and read info while the backend finishes registration configurations.

---

## Phase 4 — Registration Flow & Admin Dashboard
### Weeks 10–11 · August 28 – September 10

> **Spirit of this phase:** Assemble the multi-step registration workflow (incorporating Shibboleth SSO checking and payment verification) and deliver the new Admin tools.

---

### 🎯 Milestone 4.1 — Registration Flow & Workshop Selection (Week 10)
**"Deliver the registration wizard with SSO & Payment gates"**

**Core Objectives:**
1. Build the multi-step Registration Wizard interface: 
   * **Step 1:** Authentication (Illinois NetID via Shibboleth OR email/password signup for non-UIUC students)
   * **Step 2:** Payment verification (checking the Delegate's `payment_status` is `"paid"`)
   * **Step 3:** Workshop selection (3 sessions, checking location capacity limits)
2. Enforce registration capacity limits and session locks on the backend

**Target Files:**
| File | Change |
|---|---|
| `src/app/my-fact/register/page.tsx` | Implement multi-step registration UI wizard with validation checks |
| [`registration/delegate/views.py`](file:///c:/Users/megan/fact-website-backend/registration/delegate/views.py) | Enforce that `delegates` registration POST requires a verified payment status |
| `src/hooks/api/useRegister.ts` | Refactor registration mutations to support multi-step calls |

---

### 🎯 Milestone 4.2 — Admin Dashboard Frontend & API (Week 11)
**"Build new admin views for registration and account maintenance"**

**Core Objectives:**
1. Build Admin API endpoints for delegate deletion, admin promotion, and day-of registration bypasses
2. Implement three new Admin interfaces: Registrations table (with bulk options), Account Management (with privilege promotion), and Day-of Registration Override

**Target Files:**
| File | Change |
|---|---|
| [`fact_admin/actions/views.py`](file:///c:/Users/megan/fact-website-backend/fact_admin/actions/views.py) | Build 7 new admin endpoints (e.g., `/fact-admin/delegates/`, `/fact-admin/accounts/admins/`) |
| `src/app/admin/registrations/page.tsx` | **[NEW]** Admin list of delegates with filters, search, and bulk deletion |
| `src/app/admin/accounts/page.tsx` | **[NEW]** Admin list and controls to manage admin user privileges |
| `src/app/admin/registrations/create/page.tsx` | **[NEW]** Day-of manual registration form |

---

## Phase 5 — Testing, Hardening & Launch
### Week 12 · September 11 – September 17

> **Spirit of this phase:** Verify performance limits, implement rate-limiting protections, and open registration mid-September.

---

### 🎯 Milestone 5.1 — Load Testing & Security Sweeps (Days 1–3)
* Run load tests using `locust` simulating 100 concurrent users registering workshops to ensure response times stay under 1000ms.
* Implement rate limiting on all login, registration, and email verification routes (`django-ratelimit`).
* Verify CORS settings, configure production server variables, and confirm `DEBUG = False`.

---

### 🚀 Registration Opens (Target: Mid-September)
* **Goal:** Launch the registration wizard live! UIUC students can authenticate with their NetID and secure seats.

---

## Summary Scorecard

| Milestone / Event | Target Date | Key Deliverable | Validation Metric |
|---|---|---|---|
| **Phase 1** Cleanup | July 9 | Safe & optimized base code | Tests pass, no bare excepts or debug logs |
| **Phase 2** Styling | August 6 | Design token system & updated components | Fully responsive component preview |
| **Phase 3** Integration | August 20 | Shibboleth NetID backend & Payment webhook | Fake webhook updates delegate `payment_status` |
| **🚀 Public Launch** | **Week of Aug 24** | Public site minus registration live | Public pages load on prod, reg button is disabled |
| **Phase 4** Reg Flow | September 10 | Reg wizard & Admin UI dashboard | End-to-end user checkout & workshop selection |
| **Phase 5** Hardening | September 13 | Rate-limiting & load capacity verified | Under 100 concurrent users response is < 1s |
| **🚀 Full Launch** | **Mid-September** | Registration open to all delegates | Live Shibboleth logins & ticket verification |
