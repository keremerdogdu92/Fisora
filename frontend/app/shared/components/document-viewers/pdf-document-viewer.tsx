// File: frontend/app/shared/components/document-viewers/pdf-document-viewer.tsx
// Summary: Renders PDF.js invoices with responsive navigation, cursor magnification, and deterministic source-evidence focus.
"use client";

import { useEffect, useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";
import { findTokenSequence, sourceTokenValues, tokenizeSourceText } from "./document-source-match";
import type { DocumentSourceFocus } from "./document-inspector-types";

type FitMode = "page" | "width" | "custom";
type PdfViewport = { height: number; scale: number; transform: number[]; width: number };
type PdfTextItem = { height: number; str: string; transform: number[]; width: number };
type PdfPageHandle = {
  getTextContent: () => Promise<{ items: unknown[] }>;
  getViewport: (options: { scale: number }) => PdfViewport;
  render: (options: Record<string, unknown>) => { promise: Promise<void>; cancel: () => void };
};
type PdfDocumentHandle = {
  destroy: () => Promise<void> | void;
  getPage: (pageNumber: number) => Promise<PdfPageHandle>;
  numPages: number;
};
type PdfSourceMatch = { itemIndexes: number[]; pageNumber: number };
type HighlightRect = { height: number; left: number; top: number; width: number };
type LensState = { left: number; top: number; visible: boolean };

const MIN_ZOOM = 0.35;
const MAX_ZOOM = 3;
const LENS_SIZE = 230;
const LENS_ZOOM = 2.2;
const MAX_RENDER_PIXELS = 12_000_000;
const PINNED_FOCUS_ZOOM = 1.2;
const TOUCH_HOLD_MS = 420;

function clampZoom(value: number) {
  return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, value));
}

function isPdfTextItem(value: unknown): value is PdfTextItem {
  if (!value || typeof value !== "object") return false;
  const item = value as Partial<PdfTextItem>;
  return typeof item.str === "string"
    && Array.isArray(item.transform)
    && item.transform.length >= 6
    && typeof item.width === "number"
    && typeof item.height === "number";
}

function multiplyTransform(left: number[], right: number[]) {
  return [
    left[0] * right[0] + left[2] * right[1],
    left[1] * right[0] + left[3] * right[1],
    left[0] * right[2] + left[2] * right[3],
    left[1] * right[2] + left[3] * right[3],
    left[0] * right[4] + left[2] * right[5] + left[4],
    left[1] * right[4] + left[3] * right[5] + left[5],
  ];
}

function textItemRect(item: PdfTextItem, viewport: PdfViewport): HighlightRect {
  const matrix = multiplyTransform(viewport.transform, item.transform);
  const fontHeight = Math.max(Math.hypot(matrix[2], matrix[3]), Math.abs(item.height * viewport.scale), 1);
  return {
    height: fontHeight,
    left: matrix[4],
    top: matrix[5] - fontHeight,
    width: Math.max(Math.abs(item.width * viewport.scale), 1),
  };
}

