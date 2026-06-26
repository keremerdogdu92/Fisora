import { expect, test, type Page } from "@playwright/test";

const readyForRealDataPayload = {
  pilot_sellable: true,
  production_ready: false,
  real_data_pilot: {
    allowed: true,
    status: "ready_for_restricted_live_pilot",
    access_mode: "restricted_network",
    blocking: [],
  },
  pilot_blocking: [],
  warnings: ["zirve_field_test_pending"],
  auth: { auth_mode: "session_required" },
  store_backend: "postgres",
  ai_provider: "groq",
};

const pilotClient = {
  client_id: "pilot-client",
  profile: {
    client_id: "pilot-client",
    title: "Pilot Test AS",
    tax_id: "1111111111",
  },
};

const pilotWorkspace = {
  client: pilotClient,
  portal_users: [
    { user_id: "pilot-user", display_name: "Pilot User", role: "client_user" },
  ],
  uploaded_documents: [],
  processing_jobs: [],
  export_packages: [],
  documents: [
    {
      document_ref: "invoice-ready-1",
      document_type: "purchase_invoice",
      export_status: "review_required",
      created_at: "2026-06-10T10:00:00Z",
      result: {
        file_name: "invoice-ready.pdf",
        invoice_type: "purchase_invoice",
        intake_category: "purchase_invoice",
        export_status: "review_required",
        issue_date: "2026-06-10",
        payable_total: "1200.00",
        provider_hint: "Pilot Vendor",
        product_line_hint: "Danismanlik",
        ai_classification_reason: "Pilot fatura otomatik siniflandi.",
        draft_lines: [
          { account_code: "770.01", description: "Danismanlik", debit: "1000.00", credit: "0.00" },
          { account_code: "191.01", description: "KDV", debit: "200.00", credit: "0.00" },
          { account_code: "320.01", description: "Tedarikci", debit: "0.00", credit: "1200.00" },
        ],
        review_reason_codes: ["mixed_vat_manual_review", "counterparty_title_token_overlap"],
      },
    },
  ],
};

async function setupPilotRoutes(page: Page) {
  await page.route("**/phase0/store/system/readiness", async (route) => {
    await route.fulfill({ json: readyForRealDataPayload });
  });
  await page.route("**/phase0/store/clients", async (route) => {
    await route.fulfill({ json: { clients: [pilotClient] } });
  });
  await page.route("**/phase0/store/workspace/**", async (route) => {
    await route.fulfill({ json: pilotWorkspace });
  });
  await page.route("**/phase0/store/research/profiles**", async (route) => {
    await route.fulfill({
      json: {
        profiles: [
          {
            kind: "brand",
            key: "pilot-vendor",
            title: "Pilot Vendor",
            summary: "English supplier summary.",
            confidence: 82,
          },
        ],
      },
    });
  });
}

test("documents route has no horizontal overflow on desktop and mobile", async ({ page }) => {
  await setupPilotRoutes(page);

  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/portal/belgeler");
  await expect(page.getByText("Pilot Test AS").first()).toBeVisible();
  const desktopOverflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(desktopOverflow).toBeLessThanOrEqual(0);

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/portal/belgeler");
  const mobileOverflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(mobileOverflow).toBeLessThanOrEqual(0);
});

test("workspace backend failure does not stay as loading copy", async ({ page }) => {
  await page.route("**/phase0/store/clients", async (route) => {
    await route.fulfill({ status: 404, body: "not found" });
  });
  await page.route("**/phase0/store/system/readiness", async (route) => {
    await route.fulfill({ json: readyForRealDataPayload });
  });

  await page.goto("/portal/musavir");

  await expect(page.getByText(/Backend okunamadı|Yerel çalışma verisi|Çalışma alanı boş/).first()).toBeVisible();
  await expect(page.getByText("Çalışma alanı yükleniyor")).toHaveCount(0);
});
