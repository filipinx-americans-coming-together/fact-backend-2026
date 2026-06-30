# FACT 2026 — Summer Engineering Roadmap
#### Technical Product Manager's Plan of Action

> **Scope:** ~10 weeks, late June → early September 2026
> **Goal:** Ship a secure, modernized, fully integrated FACT platform before registration opens in October.
> **Ground rule:** Each phase must pass its validation steps before the next phase begins.

---

## At-a-Glance Timeline

```
JUNE          JULY                    AUGUST              SEPT
└─────────────┴──────────┬─────────────┴──────────┬────────┘
  Phase 1     Phase 2    │   Phase 3              │ Phase 4
  Weeks 1–2   Weeks 3–6  │   Weeks 6–9            │ Week 10
  Foundation  Core Eng.  │   Frontend Restyling   │ Testing
              & Payment  │   & Design System      │ & Deploy
              Integration│                        │
```

---

## Phase 1 — Foundation & Low-Hanging Fruit
### Weeks 1–2 · ~June 26 – July 9

> **Spirit of this phase:** Get your hands in the code, fix the embarrassing and dangerous stuff first, build confidence in the file structure. No new features — only cleanup and safety patches.

---

### 🎯 Milestone 1.1 — Security Triage (Week 1, Days 1–2)
**"Fix what could hurt us before we touch anything else"**

**Core Objectives:**
1. Remove all debug `console.log` / `print()` statements that leak sensitive data
2. Eliminate all `@csrf_exempt` decorators from mutating endpoints
3. Wrap all multi-step database writes in `transaction.atomic()`

