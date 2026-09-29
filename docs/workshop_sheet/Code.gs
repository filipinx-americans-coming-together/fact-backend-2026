/**
 * FACT 2026 Workshops — Google Apps Script
 *
 * A STANDALONE script (script.google.com → New project), owned by you, not
 * bound to the sheet: organizers edit the sheet, but can't open this
 * project, so SHEETS_API_KEY stays private. Setup: docs/workshop_sheet/README.md.
 *
 * Every 10 minutes:
 *   1. rows with "done" ticked are sent to the FACT backend's
 *      POST /fact-admin/sheets/workshops/, which adds or updates the workshop,
 *      its room, and its facilitator; the row gets its website id and a
 *      status, and "done" is unticked once it's saved;
 *   2. workshops on the website that the sheet doesn't have yet are appended
 *      (the first run fills the sheet with every current workshop).
 * Nothing is ever deleted, on either side. Rows being edited (done not
 * ticked) are never overwritten.
 */

const CONFIG = {
  // The deployed backend's base URL, no trailing slash.
  BACKEND_URL: 'https://api.psauiuc.org',
  // From the sheet's URL: docs.google.com/spreadsheets/d/<SHEET_ID>/edit
  SHEET_ID: 'PASTE_SHEET_ID_HERE',
};

const TAB = 'Workshops';
// Same keys and order as COLUMNS in fact_admin/workshop_sheet/views.py.
const COLUMNS = [
  'id', 'done', 'session', 'title', 'description', 'room', 'capacity',
  'facilitator', 'facilitator_names', 'photo', 'bio', 'position', 'status',
];
const HEADERS = [
  'ID (auto)', 'Done', 'Session', 'Title', 'Description', 'Room', 'Capacity',
  'Facilitator (org)', 'Facilitator names', 'Photo link', 'Bio', 'Position', 'Status (auto)',
];
const COL = {};
COLUMNS.forEach((c, i) => { COL[c] = i; });

const STATUS_ROW = 1;
const HEADER_ROW = 2;
const FIRST_DATA_ROW = 3;
const COLORS = { error: '#ffcdd2', missing: '#eeeeee', ok: null };

// ---------------------------------------------------------------------------
// Pure helpers (no Sheets calls)
// ---------------------------------------------------------------------------

function norm_(s) {
  return String(s == null ? '' : s).trim().toLowerCase();
}

// A workshop can have several rows (one per panel facilitator).
function rowKey_(id, facilitator) {
  return String(id) + '|' + norm_(facilitator);
}

// setValues treats text starting with = + - @ as a formula; descriptions
// often start with "-" bullets, so force website text to plain text.
function safeCell_(v) {
  return typeof v === 'string' && /^[=+\-@]/.test(v) ? "'" + v : v;
}

function toSheetRow_(w) {
  return COLUMNS.map(c => (c === 'done' ? false : safeCell_(w[c] == null ? '' : w[c])));
}

// Website rows the sheet doesn't have yet, in website order.
function missingRows_(websiteRows, sheetValues) {
  const have = new Set(sheetValues
    .filter(v => v[COL.id] !== '')
    .map(v => rowKey_(v[COL.id], v[COL.facilitator])));
  return websiteRows.filter(w => !have.has(rowKey_(w.id, w.facilitator))).map(toSheetRow_);
}

