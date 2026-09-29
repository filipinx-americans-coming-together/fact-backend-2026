# Workshops Google Sheet → website

Organizers add and edit workshops in a Google Sheet. The sheet's Apps Script
(`Code.gs`, next to this file) pushes ticked rows to
`/fact-admin/sheets/workshops/`, which creates or updates workshops and their
facilitators. The script writes each row's website `id` and a `status` back into the sheet.

## One-time setup

1. **Backend (DigitalOcean env vars):** set `WORKSHOP_SHEET_API_KEY` to a new random
   secret (`python -c "import secrets; print(secrets.token_urlsafe(32))"`). Don't
   reuse `SHEETS_API_KEY`: sheet editors can read the script's key, and the
   nametag key reads delegate data.
2. **Sheet:** create a Google Sheet, then Extensions → Apps Script. Replace `Code.gs`
   with this folder's `Code.gs` and save.
3. **Script properties** (Apps Script → Project Settings → Script properties):
   - `API_URL`: the backend's base URL (the DigitalOcean app URL, not the Vercel
     frontend)
   - `SHEETS_KEY`: the same value as `WORKSHOP_SHEET_API_KEY`
4. Reload the sheet. A **FACT website** menu appears. Run
   **Pull workshops from website** once. It creates a `Workshops` tab filled with
   everything already live, including each row's `id`. Google asks for
   permission the first time.
5. Optional: **Turn on auto-push every 15 minutes**. Otherwise use
   **Push ticked rows to website** whenever you're ready.

## Columns

| Column | Notes |
|---|---|
| `id` | Filled in by the script. Don't type or change it. It's how renames work. |
| `publish` | Checkbox. Only ticked rows are sent, so half-typed rows stay private. |
| `title`, `description` | Required. |
| `session` | 1, 2, or 3. Can't be changed once delegates are registered (move them by hand). |
| `facilitator` | Organization/department name (e.g. `Counseling Center`). Required for new workshops. A new name creates a facilitator account, and its setup link is emailed to fact.it@psauiuc.org, same as the Excel bulk upload. |
| `facilitator_names` | Comma-separated people's names. |
| `image_url`, `bio`, `position` | Facilitator details. Blank cells never erase what's already on the website. |
| `preferred_cap` | Optional number. |
| `moveable_seats` | Checkbox. |
| `status` | Written by the script: `added`, `updated`, or `error: …` with a timestamp. |

**Panels (several facilitators, one workshop):** use one row per facilitator with the
same title and session. They all attach to the same workshop.

## What it deliberately doesn't do

- **Never deletes.** Removing a row from the sheet leaves the workshop on the website,
  because deleting a workshop also deletes every delegate's registration for it.
  Delete in Django admin (`/admin/registration/workshop/`).
- **Never assigns rooms.** New workshops have no location. Set it in Django admin.
  Re-running `matchworkshoplocations` would reshuffle everyone's rooms.
- **Never removes a facilitator from a workshop.** Do that in Django admin too.
