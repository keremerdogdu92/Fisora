// File: frontend/app/shared/components/document-viewers/pdf-document-viewer.tsx
// Summary: Renders PDF.js previews with pointer-centered magnification, 100% lens suppression, shared zoom controls, and source-text highlighting.
"use client";

import { useEffect, useRef, useState } from "react";
import type { CSSProperties, PointerEvent as ReactPointerEvent } from "react";
import type { DocumentSourceTarget } from "../../../portal-types";
import { findTokenSequence, sourceTokenValues, tokenizeSourceText } from "./document-source-match";

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
type LensState = { left: number; top: number; visible: boolean };
type PdfDocumentViewerProps = {
  fileName: string;
  src: string;
  sourceTarget?: DocumentSourceTarget | null;
  onClearSourceTarget?: () => void;
};

const MIN_ZOOM = 0.35;
const MAX_ZOOM = 3;
const LENS_SIZE = 230;
const LENS_ZOOM = 2.2;
const MAX_RENDER_PIXELS = 12_000_000;
const TOUCH_HOLD_MS = 420;

function clampZoom(value: number) {
  return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, value));
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

function sourceMatchesOnPage(items: PdfTextItem[], target: DocumentSourceTarget, viewport: PdfViewport) {
  const needle = sourceTokenValues(target.text);
  if (!needle.length) return [];
  const indexedTokens: { itemIndex: number; value: string }[] = [];
  items.forEach((item, itemIndex) => {
    tokenizeSourceText(item.str).forEach((token) => indexedTokens.push({ itemIndex, value: token.value }));
  });
  const values = indexedTokens.map((token) => token.value);
  const matches: { left: number; top: number; width: number; height: number }[] = [];
  let fromIndex = 0;
  while (fromIndex < values.length) {
    const match = findTokenSequence(values, needle, fromIndex);
    if (!match) break;
    const itemIndexes = [...new Set(indexedTokens.slice(match.start, match.end + 1).map((token) => token.itemIndex))];
    matches.push(unionRects(itemIndexes.map((itemIndex) => rectForTextItem(items[itemIndex], viewport))));
    fromIndex = match.start + 1;
    if (matches.length > 1) break;
  }
  return matches;
}
export function PdfDocumentViewer({ fileName, src, sourceTarget, onClearSourceTarget }: PdfDocumentViewerProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const lensCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const stageRef = useRef<HTMLDivElement | null>(null);
  const touchTimerRef = useRef<number | null>(null);
  const touchActiveRef = useRef(false);
  const touchStartRef = useRef({ clientX: 0, clientY: 0 });
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
  const [lens, setLens] = useState<LensState>({ left: 0, top: 0, visible: false });
  const magnifierEnabled = !(fitMode === "custom" && Math.abs(effectiveScale - 1) < 0.01);

  function clearTouchTimer() {
    if (touchTimerRef.current !== null) window.clearTimeout(touchTimerRef.current);
    touchTimerRef.current = null;
  }

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
    void (async () => {
      const matches: PdfSourceHighlight[] = [];
      for (let page = 1; page <= pdfDocument.numPages; page += 1) {
        const pdfPage = await pdfDocument.getPage(page);
        const textContent = await pdfPage.getTextContent();
        if (!active) return;
        const items = textContent.items.filter(isPdfTextItem);
        const viewport = pdfPage.getViewport({ scale: 1 });
        sourceMatchesOnPage(items, sourceTarget, viewport).forEach((match) => matches.push({ page, ...match }));
        if (matches.length > 1) break;
      }
      if (!active) return;
      if (matches.length === 1) {
        setSourceHighlight(matches[0]);
        setPageNumber(matches[0].page);
        setSourceMatchStatus(`Kaynak bulundu · sayfa ${matches[0].page}`);
        return;
      }
      setSourceHighlight(null);
      setSourceMatchStatus(matches.length > 1 ? "Kaynak metin birden fazla yerde bulundu." : "Kaynak metin PDF içinde bulunamadı.");
    })().catch((scanError) => {
      if (!active) return;
      setSourceHighlight(null);
      setSourceMatchStatus(scanError instanceof Error ? scanError.message : "Kaynak eşleme yapılamadı.");
    });
    return () => { active = false; };
  }, [pdfDocument, sourceTarget?.key, sourceTarget?.text]);

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
        const baseScale = fitMode === "width"
          ? availableWidth / baseViewport.width
          : fitMode === "page"
            ? Math.min(availableWidth / baseViewport.width, availableHeight / baseViewport.height)
            : customZoom;
        const scale = clampZoom(baseScale);
        const viewport = page.getViewport({ scale });
        const desiredOutputScale = Math.max(window.devicePixelRatio || 1, LENS_ZOOM);
        const maxOutputScale = Math.sqrt(MAX_RENDER_PIXELS / Math.max(viewport.width * viewport.height, 1));
        const outputScale = Math.max(1, Math.min(desiredOutputScale, maxOutputScale));
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
      const outsideViewport = top < stage.scrollTop + 8
        || top + height > stage.scrollTop + stage.clientHeight - 8
        || left < stage.scrollLeft + 8
        || left + width > stage.scrollLeft + stage.clientWidth - 8;
      if (!sourceTarget?.pinned && !outsideViewport) return;
      stage.scrollTo({
        left: Math.max(0, left + width / 2 - stage.clientWidth / 2),
        top: Math.max(0, top + height / 2 - stage.clientHeight / 2),
        behavior: "auto",
      });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [effectiveScale, pageNumber, sourceHighlight, sourceTarget?.key, sourceTarget?.pinned, stageSize.height, stageSize.width]);

  function applyCustomZoom(nextEffectiveScale: number) {
    const scale = clampZoom(nextEffectiveScale);
    if (Math.abs(scale - 1) < 0.01) hideLens();
    setFitMode("custom");
    setCustomZoom(scale);
  }

  function hideLens() {
    clearTouchTimer();
    touchActiveRef.current = false;
    setLens((current) => ({ ...current, visible: false }));
  }

  function drawLensAt(clientX: number, clientY: number) {
    const sourceCanvas = canvasRef.current;
    const lensCanvas = lensCanvasRef.current;
    const stage = stageRef.current;
    if (!sourceCanvas || !lensCanvas || !stage) return;
    if (!magnifierEnabled) {
      hideLens();
      return;
    }
    const canvasRect = sourceCanvas.getBoundingClientRect();
    if (clientX < canvasRect.left || clientX > canvasRect.right || clientY < canvasRect.top || clientY > canvasRect.bottom) {
      hideLens();
      return;
    }
    const stageRect = stage.getBoundingClientRect();
    const outputRatioX = sourceCanvas.width / Math.max(canvasRect.width, 1);
    const outputRatioY = sourceCanvas.height / Math.max(canvasRect.height, 1);
    const centerX = (clientX - canvasRect.left) * outputRatioX;
    const centerY = (clientY - canvasRect.top) * outputRatioY;
    const outputScale = Math.max(window.devicePixelRatio || 1, 1);
    const targetSize = Math.round(LENS_SIZE * outputScale);
    if (lensCanvas.width !== targetSize || lensCanvas.height !== targetSize) {
      lensCanvas.width = targetSize;
      lensCanvas.height = targetSize;
    }
    const context = lensCanvas.getContext("2d");
    if (!context) return;
    const destinationScaleX = (LENS_ZOOM * outputScale) / outputRatioX;
    const destinationScaleY = (LENS_ZOOM * outputScale) / outputRatioY;
    const destinationX = targetSize / 2 - centerX * destinationScaleX;
    const destinationY = targetSize / 2 - centerY * destinationScaleY;
    context.clearRect(0, 0, lensCanvas.width, lensCanvas.height);
    context.drawImage(
      sourceCanvas,
      destinationX,
      destinationY,
      sourceCanvas.width * destinationScaleX,
      sourceCanvas.height * destinationScaleY,
    );
    setLens({
      left: clientX - stageRect.left + stage.scrollLeft,
      top: clientY - stageRect.top + stage.scrollTop,
      visible: true,
    });
  }

  function handlePointerMove(event: ReactPointerEvent<HTMLDivElement>) {
    if (event.pointerType === "touch" && !touchActiveRef.current) {
      const distance = Math.hypot(event.clientX - touchStartRef.current.clientX, event.clientY - touchStartRef.current.clientY);
      if (distance > 10) clearTouchTimer();
      return;
    }
    drawLensAt(event.clientX, event.clientY);
  }

  function handlePointerDown(event: ReactPointerEvent<HTMLDivElement>) {
    if (event.pointerType !== "touch") return;
    clearTouchTimer();
    touchStartRef.current = { clientX: event.clientX, clientY: event.clientY };
    const { clientX, clientY } = event;
    touchTimerRef.current = window.setTimeout(() => {
      touchActiveRef.current = true;
      drawLensAt(clientX, clientY);
    }, TOUCH_HOLD_MS);
  }

  function handlePointerUp(event: ReactPointerEvent<HTMLDivElement>) {
    if (event.pointerType === "touch") hideLens();
  }

  useEffect(() => () => clearTouchTimer(), []);

  function clearSourceFocus() {
    setSourceHighlight(null);
    setSourceMatchStatus("");
    setHighlightStyle(null);
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
        {sourceTarget?.pinned ? (
          <div className="document-source-focus-controls">
            <span>{sourceMatchStatus || "Kaynak aranıyor…"}</span>
            <button onClick={clearSourceFocus} type="button">Tam belgeye dön</button>
          </div>
        ) : null}
      </div>
      <div
        className="pdf-viewer-stage"
        onPointerCancel={handlePointerUp}
        onPointerDown={handlePointerDown}
        onPointerLeave={(event) => { if (event.pointerType !== "touch") hideLens(); }}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onScroll={hideLens}
        ref={stageRef}
      >
        {error ? (
          <div className="preview-error-panel" role="alert">
            <strong>PDF önizleme açılamadı.</strong>
            <p>{error}</p>
          </div>
        ) : null}
        {!error ? <canvas aria-label={`${fileName} sayfa ${pageNumber}`} ref={canvasRef} /> : null}
        {highlightStyle && !error ? <div className={`pdf-source-highlight${sourceTarget?.pinned ? " pinned" : ""}`} aria-label="Kaynak eşleşmesi" style={highlightStyle} /> : null}
        {!error && magnifierEnabled ? (
          <div
            aria-hidden="true"
            className={`document-magnifier pdf-document-magnifier${lens.visible ? " visible" : ""}`}
            style={{ height: LENS_SIZE, left: lens.left, top: lens.top, width: LENS_SIZE }}
          >
            <canvas ref={lensCanvasRef} />
          </div>
        ) : null}
        {status && !error ? <span className="pdf-viewer-status" role="status">{status}</span> : null}
      </div>
    </section>
  );
}