function driveId_(link) {
  const m = String(link || '').match(/drive\.google\.com\/(?:file\/d\/|open\?id=|uc\?(?:[^#]*&)?id=)([\w-]+)/);
  return m ? m[1] : null;
}

// ---------------------------------------------------------------------------
// Setup (run once by hand)
// ---------------------------------------------------------------------------

function setup() {
  const ss = SpreadsheetApp.openById(CONFIG.SHEET_ID);
  const sheet = ss.getSheetByName(TAB) || ss.insertSheet(TAB);

  sheet.getRange(HEADER_ROW, 1, 1, HEADERS.length).setValues([HEADERS])
    .setFontWeight('bold').setBackground('#1f3b57').setFontColor('#ffffff');
  sheet.setFrozenRows(HEADER_ROW);
  sheet.getRange(STATUS_ROW, 1).setValue('Not synced yet — run sync()').setFontStyle('italic');

  const rows = sheet.getMaxRows() - FIRST_DATA_ROW + 1;
  sheet.getRange(FIRST_DATA_ROW, COL.done + 1, rows).insertCheckboxes();
  sheet.getRange(FIRST_DATA_ROW, COL.session + 1, rows).setDataValidation(
    SpreadsheetApp.newDataValidation().requireValueInList(['1', '2', '3']).build());
  sheet.getRange(FIRST_DATA_ROW, COL.description + 1, rows).setWrap(true);

  // Organizers can edit everything except the status line, headers, and
  // the two auto columns.
  sheet.getProtections(SpreadsheetApp.ProtectionType.RANGE).forEach(p => p.remove());
  const me = Session.getEffectiveUser().getEmail();
  [
    sheet.getRange(STATUS_ROW, 1, HEADER_ROW, sheet.getMaxColumns()),
    sheet.getRange(FIRST_DATA_ROW, COL.id + 1, rows),
    sheet.getRange(FIRST_DATA_ROW, COL.status + 1, rows),
  ].forEach(range => {
    const p = range.protect().setDescription('Filled in automatically');
    p.removeEditors(p.getEditors().filter(u => u.getEmail() !== me));
    if (p.canDomainEdit()) p.setDomainEdit(false);
  });

  const sheet1 = ss.getSheetByName('Sheet1');
  if (sheet1 && ss.getSheets().length > 1) ss.deleteSheet(sheet1);
}

function installTrigger() {
  ScriptApp.getProjectTriggers()
    .filter(t => t.getHandlerFunction() === 'sync')
    .forEach(t => ScriptApp.deleteTrigger(t));
  ScriptApp.newTrigger('sync').timeBased().everyMinutes(10).create();
}

// ---------------------------------------------------------------------------
// Sync
// ---------------------------------------------------------------------------

function sync() {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(30 * 1000)) return;

  const sheet = SpreadsheetApp.openById(CONFIG.SHEET_ID).getSheetByName(TAB);
  const now = Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'MMM d h:mm a');
  try {
    const last = sheet.getLastRow();
    const values = last >= FIRST_DATA_ROW
      ? sheet.getRange(FIRST_DATA_ROW, 1, last - FIRST_DATA_ROW + 1, COLUMNS.length).getValues()
      : [];

    // 1. Push ticked rows.
    const outgoing = [];
    const photoErrors = {};
    values.forEach((v, i) => {
      if (v[COL.done] !== true) return;
      const rowNum = FIRST_DATA_ROW + i;
      const photoError = checkPhoto_(v[COL.photo]);
      if (photoError) { photoErrors[rowNum] = photoError; return; }
      const row = { row: rowNum };
      COLUMNS.forEach(c => { if (c !== 'done' && c !== 'status') row[c] = v[COL[c]]; });
      outgoing.push(row);
    });

    let pushed = 0;
    let errors = 0;
    Object.keys(photoErrors).forEach(rowNum => {
      writeResult_(sheet, +rowNum, null, 'error: ' + photoErrors[rowNum], now, false);
      errors++;
    });
    if (outgoing.length) {
      backend_('post', { rows: outgoing }).results.forEach(r => {
        const ok = !String(r.status).startsWith('error');
        writeResult_(sheet, r.row, r.id, r.status, now, ok);
        if (ok) pushed++; else errors++;
      });
    }

    // 2. Pull: append website workshops the sheet doesn't have yet, and
    // grey out rows whose workshop was deleted on the website.
    const website = backend_('get').rows;
    if (!Array.isArray(website)) throw new Error('Backend reply has no rows array');

    const current = sheet.getLastRow() >= FIRST_DATA_ROW
      ? sheet.getRange(FIRST_DATA_ROW, 1, sheet.getLastRow() - FIRST_DATA_ROW + 1, COLUMNS.length).getValues()
      : [];
    const onWebsite = new Set(website.map(w => String(w.id)));
    current.forEach((v, i) => {
      if (v[COL.id] === '' || onWebsite.has(String(v[COL.id]))) return;
      const rowNum = FIRST_DATA_ROW + i;
      sheet.getRange(rowNum, COL.status + 1).setValue('not on website (deleted in Django admin)');
      sheet.getRange(rowNum, 1, 1, COLUMNS.length).setBackground(COLORS.missing);
    });

    const added = missingRows_(website, current);
    if (added.length) {
      const start = Math.max(sheet.getLastRow() + 1, FIRST_DATA_ROW);
      const needed = start + added.length - 1;
      if (sheet.getMaxRows() < needed) sheet.insertRowsAfter(sheet.getMaxRows(), needed - sheet.getMaxRows());
      sheet.getRange(start, 1, added.length, COLUMNS.length).setValues(added);
      sheet.getRange(start, COL.done + 1, added.length).insertCheckboxes();
    }

    sheet.getRange(STATUS_ROW, 1)
      .setValue(`${website.length} workshop rows on website · ${pushed} saved · ${errors} errors · ${added.length} pulled in · synced ${now}`)
      .setFontColor('#000000').setFontStyle('normal');
  } catch (e) {
    sheet.getRange(STATUS_ROW, 1)
      .setValue(`⚠ Last sync failed at ${now}: ${e.message}`).setFontColor('#b00020');
    throw e; // so Apps Script's failure email goes out
  } finally {
    lock.releaseLock();
  }
}

function writeResult_(sheet, rowNum, id, status, now, ok) {
  if (!rowNum) return;
  if (id) sheet.getRange(rowNum, COL.id + 1).setValue(id);
  sheet.getRange(rowNum, COL.status + 1).setValue(`${status} (${now})`);
  sheet.getRange(rowNum, 1, 1, COLUMNS.length).setBackground(ok ? COLORS.ok : COLORS.error);
  // Saved rows untick; errors stay ticked so they retry after a fix.
  if (ok) sheet.getRange(rowNum, COL.done + 1).setValue(false);
}

// The website loads photos anonymously, so check the same way: a Drive
// link must be shared "Anyone with the link" and actually be an image.
function checkPhoto_(link) {
  const id = driveId_(link);
  if (!id) return null;
  const res = UrlFetchApp.fetch(`https://drive.google.com/uc?export=view&id=${id}`, {
    muteHttpExceptions: true, followRedirects: true,
  });
  const type = String(res.getHeaders()['Content-Type'] || '');
  if (res.getResponseCode() !== 200 || !type.startsWith('image/')) {
    return 'photo link isn\'t a public image — in Drive, Share → "Anyone with the link"';
  }
  return null;
}

// ---------------------------------------------------------------------------
// Backend
// ---------------------------------------------------------------------------

function secret_(name) {
  const v = PropertiesService.getScriptProperties().getProperty(name);
  if (!v) throw new Error(`Set the ${name} script property first.`);
  return v;
}

function backend_(method, payload) {
  const options = {
    method: method,
    headers: { 'X-Sheets-Key': secret_('SHEETS_API_KEY') },
    muteHttpExceptions: true,
  };
  if (payload) {
    options.contentType = 'application/json';
    options.payload = JSON.stringify(payload);
  }
  const res = UrlFetchApp.fetch(`${CONFIG.BACKEND_URL}/fact-admin/sheets/workshops/`, options);
  if (res.getResponseCode() !== 200) {
    throw new Error(`Backend ${res.getResponseCode()}: ${res.getContentText().slice(0, 200)}`);
  }
  return JSON.parse(res.getContentText());
}
