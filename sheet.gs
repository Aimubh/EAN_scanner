/**
 * The catalogue's door. Paste this into a script at script.google.com, point it at the sheet, deploy
 * it as a Web app, and give the URL to Vercel as SHEET_URL.
 *
 * It is deliberately stupid: it reads rows, writes a row and deletes a row, and knows nothing about
 * EANs, colours or duplicates. Every rule lives in build.py, so the panel, the local server and this
 * all agree by construction rather than by two copies staying in step.
 *
 * Setup, once. This is a STANDALONE script, made at script.google.com rather than through the
 * Sheet's Extensions menu, because that menu resolves to the wrong Google account when Chrome is
 * signed into several. It reaches the sheet by id instead, which works the same way.
 *   1. script.google.com > New project. Delete whatever is there, paste this, save.
 *   2. Project Settings (gear) > Script properties > Add two:
 *        SECRET   = a long random string
 *        SHEET_ID = the id in the sheet's URL, the part between /d/ and /edit
 *   3. Deploy > New deployment > type Web app.
 *        Execute as: Me.        Who has access: Anyone.
 *      "Anyone" is how Vercel reaches it without a Google login; the SECRET is what keeps
 *      strangers out, so make it long and never put it in the repo.
 *   4. Copy the /exec URL. That is SHEET_URL.
 * After editing this file you must Deploy > Manage deployments > edit > New version, or the old
 * code keeps running.
 */

function doGet(e) {
  return handle(e.parameter || {}, null);
}

function doPost(e) {
  var body = {};
  try {
    body = JSON.parse(e.postData.contents);
  } catch (err) {
    return json({ error: 'body was not JSON' });
  }
  return handle(body, body);
}

function handle(params, body) {
  var props = PropertiesService.getScriptProperties();
  var secret = props.getProperty('SECRET');
  var id = props.getProperty('SHEET_ID');
  if (!secret || String(params.secret) !== String(secret)) {
    return json({ error: 'wrong or missing secret' });
  }
  var book = id ? SpreadsheetApp.openById(id) : SpreadsheetApp.getActiveSpreadsheet();
  if (!book) return json({ error: 'set the SHEET_ID script property to the id from the sheet URL' });
  var sheet = book.getSheets()[0];
  try {
    if (!body) return json({ rows: sheet.getDataRange().getDisplayValues() });

    // row 1 is the header, so a zero-based data index maps to sheet row index + 2
    if (body.op === 'write') {
      var values = body.values || [];
      var row = body.index == null ? sheet.getLastRow() + 1 : Number(body.index) + 2;
      sheet.getRange(row, 1, 1, values.length).setValues([values]);
      return json({ ok: true, row: row, rows: sheet.getDataRange().getDisplayValues() });
    }
    if (body.op === 'delete') {
      sheet.deleteRow(Number(body.index) + 2);
      return json({ ok: true, rows: sheet.getDataRange().getDisplayValues() });
    }
    return json({ error: 'unknown op ' + body.op });
  } catch (err) {
    return json({ error: String(err) });
  }
}

function json(payload) {
  return ContentService.createTextOutput(JSON.stringify(payload))
    .setMimeType(ContentService.MimeType.JSON);
}
