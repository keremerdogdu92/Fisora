import type { ReactNode } from "react";
import type { AiCapacityView } from "./portal-types";

export function DocumentProcessingWorkspace({
  aiCapacity,
  capacityError,
  capacityPending,
  children,
}: {
  aiCapacity?: AiCapacityView;
  capacityError: boolean;
  capacityPending: boolean;
  children: ReactNode;
}) {
  const documentCapacity = aiCapacity?.totals?.document_queries;
  const researchCapacity = aiCapacity?.totals?.internet_researches;
  const documentText = capacityValue(documentCapacity, capacityPending, typeof documentCapacity === "number");
  const researchText = capacityValue(researchCapacity, capacityPending, typeof researchCapacity === "number");
  const isLastKnown = aiCapacity?.estimate?.confidence === "cached" || (capacityError && Boolean(aiCapacity));

  return (
    <section className="document-processing-page">
      <div className="document-capacity-strip" aria-label="AI kapasitesi">
        <span className="document-capacity-title">AI kapasitesi</span>
        <span><strong>Belge ajanı</strong> {documentText}</span>
        <span><strong>Araştırma ajanı</strong> {researchText}</span>
        <small>{isLastKnown ? "son bilinen yaklaşık değer" : "güvenli yaklaşık değer"}</small>
      </div>
      {children}
    </section>
  );
}

function capacityValue(
  value: number | null | undefined,
  pending: boolean,
  hasCachedValue: boolean,
) {
  if (typeof value === "number") return `≈ ${value}`;
  if (pending && !hasCachedValue) return "hesaplanıyor";
  return "ölçülemiyor";
}
