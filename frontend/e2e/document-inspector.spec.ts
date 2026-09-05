// File: frontend/e2e/document-inspector.spec.ts
// Summary: Verifies portal-next queue/focus layout, approval hierarchy, shortcut-bar clearance, mode-aware magnification, and deterministic journal-to-source focus for real HTML and PDF viewers.

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
              amount: "540.00",
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

async function expectHtmlLensCalibratedAtSource(page: Page) {
  const target = page.frameLocator(".html-viewer-frame").locator("#fisora-source-target");
  const targetBox = await target.boundingBox();
  expect(targetBox).not.toBeNull();
  const pointerX = targetBox!.x + targetBox!.width / 2;
  const pointerY = targetBox!.y + targetBox!.height / 2;
  await page.mouse.move(pointerX, pointerY);
  const lens = page.locator(".html-document-magnifier");
  await expect(lens).toBeVisible();
  const lensBox = await lens.boundingBox();
  expect(lensBox).not.toBeNull();
  expect(Math.abs(lensBox!.x + lensBox!.width / 2 - pointerX)).toBeLessThan(2);
  expect(Math.abs(lensBox!.y + lensBox!.height / 2 - pointerY)).toBeLessThan(2);
  const documentPoint = await target.evaluate((element) => {
    const rect = element.getBoundingClientRect();
    return { x: rect.left + rect.width / 2 + window.scrollX, y: rect.top + rect.height / 2 + window.scrollY };
  });
  const centeredPoint = await page.locator(".html-document-lens-frame").evaluate((element, point) => {
    const matrix = new DOMMatrix(getComputedStyle(element).transform);
    return {
      x: matrix.a * point.x + matrix.c * point.y + matrix.e,
      y: matrix.b * point.x + matrix.d * point.y + matrix.f,
    };
  }, documentPoint);
  expect(centeredPoint.x).toBeGreaterThan(95);
  expect(centeredPoint.x).toBeLessThan(135);
  expect(centeredPoint.y).toBeGreaterThan(95);
  expect(centeredPoint.y).toBeLessThan(135);
}

test("HTML invoice magnifier and journal source focus stay calibrated across zoom modes", async ({ page }) => {
  const html = `<!doctype html><html><body style="font:16px Arial;padding:48px">
    <h1>Inspector HTML Invoice</h1>
    <div id="duplicate-header">${SOURCE_TEXT}</div>
    <table id="lineTable"><tbody>
      <tr><td>Sıra No</td><td>Malzeme/Hizmet</td><td>Tutar</td></tr>
      <tr><td>1</td><td id="source-line">Kargo Hizmet Bedeli</td><td>540,00 TL</td></tr>
      <tr><td>&nbsp;</td><td>&nbsp;</td><td>&nbsp;</td></tr>
    </tbody></table>
  </body></html>`;
  await setupInspector(page, "inspector.html", "text/html", html);
  await openInspectorDocument(page, ".html-document-viewer");

  const sourceCell = page.frameLocator(".html-viewer-frame").locator("#source-line");
  await expect(sourceCell).toBeVisible();
  const journalRow = page.locator(".journal-source-row").first();
  await journalRow.hover();
  const focusedTarget = page.frameLocator(".html-viewer-frame").locator("#lineTable #fisora-source-target");
  await expect(focusedTarget).toBeVisible();
  await expect(page.frameLocator(".html-viewer-frame").locator("#duplicate-header#fisora-source-target")).toHaveCount(0);
  await expect(journalRow).toHaveClass(/source-focused-row/);
  await journalRow.click({ position: { x: 2, y: 2 } });
  await expect(journalRow).toHaveClass(/source-pinned-row/);
  await expectHtmlLensCalibratedAtSource(page);

  const magnifierToggle = page.locator(".html-document-viewer").getByRole("button", { name: "Büyüteç" });
  await expect(magnifierToggle).toHaveAttribute("aria-pressed", "true");
  await page.locator(".html-document-viewer").getByRole("button", { name: "Genişlik" }).click();
  await expect(magnifierToggle).toHaveAttribute("aria-pressed", "false");
  await expect(page.locator(".html-document-magnifier")).toHaveCount(0);
  await magnifierToggle.click();
  await expectHtmlLensCalibratedAtSource(page);
  await page.locator(".html-document-viewer").getByRole("button", { name: "İçerik" }).click();
  await expect(magnifierToggle).toHaveAttribute("aria-pressed", "false");
  await magnifierToggle.click();
  await expectHtmlLensCalibratedAtSource(page);
  await page.locator(".html-document-viewer").getByRole("button", { name: "%100" }).click();
  await expect(magnifierToggle).toHaveAttribute("aria-pressed", "false");
  await magnifierToggle.click();
  await expectHtmlLensCalibratedAtSource(page);
  await expect(journalRow).toHaveClass(/source-pinned-row/);
  await expect(focusedTarget).toBeVisible();
});

