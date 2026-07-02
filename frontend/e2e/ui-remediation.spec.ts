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
  await page.route("**/phase0/store/research/benchmark/runs", async (route) => {
    await route.fulfill({ json: { runs: [] } });
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

test("topbar notification and help actions open visible panels", async ({ page }) => {
  await setupPilotRoutes(page);
  await page.goto("/portal/musavir");

  await page.getByRole("button", { name: /Bildirimler/ }).click();
  await expect(page.getByRole("dialog", { name: /Bildirimler/ })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog", { name: /Bildirimler/ })).toHaveCount(0);

  await page.getByRole("button", { name: /Yardım/ }).click();
  await expect(page.getByRole("dialog", { name: /Yardım/ })).toBeVisible();
});

test("mobile portal starts with content visible and opens menu as drawer", async ({ page }) => {
  await setupPilotRoutes(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/portal/belgeler");

  await expect(page.getByLabel("Müşavir menüsü")).toHaveAttribute("data-mobile-open", "false");
  await expect(page.getByLabel("Belge işleme özeti")).toBeVisible();

  await page.getByRole("button", { name: /Menüyü aç/ }).click();
  await expect(page.getByLabel("Müşavir menüsü")).toHaveAttribute("data-mobile-open", "true");

  await page.keyboard.press("Escape");
  await expect(page.getByLabel("Müşavir menüsü")).toHaveAttribute("data-mobile-open", "false");
});

test("client management shows onboarding steps and readable blocked actions", async ({ page }) => {
  await setupPilotRoutes(page);
  await page.goto("/portal/mukellefler");
  const tabs = page.locator(".client-management-tabs button");
  await expect(tabs.nth(0)).toHaveAttribute("aria-selected", "true");
  await expect(page.locator(".tax-certificate-preview")).toBeVisible();
  await expect(page.getByLabel("Vergi levhası alanları")).toBeVisible();

  await expect(page.locator(".client-onboarding-steps")).toBeVisible();
  await expect(page.locator(".client-step")).toHaveCount(3);
  await expect(page.locator(".client-step").nth(0)).toContainText(/Vergi levhas/i);
  await expect(page.locator(".client-step").nth(1)).toContainText(/Hesap plan/i);
  await expect(page.locator(".client-step").nth(2)).toContainText(/Portal eri/i);
  await expect(page.locator(".file-drop-control").first()).toBeVisible();
  await tabs.nth(1).click();
  await expect(page.locator(".client-existing-operations")).toBeVisible();
  await expect(page.getByRole("button", { name: /Seçili belgeleri sil|SeÃ§ili belgeleri sil/i })).toBeDisabled();
  await expect(page.locator(".client-row").first().locator("strong")).toHaveText("Pilot Test AS");
  await expect(page.locator(".client-row").first().locator("span")).toContainText(/Kontrol|Bekliyor/i);
  await expect(page.locator(".blocked-reason").first()).toContainText(/nce|Önce|Ã–nce/i);
});

test("Bilgi Havuzu uses Turkish fallback copy for English-only profiles", async ({ page }) => {
  await setupPilotRoutes(page);
  await page.goto("/portal/bilgi-havuzu");

  await expect(page.getByText(/Kaynak .*Turkceye|Kaynak .*Türkçeye|Kaynak .*TÃ¼rkÃ§eye/i)).toBeVisible();
  await expect(page.locator("body")).not.toContainText("Failed to fetch");
});
test("accountant opens selected client portal in a delegated tab without return controls", async ({ page }) => {
  await page.context().route("**/phase0/store/system/readiness", async (route) => {
    await route.fulfill({ json: readyForRealDataPayload });
  });
  await page.context().route("**/phase0/store/clients", async (route) => {
    await route.fulfill({ json: { clients: [pilotClient] } });
  });
  await page.context().route("**/phase0/store/workspace/**", async (route) => {
    await route.fulfill({ json: pilotWorkspace });
  });
  await page.context().route("**/phase0/store/auth/delegated-client-session", async (route) => {
    await route.fulfill({
      json: {
        session_token: "delegated-session-1",
        delegated_by: "mali-musavir",
        delegated_client_id: "pilot-client",
        session: {
          user_id: "pilot-user",
          expires_at: "2026-07-02T22:00:00+00:00",
          delegated_by: "mali-musavir",
          delegated_client_id: "pilot-client",
        },
      },
    });
  });

  await page.goto("/portal/mukellefler");
  await page.locator(".client-management-tabs button").nth(1).click();

  const popupPromise = page.waitForEvent("popup");
  await page.getByRole("button", { name: /Mükellef ekranına git|MÃ¼kellef ekranÄ±na git|MÃƒÂ¼kellef ekran/i }).click();
  const popup = await popupPromise;
  await popup.waitForLoadState("domcontentloaded");

  await expect(popup).toHaveURL(/\/portal\/mukellef/);
  await expect(popup.getByText("Pilot Test AS").first()).toBeVisible();
  await expect(popup.getByText(/Müşavir vekaletinde|MÃ¼ÅŸavir vekaletinde|MÃƒÂ¼ÅŸavir vekaletinde|Musavir vekaletinde/i)).toBeVisible();
  await expect(popup.getByRole("button", { name: /Müşavir ekranına dön|MÃ¼ÅŸavir ekranÄ±na dÃ¶n|sekme kapat|kapat/i })).toHaveCount(0);
});
