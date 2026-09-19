// File: frontend/e2e/document-inspector.spec.ts
// Summary: Verifies portal-next queue/focus layout, approval hierarchy, shortcut-bar clearance, mode-aware magnification, and deterministic journal-to-source focus for real HTML and PDF viewers.

import { expect, test, type Page } from "@playwright/test";

const SOURCE_TEXT = "Kargo Hizmet Bedeli 540,00 TL";
const SECOND_SOURCE_TEXT = "Paketleme Hizmeti 60,00 TL";
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
  return pdfBytesLines([text]);
}

function pdfBytesLines(texts: string[]) {
  const newline = String.fromCharCode(10);
  const lines = texts.map((text) => text.replace(/\\/g, "\\\\").replace(/\(/g, "\\(").replace(/\)/g, "\\)"));
  const textCommands = lines.map((text, index) => `${index ? "0 -36 Td" + newline : ""}(${text}) Tj`).join(newline);
  const stream = ["BT", "/F1 18 Tf", "72 700 Td", textCommands, "ET", ""].join(newline);
  const objects = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
    `<< /Length ${Buffer.byteLength(stream, "ascii")} >>${newline}stream${newline}${stream}endstream`,
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
  ];
  let body = `%PDF-1.4${newline}`;
  const offsets = [0];
  objects.forEach((object, index) => {
    offsets.push(Buffer.byteLength(body, "ascii"));
    body += `${index + 1} 0 obj${newline}${object}${newline}endobj${newline}`;
  });
  const xrefOffset = Buffer.byteLength(body, "ascii");
  const xref = offsets.slice(1).map((offset) => `${String(offset).padStart(10, "0")} 00000 n `).join(newline);
  body += `xref${newline}0 6${newline}0000000000 65535 f ${newline}${xref}${newline}`;
  body += `trailer${newline}<< /Size 6 /Root 1 0 R >>${newline}startxref${newline}${xrefOffset}${newline}%%EOF${newline}`;
  return Buffer.from(body, "ascii");
}

