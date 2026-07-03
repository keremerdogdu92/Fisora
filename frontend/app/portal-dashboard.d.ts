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

export type AgentSummaryView = {
  key: string;
  name: string;
  statusLabel: string;
  touchedCount: number;
  capacityLabel: string;
  unchangedApprovalRateLabel: string;
  correctionCount: number;
  learningLabel: string;
};

export type AgentLearningInsightView = {
  id: string;
  documentLabel: string;
  stageLabel: string;
  summary: string;
  confidenceLabel: string;
};

export type DashboardDurationMetrics = {
  averageDocumentTimeLabel: string;
  uploadToDecisionTimeLabel: string;
  clientAverageCompletionTimeLabel: string;
};

export type PriorityWorkItem = {
  id: string;
  kind: string;
  label: string;
  title: string;
  detail: string;
  statusLabel: string;
};

export type PortalDashboardViewModels = {
  dashboardMetrics: PortalDashboardMetrics;
  dashboardClientRows: PortalClientDashboardRow[];
  intakeDistribution: PortalChartRow[];
  funnelRows: PortalChartRow[];
  uploadTrackingRows: PortalChartRow[];
  agentSummaries: AgentSummaryView[];
  learningInsights: AgentLearningInsightView[];
  durationMetrics: DashboardDurationMetrics;
  priorityItems: PriorityWorkItem[];
};

export type PortalDocumentSegment = "sales_invoices" | "purchase_invoices" | "invoices" | "bank_statements" | "other_documents";

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
export function buildAgentSummaries(input?: { documents?: unknown[]; aiCapacity?: unknown }): AgentSummaryView[];
export function buildAgentLearningInsights(input?: { documents?: unknown[]; limit?: number }): AgentLearningInsightView[];
export function buildDashboardDurationMetrics(input?: { documents?: unknown[] }): DashboardDurationMetrics;
export function buildPortalDashboard(input?: PortalDashboardInput): PortalDashboardMetrics;
export function buildPortalDashboardViewModels(input?: { data?: PortalDashboardInput; aiCapacity?: unknown }): PortalDashboardViewModels;
export function clientDashboardRows(input?: PortalDashboardInput): PortalClientDashboardRow[];
export function clientUploadTracking(input?: PortalDashboardInput): PortalChartRow[];
export function documentIntakeDistribution(documents?: unknown[]): PortalChartRow[];
export function documentsForProcessing(input?: {
  documents?: unknown[];
  clientId?: string;
  segment?: PortalDocumentSegment;
}): unknown[];
export function statusFunnel(documents?: unknown[]): PortalChartRow[];
