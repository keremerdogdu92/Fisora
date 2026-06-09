export type PortalDashboardInput = {
  clients?: unknown[];
  documents?: unknown[];
  cancellationRequests?: unknown[];
};

export type PortalDashboardMetrics = {
  totalClients: number;
  uploadedClients: number;
  notUploadedClients: number;
  pendingReviewDocuments: number;
  exportReadyDocuments: number;
  openCancellationRequests: number;
};

export type PortalClientDashboardRow = {
  clientId: string;
  clientName: string;
  taxId: string;
  documentCount: number;
  pendingReviewCount: number;
  exportReadyCount: number;
  inProgressCount: number;
  cancellationCount: number;
  lastUploadedAt: string;
  status: string;
};

export type PortalChartRow = {
  key: string;
  label: string;
  count: number;
};

export type PortalDocumentSegment = "invoices" | "bank_statements" | "other_documents";

export type ClientCancellationViewModel<TDocument = unknown> = {
  selectedDocument: TDocument | null;
  requestDocument: TDocument | null;
  requestReason: string;
  canSubmitCancellation: boolean;
  emptyActionText: string;
};

export function buildClientCancellationViewModel<TDocument extends { id?: unknown } = unknown>(input?: {
  documents?: TDocument[];
  selectedDocumentId?: string;
  requestDocumentId?: string;
  cancellationReason?: string;
}): ClientCancellationViewModel<TDocument>;
export function buildPortalDashboard(input?: PortalDashboardInput): PortalDashboardMetrics;
export function clientDashboardRows(input?: PortalDashboardInput): PortalClientDashboardRow[];
export function clientUploadTracking(input?: PortalDashboardInput): PortalChartRow[];
export function documentIntakeDistribution(documents?: unknown[]): PortalChartRow[];
export function documentsForProcessing(input?: {
  documents?: unknown[];
  clientId?: string;
  segment?: PortalDocumentSegment;
}): unknown[];
export function statusFunnel(documents?: unknown[]): PortalChartRow[];
