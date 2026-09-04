// File: frontend/app/shared/components/document-viewers/pdf-document-viewer.tsx
// Summary: Renders PDF.js previews with shared zoom controls and source-text locator highlighting.
"use client";

import { useEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";
import type { DocumentSourceTarget } from "../../../portal-types";

type FitMode = "page" | "width" | "custom";
type PdfViewport = { width: number; height: number; transform: number[] };
type PdfTextItem = { str: string; width: number; height: number; transform: number[] };
type PdfPageHandle = {
  getViewport: (options: { scale: number }) => PdfViewport;
  getTextContent: () => Promise<{ items: unknown[] }>;
  render: (options: Record<string, unknown>) => { promise: Promise<void>; cancel: () => void };
};
type PdfDocumentHandle = {
  numPages: number;
  getPage: (pageNumber: number) => Promise<PdfPageHandle>;
  destroy: () => Promise<void> | void;
};
type PdfSourceHighlight = { page: number; left: number; top: number; width: number; height: number };
type PdfDocumentViewerProps = {
  fileName: string;
  src: string;
  sourceTarget?: DocumentSourceTarget | null;
  onClearSourceTarget?: () => void;
};

const MIN_ZOOM = 0.35;
const MAX_ZOOM = 3;

function clampZoom(value: number) {
  return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, value));
}
function normalizeSourceText(value: string) {
  return String(value || "")
    .normalize("NFKC")
    .toLocaleLowerCase("tr-TR")
    .replace(/\u00a0/g, " ")
    .replace(/\s+/g, " ")
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .trim();
}

function isPdfTextItem(value: unknown): value is PdfTextItem {
  if (!value || typeof value !== "object") return false;
  const item = value as Partial<PdfTextItem>;
  return typeof item.str === "string"
    && typeof item.width === "number"
    && Array.isArray(item.transform)
    && item.transform.length >= 6;
}

function multiplyTransforms(viewport: number[], item: number[]) {
  return [
    viewport[0] * item[0] + viewport[2] * item[1],
    viewport[1] * item[0] + viewport[3] * item[1],
    viewport[0] * item[2] + viewport[2] * item[3],
    viewport[1] * item[2] + viewport[3] * item[3],
    viewport[0] * item[4] + viewport[2] * item[5] + viewport[4],
    viewport[1] * item[4] + viewport[3] * item[5] + viewport[5],
  ];
}

function rectForTextItem(item: PdfTextItem, viewport: PdfViewport) {
  const matrix = multiplyTransforms(viewport.transform, item.transform);
  const height = Math.max(7, Math.hypot(matrix[2], matrix[3]), item.height || 0);
  return { left: matrix[4], top: matrix[5] - height, width: Math.max(6, item.width), height };
}
function unionRects(rects: { left: number; top: number; width: number; height: number }[]) {
  const left = Math.min(...rects.map((rect) => rect.left));
  const top = Math.min(...rects.map((rect) => rect.top));
  const right = Math.max(...rects.map((rect) => rect.left + rect.width));
  const bottom = Math.max(...rects.map((rect) => rect.top + rect.height));
  return { left, top, width: right - left, height: bottom - top };
}