test("queue visibility and focus mode preserve the active workbench", async ({ page }) => {
  const html = `<!doctype html><html><body><table id="lineTable"><tbody><tr><td>Sıra No</td><td>Malzeme/Hizmet</td><td>Tutar</td></tr><tr><td>1</td><td>${SOURCE_TEXT}</td><td>540,00 TL</td></tr></tbody></table></body></html>`;
  await setupInspector(page, "queue-focus.html", "text/html", html);
  await openInspectorDocument(page, ".html-document-viewer");

  const stage = page.locator(".portal-next-workbench-stage.next");
  const queue = page.locator(".portal-next-document-queue");
  const main = page.locator(".document-review-main");
  await expect(queue).toBeVisible();

  await page.locator(".portal-next-workbench-actions").getByRole("button", { name: "Belgeyi incele" }).click();
  await expect(stage).toHaveClass(/focus-mode/);
  await expect(queue).toBeVisible();

  const focusToolbar = page.locator(".portal-next-focus-toolbar");
  await focusToolbar.getByRole("button", { name: "Kuyruğu gizle" }).click();
  await expect(queue).toBeHidden();
  await expect(focusToolbar.getByText("Evrak 1 / 1", { exact: true })).toBeVisible();
  const focusedMainBox = await main.boundingBox();
  expect(focusedMainBox).not.toBeNull();
  expect(focusedMainBox!.width).toBeGreaterThan(700);

  await focusToolbar.getByRole("button", { name: "Kuyruğu göster" }).click();
  await expect(queue).toBeVisible();
  await expect(focusToolbar.getByText("Evrak 1 / 1", { exact: true })).toHaveCount(0);
  await focusToolbar.getByRole("button", { name: "× Kapat" }).click();
  await expect(stage).not.toHaveClass(/focus-mode/);

  await page.locator(".portal-next-workbench-actions").getByRole("button", { name: "Kuyruğu gizle" }).click();
  await expect(queue).toBeHidden();
  const mainBox = await main.boundingBox();
  expect(mainBox).not.toBeNull();
  expect(mainBox!.width).toBeGreaterThan(700);
});

test("ledger hierarchy keeps approval dominant and shortcut help clear of decisions", async ({ page }) => {
  const html = `<!doctype html><html><body><table id="lineTable"><tbody><tr><td>Sira No</td><td>Malzeme/Hizmet</td><td>Tutar</td></tr><tr><td>1</td><td>${SOURCE_TEXT}</td><td>540,00 TL</td></tr></tbody></table></body></html>`;
  await setupInspector(page, "approval-hierarchy.html", "text/html", html);
  await openInspectorDocument(page, ".html-document-viewer");

  await expect(page.locator(".journal-ledger thead th")).toHaveCount(4);
  await expect(page.locator(".journal-ledger thead th").first()).toContainText("Hesap");
  await expect(page.locator(".journal-account-line").first()).toBeVisible();

  const sourceChip = page.locator(".source-review-chip").first();
  await expect(sourceChip).toBeVisible();
  await expect(sourceChip).toHaveCSS("background-color", "rgb(244, 246, 248)");

  const actionBar = page.locator(".journal-next-actions");
  const approve = actionBar.locator("button.primary");
  const hold = actionBar.locator("button.secondary:not(.danger)");
  const exclude = actionBar.locator("button.secondary.danger");
  await expect(approve).toBeVisible();
  await expect(hold).toBeVisible();
  await expect(exclude).toBeVisible();

  const approveBox = await approve.boundingBox();
  const holdBox = await hold.boundingBox();
  const excludeBox = await exclude.boundingBox();
  expect(approveBox).not.toBeNull();
  expect(holdBox).not.toBeNull();
  expect(excludeBox).not.toBeNull();
  expect(approveBox!.height).toBeGreaterThan(holdBox!.height);
  expect(approveBox!.height).toBeGreaterThan(excludeBox!.height);
  expect(approveBox!.width).toBeGreaterThan(holdBox!.width * 1.5);

  const actionBox = await actionBar.boundingBox();
  const shortcutBox = await page.locator(".portal-next-shortcut-bar").boundingBox();
  expect(actionBox).not.toBeNull();
  expect(shortcutBox).not.toBeNull();
  expect(actionBox!.y + actionBox!.height).toBeLessThanOrEqual(shortcutBox!.y + 1);
});

