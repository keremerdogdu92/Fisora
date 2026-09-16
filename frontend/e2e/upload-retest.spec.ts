// File: frontend/e2e/upload-retest.spec.ts
// Summary: Verifies the canonical accountant upload screen auto-dispatches selected invoice files with correct client, period, direction, file type, and duplicate-safe summary.
import { expect, test, type Page } from "@playwright/test";

const pilotClient = {
  client_id: "pilot-client",
  profile: { client_id: "pilot-client", title: "Pilot Test AŞ", tax_id: "1111111111" },
};

type CapturedUpload = {
  fileName: string;
  documentType: string;
  intakeCategory: string;
  period: string;
  clientId: string;
  body: string;
};

function multipartValue(body: string, field: string) {
  const marker = `name="${field}"`;
  const start = body.indexOf(marker);
  if (start < 0) return "";
  const valueStart = body.indexOf("\r\n\r\n", start);
  if (valueStart < 0) return "";
  return body.slice(valueStart + 4, body.indexOf("\r\n", valueStart + 4));
}

function multipartFileName(body: string) {
  return body.match(/filename="([^"]+)"/)?.[1] ?? "";
}async function setupUploadRoutes(page: Page) {
  const capturedUploads: CapturedUpload[] = [];
  const workspace = {
    client: pilotClient,
    portal_users: [],
    chart_accounts: { account_count: 0, accounts: [] },
    uploaded_documents: [
      {
        document_ref: "already-there.xml",
        original_file_name: "already-there.xml",
        document_type: "invoice",
        intake_category: "purchase_invoice",
        period: "2026-08",
        uploaded_by: "mali-musavir",
        status: "queued",
        created_at: "2026-09-01T10:00:00Z",
      },
    ],
    processing_jobs: [],
    documents: [],
    export_packages: [],
  };

  await page.addInitScript(() => {
    window.localStorage.setItem("fisora.office.session.v1", JSON.stringify({
      userId: "mali-musavir", role: "accountant", sessionToken: "accountant-session", storageScope: "local",
    }));
  });  await page.route("**/phase0/store/auth/session", async (route) => {
    await route.fulfill({ json: { valid: true, user_id: "mali-musavir", expires_at: "2026-12-31T22:00:00+00:00" } });
  });
  await page.route("**/phase0/store/system/readiness", async (route) => {
    await route.fulfill({ json: { real_data_pilot: { allowed: true, blocking: [] } } });
  });
  await page.route("**/phase0/store/ai-capacity", async (route) => {
    await route.fulfill({ json: { agents: [] } });
  });
  await page.route("**/phase0/store/clients", async (route) => {
    await route.fulfill({ json: { clients: [pilotClient] } });
  });
  await page.route("**/phase0/store/workspace/**", async (route) => {
    await route.fulfill({ json: workspace });
  });
  await page.route("**/phase0/store/client", async (route) => {
    await route.fulfill({ json: { client: pilotClient } });
  });
  await page.route("**/phase0/store/document-upload-multipart", async (route) => {
    const body = route.request().postDataBuffer()?.toString("utf8") ?? "";
    const fileName = multipartFileName(body);
    const documentType = multipartValue(body, "document_type");
    const intakeCategory = multipartValue(body, "intake_category");
    const period = multipartValue(body, "period");
    const clientId = multipartValue(body, "client_id");
    capturedUploads.push({ fileName, documentType, intakeCategory, period, clientId, body });
    const deduplicated = fileName === "already-there.xml";
    if (!deduplicated) {
      workspace.uploaded_documents.push({
        document_ref: fileName,
        original_file_name: fileName,
        document_type: documentType,
        intake_category: intakeCategory,
        period,
        uploaded_by: "mali-musavir",
        status: "queued",
        created_at: "2026-09-16T07:00:00Z",
      });
    }
    await route.fulfill({ json: { document_ref: fileName, deduplicated } });
  });

  return { capturedUploads, workspace };
}

test("new upload sends every selected invoice file and reports duplicate-safe batch results", async ({ page }) => {
  const { capturedUploads } = await setupUploadRoutes(page);
  await page.goto("/portal-next");
  await page.getByRole("button", { name: "Yeni Yükleme", exact: true }).click();

  await expect(page.getByRole("heading", { name: "Yeni yüklemeler" })).toBeVisible();
  await expect(page.getByText("08.2026", { exact: true })).toBeVisible();
  await expect(page.getByRole("tab", { name: "Alış" })).toHaveAttribute("aria-selected", "true");

  const input = page.locator('.portal-next-upload-dropzone input[type="file"]');
  await input.setInputFiles([    { name: "invoice-a.pdf", mimeType: "application/pdf", buffer: Buffer.from("pdf-a") },
    { name: "invoice-b.html", mimeType: "text/html", buffer: Buffer.from("<html></html>") },
    { name: "already-there.xml", mimeType: "application/xml", buffer: Buffer.from("<xml />") },
    { name: "ignore-me.txt", mimeType: "text/plain", buffer: Buffer.from("skip") },
  ]);

  await expect(page.getByText("1 desteklenmeyen dosya atlandı.")).toBeVisible();
  await expect.poll(() => capturedUploads.length).toBe(3);
  await expect(page.getByRole("status")).toContainText("3 dosya · 2 işleme alındı · 1 daha önce yüklenmiş.");
  await expect(page.getByLabel("Yüklenecek dosyalar")).toHaveCount(0);
  await expect(page.getByRole("button", { name: /Yüklemeyi Başlat/ })).toHaveCount(0);

  expect(capturedUploads.map((upload) => upload.fileName).sort()).toEqual([
    "already-there.xml", "invoice-a.pdf", "invoice-b.html",
  ]);
  for (const upload of capturedUploads) {
    expect(upload.intakeCategory).toBe("purchase_invoice");
    expect(upload.period).toBe("2026-08");
    expect(upload.clientId).toBe("pilot-client");
    expect(upload.documentType).toBe(upload.fileName.endsWith(".xml") ? "einvoice_xml" : "invoice");
    expect(upload.body).toContain('name="uploaded_by_user_id"');
  }
  await expect(page.getByRole("cell", { name: "invoice-a.pdf" })).toBeVisible();
  await expect(page.getByRole("cell", { name: "invoice-b.html" })).toBeVisible();
});

test("new upload preserves sales direction for a multi-file batch", async ({ page }) => {
  const { capturedUploads } = await setupUploadRoutes(page);
  await page.goto("/portal-next");
  await page.getByRole("button", { name: "Yeni Yükleme", exact: true }).click();
  await page.getByRole("tab", { name: "Satış" }).click();
  await expect(page.getByRole("tab", { name: "Satış" })).toHaveAttribute("aria-selected", "true");

  const input = page.locator('.portal-next-upload-dropzone input[type="file"]');
  await input.setInputFiles([
    { name: "sales-a.pdf", mimeType: "application/pdf", buffer: Buffer.from("sales-a") },
    { name: "sales-b.xml", mimeType: "application/xml", buffer: Buffer.from("<xml />") },
  ]);
  await expect.poll(() => capturedUploads.length).toBe(2);
  await expect(page.getByRole("status")).toContainText("2 dosya · 2 işleme alındı.");
  await expect(page.getByLabel("Yüklenecek dosyalar")).toHaveCount(0);
  expect(capturedUploads.map((upload) => upload.intakeCategory)).toEqual(["sales_invoice", "sales_invoice"]);
  expect(capturedUploads.map((upload) => upload.documentType)).toEqual(["invoice", "einvoice_xml"]);
  expect(capturedUploads.every((upload) => upload.period === "2026-08")).toBe(true);
});