function matchSourceOnPage(items: PdfTextItem[], target: DocumentSourceTarget, viewport: PdfViewport) {
  const needle = normalizeSourceText(target.text);
  if (!needle) return null;
  const targetTokens = new Set(needle.split(" ").filter((token) => token.length > 1));
  let best: { start: number; end: number; score: number } | null = null;
  for (let start = 0; start < items.length; start += 1) {
    let joined = "";
    for (let end = start; end < Math.min(items.length, start + 10); end += 1) {
      joined = normalizeSourceText(`${joined} ${items[end].str}`);
      if (!joined) continue;
      let score = 0;
      if (joined.includes(needle) || needle.includes(joined)) {
        score = 2 + Math.min(joined.length, needle.length) / Math.max(joined.length, needle.length);
      } else if (targetTokens.size) {
        const joinedTokens = new Set(joined.split(" "));
        const overlap = [...targetTokens].filter((token) => joinedTokens.has(token)).length;
        score = overlap / targetTokens.size;
      }
      if (score >= 0.55 && (!best || score > best.score)) best = { start, end, score };
    }
  }
  if (!best) return null;
  const rects = items.slice(best.start, best.end + 1).map((item) => rectForTextItem(item, viewport));
  return unionRects(rects);
}
export function PdfDocumentViewer({ fileName, src, sourceTarget, onClearSourceTarget }: PdfDocumentViewerProps) {
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
  const [sourceHighlight, setSourceHighlight] = useState<PdfSourceHighlight | null>(null);
  const [sourceMatchStatus, setSourceMatchStatus] = useState("");
  const [highlightStyle, setHighlightStyle] = useState<CSSProperties | null>(null);

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
        pdfjs.GlobalWorkerOptions.workerSrc = new URL("pdfjs-dist/build/pdf.worker.min.mjs", import.meta.url).toString();
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
    if (!pdfDocument || !sourceTarget) {
      setSourceHighlight(null);
      setSourceMatchStatus("");
      return undefined;
    }
    let active = true;
    setSourceMatchStatus("Kaynak aranıyor…");
    setFitMode("custom");
    setCustomZoom(1);
    void (async () => {
      for (let page = 1; page <= pdfDocument.numPages; page += 1) {
        const pdfPage = await pdfDocument.getPage(page);
        const textContent = await pdfPage.getTextContent();
        if (!active) return;
        const items = textContent.items.filter(isPdfTextItem);
        const viewport = pdfPage.getViewport({ scale: 1 });
        const match = matchSourceOnPage(items, sourceTarget, viewport);
        if (!match) continue;
        setSourceHighlight({ page, ...match });
        setPageNumber(page);
        setSourceMatchStatus(`Kaynak bulundu · sayfa ${page}`);
        return;
      }
      if (active) {
        setSourceHighlight(null);
        setSourceMatchStatus("Kaynak metin PDF içinde bulunamadı.");
      }
    })().catch((scanError) => {
      if (!active) return;
      setSourceHighlight(null);
      setSourceMatchStatus(scanError instanceof Error ? scanError.message : "Kaynak eşleme yapılamadı.");
    });
    return () => { active = false; };
  }, [pdfDocument, sourceTarget?.key]);

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
        const availableWidth = Math.max(stageSize.width - 24, 120);
        const availableHeight = Math.max(stageSize.height - 24, 160);
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
  useEffect(() => {
    if (!sourceHighlight || sourceHighlight.page !== pageNumber) {
      setHighlightStyle(null);
      return undefined;
    }
    const frame = window.requestAnimationFrame(() => {
      const canvas = canvasRef.current;
      const stage = stageRef.current;
      if (!canvas || !stage) return;
      const left = canvas.offsetLeft + sourceHighlight.left * effectiveScale;
      const top = canvas.offsetTop + sourceHighlight.top * effectiveScale;
      const width = Math.max(10, sourceHighlight.width * effectiveScale);
      const height = Math.max(10, sourceHighlight.height * effectiveScale);
      setHighlightStyle({ left, top, width, height });
      stage.scrollTo({
        left: Math.max(0, left + width / 2 - stage.clientWidth / 2),
        top: Math.max(0, top + height / 2 - stage.clientHeight / 2),
        behavior: "smooth",
      });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [effectiveScale, pageNumber, sourceHighlight, stageSize.height, stageSize.width]);

  function applyCustomZoom(nextScale: number) {
    const scale = clampZoom(nextScale);
    setFitMode("custom");
    setCustomZoom(scale);
  }

  function clearSourceFocus() {
    setSourceHighlight(null);
    setSourceMatchStatus("");
    setHighlightStyle(null);
    setFitMode("page");
    onClearSourceTarget?.();
  }

  const pageCount = pdfDocument?.numPages ?? 0;
  return (
    <section className="pdf-document-viewer" aria-label={`${fileName} PDF görüntüleyici`}>
      <div className="pdf-viewer-toolbar document-viewer-toolbar">
        <div className="pdf-viewer-page-controls">
          <button disabled={pageNumber <= 1} onClick={() => setPageNumber((value) => Math.max(1, value - 1))} type="button">‹</button>
          <span>{pageCount ? `${pageNumber} / ${pageCount}` : "- / -"}</span>
          <button disabled={!pageCount || pageNumber >= pageCount} onClick={() => setPageNumber((value) => Math.min(pageCount, value + 1))} type="button">›</button>
        </div>
        <div className="pdf-viewer-zoom-controls">
          <button className={fitMode === "page" ? "active" : ""} onClick={() => setFitMode("page")} type="button">Sığdır</button>
          <button className={fitMode === "width" ? "active" : ""} onClick={() => setFitMode("width")} type="button">Genişlik</button>
          <button className={fitMode === "custom" && Math.abs(effectiveScale - 1) < 0.01 ? "active" : ""} onClick={() => applyCustomZoom(1)} type="button">%100</button>
          <button onClick={() => applyCustomZoom(effectiveScale - 0.1)} type="button" aria-label="Uzaklaştır">−</button>
          <span>{Math.round(effectiveScale * 100)}%</span>
          <button onClick={() => applyCustomZoom(effectiveScale + 0.1)} type="button" aria-label="Yakınlaştır">+</button>
        </div>
        {sourceTarget ? (
          <div className="document-source-focus-controls">
            <span>{sourceMatchStatus || "Kaynak aranıyor…"}</span>
            <button onClick={clearSourceFocus} type="button">Tam belgeye dön</button>
          </div>
        ) : null}
      </div>
      <div className="pdf-viewer-stage" ref={stageRef}>
        {error ? (
          <div className="preview-error-panel" role="alert">
            <strong>PDF önizleme açılamadı.</strong>
            <p>{error}</p>
          </div>
        ) : null}
        {!error ? <canvas aria-label={`${fileName} sayfa ${pageNumber}`} ref={canvasRef} /> : null}
        {highlightStyle && !error ? <div className="pdf-source-highlight" aria-label="Kaynak eşleşmesi" style={highlightStyle} /> : null}
        {status && !error ? <span className="pdf-viewer-status" role="status">{status}</span> : null}
      </div>
    </section>
  );
}