function workspaceFor(fileName: string, contentType: string) {
  const documentRef = `${fileName}-ref`;
  return {
    client,
    portal_users: [{ user_id: "mali-musavir", display_name: "Mali Musavir", role: "accountant" }],
    chart_accounts: { accounts: [] as Array<Record<string, unknown>> },
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

async function setupInspector(
  page: Page,
  fileName: string,
  contentType: string,
  fileBody: string | Buffer,
  mutateWorkspace?: (workspace: ReturnType<typeof workspaceFor>) => void,
) {
  const workspace = workspaceFor(fileName, contentType);
  mutateWorkspace?.(workspace);
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
  await page.locator(".html-document-viewer").getByRole("button", { name: "Yüzde 100'e dön" }).click();
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
  await expect(focusToolbar.getByText("Kuyruk 1 / 1", { exact: true })).toBeVisible();
  const focusedMainBox = await main.boundingBox();
  expect(focusedMainBox).not.toBeNull();
  expect(focusedMainBox!.width).toBeGreaterThan(700);

  await focusToolbar.getByRole("button", { name: "Kuyruğu göster" }).click();
  await expect(queue).toBeVisible();
  await expect(focusToolbar.getByText("Kuyruk 1 / 1", { exact: true })).toHaveCount(0);
  await focusToolbar.getByRole("button", { name: "× Kapat" }).click();
  await expect(stage).not.toHaveClass(/focus-mode/);

  await page.locator(".portal-next-workbench-actions").getByRole("button", { name: "Kuyruğu gizle" }).click();
  await expect(queue).toBeHidden();
  const mainBox = await main.boundingBox();
  expect(mainBox).not.toBeNull();
  expect(mainBox!.width).toBeGreaterThan(700);
});

test("reopening queue reveals the current selected document", async ({ page }) => {
  const html = `<!doctype html><html><body><table id="lineTable"><tbody><tr><td>1</td><td>${SOURCE_TEXT}</td><td>540,00 TL</td></tr></tbody></table></body></html>`;
  await setupInspector(page, "queue-scroll.html", "text/html", html, (workspace) => {
    const baseUpload = workspace.uploaded_documents[0];
    const baseDocument = workspace.documents[0];
    workspace.uploaded_documents = Array.from({ length: 25 }, (_, index) => ({
      ...baseUpload,
      document_ref: `queue-doc-${index + 1}`,
      original_file_name: `queue-${String(index + 1).padStart(2, "0")}.html`,
    }));
    workspace.documents = Array.from({ length: 25 }, (_, index) => ({
      ...baseDocument,
      document_ref: `queue-doc-${index + 1}`,
      result: { ...baseDocument.result, file_name: `queue-${String(index + 1).padStart(2, "0")}.html` },
    }));
  });
  await openInspectorDocument(page, ".html-document-viewer");

  const queue = page.locator(".portal-next-document-queue");
  const list = page.locator(".portal-next-queue-list");
  await page.locator(".portal-next-workbench-actions .queue-action").click();
  await expect(queue).toBeHidden();
  for (let index = 0; index < 11; index += 1) await page.keyboard.press("ArrowDown");
  await expect(page.locator(".portal-next-workbench-actions")).toContainText("Kuyruk 12 / 25");
  await page.locator(".portal-next-workbench-actions .queue-action").click();
  await expect(queue).toBeVisible();

  const active = list.locator("button.active");
  await expect(active).toHaveAttribute("title", "Orijinal dosya: queue-12.html");
  await expect(active).toBeInViewport();
});

test("queue business identity stays readable without growing compact cards", async ({ page }) => {
  const html = `<!doctype html><html><body><table id="lineTable"><tbody><tr><td>1</td><td>${SOURCE_TEXT}</td><td>12.345,67 TL</td></tr></tbody></table></body></html>`;
  await page.setViewportSize({ width: 1366, height: 768 });
  await setupInspector(page, "1790617537_BEF2026002324731.html", "text/html", html, (workspace) => {
    const result = workspace.documents[0].result as Record<string, unknown>;
    result.counterparty_title = "Yurtiçi Kargo Gönderim Hizmetleri ve Ticaret A.Ş.";
    result.invoice_number = "BEF2026002324731";
    result.payable_total = "12345.67";
  });
  await openInspectorDocument(page, ".html-document-viewer");

  const card = page.locator(".portal-next-queue-list button.active");
  await expect(card.locator(".portal-next-queue-identity-title strong")).toHaveText("Yurtiçi Kargo Gönderim Hizmetleri ve Ticaret A.Ş.");
  await expect(card.locator(".portal-next-queue-identity-meta small")).toHaveText("BEF2026002324731");
  await expect(card.locator(".portal-next-queue-identity-meta b")).toHaveText("12.345,67");
  await expect(card.locator(".portal-next-queue-identity-footer small")).toHaveText("04.09.2026");
  await expect(card).toHaveAttribute("title", "Orijinal dosya: 1790617537_BEF2026002324731.html");

  for (const viewport of [{ width: 1366, height: 768 }, { width: 1093, height: 614 }, { width: 1000, height: 700 }]) {
    await page.setViewportSize(viewport);
    const metrics = await card.evaluate((element) => {
      const title = element.querySelector<HTMLElement>(".portal-next-queue-identity-title strong");
      const invoice = element.querySelector<HTMLElement>(".portal-next-queue-identity-meta small");
      const date = element.querySelector<HTMLElement>(".portal-next-queue-identity-footer small");
      const rect = element.getBoundingClientRect();
      return {
        height: rect.height,
        titleClient: title?.clientWidth || 0,
        titleScroll: title?.scrollWidth || 0,
        invoiceClient: invoice?.clientWidth || 0,
        invoiceScroll: invoice?.scrollWidth || 0,
        dateClient: date?.clientWidth || 0,
        dateScroll: date?.scrollWidth || 0,
      };
    });
    expect(metrics.height).toBe(72);
    expect(metrics.titleClient).toBeGreaterThan(150);
    expect(metrics.titleScroll).toBeGreaterThan(metrics.titleClient);
    expect(metrics.invoiceScroll).toBeLessThanOrEqual(metrics.invoiceClient);
    expect(metrics.dateScroll).toBeLessThanOrEqual(metrics.dateClient);
  }
});

test("queue identity fallback prefers meaningful provider and skips generic provider labels", async ({ page }) => {
  const html = `<!doctype html><html><body><table id="lineTable"><tbody><tr><td>1</td><td>${SOURCE_TEXT}</td><td>540,00 TL</td></tr></tbody></table></body></html>`;
  await setupInspector(page, "meaningful-provider.html", "text/html", html, (workspace) => {
    const baseUpload = workspace.uploaded_documents[0];
    const baseDocument = workspace.documents[0];
    workspace.uploaded_documents = [
      { ...baseUpload, document_ref: "meaningful-provider-ref", original_file_name: "meaningful-provider.html" },
      { ...baseUpload, document_ref: "generic-provider-ref", original_file_name: "generic-provider.html" },
    ];
    workspace.documents = [
      { ...baseDocument, document_ref: "meaningful-provider-ref", result: { ...baseDocument.result, file_name: "meaningful-provider.html", provider_hint: "Yurtiçi Kargo" } },
      { ...baseDocument, document_ref: "generic-provider-ref", result: { ...baseDocument.result, file_name: "generic-provider.html", provider_hint: "Çalışma alanı" } },
    ];
  });
  await openInspectorDocument(page, ".html-document-viewer");

  const meaningfulCard = page.locator('.portal-next-queue-list button[title="Orijinal dosya: meaningful-provider.html"]');
  const genericCard = page.locator('.portal-next-queue-list button[title="Orijinal dosya: generic-provider.html"]');
  await expect(meaningfulCard.locator(".portal-next-queue-identity-title strong")).toHaveText("Yurtiçi Kargo");
  await expect(genericCard.locator(".portal-next-queue-identity-title strong")).toHaveText("generic-provider.html");
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
  await expect(page.locator(".pdf-viewer-page-controls")).toContainText("Sayfa 1 / 1");
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
  await page.locator(".pdf-document-viewer").getByRole("button", { name: "Yüzde 100'e dön" }).click();
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


test("generated HTML journal keeps source focus when accountant description differs from invoice text", async ({ page }) => {
  const html = `<!doctype html><html><body><table id="lineTable"><tbody><tr><td>Sira No</td><td>Malzeme/Hizmet</td><td>Tutar</td></tr><tr><td>1</td><td>${SOURCE_TEXT}</td><td>540,00 TL</td></tr></tbody></table></body></html>`;
  await setupInspector(page, "generated-anchor.html", "text/html", html, (workspace) => {
    const result = workspace.documents[0].result as Record<string, unknown>;
    result["draft_status"] = "draft_ready";
    result["draft_lines"] = [{
      account_code: "770.01",
      description: "Kargo gideri",
      debit: "540.00",
      credit: "0.00",
      contributing_line_ids: ["line-anchor-1"],
      source_line_numbers: [1],
      source_position: "1",
      source_text: SOURCE_TEXT,
    }];
  });
  await openInspectorDocument(page, ".html-document-viewer");
  const journalRow = page.locator(".journal-source-row").first();
  await expect(journalRow.locator("input").nth(0)).toHaveValue("770.01");
  await expect(journalRow.locator("input").nth(1)).toHaveValue("Kargo gideri");
  await journalRow.hover();
  await expect(page.frameLocator(".html-viewer-frame").locator("#lineTable #fisora-source-target")).toBeVisible();
});

test("generated PDF journal keeps source focus when accountant description differs from invoice text", async ({ page }) => {
  await setupInspector(page, "generated-anchor.pdf", "application/pdf", pdfBytes(SOURCE_TEXT), (workspace) => {
    const result = workspace.documents[0].result as Record<string, unknown>;
    result["draft_status"] = "draft_ready";
    result["draft_lines"] = [{
      account_code: "770.01",
      description: "Kargo gideri",
      debit: "540.00",
      credit: "0.00",
      contributing_line_ids: ["line-anchor-1"],
      source_line_numbers: [1],
      source_position: "1",
      source_text: SOURCE_TEXT,
    }];
  });
  await openInspectorDocument(page, ".pdf-document-viewer");
  const journalRow = page.locator(".journal-source-row").first();
  await expect(journalRow.locator("input").nth(0)).toHaveValue("770.01");
  await expect(journalRow.locator("input").nth(1)).toHaveValue("Kargo gideri");
  await journalRow.hover();
  await expect(page.locator(".pdf-source-highlight")).toBeVisible();
});

test("multi-source HTML journal highlights all contributing invoice rows", async ({ page }) => {
  const html = `<!doctype html><html><body><table id="lineTable"><tbody><tr><td>Sira No</td><td>Malzeme/Hizmet</td><td>Tutar</td></tr><tr><td>1</td><td>${SOURCE_TEXT}</td><td>540,00 TL</td></tr><tr><td>2</td><td>${SECOND_SOURCE_TEXT}</td><td>60,00 TL</td></tr></tbody></table></body></html>`;
  await setupInspector(page, "multi-anchor.html", "text/html", html, (workspace) => {
    const result = workspace.documents[0].result as Record<string, unknown>;
    result["draft_status"] = "draft_ready";
    result["draft_lines"] = [{
      account_code: "770.01",
      description: "Toplam hizmet gideri",
      debit: "600.00",
      credit: "0.00",
      contributing_line_ids: ["line-anchor-1", "line-anchor-2"],
      source_line_numbers: [1, 2],
      source_anchors: [
        { canonical_line_id: "line-anchor-1", source_position: "1", source_text: SOURCE_TEXT },
        { canonical_line_id: "line-anchor-2", source_position: "2", source_text: SECOND_SOURCE_TEXT },
      ],
    }];
  });
  await openInspectorDocument(page, ".html-document-viewer");
  const journalRow = page.locator(".journal-source-row").first();
  const sourceChip = journalRow.locator(".source-review-chip");
  await expect(sourceChip).toContainText("Kaynak 1, 2");
  await journalRow.hover();
  await expect(page.frameLocator(".html-viewer-frame").locator('[data-fisora-source-target="true"]')).toHaveCount(2);
  await sourceChip.click();
  await page.mouse.move(0, 0);
  const htmlSourceOverlay = page.locator(".html-document-viewer .document-source-focus-controls");
  await expect(htmlSourceOverlay).toContainText("2/2 kaynak bulundu");
  await expect(htmlSourceOverlay).toHaveCSS("position", "absolute");
  const htmlSourceStatus = htmlSourceOverlay.locator(".document-source-focus-status");
  await htmlSourceStatus.evaluate((element) => element.getAnimations().forEach((animation) => animation.finish()));
  await expect(htmlSourceStatus).toHaveCSS("opacity", "0");
  await expect(htmlSourceOverlay.getByRole("button", { name: "Vurguyu kaldır" })).toBeVisible();
  await expect(page.frameLocator(".html-viewer-frame").locator('[data-fisora-source-target="true"]')).toHaveCount(2);
});

test("multi-source PDF journal highlights all contributing invoice rows", async ({ page }) => {
  await setupInspector(page, "multi-anchor.pdf", "application/pdf", pdfBytesLines([SOURCE_TEXT, SECOND_SOURCE_TEXT]), (workspace) => {
    const result = workspace.documents[0].result as Record<string, unknown>;
    result["draft_status"] = "draft_ready";
    result["draft_lines"] = [{
      account_code: "770.01",
      description: "Toplam hizmet gideri",
      debit: "600.00",
      credit: "0.00",
      contributing_line_ids: ["line-anchor-1", "line-anchor-2"],
      source_line_numbers: [1, 2],
      source_anchors: [
        { canonical_line_id: "line-anchor-1", source_position: "1", source_text: SOURCE_TEXT },
        { canonical_line_id: "line-anchor-2", source_position: "2", source_text: SECOND_SOURCE_TEXT },
      ],
    }];
  });
  await openInspectorDocument(page, ".pdf-document-viewer");
  const journalRow = page.locator(".journal-source-row").first();
  const sourceChip = journalRow.locator(".source-review-chip");
  await expect(sourceChip).toContainText("Kaynak 1, 2");
  await journalRow.hover();
  await expect(page.locator(".pdf-source-highlight")).toHaveCount(2);
  await sourceChip.click();
  await page.mouse.move(0, 0);
  const pdfSourceOverlay = page.locator(".pdf-document-viewer .document-source-focus-controls");
  await expect(pdfSourceOverlay).toContainText("2/2 kaynak bulundu");
  await expect(pdfSourceOverlay).toHaveCSS("position", "absolute");
  await expect(pdfSourceOverlay.getByRole("button", { name: "Vurguyu kaldır" })).toBeVisible();
  await expect(page.locator(".pdf-source-highlight.pinned")).toHaveCount(2);
});


test("journal stays readable through narrow desktop two-tier layout", async ({ page }) => {
  const longAccountName = "Yurtiçi Kargo Gönderim Bedelleri";
  const html = `<!doctype html><html><body><table id="lineTable"><tbody><tr><td>1</td><td>${SOURCE_TEXT}</td><td>540,00 TL</td></tr></tbody></table></body></html>`;
  await page.setViewportSize({ width: 1366, height: 768 });
  await setupInspector(page, "account-readability.html", "text/html", html, (workspace) => {
    (workspace.chart_accounts.accounts as Array<Record<string, unknown>>).push({
      raw_account_code: "770.01.003",
      normalized_account_code: "770.01.003",
      account_name: longAccountName,
      is_detail_account: true,
    });
    const result = workspace.documents[0].result as Record<string, unknown>;
    result["draft_status"] = "draft_ready";
    result["draft_lines"] = [{
      account_code: "770.01.003",
      description: "Kargo gideri",
      debit: "540.00",
      credit: "0.00",
      source_line_numbers: [1],
      source_position: "1",
      source_text: SOURCE_TEXT,
    }];
  });
  await openInspectorDocument(page, ".html-document-viewer");

  const accountName = page.locator(".journal-account-name").first();
  await expect(accountName).toHaveText(longAccountName);
  await expect(page.getByLabel("Fiş satırı açıklaması")).toHaveValue("Kargo gideri");
  await expect(page.getByLabel("Fatura satırı açıklaması")).toHaveCount(0);

  async function expectReadableJournal(viewportWidth: number) {
    const metrics = await accountName.evaluate((element) => {
      const style = getComputedStyle(element);
      const lineHeight = Number.parseFloat(style.lineHeight);
      return {
        clamp: style.webkitLineClamp,
        whiteSpace: style.whiteSpace,
        clientHeight: element.clientHeight,
        scrollHeight: element.scrollHeight,
        lineHeight,
      };
    });
    expect(metrics.clamp).toBe("2");
    expect(metrics.whiteSpace).toBe("normal");
    expect(metrics.clientHeight).toBeLessThanOrEqual(metrics.lineHeight * 2 + 2);
    expect(metrics.scrollHeight).toBeLessThanOrEqual(metrics.clientHeight + 1);

    const row = page.locator(".journal-source-row").first();
    const rowBox = await row.boundingBox();
    const debitBox = await row.locator('input[inputmode="decimal"]').nth(0).boundingBox();
    const creditBox = await row.locator('input[inputmode="decimal"]').nth(1).boundingBox();
    expect(rowBox).not.toBeNull();
    expect(debitBox).not.toBeNull();
    expect(creditBox).not.toBeNull();
    expect(rowBox!.x + rowBox!.width).toBeLessThanOrEqual(viewportWidth + 1);
    expect(debitBox!.x + debitBox!.width).toBeLessThanOrEqual(viewportWidth + 1);
    expect(creditBox!.x + creditBox!.width).toBeLessThanOrEqual(viewportWidth + 1);
  }

  await expectReadableJournal(1366);
  await page.setViewportSize({ width: 1093, height: 614 });
  await expectReadableJournal(1093);
  async function expectTwoTierJournal() {
    const row = page.locator(".journal-source-row").first();
    expect(await row.evaluate((element) => getComputedStyle(element).display)).toBe("grid");
    await expect(row.locator(".journal-responsive-amount-label")).toHaveCount(2);
    expect(await row.locator(".journal-responsive-amount-label").first().evaluate((element) => getComputedStyle(element).display)).toBe("block");
  }

  await page.setViewportSize({ width: 1000, height: 700 });
  await expectReadableJournal(1000);
  await expectTwoTierJournal();
  await page.setViewportSize({ width: 900, height: 700 });
  await expectReadableJournal(900);
  await expectTwoTierJournal();
  await page.locator(".portal-next-collapse").click();
  await expect(page.locator(".portal-next-sidebar")).not.toHaveClass(/collapsed/);
  await expectReadableJournal(900);
  await expectTwoTierJournal();
  await page.locator(".portal-next-collapse").click();
  await expect(page.locator(".portal-next-sidebar")).toHaveClass(/collapsed/);
  await page.setViewportSize({ width: 1093, height: 614 });
  await page.locator(".portal-next-collapse").click();
  await expect(page.locator(".portal-next-sidebar")).not.toHaveClass(/collapsed/);
  await expectReadableJournal(1093);
  await page.locator(".portal-next-collapse").click();
  await expect(page.locator(".portal-next-sidebar")).toHaveClass(/collapsed/);
  await expectReadableJournal(1093);
});


test("learned rule audit auto-applies the validated correction and preserves the AI provenance", async ({ page }) => {
  const html = `<!doctype html><html><body><table id="lineTable"><tbody><tr><td>Sıra No</td><td>Malzeme/Hizmet</td><td>Tutar</td></tr><tr><td>1</td><td>${SOURCE_TEXT}</td><td>540,00 TL</td></tr></tbody></table></body></html>`;
  await setupInspector(page, "rule-audit.html", "text/html", html, (workspace) => {
    workspace.chart_accounts.accounts = [
      { normalized_account_code: "153.01", account_name: "Cihaz stoku", is_detail_account: true, is_active: true },
      { normalized_account_code: "153.02", account_name: "Aksesuar stoku", is_detail_account: true, is_active: true },
    ];
    const result = workspace.documents[0].result as Record<string, unknown>;
    result.draft_status = "draft_ready";
    result.draft_lines = [
      {
        account_code: "153.01",
        description: "MINIFIT HOPARLÖR 3R 85",
        debit: "540.00",
        credit: "0.00",
        source_position: "1",
        source_text: SOURCE_TEXT,
      },
    ];
    result.technical_details = {
      learned_rule_audit_shadow: {
        status: "completed",
        audit_status: "complete",
        model: "gemini-3.5-flash-lite",
        elapsed_ms: 5100,
        application_status: "applied",
        applied_correction_count: 1,
        corrections: [
          {
            row_id: "1",
            rule_id: "rule-minifit",
            from_account: "153.02",
            to_account: "153.01",
            reason: "Aktif öğrenilmiş MINIFIT hoparlör kuralı bu satırı cihaz stok hesabına yönlendiriyor.",
            application_status: "applied",
          },
        ],
        unresolved_rows: [],
        validation_errors: [],
      },
    };
  });

  await openInspectorDocument(page, ".html-document-viewer");

  const auditPanel = page.getByRole("region", { name: "Öğrenilmiş kural kontrolü" });
  await expect(auditPanel).toBeVisible();
  await expect(auditPanel).toContainText("Muhasebe AI: 153.02");
  await expect(auditPanel).toContainText("Kural: 153.01");
  await expect(auditPanel).toContainText("Kural uygulandı");
  await expect(page.getByLabel("Hesap kodu").first()).toHaveValue("153.01");
  await expect(auditPanel.getByRole("button", { name: "Uygula", exact: true })).toHaveCount(0);
  await expect(auditPanel.getByRole("button", { name: "Doğru değil", exact: true })).toHaveCount(0);
});

test("learned rule audit keeps the AI draft unchanged when automatic application is blocked", async ({ page }) => {
  const html = `<!doctype html><html><body><table id="lineTable"><tbody><tr><td>Sıra No</td><td>Malzeme/Hizmet</td><td>Tutar</td></tr><tr><td>1</td><td>${SOURCE_TEXT}</td><td>540,00 TL</td></tr></tbody></table></body></html>`;
  await setupInspector(page, "rule-audit-reject.html", "text/html", html, (workspace) => {
    workspace.chart_accounts.accounts = [
      { normalized_account_code: "153.01", account_name: "Cihaz stoku", is_detail_account: true, is_active: true },
      { normalized_account_code: "153.02", account_name: "Aksesuar stoku", is_detail_account: true, is_active: true },
    ];
    const result = workspace.documents[0].result as Record<string, unknown>;
    result.draft_status = "draft_ready";
    result.draft_lines = [
      {
        account_code: "153.02",
        description: "MINIFIT HOPARLÖR 3R 85",
        debit: "540.00",
        credit: "0.00",
        source_position: "1",
        source_text: SOURCE_TEXT,
      },
    ];
    result.technical_details = {
      learned_rule_audit_shadow: {
        status: "completed",
        audit_status: "complete",
        model: "gemini-3.5-flash-lite",
        elapsed_ms: 5100,
        application_status: "blocked",
        applied_correction_count: 0,
        corrections: [
          {
            row_id: "1",
            rule_id: "rule-minifit",
            from_account: "153.02",
            to_account: "153.01",
            reason: "Aktif öğrenilmiş MINIFIT hoparlör kuralı bu satırı cihaz stok hesabına yönlendiriyor.",
          },
        ],
        unresolved_rows: [],
        validation_errors: [],
      },
    };
  });

  await openInspectorDocument(page, ".html-document-viewer");

  const auditPanel = page.getByRole("region", { name: "Öğrenilmiş kural kontrolü" });
  await expect(page.getByLabel("Hesap kodu").first()).toHaveValue("153.02");
  await expect(auditPanel).toContainText("Kural uygulaması durduruldu");
  await expect(auditPanel).toContainText("mevcut fiş değiştirilmedi");
  await expect(auditPanel.getByRole("button", { name: "Uygula", exact: true })).toHaveCount(0);
  await expect(auditPanel.getByRole("button", { name: "Doğru değil", exact: true })).toHaveCount(0);
});


test("learned rule teaching uses the account actually applied in the journal", async ({ page }) => {
  const html = `<!doctype html><html><body><table id="lineTable"><tbody><tr><td>Sıra No</td><td>Malzeme/Hizmet</td><td>Tutar</td></tr><tr><td>1</td><td>${SOURCE_TEXT}</td><td>540,00 TL</td></tr></tbody></table></body></html>`;
  await setupInspector(page, "rule-teaching-account.html", "text/html", html, (workspace) => {
    workspace.chart_accounts.accounts = [
      { normalized_account_code: "153.01", account_name: "Cihaz stoku", is_detail_account: true, is_active: true },
      { normalized_account_code: "153.02", account_name: "Aksesuar stoku", is_detail_account: true, is_active: true },
    ];
    const result = workspace.documents[0].result as Record<string, unknown>;
    result.draft_status = "draft_ready";
    result.draft_lines = [
      {
        account_code: "153.01",
        description: "FISORA PILOT TEST HIZMETI",
        debit: "540.00",
        credit: "0.00",
        source_position: "1",
        source_text: SOURCE_TEXT,
      },
    ];
    result.technical_details = {
      learned_rule_audit_shadow: {
        status: "completed",
        audit_status: "complete",
        model: "gemini-3.5-flash-lite",
        elapsed_ms: 3100,
        application_status: "applied",
        applied_correction_count: 1,
        corrections: [
          {
            row_id: "1",
            rule_id: "rule-pilot",
            from_account: "153.02",
            to_account: "153.01",
            reason: "Pilot learned rule correction.",
            application_status: "applied",
          },
        ],
        unresolved_rows: [],
        validation_errors: [],
      },
    };
  });

  await openInspectorDocument(page, ".html-document-viewer");

  const auditPanel = page.getByRole("region", { name: "Öğrenilmiş kural kontrolü" });
  await expect(auditPanel).toContainText("Kural uygulandı");
  await expect(page.getByLabel("Hesap kodu").first()).toHaveValue("153.01");

  const learningDetails = page.locator(".journal-learning-details");
  const summary = learningDetails.locator("summary");
  if (await summary.isVisible()) {
    await summary.click();
  }
  const note = page.getByPlaceholder("Bu fişte neyi neden değiştirdiniz? Benzer belgelerde nasıl uygulanmalı?");
  await note.fill("Bu pilot satır için 153.01 hesabını kullan; başka kapsamlara genelleme.");

  const previewRequestPromise = page.waitForRequest((request) =>
    request.url().includes("/phase0/store/review-rule/preview") && request.method() === "POST",
  );
  await page.getByRole("button", { name: "Egitim notunu kaydet", exact: true }).click();
  const previewRequest = await previewRequestPromise;
  const payload = previewRequest.postDataJSON() as { decision?: { corrected_account_code?: string; draft_lines?: Array<{ account_code?: string }> } };

  expect(payload.decision?.corrected_account_code).toBe("153.01");
  expect(payload.decision?.draft_lines).toBeUndefined();
});


test("learned rule teaching ignores counterparty account edits when resolving the business account", async ({ page }) => {
  const html = `<!doctype html><html><body><table id="lineTable"><tbody><tr><td>Sıra No</td><td>Malzeme/Hizmet</td><td>Tutar</td></tr><tr><td>1</td><td>FISORA PILOT TEST HIZMETI ALFA</td><td>352,34 TL</td></tr></tbody></table></body></html>`;
  await setupInspector(page, "rule-teaching-counterparty.html", "text/html", html, (workspace) => {
    workspace.chart_accounts.accounts = [
      { normalized_account_code: "770.01.004", account_name: "Kırtasiye gideri", is_detail_account: true, is_active: true },
      { normalized_account_code: "770.01.009", account_name: "Diğer çeşitli giderler", is_detail_account: true, is_active: true },
      { normalized_account_code: "191.01.020", account_name: "İndirilecek KDV", is_detail_account: true, is_active: true },
      { normalized_account_code: "320.A01", account_name: "Pilot satıcı", is_detail_account: true, is_active: true },
    ];
    const result = workspace.documents[0].result as Record<string, unknown>;
    result.draft_status = "draft_ready";
    result.draft_lines = [
      { account_code: "770.01.009", description: "FISORA PILOT TEST HIZMETI ALFA", debit: "352.34", credit: "0.00", source_position: "1", source_text: SOURCE_TEXT },
      { account_code: "191.01.020", description: "KDV", debit: "70.47", credit: "0.00" },
      { account_code: "320.", description: "Pilot satıcı", debit: "0.00", credit: "422.81" },
    ];
  });

  await page.route("**/phase0/store/review-rule/preview", async (route) => {
    await route.fulfill({
      json: {
        rule_interpretation: {
          source: "accountant_confirmed",
          provider: "test",
          status: "ready",
          summary_tr: "Yalnız FISORA PILOT TEST HIZMETI ALFA satırlarında 770.01.004 kullan.",
          trigger_tr: "FISORA PILOT TEST HIZMETI ALFA",
          action_tr: "770.01.004 hesabını öner.",
          guardrail_tr: "Başka satırlara genelleme.",
          confidence: 100,
          reason_codes: [],
        },
      },
    });
  });

  await openInspectorDocument(page, ".html-document-viewer");

  const accountInputs = page.getByLabel("Hesap kodu");
  await accountInputs.nth(0).fill("770.01.004");
  await accountInputs.nth(2).fill("320.A01");

  const learningDetails = page.locator(".journal-learning-details");
  const summary = learningDetails.locator("summary");
  if (await summary.isVisible()) {
    await summary.click();
  }
  await page.getByPlaceholder("Bu fişte neyi neden değiştirdiniz? Benzer belgelerde nasıl uygulanmalı?")
    .fill("Yalnız pilot hizmet satırını 770.01.004 hesabına al.");

  const previewRequestPromise = page.waitForRequest((request) =>
    request.url().includes("/phase0/store/review-rule/preview") && request.method() === "POST",
  );
  await page.getByRole("button", { name: "Egitim notunu kaydet", exact: true }).click();
  const previewRequest = await previewRequestPromise;
  const payload = previewRequest.postDataJSON() as {
    decision?: { corrected_account_code?: string; draft_lines?: Array<{ account_code?: string }> };
  };

  expect(payload.decision?.corrected_account_code).toBe("770.01.004");
  expect(payload.decision?.draft_lines).toBeUndefined();

  const saveRequestPromise = page.waitForRequest((request) =>
    request.url().includes("/phase0/store/review-decision") && request.method() === "POST",
  );
  await page.getByRole("button", { name: "Kural olarak kaydet", exact: true }).click();
  const saveRequest = await saveRequestPromise;
  const savePayload = saveRequest.postDataJSON() as {
    decision?: { learning_confirmation?: string; draft_lines?: Array<{ account_code?: string }> };
  };
  expect(savePayload.decision?.learning_confirmation).toBe("save_rule");
  expect(savePayload.decision?.draft_lines).toBeUndefined();
});


test("learning prompt pauses review and opens the accountant rule preview flow", async ({ page }) => {
  const html = `<!doctype html><html><body><table id="lineTable"><tbody><tr><td>Sıra No</td><td>Malzeme/Hizmet</td><td>Tutar</td></tr><tr><td>1</td><td>${SOURCE_TEXT}</td><td>540,00 TL</td></tr></tbody></table></body></html>`;
  await setupInspector(page, "learning-prompt.html", "text/html", html, (workspace) => {
    workspace.chart_accounts.accounts = [
      { normalized_account_code: "770.01.004", account_name: "Kırtasiye gideri", is_detail_account: true, is_active: true },
    ];
    const result = workspace.documents[0].result as Record<string, unknown>;
    result.draft_status = "draft_ready";
    result.draft_lines = [
      {
        account_code: "770.01.004",
        description: SOURCE_TEXT,
        debit: "540.00",
        credit: "0.00",
        source_position: "1",
        source_text: SOURCE_TEXT,
      },
    ];
    result.rule_prompt = {
      show: true,
      status: "client_repeat_prompt",
      prompt_key: "repeat:kargo:770.01.004",
      default_scope: "client_narrow",
      message: "Aynı karar üç farklı faturada tekrarlandı.",
      client_consistent_decision_count: 3,
      office_distinct_client_count: 1,
      office_consistent_decision_count: 3,
      evidence_documents: [
        { document_ref: "doc-a", issue_date: "2026-09-01" },
        { document_ref: "doc-b", issue_date: "2026-09-05" },
        { document_ref: "doc-c", issue_date: "2026-09-10" },
      ],
      utility_precedent: {},
      suggested_note: "Kargo hizmetlerini 770.01.004 hesabında izle.",
    };
  });

  await page.route("**/phase0/store/review-rule/preview", async (route) => {
    await route.fulfill({
      json: {
        rule_interpretation: {
          source: "accountant_confirmed",
          provider: "test",
          status: "ready",
          summary_tr: "Kargo hizmetlerini 770.01.004 hesabında izle.",
          trigger_tr: "Kargo hizmeti",
          action_tr: "770.01.004 hesabını öner.",
          guardrail_tr: "Yalnız benzer kargo hizmetlerinde uygula.",
          confidence: 100,
          reason_codes: [],
        },
      },
    });
  });

  await openInspectorDocument(page, ".html-document-viewer");

  const prompt = page.getByRole("region", { name: "Fisora öğrenme önerisi" });
  await expect(prompt).toBeVisible();
  await expect(prompt).toContainText("Fisora bir tekrar fark etti");
  await expect(prompt).toContainText("3/3");
  await expect(prompt).toContainText("Kargo hizmetlerini 770.01.004 hesabında izle.");

  await prompt.getByRole("button", { name: "Kuralı incele", exact: true }).click();

  await expect(page.getByRole("region", { name: "Fisora karar notu yorumu" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Kural olarak kaydet", exact: true })).toBeEnabled();
});
