const DEFAULT_INTAKE_CATEGORY = "purchase_invoice";

const INTAKE_CONFIG = {
  sales_invoice: {
    id: "sales_invoice",
    label: "Satış faturaları",
    documentType: "invoice",
    status: "queued",
    accept: ".pdf,.xml,.zip",
    provider: "Satış faturası yükleme",
    productLine: "Satış faturası otomatik kuyruğa alındı.",
    productCategory: "Satış faturası",
    previewText: "Satış faturası yüklendi; belge içeriğiyle yön kontrolü yapılacak.",
    aiReason: "Satış/gelir yönü mükellef seçimiyle geldi, worker sonucu bekleniyor.",
    deterministicSummary: "Satış faturası parser kuyruğu bekleniyor.",
    exportGateReason: "İşleme tamamlanmadan çıktıya eklenemez.",
  },
  purchase_invoice: {
    id: "purchase_invoice",
    label: "Alış faturaları",
    documentType: "invoice",
    status: "queued",
    accept: ".pdf,.xml,.zip",
    provider: "Alış faturası yükleme",
    productLine: "Alış faturası otomatik kuyruğa alındı.",
    productCategory: "Alış faturası",
    previewText: "Alış faturası yüklendi; belge içeriğiyle yön kontrolü yapılacak.",
    aiReason: "Alış/gider yönü mükellef seçimiyle geldi, worker sonucu bekleniyor.",
    deterministicSummary: "Alış faturası parser kuyruğu bekleniyor.",
    exportGateReason: "İşleme tamamlanmadan çıktıya eklenemez.",
  },
  bank_statement: {
    id: "bank_statement",
    label: "Banka ekstreleri",
    documentType: "bank_statement",
    status: "queued",
    accept: ".csv,.xls,.xlsx,.pdf",
    provider: "Banka ekstresi yükleme",
    productLine: "Ekstre otomatik kuyruğa alındı.",
    productCategory: "Banka ekstresi",
    previewText: "Banka ekstresi yüklendi; satır parse sonucu bekleniyor.",
    aiReason: "Ekstre satırları deterministik kurallarla hazırlanacak.",
    deterministicSummary: "Banka ekstresi parser kuyruğu bekleniyor.",
    exportGateReason: "Ekstre işleme tamamlanmadan çıktıya eklenemez.",
  },
  special_document: {
    id: "special_document",
    label: "Özel belgeler",
    documentType: "special_document",
    status: "review_required",
    accept: ".pdf,.xml,.csv,.xlsx,.xls,.zip",
    provider: "Özel belge yükleme",
    productLine: "Özel belge müşavir kontrolüne bırakıldı.",
    productCategory: "Özel belge",
    previewText: "Özel belge yüklendi; otomatik ayrıştırma yapılmadan müşavir kontrolüne düşer.",
    aiReason: "Bu kategori ilk adımda manuel müşavir kontrolüne ayrıldı.",
    deterministicSummary: "Manuel kontrol akışı seçildi.",
    exportGateReason: "Müşavir kontrolü olmadan çıktıya eklenemez.",
  },
};

const INTAKE_TABS = Object.freeze([
  INTAKE_CONFIG.sales_invoice,
  INTAKE_CONFIG.purchase_invoice,
  INTAKE_CONFIG.bank_statement,
  INTAKE_CONFIG.special_document,
]);

function normalizeIntakeCategory(value) {
  return Object.prototype.hasOwnProperty.call(INTAKE_CONFIG, value) ? value : DEFAULT_INTAKE_CATEGORY;
}

function documentTypeForIntakeCategory(value) {
  return INTAKE_CONFIG[normalizeIntakeCategory(value)].documentType;
}

function labelForIntakeCategory(value) {
  return INTAKE_CONFIG[normalizeIntakeCategory(value)].label;
}

function acceptForIntakeCategory(value) {
  return INTAKE_CONFIG[normalizeIntakeCategory(value)].accept;
}

function buildUploadIntakeMetadata(value) {
  const config = INTAKE_CONFIG[normalizeIntakeCategory(value)];
  return {
    intakeCategory: config.id,
    label: config.label,
    documentType: config.documentType,
    status: config.status,
    accept: config.accept,
    provider: config.provider,
    productLine: config.productLine,
    productCategory: config.productCategory,
    previewText: config.previewText,
    aiReason: config.aiReason,
    deterministicSummary: config.deterministicSummary,
    exportGateReason: config.exportGateReason,
  };
}

module.exports = {
  DEFAULT_INTAKE_CATEGORY,
  INTAKE_TABS,
  acceptForIntakeCategory,
  buildUploadIntakeMetadata,
  documentTypeForIntakeCategory,
  labelForIntakeCategory,
  normalizeIntakeCategory,
};
