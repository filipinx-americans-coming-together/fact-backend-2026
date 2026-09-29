# Known issues

Open issues that are understood but deliberately not fixed yet. Last updated 2026-09-28.

## 1. UIUC promo-code ownership check is disabled

**Where:** `registration/payment/views.py`, `verify_payment` (the commented-out block under "Per-delegate discount-code ownership check temporarily disabled").

**What it was meant to do:** reject an order whose Eventbrite discount code wasn't issued to *this* delegate. Each UIUC student was supposed to get a single-use code (`UIUCPromoCode`) after verifying through Shibboleth.

**Why it's off:** Shibboleth/iTrust isn't approved yet, so UIUC students all use one fixed, shared Eventbrite code with no per-delegate `UIUCPromoCode` row. The check rejected every legitimate use of that code, so it was commented out, not deleted.

**Effect right now:** anyone who has the shared code can get the UIUC ticket and register, UIUC student or not. This is covered manually by the NetID order-check Google Sheet (NetIDs checked against the UIUC directory).

**Side effect:** two tests fail in CI because they assert the disabled behavior:
- `registration.payment.tests.VerifyPaymentPOSTTest.test_order_with_someone_elses_promo_code_rejected`
- `registration.payment.tests.VerifyPaymentPOSTTest.test_uiuc_order_with_matching_promo_redeems_it`

**When to fix:** once iTrust approves the SP registration, `SAML_MOCK_MODE=False` is set, and students get per-delegate codes from `POST /registration/uiuc-promo-code/`. Uncomment the block; the two tests should then pass again.

## 2. Password reset crashes if two accounts share an email

**Where:** `User.objects.get(email=email)` in:
- `registration/delegate/views.py`: lines ~266, ~475 (request password reset) and ~540 (confirm reset)
- `fact_admin/actions/views.py`: admin promote and admin password reset (lines ~446, ~545, ~594, ~659)

**Problem:** Django's `User.email` isn't unique. If two `User` rows share an email, `.get()` raises `MultipleObjectsReturned`, which surfaces as a generic "Server error", and that person can't reset their password at all.

**How likely:** low. Normal sign-up and `claim-order` reject an email that's already in use, so duplicates mostly come from accounts created by hand in the Django admin or from old data.

**Fix when picked up:** handle multiple matches explicitly, e.g. prefer the account with a `Delegate` profile (or the admin account for the admin flows), or return a clear error; add a test that creates two users with the same email first.

## 3. Email verification isn't enforced by the backend

**Where:** `one_time_verification/views.py` (`verify`) and `registration/delegate/views.py` (`create_delegate` / `_create_delegate_account`).

**Problem:** the create-account page asks for a 6-digit code emailed to the address before showing the sign-up form, but that check only exists in the web page. The backend's `verify` endpoint confirms the code, deletes it and replies "Email verified" without recording anything, and `POST /registration/delegates/create-account` never checks that the email was verified. Anyone who sends the create-account request directly (command line, browser dev tools, a script) can create an account with an email they don't own.

**Effect right now:** low. An attacker could create an account under someone else's email and set its password; the real owner then gets "Email already in use" until an admin fixes it. It becomes serious for any feature that trusts the account email as proof of identity, e.g. automatically linking an Eventbrite order found under that email. The existing-order lookup on the register page (2026-09-29) was designed around this: it only shows a masked order number and requires the full order number to link.

**Fix when picked up:** when `verify` succeeds, record that the email was verified for a short window (e.g. a `verified_at` on `PendingVerification` kept for 30 minutes, or a flag in the session); have `create_delegate` (and `claim_order`, if ever used) reject emails without a recent verification; add tests for both paths. After that, auto-linking orders by email becomes safe.
