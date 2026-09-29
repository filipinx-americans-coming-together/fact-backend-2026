# Workshops Google Sheet → website

Organizers add and edit workshops in a Google Sheet. Every 10 minutes a
standalone Apps Script (`Code.gs`, next to this file) does two things:

- **Push:** it sends rows with **Done** ticked to `POST /fact-admin/sheets/workshops/`.
- **Pull:** it appends any workshop that's on the website but not yet in the sheet.

The website reads workshops from the backend on every page load, so a saved row
shows up without a redeploy.

It only **adds and edits**. Nothing is deleted on either side: deleting a
workshop also deletes every delegate's registration for it, so that stays a
deliberate step in Django admin.

## One-time setup

1. **Backend:** `SHEETS_API_KEY` is already set on DigitalOcean for the nametag sheet.
   This uses the same key, so there's nothing new to configure.
2. **Sheet:** create a Google Sheet and share it with organizers as editors.
   Copy its ID from the URL (`docs.google.com/spreadsheets/d/<ID>/edit`).
3. **Script:** in the sheet, open Extensions → Apps Script (or create a
   standalone project at script.google.com). Paste in `Code.gs` and set
   `CONFIG.SHEET_ID`.
   - If the script is attached to the sheet, every editor can read
     `SHEETS_API_KEY`.
   - That key also unlocks the nametag export (delegate names, emails,
     pronouns, schools), so keep editors to trusted organizers.
   - Change the key after the conference.
4. **Key:** go to Project Settings → Script properties and add `SHEETS_API_KEY`
   (same value as on DigitalOcean).
5. **Run once:** choose and run `setup` (Google asks for permission), then `sync`,
   then `installTrigger`.
   - `setup` builds the headers and checkboxes, and protects the ID and Status columns.
   - `sync` fills the sheet with every current workshop.
   - `installTrigger` makes `sync` run every 10 minutes.

## For organizers

- **To edit a workshop:** change its cells, then tick **Done**. Within 10 minutes
  the Status shows `updated`, and Done unticks itself.
- **To add a workshop:** fill in a new row at the bottom and tick **Done**.
  - Required: Session, Title, Description, Facilitator.
  - The ID fills in by itself.
- **Panels (several facilitators, one workshop):** use one row per facilitator,
  with the same title and session.
- **Leave Done unticked** while you're still typing. Unticked rows are never sent
  and never overwritten.
- **Red row:** the Status says what's wrong. Fix it and leave Done ticked; it
  retries on the next sync.
- **Grey row:** the workshop was deleted in Django admin.
- **To refresh a row from the website** (e.g. after an edit in Django admin):
  delete the row, and the next sync adds it back.

| Column | Notes |
|---|---|
| ID (auto) | Protected. It's how a renamed workshop stays the same workshop. |
| Room | Must match an existing room for that session, as "Building Room" (e.g. `Lincoln Hall 1000`). Add new rooms under Locations in Django admin. Delegates can't register for a workshop until it has a room. |
| Capacity | The room's capacity, which is what registration enforces. Needs a room. |
| Facilitator (org) | A new name creates a facilitator account. Its setup link is emailed to fact.it@psauiuc.org. |
| Photo link | A Google Drive link shared as "Anyone with the link", or any `https://` image URL. Drive links are checked before sending. |
| Blank cells | Never erase what's already on the website (room, capacity, photo, bio, names). |

## Backend guarantees

- Each row is saved on its own, so a bad row doesn't block the rest.
- A workshop's session can't change once delegates are registered for it.
- A room can't be given to two workshops.
- Registration returns "isn't open for registration yet" for a workshop with no
  room, instead of crashing.
- Drive share links are stored as `https://drive.google.com/uc?export=view&id=…`,
  which the frontend's `next.config.mjs` already allows.

## Frontend note

The live workshops page takes facilitator names, photos, and bios from the
hardcoded `src/util/facilitatorPhotos.ts`, looked up by exact title, not from
the backend. Until the frontend falls back to the backend's facilitator data
(`/registration/workshops/all/`):

- facilitator details for sheet-added workshops won't show there;
- renaming a workshop drops its hardcoded card.