test("PDF invoice magnifier and journal source focus use PDF.js text evidence", async ({ page }) => {
  await setupInspector(page, "inspector.pdf", "application/pdf", pdfBytes(SOURCE_TEXT));
  await openInspectorDocument(page, ".pdf-document-viewer");

  const canvas = page.locator(".pdf-viewer-stage > canvas");
  await expect(canvas).toBeVisible();
  await expect(page.locator(".pdf-viewer-status")).toHaveCount(0);
  const rasterScale = await canvas.evaluate((element) => (element as HTMLCanvasElement).width / Math.max(element.getBoundingClientRect().width, 1));
  expect(rasterScale).toBeGreaterThan(1.5);
  const canvasBox = await canvas.boundingBox();
  expect(canvasBox).not.toBeNull();
  const pointerX = canvasBox!.x + 120;
  const pointerY = canvasBox!.y + 90;
  await page.mouse.move(pointerX, pointerY);
  const pdfLens = page.locator(".pdf-document-magnifier");
  await expect(pdfLens).toBeVisible();
  await expect(pdfLens).toHaveCSS("opacity", "1");
  const lensBox = await pdfLens.boundingBox();
  expect(lensBox).not.toBeNull();
  expect(Math.abs(lensBox!.x + lensBox!.width / 2 - pointerX)).toBeLessThan(2);
  expect(Math.abs(lensBox!.y + lensBox!.height / 2 - pointerY)).toBeLessThan(2);
  const magnifierToggle = page.locator(".pdf-document-viewer").getByRole("button", { name: "Büyüteç" });
  await expect(magnifierToggle).toHaveAttribute("aria-pressed", "true");
  await page.locator(".pdf-document-viewer").getByRole("button", { name: "Genişlik" }).click();
  await expect(magnifierToggle).toHaveAttribute("aria-pressed", "false");
  await expect(page.locator(".pdf-document-magnifier")).toHaveCount(0);
  await magnifierToggle.click();
  const widthCanvasBox = await canvas.boundingBox();
  expect(widthCanvasBox).not.toBeNull();
  await page.mouse.move(widthCanvasBox!.x + 120, widthCanvasBox!.y + 90);
  await expect(pdfLens).toBeVisible();
  await page.locator(".pdf-document-viewer").getByRole("button", { name: "%100" }).click();
  await expect(magnifierToggle).toHaveAttribute("aria-pressed", "false");
  await magnifierToggle.click();
  const fullScaleCanvasBox = await canvas.boundingBox();
  expect(fullScaleCanvasBox).not.toBeNull();
  await page.mouse.move(fullScaleCanvasBox!.x + 120, fullScaleCanvasBox!.y + 90);
  await expect(pdfLens).toBeVisible();

  const journalRow = page.locator(".journal-source-row").first();
  await journalRow.hover();
  await expect(page.locator(".pdf-source-highlight")).toBeVisible();
  await expect(journalRow).toHaveClass(/source-focused-row/);

  await journalRow.click({ position: { x: 2, y: 2 } });
  await expect(journalRow).toHaveClass(/source-pinned-row/);
  await expect(page.locator(".pdf-source-highlight.pinned")).toBeVisible();
});
