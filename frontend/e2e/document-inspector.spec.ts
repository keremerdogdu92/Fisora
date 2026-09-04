// File: frontend/e2e/document-inspector.spec.ts
// Summary: Verifies portal-next magnification and deterministic journal-to-source focus for real HTML and PDF viewers.

import { expect, test, type Page } from "@playwright/test";

const SOURCE_TEXT = "Kargo Hizmet Bedeli 540,00 TL";
const CLIENT_ID = "inspector-client";

const readiness = {
  pilot_sellable: true,
  production_ready: false,
  real_data_pilot: {
    allowed: true,
    status: "ready_for_restricted_live_pilot",
    access_mode: "restricted_network",
    blocking: [],
  },
  pilot_blocking: [],
  warnings: [],
  auth: { auth_mode: "session_required" },
  store_backend: "postgres",
  ai_provider: "xkiro",
};

const client = {
  client_id: CLIENT_ID,
  profile: { client_id: CLIENT_ID, title: "Inspector Test AS", tax_id: "1111111111" },
};

function pdfBytes(text: string) {
  const escaped = text.replace(/\\/g, "\\\\").replace(/\(/g, "\\(").replace(/\)/g, "\\)");
  const stream = `BT\n/F1 18 Tf\n72 700 Td\n(${escaped}) Tj\nET\n`;
  const objects = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
    `<< /Length ${Buffer.byteLength(stream, "ascii")} >>\nstream\n${stream}endstream`,
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
  ];
  let body = "%PDF-1.4\n";
  const offsets = [0];
  objects.forEach((object, index) => {
    offsets.push(Buffer.byteLength(body, "ascii"));
    body += `${index + 1} 0 obj\n${object}\nendobj\n`;
  });
  const xrefOffset = Buffer.byteLength(body, "ascii");
  const xref = offsets.slice(1).map((offset) => `${String(offset).padStart(10, "0")} 00000 n `).join("\n");
  body += `xref\n0 6\n0000000000 65535 f \n${xref}\n`;
  body += `trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n${xrefOffset}\n%%EOF\n`;
  return Buffer.from(body, "ascii");
}

function workspaceFor(fileName: string, contentType: string) {
  const documentRef = `${fileName}-ref`;
  return {
    client,
    portal_users: [{ user_id: "mali-musavir", display_name: "Mali Musavir", role: "accountant" }],
    chart_accounts: { accounts: [] },
    uploaded_documents: [
      {
        document_ref: documentRef,
        original_file_name: fileName,
        content_type: contentType,
        intake_category: "purchase_invoice",
        period: "2026-09",
        created_at: "2026-09-04T12:00:00Z",
      },
    ],
    processing_jobs: [],
    export_packages: [],
    documents: [
      {
        document_ref: documentRef,
        document_type: "purchase_invoice",
        export_status: "review_required",
        created_at: "2026-09-04T12:00:00Z",
        result: {
          file_name: fileName,
          invoice_type: "purchase_invoice",
          intake_category: "purchase_invoice",
          export_status: "review_required",
          issue_date: "2026-09-04",
          payable_total: "540.00",
          provider_hint: "Inspector Fixture",
          product_line_hint: SOURCE_TEXT,
          product_category: "service",
          accounting_direction: "purchase",
          draft_status: "manual_draft_required",
          source_review_rows: [
            {
              source_position: "1",
              source_text: SOURCE_TEXT,
              description: SOURCE_TEXT,
              amount: "540,00",
              amount_label: "Satır toplamı",
              amount_basis: "line_total_inc_tax",
              role: "posting_candidate",
            },
          ],
          draft_lines: [],
          review_reason_codes: ["manual_review"],
        },
      },
    ],
  };
}

