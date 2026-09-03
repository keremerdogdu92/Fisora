// File: frontend/app/shared/components/document-viewers/pdf-document-viewer.tsx
// Summary: Renders authenticated PDF object URLs with PDF.js page navigation, responsive fit modes, and zoom controls.
"use client";

import { useEffect, useRef, useState } from "react";

type FitMode = "page" | "width" | "custom";
type PdfDocumentHandle = {
  numPages: number;
  getPage: (pageNumber: number) => Promise<PdfPageHandle>;
  destroy: () => Promise<void> | void;
};
type PdfPageHandle = {
  getViewport: (options: { scale: number }) => { width: number; height: number };
  render: (options: Record<string, unknown>) => { promise: Promise<void>; cancel: () => void };
};

const MIN_ZOOM = 0.35;
const MAX_ZOOM = 3;

function clampZoom(value: number) {
  return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, value));
}
export function PdfDocumentViewer({ fileName, src }: { fileName: string; src: string }) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const stageRef = useRef<HTMLDivElement | null>(null);
  const [pdfDocument, setPdfDocument] = useState<PdfDocumentHandle | null>(null);
  const [pageNumber, setPageNumber] = useState(1);
  const [fitMode, setFitMode] = useState<FitMode>("page");
  const [customZoom, setCustomZoom] = useState(1);
  const [effectiveScale, setEffectiveScale] = useState(1);
  const [stageSize, setStageSize] = useState({ width: 0, height: 0 });
  const [status, setStatus] = useState("PDF yükleniyor.");
  const [error, setError] = useState("");

  useEffect(() => {
    const stage = stageRef.current;
    if (!stage) return;
    const updateSize = () => setStageSize({ width: stage.clientWidth, height: stage.clientHeight });
    updateSize();
    const observer = new ResizeObserver(updateSize);
    observer.observe(stage);
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    let active = true;
    let loadedDocument: PdfDocumentHandle | null = null;
    setPdfDocument(null);
    setPageNumber(1);
    setError("");
    setStatus("PDF yükleniyor.");

    void (async () => {
      try {
        const pdfjs = await import("pdfjs-dist");
        pdfjs.GlobalWorkerOptions.workerSrc = new URL(
          "pdfjs-dist/build/pdf.worker.min.mjs",
          import.meta.url,
        ).toString();
        const loadingTask = pdfjs.getDocument({ url: src });
        loadedDocument = await loadingTask.promise as unknown as PdfDocumentHandle;
        if (!active) {
          await loadedDocument.destroy();
          return;
        }
        setPdfDocument(loadedDocument);
        setStatus("");
      } catch (loadError) {
        if (active) setError(loadError instanceof Error ? loadError.message : "PDF açılamadı.");
      }
    })();
    return () => {
      active = false;
      if (loadedDocument) void loadedDocument.destroy();
    };
  }, [src]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!pdfDocument || !canvas || !stageSize.width) return;
    let active = true;
    let renderTask: { promise: Promise<void>; cancel: () => void } | null = null;

    void (async () => {
      try {
        const page = await pdfDocument.getPage(pageNumber);
        if (!active) return;
        const baseViewport = page.getViewport({ scale: 1 });
        const availableWidth = Math.max(stageSize.width - 28, 120);
        const availableHeight = Math.max(stageSize.height - 28, 160);
        const nextScale = fitMode === "width"
          ? availableWidth / baseViewport.width
          : fitMode === "page"
            ? Math.min(availableWidth / baseViewport.width, availableHeight / baseViewport.height)
            : customZoom;
        const scale = clampZoom(nextScale);
        const viewport = page.getViewport({ scale });
        const outputScale = Math.max(window.devicePixelRatio || 1, 1);
        const context = canvas.getContext("2d");
        if (!context) throw new Error("PDF canvas hazırlanamadı.");
        canvas.width = Math.floor(viewport.width * outputScale);
        canvas.height = Math.floor(viewport.height * outputScale);
        canvas.style.width = `${Math.floor(viewport.width)}px`;
        canvas.style.height = `${Math.floor(viewport.height)}px`;
        setEffectiveScale(scale);
        setStatus("PDF sayfası çiziliyor.");
        renderTask = page.render({
          canvasContext: context,
          transform: outputScale === 1 ? undefined : [outputScale, 0, 0, outputScale, 0, 0],
          viewport,
        });
        await renderTask.promise;
        if (active) {
          setStatus("");
          setError("");
        }
      } catch (renderError) {
        if (!active || (renderError instanceof Error && renderError.name === "RenderingCancelledException")) return;
        setError(renderError instanceof Error ? renderError.message : "PDF sayfası çizilemedi.");
      }
    })();
    return () => {
      active = false;
      renderTask?.cancel();
    };
  }, [customZoom, fitMode, pageNumber, pdfDocument, stageSize.height, stageSize.width]);

  function applyCustomZoom(nextScale: number) {
    const scale = clampZoom(nextScale);
    setFitMode("custom");
    setCustomZoom(scale);
  }

  const pageCount = pdfDocument?.numPages ?? 0;
  return (
    <section className="pdf-document-viewer" aria-label={`${fileName} PDF görüntüleyici`}>
      <div className="pdf-viewer-toolbar">
        <div className="pdf-viewer-page-controls">
          <button disabled={pageNumber <= 1} onClick={() => setPageNumber((value) => Math.max(1, value - 1))} type="button">‹</button>
          <span>{pageCount ? `${pageNumber} / ${pageCount}` : "- / -"}</span>
          <button disabled={!pageCount || pageNumber >= pageCount} onClick={() => setPageNumber((value) => Math.min(pageCount, value + 1))} type="button">›</button>
        </div>
        <div className="pdf-viewer-zoom-controls">
          <button className={fitMode === "page" ? "active" : ""} onClick={() => setFitMode("page")} type="button">Sayfaya sığdır</button>
          <button className={fitMode === "width" ? "active" : ""} onClick={() => setFitMode("width")} type="button">Genişliğe sığdır</button>
          <button onClick={() => applyCustomZoom(effectiveScale - 0.1)} type="button" aria-label="Uzaklaştır">−</button>
          <span>{Math.round(effectiveScale * 100)}%</span>
          <button onClick={() => applyCustomZoom(effectiveScale + 0.1)} type="button" aria-label="Yakınlaştır">+</button>
        </div>
      </div>
      <div className="pdf-viewer-stage" ref={stageRef}>
        {error ? (
          <div className="preview-error-panel" role="alert">
            <strong>PDF önizleme açılamadı.</strong>
            <p>{error}</p>
          </div>
        ) : null}
        {!error ? <canvas aria-label={`${fileName} sayfa ${pageNumber}`} ref={canvasRef} /> : null}
        {status && !error ? <span className="pdf-viewer-status" role="status">{status}</span> : null}
      </div>
    </section>
  );
}