**Target Files:**
| File | What to Change |
|---|---|
| [`src/util/fetchWithCredentials.ts`](file:///c:/Users/megan/fact-website-frontend/src/util/fetchWithCredentials.ts) | Remove `console.log("cooke", document.cookie)` — L22 |
| [`src/hooks/api/useVerifyEmail.ts`](file:///c:/Users/megan/fact-website-frontend/src/hooks/api/useVerifyEmail.ts) | Remove `console.log(email, code)` — L6 |
| [`src/hooks/api/useAdminLogin.ts`](file:///c:/Users/megan/fact-website-frontend/src/hooks/api/useAdminLogin.ts) | Remove `console.log(response)` — L16 |
| [`registration/workshop/views.py`](file:///c:/Users/megan/fact-website-backend/registration/workshop/views.py) | Remove `@csrf_exempt` from `workshops_bulk` — L76 |
| [`registration/school/views.py`](file:///c:/Users/megan/fact-website-backend/registration/school/views.py) | Remove `@csrf_exempt` from `schools_bulk` — L72 |
| [`registration/location/views.py`](file:///c:/Users/megan/fact-website-backend/registration/location/views.py) | Remove `@csrf_exempt` from `locations_bulk` — L138 |
| [`fact_admin/actions/views.py`](file:///c:/Users/megan/fact-website-backend/fact_admin/actions/views.py) | Remove `@csrf_exempt` from `send_facilitator_links` — L254 |
| [`fact_admin/agenda/views.py`](file:///c:/Users/megan/fact-website-backend/fact_admin/agenda/views.py) | Remove `@csrf_exempt` from `agenda_items_bulk` — L110 |
| [`registration/delegate/views.py`](file:///c:/Users/megan/fact-website-backend/registration/delegate/views.py) | Wrap `create_delegate` and `delegates` POST in `transaction.atomic()` |

**Validation Steps:**
- [ ] Open browser DevTools on `/my-fact/register` — confirm no cookies or codes appear in the Console tab
- [ ] Run the existing backend test suite: `python manage.py test`
- [ ] Test bulk upload endpoints from the admin panel — confirm they still work (CSRF tokens are already sent by `fetchWithCredentials`)
- [ ] Manually trigger a registration flow in dev: create account → register workshops → confirm 3 `Registration` rows exist and no partial records are left if you kill the server mid-request

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
- [ ] Manually trigger each error path (wrong password, bad email, etc.) — confirm error responses still return the correct status codes and messages (the bare except → specific except change must not alter the user-visible behavior)

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
| [`src/util/parseApiResponse.ts`](file:///c:/Users/megan/fact-website-frontend/src/util/) | **[NEW]** Create shared response parser utility |
| `src/hooks/api/useCreateAccount.ts`, `useRegister.ts`, `useUpdateUser.ts` (+ 12 others) | Replace copy-pasted error-handling block with `parseApiResponse()` call |

**Validation Steps:**
- [ ] Open browser DevTools → Network tab on `/my-fact/workshops` — confirm **1 request** instead of 31
- [ ] Open Admin → download Delegate sheet — confirm it still exports correctly and is noticeably faster
- [ ] Run all existing frontend tests: `npm run test`
- [ ] Spot-check 3 different hooks to confirm error messages still display correctly after the parser refactor

---

## Phase 2 — Core Engineering & Integration
### Weeks 3–6 · ~July 10 – August 6

> **Spirit of this phase:** Build the two most architecturally significant features: the payment integration bridge and the Admin Dashboard backend. These are the features with the highest operational risk if they don't exist.

---

### 🎯 Milestone 2.1 — Payment Bridge: Client-Side Fix (Week 3)
**"Close the free-registration bypass. Today."**

**Core Objectives:**
1. Replace the `onOrderComplete` boolean flip with an authenticated backend call that logs payment intent
2. Add `payment_status`, `eventbrite_order_id`, and `ticket_type` fields to the `Delegate` model
3. Create the `POST /registration/payment-intent/` endpoint

**Target Files:**
| File | Change |
|---|---|
| [`registration/models.py`](file:///c:/Users/megan/fact-website-backend/registration/models.py) | Add 3 new fields to `Delegate` model |
| `registration/migrations/` | **[NEW]** Generate migration: `python manage.py makemigrations` |
| [`registration/delegate/views.py`](file:///c:/Users/megan/fact-website-backend/registration/delegate/views.py) | **[NEW]** Add `record_payment_intent()` view |
| [`registration/urls.py`](file:///c:/Users/megan/fact-website-backend/registration/urls.py) | Add `path("delegates/payment-intent/", ...)` |
| [`src/app/my-fact/register/page.tsx`](file:///c:/Users/megan/fact-website-frontend/src/app/my-fact/register/page.tsx) | Replace `onOrderComplete` with async backend call |
| **[NEW]** `src/hooks/api/useRecordPaymentIntent.ts` | New mutation hook |

**Validation Steps:**
- [ ] Run migration: `python manage.py migrate` — confirm no errors
- [ ] Complete an Eventbrite checkout in dev → inspect database: confirm `payment_intent_at` is populated on the `Delegate` row
- [ ] Attempt to bypass payment by calling `register()` directly without completing checkout — confirm backend returns 403 (the payment intent record is absent)
- [ ] Check Admin panel → Delegate list — confirm new payment fields are visible

---

### 🎯 Milestone 2.2 — Payment Bridge: Eventbrite Webhook (Weeks 4–5)
**"Make payment verification server-to-server and bypass-proof"**

**Core Objectives:**
1. Build and register the Eventbrite webhook endpoint with HMAC signature verification
2. Implement Eventbrite API order lookup to retrieve buyer email
3. Auto-update `delegate.payment_status = "paid"` when webhook fires

**Target Files:**
| File | Change |
|---|---|
| `fact_admin/webhook/` | **[NEW DIRECTORY]** Create Django app or subdirectory for webhook handler |
| `fact_admin/webhook/views.py` | **[NEW]** `eventbrite_webhook()` — verify signature, fetch order, update delegate |
| [`fact_registration_backend/urls.py`](file:///c:/Users/megan/fact-website-backend/fact_registration_backend/urls.py) | Add `path("webhooks/eventbrite/", ...)` |
| [`fact_registration_backend/settings.py`](file:///c:/Users/megan/fact-website-backend/fact_registration_backend/settings.py) | Add `EVENTBRITE_API_KEY` and `EVENTBRITE_WEBHOOK_SECRET` env vars |
| `.env` / hosting environment | Add the two new secrets |

**External Setup Required:**
1. Log in to [Eventbrite Developer portal](https://www.eventbrite.com/platform/api)
2. Register webhook URL: `https://your-domain.com/webhooks/eventbrite/`
3. Copy the webhook signing secret into your `.env` file

**Validation Steps:**
- [ ] Use [Eventbrite's webhook test tool](https://www.eventbrite.com/platform/api) or `ngrok` to forward a test webhook to your local server — confirm the view receives and processes it
- [ ] Simulate a fake order payload: confirm signature verification rejects requests with bad signatures (returns 401)
- [ ] Simulate a successful order: confirm `delegate.payment_status` flips to `"paid"` in the database
- [ ] Simulate an order for an email that doesn't exist in your DB: confirm a graceful 200 response (don't crash — the person may have paid without creating an account yet)

---

### 🎯 Milestone 2.3 — Admin Dashboard Backend (Week 6)
**"Build all 7 new admin API endpoints"**

**Core Objectives:**
1. Build Database Cleanup endpoints (list delegates with filters, single delete, bulk delete)
2. Build Privilege Management endpoints (list admins, promote, revoke, search users)
3. Build Day-of Registration endpoint (admin create delegate, bypasses checkout)

**Target Files:**
| File | Change |
|---|---|
| [`fact_admin/actions/views.py`](file:///c:/Users/megan/fact-website-backend/fact_admin/actions/views.py) | Add 7 new view functions (see API spec in `admin_reference.md`) |
| [`fact_admin/urls.py`](file:///c:/Users/megan/fact-website-backend/fact_admin/urls.py) | Add 7 new `path()` entries |
| [`fact_admin/actions/tests.py`](file:///c:/Users/megan/fact-website-backend/fact_admin/actions/tests.py) | Write tests for each new endpoint |

**Endpoint Checklist:**
- [ ] `GET /fact-admin/delegates/` — list with `?search`, `?school_id`, `?no_registrations`
- [ ] `DELETE /fact-admin/delegates/<id>/` — single delete with `confirm: true` body
- [ ] `DELETE /fact-admin/delegates/bulk/` — bulk delete, max 50
- [ ] `GET /fact-admin/accounts/admins/` — list FACTAdmin group members
- [ ] `POST /fact-admin/accounts/admins/<user_id>/` — promote to admin
- [ ] `DELETE /fact-admin/accounts/admins/<user_id>/` — revoke admin (with last-admin guard)
- [ ] `GET /fact-admin/accounts/search/?q=` — user search typeahead
- [ ] `POST /fact-admin/delegates/create/` — day-of registration override

**Validation Steps:**
- [ ] Run `python manage.py test fact_admin` — all new tests pass
- [ ] Test each endpoint with a tool like Postman or HTTPie: confirm 403 for unauthenticated requests, 200/201 for valid admin requests
- [ ] Test "last admin" guard: attempt to revoke the only admin — confirm 400 response
- [ ] Test bulk delete cap: attempt to pass 51 delegate IDs — confirm 400 response
- [ ] Test day-of registration: create a delegate via admin endpoint, confirm `User` + `Delegate` + 3 `Registration` rows all exist and no partial records appear on failure

---

## Phase 3 — Frontend Restyling & Design System
### Weeks 6–9 · ~August 3 – August 27

> **Spirit of this phase:** Build a cohesive, premium visual identity for FACT 2026. Establish a design token system first, then update components, then assemble new pages. Design flows top-down: tokens → components → pages.

> **Note:** Week 6 overlaps with Phase 2 (Admin Backend). Run these in parallel if you have the bandwidth — the backend and frontend work are fully independent.

---

### 🎯 Milestone 3.1 — Design Token System (Week 6)
**"Establish the visual language before touching a single component"**

**Core Objectives:**
1. Define FACT 2026 color palette, typography scale, and spacing system as CSS custom properties
2. Replace ad-hoc Tailwind class strings with semantic token names
3. Set up Google Fonts import (e.g., Inter, Outfit, or your chosen typeface)

**Target Files:**
| File | Change |
|---|---|
| [`src/app/globals.css`](file:///c:/Users/megan/fact-website-frontend/src/app/globals.css) | Define all CSS custom properties (`--color-primary`, `--font-heading`, `--radius-card`, etc.) |
| [`tailwind.config`](file:///c:/Users/megan/fact-website-frontend) | Map Tailwind theme to CSS variables (if keeping Tailwind) |
| [`src/app/layout.tsx`](file:///c:/Users/megan/fact-website-frontend/src/app/layout.tsx) | Add Google Fonts `<link>` or `next/font` import |
| **[NEW]** `src/styles/tokens.css` | Optional: isolate tokens into their own file for clarity |

**Questions to Decide Before Writing Code:**
- What is the FACT 2026 primary color (accent/brand color)?
- What typeface? (Inter is a safe modern default; Outfit has more personality)
- Dark mode, light mode, or both?
- What is the overall visual direction — glassmorphism (current), flat/minimal, bold/editorial?

**Validation Steps:**
- [ ] Create a single "Token Preview" page at `/admin/design-tokens` (dev only) that renders swatches of every color, font, and spacing value — use it as your living style guide
- [ ] Confirm the homepage still renders without visual regression (nothing should change yet — tokens are defined but not applied)

---

### 🎯 Milestone 3.2 — Core Component Library Update (Weeks 7–8)
**"Rebuild the shared UI components to use the new design system"**

**Core Objectives:**
1. Redesign shared UI components (buttons, inputs, cards, modals) to use design tokens
2. Build the `withAdminAuth` HOC / layout wrapper to centralize admin auth guard
3. Modernize the public-facing `Navbar` and `Footer`

**Target Files — Shared Components:**
| File | Change |
|---|---|
| [`src/components/ui/`](file:///c:/Users/megan/fact-website-frontend/src/components/ui) | Redesign: `WorkshopSelect`, `SchoolSelect`, `Select`, `TextInput`, `LinkButton`, `InteractiveButton` |
| [`src/components/formatting/FormContainer.tsx`](file:///c:/Users/megan/fact-website-frontend/src/components/formatting/FormContainer.tsx) | Apply new input/button tokens; improve error state styling |
| [`src/components/navigation/Navbar.tsx`](file:///c:/Users/megan/fact-website-frontend/src/components/navigation/Navbar.tsx) | Apply new typography and color tokens |
| [`src/components/formatting/PageFooter.tsx`](file:///c:/Users/megan/fact-website-frontend/src/components/formatting) | Apply new tokens |

**Target Files — Admin Components:**
| File | Change |
|---|---|
| [`src/app/admin/components/Navbar.tsx`](file:///c:/Users/megan/fact-website-frontend/src/app/admin/components/Navbar.tsx) | Add "Registrations" and "Accounts" links; apply new tokens |
| [`src/app/admin/components/Button.tsx`](file:///c:/Users/megan/fact-website-frontend/src/app/admin/components/Button.tsx) | Restyle with design tokens |
| [`src/app/admin/components/FormContainer.tsx`](file:///c:/Users/megan/fact-website-frontend/src/app/admin/components/FormContainer.tsx) | Apply tokens |
| **[NEW]** `src/app/admin/AdminLayout.tsx` | `withAdminAuth` wrapper — centralizes `useAdminUser()` guard |

**Validation Steps:**
- [ ] Visually inspect every page that uses shared components — no layout breakages
- [ ] Test all interactive states: hover, focus, disabled, loading, error
- [ ] Run `npm run test` — all existing component tests pass
- [ ] Test on mobile viewport (375px) — confirm responsive behavior is intact

---

### 🎯 Milestone 3.3 — Page-Level Restyling + New Admin Pages (Week 9)
**"Apply the new design system to every page, and ship the three new Admin Dashboard pages"**

**Core Objectives:**
1. Restyle all public-facing pages using updated components
2. Build the three new Admin pages (Registrations, Accounts, Day-of Registration form)
3. Update the main Admin Dashboard to show `payment_status` data

**Target Files — Public Pages:**
| Page | Priority |
|---|---|
| `src/app/page.tsx` (Homepage) | High — first impression |
| `src/app/my-fact/create-account/page.tsx` | High — conversion-critical |
| `src/app/my-fact/register/page.tsx` | High — conversion-critical |
| `src/app/my-fact/dashboard/page.tsx` | High — post-registration experience |
| `src/app/workshops/page.tsx` and `[slug]/page.tsx` | Medium |
| `src/app/about/`, `faq/`, `team/` etc. | Low — informational pages |

**Target Files — New Admin Pages:**
| File | What to Build |
|---|---|
| **[NEW]** `src/app/admin/registrations/page.tsx` | Delegate table with search/filter/bulk delete |
| **[NEW]** `src/app/admin/registrations/create/page.tsx` | Day-of Registration form |
| **[NEW]** `src/app/admin/accounts/page.tsx` | Admin privilege management |
| **[NEW]** `src/hooks/api/useDelegates.ts` | Hook for delegate list API |
| **[NEW]** `src/hooks/api/useDeleteDelegate.ts` | Mutation hook for delete |
| **[NEW]** `src/hooks/api/useAdminAccounts.ts` | Hook for admin privilege API |
| **[NEW]** `src/hooks/api/useAdminCreateDelegate.ts` | Mutation hook for day-of form |
| [`src/app/admin/dashboard/page.tsx`](file:///c:/Users/megan/fact-website-frontend/src/app/admin/dashboard/page.tsx) | Add payment status summary widget |

**Validation Steps:**
- [ ] Complete end-to-end registration flow (create account → checkout → register workshops) — confirm no visual or functional regressions
- [ ] Log in to Admin panel → test all three new pages: create a test delegate via Day-of form, search and delete it via the Registrations table
- [ ] Promote a test user to FACTAdmin via the Accounts page, confirm they can log in as admin
- [ ] Check all pages at 3 viewport sizes: mobile (375px), tablet (768px), desktop (1280px)
- [ ] Lighthouse audit on Homepage and Create Account page — target Performance ≥ 85, Accessibility ≥ 90

---

## Phase 4 — Testing & Deployment
### Week 10 · ~August 28 – September 5

> **Spirit of this phase:** Simulate real conference conditions before handing off to the broader team. No new features — only hardening, testing, and documentation.

---

### 🎯 Milestone 4.1 — Load & Integration Testing (Days 1–3)

**Core Objectives:**
1. Simulate high-traffic registration load to find performance bottlenecks
2. Run full end-to-end integration tests across the entire user journey
3. Verify all admin features work with a real FACTAdmin test account

**Target Files:**
| File | Action |
|---|---|
| [`fact_admin/actions/tests.py`](file:///c:/Users/megan/fact-website-backend/fact_admin/actions/tests.py) | Verify all new endpoint tests pass |
| [`registration/delegate/tests.py`](file:///c:/Users/megan/fact-website-backend) | Add integration tests for registration + payment intent flow |
| `tests/` (frontend) | Add or update tests for new hooks and pages |

**Load Test Protocol:**
```
Tool: Use locust (pip install locust) or k6
Scenario: Simulate 100 concurrent users all hitting:
  1. GET /registration/workshops/        (workshop listing)
  2. POST /registration/delegates/       (workshop registration submit)
  3. GET /registration/delegates/me/     (dashboard load)

Threshold:
  - p95 response time < 500ms for GET /workshops/
  - p95 response time < 1000ms for POST /delegates/
  - 0 errors under 50 concurrent users
```

**Integration Test Checklist (Manual):**
- [ ] New user: create account → verify email → Eventbrite checkout → workshop registration → dashboard
- [ ] Returning user: log in → update workshops (if flag enabled) → log out
- [ ] Admin: log in → view delegates → delete a test record → bulk delete 3 records → create day-of delegate → promote user → revoke user → log out
- [ ] Webhook: trigger a test Eventbrite webhook → confirm delegate `payment_status` updates in DB

---

### 🎯 Milestone 4.2 — Rate Limiting & Final Security Hardening (Days 3–4)

**Core Objectives:**
1. Add rate limiting to all authentication endpoints
2. Verify CORS configuration for production domain
3. Final security sweep: confirm no secrets in code, no debug flags left on

**Target Files:**
| File | Change |
|---|---|
| [`registration/delegate/views.py`](file:///c:/Users/megan/fact-website-backend/registration/delegate/views.py) | Add `@ratelimit(key='ip', rate='10/m', block=True)` to `login_delegate` and `request_password_reset` |
| [`fact_admin/login/views.py`](file:///c:/Users/megan/fact-website-backend/fact_admin/login/views.py) | Add rate limit to `login_admin` |
| [`one_time_verification/views.py`](file:///c:/Users/megan/fact-website-backend/one_time_verification/views.py) | Add rate limit to `request_verification` |
| [`fact_registration_backend/settings.py`](file:///c:/Users/megan/fact-website-backend/fact_registration_backend/settings.py) | Confirm `DEBUG = False` in production; verify `ALLOWED_HOSTS` is locked down |
| `requirements.txt` | Add `django-ratelimit` |

**Security Checklist:**
- [ ] `grep -r "SECRET_KEY"` — confirm no hardcoded secret keys anywhere in code
- [ ] `grep -r "console.log"` — confirm count is 0 (or only intentional/non-sensitive)
- [ ] Confirm all `.env` values are set on the production server and NOT committed to git
- [ ] Run `python manage.py check --deploy` — address any warnings
- [ ] Test rate limiting: send 15 rapid login attempts — confirm 429 response after 10

---

### 🎯 Milestone 4.3 — Documentation & Handoff (Days 4–5)

**Core Objectives:**
1. Write a concise developer onboarding README for the next IT chair
2. Document all new environment variables required by the webhook integration
3. Archive all planning artifacts from this summer into the project wiki or repo

**Target Files:**
| File | Action |
|---|---|
| `fact-website-backend/README.md` | Update: setup steps, env var list, how to run tests, how to deploy |
| `fact-website-frontend/README.md` | Update: setup steps, how to run dev server, environment variables |
| **[NEW]** `ARCHITECTURE.md` (repo root) | Brief map of all apps, their responsibilities, and key decisions made this summer |

**Handoff Checklist:**
- [ ] Another team member can clone the repo and run the project locally following only the README
- [ ] All new API endpoints are documented (can reference `admin_reference.md` from this summer)
- [ ] All new environment variables are listed in the README with descriptions (not values)
- [ ] The Eventbrite webhook URL and signing secret rotation procedure is documented

---

## Summary Scorecard

| Phase | Duration | Key Deliverable | Done When... |
|---|---|---|---|
| **1.1** Security Triage | 2 days | No more debug leaks, CSRF restored, atomic writes | `python manage.py test` passes, DevTools shows no cookie logs |
| **1.2** Code Cleanup | 3 days | Specific exceptions, dead code removed | Lint passes, error paths still return correct HTTP codes |
| **1.3** Performance Wins | 5 days | 31 → 1 API call on workshops page | Network tab confirms single request; export is faster |
| **2.1** Payment Bridge v1 | 5 days | `payment_intent_at` written to DB on checkout | DB row updated on every Eventbrite completion |
| **2.2** Payment Webhook | 10 days | Server-to-server payment verification | Webhook fires → `payment_status = "paid"` in DB |
| **2.3** Admin Backend | 5 days | All 7 new admin API endpoints | All endpoint tests pass, Postman confirms correct responses |
| **3.1** Design Tokens | 5 days | CSS token system and Google Font configured | Token preview page renders all swatches correctly |
| **3.2** Component Library | 10 days | All shared components updated, admin auth centralized | All pages render correctly, responsive at 3 breakpoints |
| **3.3** Pages + Admin UI | 5 days | All pages restyled, 3 new admin pages shipped | Full end-to-end UI flow works, Lighthouse ≥ 85 |
| **4.1** Load Testing | 3 days | Handles 50 concurrent users without errors | Load test passes defined thresholds |
| **4.2** Security Hardening | 2 days | Rate limiting live, prod settings locked down | `manage.py check --deploy` is clean |
| **4.3** Handoff Docs | 2 days | README and architecture docs complete | New team member can run app from README alone |

---

> **One rule to live by this summer:** Always run `python manage.py test` and `npm run test` before committing any change. These are your safety nets — keep them green.
