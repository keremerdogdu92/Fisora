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
  commercial_readiness: {
    primary_offer: "accountant_reviewed_controlled_export",
    export_positioning: "controlled_csv_and_manifest_candidate",
    zirve_import_claim: "unverified_until_field_test",
  },
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
    {
      user_id: "pilot-user",
      display_name: "Pilot User",
      role: "client_user",
    },
  ],
  uploaded_documents: [],
  processing_jobs: [],
  export_packages: [
    {
      id: "export-ready-1",
      created_at: "2026-06-10T10:00:00Z",
      package: {
        document_refs: ["invoice-ready-1"],
        entry_count: 1,
        created_at: "2026-06-10T10:00:00Z",
      },
    },
  ],
  documents: [
    {
      document_ref: "invoice-ready-1",
      document_type: "purchase_invoice",
      export_status: "review_required",
      created_at: "2026-06-10T10:00:00Z",
      result: {
        file_name: "invoice-ready.pdf",
        invoice_type: "purchase_invoice",
        export_status: "review_required",
        issue_date: "2026-06-10",
        payable_total: "1200.00",
        vat_rates: ["20"],
        provider_hint: "Pilot Vendor",
        product_line_hint: "Danismanlik",
        product_category: "service",
        business_relevance_relation: "Ofis gideri",
        business_relevance_account_treatment: "770",
        business_relevance_requires_review: false,
        ai_classification_reason: "Pilot fatura otomatik siniflandi.",
        ai_classification_provider: "groq",
        ai_suggested_account_code: "770.01",
        selected_expense_account: "770.01",
        selected_vat_account: "191.01",
        selected_supplier_account: "320.01",
        counterparty_match_confidence: 90,
        deterministic_checks: ["balanced"],
        export_gate_reason: "Kontrol tamamlandi.",
        draft_lines: [
          { account_code: "770.01", description: "Danismanlik", debit: "1000.00", credit: "0.00" },
          { account_code: "191.01", description: "KDV", debit: "200.00", credit: "0.00" },
          { account_code: "320.01", description: "Tedarikci", debit: "0.00", credit: "1200.00" },
        ],
      },
    },
    {
      document_ref: "bank-doc-1",
      document_type: "bank_statement",
      export_status: "review_required",
      created_at: "2026-06-11T10:00:00Z",
      result: {
        file_name: "bank-haziran.csv",
        invoice_type: "bank_statement",
        intake_category: "bank_statement",
        export_status: "review_required",
        issue_date: "2026-06-11",
        payable_total: "1250.00",
        provider_hint: "Pilot Bank",
        product_line_hint: "Banka hareketi",
        product_category: "bank",
        business_relevance_relation: "Banka hareketi",
        business_relevance_account_treatment: "102",
        business_relevance_requires_review: true,
        ai_classification_reason: "Banka satirlari kontrol bekliyor.",
        ai_classification_provider: "groq",
        selected_expense_account: "102.01",
        selected_vat_account: "-",
        selected_supplier_account: "320.10",
        counterparty_match_confidence: 70,
        deterministic_checks: ["statement_parsed"],
        export_gate_reason: "Musteri satirlari musavir onayi bekliyor.",
        statement_lines: [
          {
            line_no: 1,
            transaction_date: "2026-06-11",
            description: "Pilot tahsilat",
            amount: "1250.00",
            direction: "in",
            balance_after: "1250.00",
            counterparty_name: "Pilot Buyer",
            tax_id: "2222222222",
            iban: "TR000000000000000000000000",
            suggested_account_code: "120.01",
            transaction_type: "counterparty_payment",
            confidence: 82,
            risk_flags: [],
            review_reason: "ai_suggestion_available",
          },
          {
            line_no: 2,
            transaction_date: "2026-06-12",
            description: "Pilot vergi odemesi",
            amount: "250.00",
            direction: "out",
            balance_after: "1000.00",
            counterparty_name: "Vergi Dairesi",
            tax_id: "",
            iban: "",
            suggested_account_code: "360.01",
            transaction_type: "tax_payment",
            confidence: 76,
            risk_flags: ["tax_payment"],
            review_reason: "tax_payment_review",
          },
        ],
        statement_entries: [
          {
            statement_line_no: 1,
            statement_fingerprint: "bank-doc-1-1",
            source_document_ref: "bank-doc-1",
            risk_flags: [],
            lines: [
              { account_code: "102.01", description: "Banka", debit: "1250.00", credit: "0.00" },
              { account_code: "120.01", description: "Cari", debit: "0.00", credit: "1250.00" },
            ],
          },
        ],
        statement_ai_suggestions: [],
        statement_ai_summary: "",
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
  await page.route("**/phase0/statement/ai-suggestions", async (route) => {
    await route.fulfill({
      json: {
        ai_used_count: 1,
        skipped_count: 1,
        suggestions: [
          {
            line_no: 1,
            transaction_type: "counterparty_payment",
            suggested_account_code: "120.01",
            confidence: 88,
            reason: "Pilot alici tahsilati ile eslesti.",
            evidence: ["iban", "description"],
            risk_flags: [],
            export_allowed: true,
          },
        ],
      },
    });
  });
  await page.route("**/phase0/store/review-decision", async (route) => {
    await route.fulfill({ json: { status: "ok" } });
  });
}

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.clear();
    window.sessionStorage.clear();
  });
  await setupPilotRoutes(page);
});