async function setupInspector(page: Page, fileName: string, contentType: string, fileBody: string | Buffer) {
  const workspace = workspaceFor(fileName, contentType);
  await page.addInitScript(() => {
    window.localStorage.setItem("fisora.office.session.v1", JSON.stringify({
      userId: "mali-musavir",
      role: "accountant",
      sessionToken: "accountant-session",
      storageScope: "local",
    }));
  });
  await page.route("**/phase0/**", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    if (path.endsWith("/phase0/store/auth/session")) {
      await route.fulfill({ json: { valid: true, user_id: "mali-musavir", expires_at: "2026-12-31T22:00:00+00:00" } });
      return;
    }
    if (path.endsWith("/phase0/store/system/readiness")) {
      await route.fulfill({ json: readiness });
      return;
    }
    if (path.endsWith("/phase0/store/clients")) {
      await route.fulfill({ json: { clients: [client] } });
      return;
    }
    if (path.includes(`/phase0/store/workspace/${CLIENT_ID}`)) {
      await route.fulfill({ json: workspace });
      return;
    }
    if (path.includes("/phase0/store/document-file/")) {
      await route.fulfill({ status: 200, contentType, body: fileBody });
      return;
    }
    if (path.includes("/phase0/store/research/")) {
      await route.fulfill({ json: { profiles: [], runs: [] } });
      return;
    }
    await route.fulfill({ json: {} });
  });
}

async function openInspectorDocument(page: Page, expectedViewerClass: string) {
  await page.goto("/portal-next");
  await page.getByRole("button", { name: "Çalışma Masası", exact: true }).click();
  await expect(page.locator(expectedViewerClass)).toBeVisible();
  await expect(page.locator(".journal-source-row").first()).toBeVisible();
}

test("HTML invoice magnifier and journal source focus work without extra controls", async ({ page }) => {
  const html = `<!doctype html><html><body style="font:16px Arial;padding:48px">
    <h1>Inspector HTML Invoice</h1>
    <table><tbody><tr><td id="source-line">${SOURCE_TEXT}</td></tr></tbody></table>
  </body></html>`;
  await setupInspector(page, "inspector.html", "text/html", html);
  await openInspectorDocument(page, ".html-document-viewer");

  const sourceCell = page.frameLocator(".html-viewer-frame").locator("#source-line");
  await expect(sourceCell).toBeVisible();
  const frameBox = await page.locator(".html-viewer-frame").boundingBox();
  expect(frameBox).not.toBeNull();
  await page.mouse.move(frameBox!.x + 120, frameBox!.y + 120);
  await expect(page.locator(".html-document-magnifier")).toBeVisible();
  await expect(page.locator(".html-document-magnifier")).toHaveCSS("opacity", "1");

  const journalRow = page.locator(".journal-source-row").first();
  await journalRow.hover();
  await expect(page.frameLocator(".html-viewer-frame").locator("#fisora-source-target")).toBeVisible();
  await expect(journalRow).toHaveClass(/source-focused-row/);

  await journalRow.click({ position: { x: 2, y: 2 } });
  await expect(journalRow).toHaveClass(/source-pinned-row/);
  await expect(page.frameLocator(".html-viewer-frame").locator("#fisora-source-target")).toBeVisible();
});

test("PDF invoice magnifier and journal source focus use PDF.js text evidence", async ({ page }) => {
  await setupInspector(page, "inspector.pdf", "application/pdf", pdfBytes(SOURCE_TEXT));
  await openInspectorDocument(page, ".pdf-document-viewer");

  const canvas = page.locator(".pdf-viewer-stage > canvas");
  await expect(canvas).toBeVisible();
  await expect(page.locator(".pdf-viewer-status")).toHaveCount(0);
  const rasterScale = await canvas.evaluate((element) => (element as HTMLCanvasElement).width / Math.max(element.getBoundingClientRect().width, 1));
  expect(rasterScale).toBeGreaterThan(1.5);
  await canvas.hover({ position: { x: 120, y: 90 } });
  await expect(page.locator(".pdf-document-magnifier")).toBeVisible();
  await expect(page.locator(".pdf-document-magnifier")).toHaveCSS("opacity", "1");

  const journalRow = page.locator(".journal-source-row").first();
  await journalRow.hover();
  await expect(page.locator(".pdf-source-highlight")).toBeVisible();
  await expect(journalRow).toHaveClass(/source-focused-row/);

  await journalRow.click({ position: { x: 2, y: 2 } });
  await expect(journalRow).toHaveClass(/source-pinned-row/);
  await expect(page.locator(".pdf-source-highlight.pinned")).toBeVisible();
});
