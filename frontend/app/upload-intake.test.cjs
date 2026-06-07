const assert = require("node:assert/strict");
const test = require("node:test");

const {
  INTAKE_TABS,
  buildUploadIntakeMetadata,
  documentTypeForIntakeCategory,
  labelForIntakeCategory,
} = require("./upload-intake");

test("invoice intake tabs keep parser type as invoice while preserving sales and purchase intent", () => {
  assert.deepEqual(
    INTAKE_TABS.map((tab) => tab.id),
    ["sales_invoice", "purchase_invoice", "bank_statement", "special_document"],
  );
  assert.equal(documentTypeForIntakeCategory("sales_invoice"), "invoice");
  assert.equal(documentTypeForIntakeCategory("purchase_invoice"), "invoice");
  assert.equal(labelForIntakeCategory("sales_invoice"), "Satış faturaları");
  assert.equal(labelForIntakeCategory("purchase_invoice"), "Alış faturaları");
});

test("special documents use manual review metadata instead of invoice parsing", () => {
  const metadata = buildUploadIntakeMetadata("special_document");

  assert.equal(metadata.documentType, "special_document");
  assert.equal(metadata.intakeCategory, "special_document");
  assert.equal(metadata.status, "review_required");
  assert.match(metadata.previewText, /müşavir kontrolüne/i);
  assert.match(metadata.exportGateReason, /kontrol/i);
});

test("bank statement intake accepts xls and text pdf formats", () => {
  const metadata = buildUploadIntakeMetadata("bank_statement");

  assert.equal(metadata.documentType, "bank_statement");
  assert.match(metadata.accept, /\.xls\b/);
  assert.match(metadata.accept, /\.xlsx\b/);
  assert.match(metadata.accept, /\.pdf\b/);
  assert.doesNotMatch(metadata.accept, /\.zip\b/);
});

test("unknown intake categories fall back to purchase invoices", () => {
  const metadata = buildUploadIntakeMetadata("unknown");

  assert.equal(metadata.documentType, "invoice");
  assert.equal(metadata.intakeCategory, "purchase_invoice");
  assert.equal(metadata.label, "Alış faturaları");
});