test("operations screen separates restricted real-data pilot readiness from production readiness", async ({ page }) => {
  await page.goto("/portal/operasyon");

  await expect(page.getByText(/Ger.ek veri/).first()).toBeVisible();
  await expect(page.getByText(/K.s.tl. canl. pilot haz.r/)).toBeVisible();
  await expect(page.getByText("restricted_network")).toBeVisible();
  await expect(page.getByText("Production", { exact: true })).toBeVisible();
  await expect(page.locator("body")).not.toContainText(/[ÃƒÃ„Ã…]/);
});

test("landing role gateway enters accountant portal and document selection uses backend workspace data", async ({ page }) => {
  await page.goto("/");
  await page.locator(".role-card").first().click();
  await page.locator(".landing-login .primary").click();

  await expect(page).toHaveURL(/\/portal\/musavir$/);
  await page.goto("/portal/belgeler");

  await expect(page.getByText("Pilot Test AS").first()).toBeVisible();
  await page.getByRole("button", { name: /^Aç$/ }).first().click();
  await expect(page.getByLabel("Belge işleme özeti")).toContainText("invoice-ready.pdf");
  await expect(page.getByText("invoice-ready.pdf").first()).toBeVisible();
  await expect(page.getByText(/AI ajan destekli|Fiş taslağı|Danismanlik/).first()).toBeVisible();
  await expect(page.getByText("Belge seçilmedi")).toHaveCount(0);
});

test("accountant can request AI draft and approve a bank statement line", async ({ page }) => {
  await page.goto("/portal/belgeler");

  await page.getByRole("tab", { name: /Banka/ }).click();
  await page.locator(".toolbar-controls select").nth(1).selectOption("bank-doc-1");
  await expect(page.getByText("bank-haziran.csv").first()).toBeVisible();

  await page.getByRole("button", { name: /AI .* al/ }).click();
  await expect(page.getByText("Pilot alici tahsilati ile eslesti.")).toBeVisible();

  await page.getByRole("button", { name: /Sat.r. onayla/ }).click();
  await expect(page.getByText(/bank-haziran.csv \/ 1\. satir.*backend'e kaydedildi/)).toBeVisible();
});

test("export basket can be packaged from deterministic workspace data", async ({ page }) => {
  await page.goto("/portal/cikti");

  await expect(page.getByText("Pilot Test AS").first()).toBeVisible();
  await expect(page.getByText(/Haz.r/).first()).toBeVisible();

  await page.getByRole("button", { name: /haz.rla/i }).click();
  await expect(page.getByText(/toplu paket hazir gorunuyor/)).toBeVisible();
  await expect(page.getByText(/Paketlendi/)).toBeVisible();
});