export function PdfDocumentViewer({
  fileName,
  sourceFocus,
  src,
}: {
  fileName: string;
  sourceFocus?: DocumentSourceFocus | null;
  src: string;
}) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const lensCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const pageSurfaceRef = useRef<HTMLDivElement | null>(null);
  const stageRef = useRef<HTMLDivElement | null>(null);
  const textCacheRef = useRef(new Map<number, PdfTextItem[]>());
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
  const [sourceMatch, setSourceMatch] = useState<PdfSourceMatch | null>(null);
  const [highlightRects, setHighlightRects] = useState<HighlightRect[]>([]);
  const [lens, setLens] = useState<LensState>({ left: 0, top: 0, visible: false });

  const focusZoomActive = Boolean(sourceFocus?.pinned && sourceMatch?.pageNumber === pageNumber);
  const focusZoomMultiplier = focusZoomActive ? PINNED_FOCUS_ZOOM : 1;

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
    textCacheRef.current.clear();
    setPdfDocument(null);
    setPageNumber(1);
    setSourceMatch(null);
    setHighlightRects([]);
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

  async function getPageTextItems(documentHandle: PdfDocumentHandle, targetPageNumber: number) {
    const cached = textCacheRef.current.get(targetPageNumber);
    if (cached) return cached;
    const page = await documentHandle.getPage(targetPageNumber);
    const textContent = await page.getTextContent();
    const items = textContent.items.filter(isPdfTextItem);
    textCacheRef.current.set(targetPageNumber, items);
    return items;
  }

  useEffect(() => {
    if (!pdfDocument || !sourceFocus?.sourceText) {
      setSourceMatch(null);
      setHighlightRects([]);
      return;
    }
    let active = true;
    const needle = sourceTokenValues(sourceFocus.sourceText);
    void (async () => {
      for (let candidatePage = 1; candidatePage <= pdfDocument.numPages; candidatePage += 1) {
        const items = await getPageTextItems(pdfDocument, candidatePage);
        if (!active) return;
        const indexedTokens: { itemIndex: number; value: string }[] = [];
        items.forEach((item, itemIndex) => {
          tokenizeSourceText(item.str).forEach((token) => indexedTokens.push({ itemIndex, value: token.value }));
        });
        const match = findTokenSequence(indexedTokens.map((token) => token.value), needle);
        if (!match) continue;
        const itemIndexes = [...new Set(indexedTokens.slice(match.start, match.end + 1).map((token) => token.itemIndex))];
        const nextMatch = { itemIndexes, pageNumber: candidatePage };
        setSourceMatch(nextMatch);
        setPageNumber(candidatePage);
        return;
      }
      if (active) setSourceMatch(null);
    })();
    return () => {
      active = false;
    };
  }, [pdfDocument, sourceFocus?.key, sourceFocus?.sourceText]);

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
        const baseScale = fitMode === "width"
          ? availableWidth / baseViewport.width
          : fitMode === "page"
            ? Math.min(availableWidth / baseViewport.width, availableHeight / baseViewport.height)
            : customZoom;
        const scale = clampZoom(baseScale * focusZoomMultiplier);
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
        if (!active) return;
        if (sourceMatch?.pageNumber === pageNumber) {
          const items = await getPageTextItems(pdfDocument, pageNumber);
          if (!active) return;
          setHighlightRects(sourceMatch.itemIndexes
            .map((itemIndex) => items[itemIndex])
            .filter((item): item is PdfTextItem => Boolean(item))
            .map((item) => textItemRect(item, viewport)));
        } else {
          setHighlightRects([]);
        }
        setStatus("");
        setError("");
      } catch (renderError) {
        if (!active || (renderError instanceof Error && renderError.name === "RenderingCancelledException")) return;
        setError(renderError instanceof Error ? renderError.message : "PDF sayfası çizilemedi.");
      }
    })();
    return () => {
      active = false;
      renderTask?.cancel();
    };
  }, [customZoom, fitMode, focusZoomMultiplier, pageNumber, pdfDocument, sourceMatch, stageSize.height, stageSize.width]);

  useEffect(() => {
    const stage = stageRef.current;
    const surface = pageSurfaceRef.current;
    if (!stage || !surface || !highlightRects.length || !sourceFocus) return;
    const left = Math.min(...highlightRects.map((rect) => rect.left));
    const top = Math.min(...highlightRects.map((rect) => rect.top));
    const right = Math.max(...highlightRects.map((rect) => rect.left + rect.width));
    const bottom = Math.max(...highlightRects.map((rect) => rect.top + rect.height));
    const targetLeft = surface.offsetLeft + left;
    const targetTop = surface.offsetTop + top;
    const outsideViewport = targetTop < stage.scrollTop + 8
      || targetTop + (bottom - top) > stage.scrollTop + stage.clientHeight - 8
      || targetLeft < stage.scrollLeft + 8
      || targetLeft + (right - left) > stage.scrollLeft + stage.clientWidth - 8;
    if (!sourceFocus.pinned && !outsideViewport) return;
    stage.scrollTo({
      behavior: "auto",
      left: Math.max(0, targetLeft + (right - left) / 2 - stage.clientWidth / 2),
      top: Math.max(0, targetTop + (bottom - top) / 2 - stage.clientHeight / 2),
    });
  }, [highlightRects, sourceFocus?.key, sourceFocus?.pinned]);

  function applyCustomZoom(nextEffectiveScale: number) {
    const scale = clampZoom(nextEffectiveScale / focusZoomMultiplier);
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
    const canvasRect = sourceCanvas.getBoundingClientRect();
    if (clientX < canvasRect.left || clientX > canvasRect.right || clientY < canvasRect.top || clientY > canvasRect.bottom) {
      hideLens();
      return;
    }
    const stageRect = stage.getBoundingClientRect();
    const outputRatioX = sourceCanvas.width / Math.max(canvasRect.width, 1);
    const outputRatioY = sourceCanvas.height / Math.max(canvasRect.height, 1);
    const sourceWidth = (LENS_SIZE / LENS_ZOOM) * outputRatioX;
    const sourceHeight = (LENS_SIZE / LENS_ZOOM) * outputRatioY;
    const centerX = (clientX - canvasRect.left) * outputRatioX;
    const centerY = (clientY - canvasRect.top) * outputRatioY;
    const sourceX = Math.max(0, Math.min(sourceCanvas.width - sourceWidth, centerX - sourceWidth / 2));
    const sourceY = Math.max(0, Math.min(sourceCanvas.height - sourceHeight, centerY - sourceHeight / 2));
    const outputScale = Math.max(window.devicePixelRatio || 1, 1);
    const targetSize = Math.round(LENS_SIZE * outputScale);
    if (lensCanvas.width !== targetSize || lensCanvas.height !== targetSize) {
      lensCanvas.width = targetSize;
      lensCanvas.height = targetSize;
    }
    const context = lensCanvas.getContext("2d");
    if (!context) return;
    context.clearRect(0, 0, lensCanvas.width, lensCanvas.height);
    context.drawImage(
      sourceCanvas,
      sourceX,
      sourceY,
      sourceWidth,
      sourceHeight,
      0,
      0,
      lensCanvas.width,
      lensCanvas.height,
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
      <div
        className="pdf-viewer-stage"
        onPointerCancel={handlePointerUp}
        onPointerDown={handlePointerDown}
        onPointerLeave={(event) => { if (event.pointerType !== "touch") hideLens(); }}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        ref={stageRef}
      >
        {error ? (
          <div className="preview-error-panel" role="alert">
            <strong>PDF önizleme açılamadı.</strong>
            <p>{error}</p>
          </div>
        ) : null}
        {!error ? (
          <div className="pdf-page-surface" ref={pageSurfaceRef}>
            <canvas aria-label={`${fileName} sayfa ${pageNumber}`} ref={canvasRef} />
            {highlightRects.map((rect, index) => (
              <span
                aria-hidden="true"
                className={`document-source-highlight${sourceFocus?.pinned ? " pinned" : ""}`}
                key={`${sourceFocus?.key || "source"}-${index}`}
                style={{ height: rect.height, left: rect.left, top: rect.top, width: rect.width }}
              />
            ))}
          </div>
        ) : null}
        {!error ? (
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
