/**
 * FACT workshops sheet -> website sync.
 * Paste into Extensions > Apps Script of the workshops Google Sheet.
 * Setup steps: docs/workshop_sheet/README.md in fact-backend-2026.
 *
 * Script properties (Project Settings > Script properties):
 *   API_URL     backend base URL, no trailing slash
 *   SHEETS_KEY  same value as WORKSHOP_SHEET_API_KEY on DigitalOcean
 */

var SHEET_NAME = 'Workshops';
var COLUMNS = [
  'id', 'publish', 'title', 'session', 'description', 'facilitator',
  'facilitator_names', 'image_url', 'bio', 'position', 'preferred_cap',
  'moveable_seats', 'status'
];

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('FACT website')
    .addItem('Push ticked rows to website', 'pushToWebsite')
    .addItem('Pull workshops from website (fills an empty sheet)', 'pullFromWebsite')
    .addItem('Turn on auto-push every 15 minutes', 'installAutoPush')
    .addToUi();
}

function config_() {
  var props = PropertiesService.getScriptProperties();
  var url = props.getProperty('API_URL');
  var key = props.getProperty('SHEETS_KEY');
  if (!url || !key) throw new Error('Set API_URL and SHEETS_KEY in Script properties first.');
  return { url: url.replace(/\/$/, '') + '/fact-admin/sheets/workshops/', key: key };
}

function sheet_() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sh = ss.getSheetByName(SHEET_NAME) || ss.insertSheet(SHEET_NAME);
  if (sh.getLastRow() === 0) {
    sh.appendRow(COLUMNS);
    sh.setFrozenRows(1);
    sh.getRange(2, COLUMNS.indexOf('publish') + 1, sh.getMaxRows() - 1).insertCheckboxes();
    sh.getRange(2, COLUMNS.indexOf('moveable_seats') + 1, sh.getMaxRows() - 1).insertCheckboxes();
  }
  return sh;
}

function headerIndex_(sh) {
  var header = sh.getRange(1, 1, 1, sh.getLastColumn()).getValues()[0];
  var idx = {};
  header.forEach(function (name, i) { idx[String(name).trim()] = i; });
  COLUMNS.forEach(function (c) {
    if (idx[c] === undefined) throw new Error('Missing column "' + c + '" in row 1.');
  });
  return idx;
}

function call_(method, payload) {
  var cfg = config_();
  var options = {
    method: method,
    headers: { 'X-Sheets-Key': cfg.key },
    muteHttpExceptions: true
  };
  if (payload) {
    options.contentType = 'application/json';
    options.payload = JSON.stringify(payload);
  }
  var res = UrlFetchApp.fetch(cfg.url, options);
  var code = res.getResponseCode();
  if (code !== 200) throw new Error('Website returned ' + code + ': ' + res.getContentText());
  return JSON.parse(res.getContentText());
}

function pushToWebsite() {
  var sh = sheet_();
  var idx = headerIndex_(sh);
  var last = sh.getLastRow();
  if (last < 2) return;
  var values = sh.getRange(2, 1, last - 1, sh.getLastColumn()).getValues();

  var rows = [];
  values.forEach(function (v, i) {
    if (v[idx.publish] !== true) return;
    var row = { row: i + 2 };
    COLUMNS.forEach(function (c) { if (c !== 'status' && c !== 'publish') row[c] = v[idx[c]]; });
    rows.push(row);
  });
  if (!rows.length) return;

  var results = call_('post', { rows: rows }).results;
  var stamp = Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'MMM d h:mm a');
  results.forEach(function (r) {
    if (!r.row) return;
    if (r.id) sh.getRange(r.row, idx.id + 1).setValue(r.id);
    sh.getRange(r.row, idx.status + 1).setValue(r.status + ' (' + stamp + ')');
  });
}

function pullFromWebsite() {
  var sh = sheet_();
  if (sh.getLastRow() > 1) {
    SpreadsheetApp.getUi().alert('The sheet already has rows. Pull only fills an empty sheet, so nothing was changed.');
    return;
  }
  var idx = headerIndex_(sh);
  var data = call_('get').rows;
  if (!data.length) return;
  var width = sh.getLastColumn();
  var out = data.map(function (r) {
    var line = new Array(width).fill('');
    COLUMNS.forEach(function (c) { line[idx[c]] = r[c]; });
    return line;
  });
  sh.getRange(2, 1, out.length, width).setValues(out);
}

function installAutoPush() {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'pushToWebsite') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('pushToWebsite').timeBased().everyMinutes(15).create();
  SpreadsheetApp.getUi().alert('Ticked rows will now push to the website every 15 minutes.');
}
