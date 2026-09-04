// File: frontend/app/shared/components/document-viewers/html-document-viewer.tsx
// Summary: Renders sandboxed invoice HTML with mode-aware pointer-centered magnification, content fitting, and deterministic source-evidence highlighting.
"use client";

import { useEffect, useRef, useState } from "react";
import type { DocumentSourceTarget } from "../../../portal-types";
import { findTokenSequence, sourceTokenValues } from "./document-source-match";

type FitMode = "page" | "width" | "content" | "custom";
type HtmlDocumentViewerProps = {
  fileName: string;
  src: string;
  sourceTarget?: DocumentSourceTarget | null;
  onClearSourceTarget?: () => void;
};
type LensState = { docX: number; docY: number; left: number; top: number; visible: boolean };
type DocumentBounds = { left: number; top: number; width: number; height: number };

const MIN_ZOOM = 0.35;
const MAX_ZOOM = 3;
const VIRTUAL_SOURCE_WIDTH = 960;
const VIRTUAL_SOURCE_HEIGHT = 1280;
const SOURCE_TARGET_ID = "fisora-source-target";
const LENS_SIZE = 230;
const LENS_ZOOM = 2.2;
const TOUCH_HOLD_MS = 420;

function clampZoom(value: number) {
  return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, value));
}

function elementText(element: HTMLElement) {
  if (element.tagName === "TR") {
    return Array.from(element.querySelectorAll("th,td")).map((cell) => cell.textContent || "").join(" ");
  }
  return element.textContent || "";
}

function containsExactTokenSequence(value: string, needle: string[]) {
  const tokens = sourceTokenValues(value);
  return Boolean(findTokenSequence(tokens, needle));
}

function invoiceLineRows(document: Document) {
  const tables = Array.from(document.querySelectorAll<HTMLTableElement>("table"));
  const preferred = document.querySelector<HTMLTableElement>("#lineTable");
  const candidates = preferred ? [preferred, ...tables.filter((table) => table !== preferred)] : tables;
  const headerHints = new Set(["malzeme", "hizmet", "ürün", "miktar", "birim", "kdv", "tutar", "amount", "description"]);

  for (const table of candidates) {
    const rows = Array.from(table.querySelectorAll<HTMLTableRowElement>("tr")).filter((row) => row.querySelector("td"));
    if (!rows.length) continue;
    const tableTokens = sourceTokenValues(elementText(table));
    const hintCount = [...new Set(tableTokens.filter((token) => headerHints.has(token)))].length;
    if (table !== preferred && hintCount < 2) continue;
    const dataRows = rows.filter((row) => {
      const tokens = sourceTokenValues(elementText(row));
      if (!tokens.length) return false;
      const normalized = tokens.join(" ");
      const looksLikeHeader = normalized.includes("sıra no")
        || normalized.includes("malzeme hizmet")
        || normalized.includes("birim fiyat")
        || normalized.includes("kdv oran");
      return !looksLikeHeader;
    });
    if (dataRows.length) return dataRows;
  }
  return [];
}

function containsEquivalentAmount(value: string, sourceAmount: string) {
  const amountDigits = String(sourceAmount || "").replace(/\D/g, "");
  if (!amountDigits) return true;
  const candidates = value.match(/\d[\d.,]*\d|\d/g) || [];
  return candidates.some((candidate) => candidate.replace(/\D/g, "") === amountDigits);
}

function elementMatchesTarget(element: HTMLElement, target: DocumentSourceTarget) {
  const textNeedle = sourceTokenValues(target.text);
  const value = elementText(element);
  const textMatches = !textNeedle.length || containsExactTokenSequence(value, textNeedle);
  const amountMatches = containsEquivalentAmount(value, target.sourceAmount || "");
  return textMatches && amountMatches;
}

function findBestSourceElement(document: Document, target: DocumentSourceTarget) {
  const sourceIndex = Number.parseInt(String(target.sourcePosition || ""), 10);
  const lineRows = invoiceLineRows(document);
  const indexedRow = Number.isInteger(sourceIndex) && sourceIndex > 0 ? lineRows[sourceIndex - 1] : undefined;

  if (indexedRow && elementMatchesTarget(indexedRow, target)) return indexedRow;

  const matchingLineRows = lineRows.filter((row) => elementMatchesTarget(row, target));
  if (matchingLineRows.length === 1) return matchingLineRows[0];
  if (indexedRow && matchingLineRows.includes(indexedRow)) return indexedRow;

  const textNeedle = sourceTokenValues(target.text);
  if (!textNeedle.length) return null;
  const selectors = "tr,td,th,p,li,span,strong,b,div";
  const matches = Array.from(document.querySelectorAll<HTMLElement>(selectors))
    .filter((element) => elementMatchesTarget(element, target));
  const leafMatches = matches.filter((element) => !matches.some((other) => element !== other && element.contains(other)));
  return leafMatches.length === 1 ? leafMatches[0] : null;
}

function instrumentHtmlSource(rawHtml: string, target: DocumentSourceTarget) {
  const parsed = new DOMParser().parseFromString(rawHtml, "text/html");
  const targetElement = findBestSourceElement(parsed, target);
  if (!targetElement) return null;
  targetElement.id = SOURCE_TARGET_ID;
  const style = parsed.createElement("style");
  style.setAttribute("data-fisora-source-focus", "true");
  style.textContent = `#${SOURCE_TARGET_ID}{outline:3px solid #f59e0b!important;outline-offset:2px!important;box-shadow:0 0 0 5px rgba(245,158,11,.18)!important;background:rgba(254,243,199,.65)!important;scroll-margin:180px!important}`;
  parsed.head.appendChild(style);
  return `<!doctype html>${parsed.documentElement.outerHTML}`;
}

function measureDocumentLayout(document: Document) {
  const root = document.documentElement;
  const body = document.body;
  const width = Math.max(VIRTUAL_SOURCE_WIDTH, root?.scrollWidth || 0, body?.scrollWidth || 0);
  const height = Math.max(VIRTUAL_SOURCE_HEIGHT, root?.scrollHeight || 0, body?.scrollHeight || 0);
  const candidates = Array.from(document.querySelectorAll<HTMLElement>("td,th,span,p,h1,h2,h3,img,svg"))
    .filter((element) => {
      const rect = element.getBoundingClientRect();
      if (rect.width < 1 || rect.height < 1) return false;
      return ["IMG", "SVG"].includes(element.tagName) || sourceTokenValues(element.textContent || "").length > 0;
    });
  if (!candidates.length) return { size: { width, height }, bounds: { left: 0, top: 0, width, height } };
  const rects = candidates.map((element) => element.getBoundingClientRect());
  const padding = 8;
  const left = Math.max(0, Math.min(...rects.map((rect) => rect.left)) - padding);
  const top = Math.max(0, Math.min(...rects.map((rect) => rect.top)) - padding);
  const right = Math.min(width, Math.max(...rects.map((rect) => rect.right)) + padding);
  const bottom = Math.min(height, Math.max(...rects.map((rect) => rect.bottom)) + padding);
  return {
    size: { width, height },
    bounds: { left, top, width: Math.max(120, right - left), height: Math.max(160, bottom - top) },
  };
}

export function HtmlDocumentViewer({ fileName, src, sourceTarget, onClearSourceTarget }: HtmlDocumentViewerProps) {
  const stageRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLDivElement | null>(null);
  const frameRef = useRef<HTMLIFrameElement | null>(null);
  const lensFrameRef = useRef<HTMLIFrameElement | null>(null);
  const frameCleanupRef = useRef<(() => void) | null>(null);
  const rawHtmlRef = useRef<{ src: string; text: string } | null>(null);
  const touchTimerRef = useRef<number | null>(null);
  const touchActiveRef = useRef(false);
  const touchStartRef = useRef({ clientX: 0, clientY: 0 });
  const viewStateRef = useRef({ effectiveScale: 1, magnifierEnabled: true });
  const [fitMode, setFitMode] = useState<FitMode>("page");
  const [magnifierRequested, setMagnifierRequested] = useState(true);
  const [customZoom, setCustomZoom] = useState(1);
  const [stageSize, setStageSize] = useState({ width: 0, height: 0 });
  const [documentSize, setDocumentSize] = useState({ width: VIRTUAL_SOURCE_WIDTH, height: VIRTUAL_SOURCE_HEIGHT });
  const [contentBounds, setContentBounds] = useState<DocumentBounds>({ left: 0, top: 0, width: VIRTUAL_SOURCE_WIDTH, height: VIRTUAL_SOURCE_HEIGHT });
  const [focusedSrc, setFocusedSrc] = useState("");
  const [sourceMatchStatus, setSourceMatchStatus] = useState("");
  const [lens, setLens] = useState<LensState>({ docX: 0, docY: 0, left: 0, top: 0, visible: false });

  function clearTouchTimer() {
    if (touchTimerRef.current !== null) window.clearTimeout(touchTimerRef.current);
    touchTimerRef.current = null;
  }

  async function readRawHtml() {
    if (rawHtmlRef.current?.src === src) return rawHtmlRef.current.text;
    const response = await fetch(src, { cache: "no-store" });
    const text = await response.text();
    rawHtmlRef.current = { src, text };
    return text;
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
    rawHtmlRef.current = null;
    setDocumentSize({ width: VIRTUAL_SOURCE_WIDTH, height: VIRTUAL_SOURCE_HEIGHT });
    setContentBounds({ left: 0, top: 0, width: VIRTUAL_SOURCE_WIDTH, height: VIRTUAL_SOURCE_HEIGHT });
  }, [src]);

  useEffect(() => {
    if (!sourceTarget) {
      setFocusedSrc("");
      setSourceMatchStatus("");
      return undefined;
    }
    let active = true;
    let objectUrl = "";
    void (async () => {
      try {
        const rawHtml = await readRawHtml();
        const instrumented = instrumentHtmlSource(rawHtml, sourceTarget);
        if (!active) return;
        if (!instrumented) {
          setFocusedSrc("");
          setSourceMatchStatus("Kaynak metin HTML içinde bulunamadı.");
          return;
        }
        objectUrl = URL.createObjectURL(new Blob([instrumented], { type: "text/html" }));
        setFocusedSrc(objectUrl);
        setSourceMatchStatus("Kaynak bulundu");
      } catch (error) {
        if (!active) return;
        setFocusedSrc("");
        setSourceMatchStatus(error instanceof Error ? error.message : "Kaynak eşleme yapılamadı.");
      }
    })();
    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [sourceTarget?.key, sourceTarget?.text, sourceTarget?.sourceAmount, src]);

  const availableWidth = Math.max(stageSize.width - 24, 120);
  const availableHeight = Math.max(stageSize.height - 24, 160);
  const fitPageScale = Math.min(1, availableWidth / documentSize.width, availableHeight / documentSize.height);
  const fitWidthScale = Math.min(1, availableWidth / documentSize.width);
  const fitContentScale = Math.min(1, availableWidth / contentBounds.width);
  const baseScale = fitMode === "page"
    ? fitPageScale
    : fitMode === "width"
      ? fitWidthScale
      : fitMode === "content"
        ? fitContentScale
        : customZoom;
  const effectiveScale = clampZoom(baseScale);
  const magnifierEnabled = magnifierRequested;
  const viewportBounds = fitMode === "content"
    ? contentBounds
    : { left: 0, top: 0, width: documentSize.width, height: documentSize.height };
  viewStateRef.current = { effectiveScale, magnifierEnabled };

  function selectFitMode(mode: Exclude<FitMode, "custom">) {
    hideLens();
    setFitMode(mode);
    setMagnifierRequested(mode === "page");
  }

  function applyCustomZoom(nextEffectiveScale: number) {
    const nextScale = clampZoom(nextEffectiveScale);
    hideLens();
    setFitMode("custom");
    setMagnifierRequested(false);
    setCustomZoom(nextScale);
  }

  function hideLens() {
    clearTouchTimer();
    touchActiveRef.current = false;
    setLens((current) => ({ ...current, visible: false }));
  }

  function toggleMagnifier() {
    if (magnifierRequested) hideLens();
    setMagnifierRequested((current) => !current);
  }

  function resetLensScroll() {
    lensFrameRef.current?.contentWindow?.scrollTo(0, 0);
  }

  function updateLens(event: PointerEvent) {
    const frame = frameRef.current;
    const frameWindow = frame?.contentWindow;
    const stage = stageRef.current;
    if (!frame || !frameWindow || !stage) return;
    const { effectiveScale: currentScale, magnifierEnabled: canMagnify } = viewStateRef.current;
    if (!canMagnify) {
      hideLens();
      return;
    }
    const frameRect = frame.getBoundingClientRect();
    const stageRect = stage.getBoundingClientRect();
    const docX = event.clientX + frameWindow.scrollX;
    const docY = event.clientY + frameWindow.scrollY;
    const pointerClientX = frameRect.left + event.clientX * currentScale;
    const pointerClientY = frameRect.top + event.clientY * currentScale;
    setLens({
      docX,
      docY,
      left: pointerClientX - stageRect.left + stage.scrollLeft,
      top: pointerClientY - stageRect.top + stage.scrollTop,
      visible: true,
    });
  }

  function focusSourceInStage() {
    const stage = stageRef.current;
    const canvas = canvasRef.current;
    const frame = frameRef.current;
    const frameWindow = frame?.contentWindow;
    const targetElement = frame?.contentDocument?.getElementById(SOURCE_TARGET_ID);
    if (!stage || !canvas || !frameWindow || !targetElement || !sourceTarget) return;
    const rect = targetElement.getBoundingClientRect();
    const left = canvas.offsetLeft + (rect.left + frameWindow.scrollX - viewportBounds.left) * effectiveScale;
    const top = canvas.offsetTop + (rect.top + frameWindow.scrollY - viewportBounds.top) * effectiveScale;
    const width = Math.max(8, rect.width * effectiveScale);
    const height = Math.max(8, rect.height * effectiveScale);
    const outsideViewport = top < stage.scrollTop + 8
      || top + height > stage.scrollTop + stage.clientHeight - 8
      || left < stage.scrollLeft + 8
      || left + width > stage.scrollLeft + stage.clientWidth - 8;
    if (!sourceTarget.pinned && !outsideViewport) return;
    stage.scrollTo({
      left: Math.max(0, left + width / 2 - stage.clientWidth / 2),
      top: Math.max(0, top + height / 2 - stage.clientHeight / 2),
      behavior: "auto",
    });
  }

  function handleFrameLoad() {
    frameCleanupRef.current?.();
    const frameWindow = frameRef.current?.contentWindow;
    const documentNode = frameRef.current?.contentDocument;
    if (!frameWindow || !documentNode) return;
    const layout = measureDocumentLayout(documentNode);
    setDocumentSize(layout.size);
    setContentBounds(layout.bounds);
    const handlePointerMove = (event: PointerEvent) => {
      if (event.pointerType === "touch" && !touchActiveRef.current) {
        const distance = Math.hypot(event.clientX - touchStartRef.current.clientX, event.clientY - touchStartRef.current.clientY);
        if (distance > 10) clearTouchTimer();
        return;
      }
      updateLens(event);
    };
    const handlePointerDown = (event: PointerEvent) => {
      if (event.pointerType !== "touch") return;
      clearTouchTimer();
      touchStartRef.current = { clientX: event.clientX, clientY: event.clientY };
      touchTimerRef.current = window.setTimeout(() => {
        touchActiveRef.current = true;
        updateLens(event);
      }, TOUCH_HOLD_MS);
    };
    const handlePointerUp = (event: PointerEvent) => {
      if (event.pointerType === "touch") hideLens();
    };
    const handlePointerLeave = (event: PointerEvent) => {
      if (event.pointerType !== "touch") hideLens();
    };
    documentNode.addEventListener("pointermove", handlePointerMove);
    documentNode.addEventListener("pointerdown", handlePointerDown);
    documentNode.addEventListener("pointerup", handlePointerUp);
    documentNode.addEventListener("pointercancel", handlePointerUp);
    documentNode.addEventListener("pointerleave", handlePointerLeave);
    frameWindow.addEventListener("scroll", hideLens, { passive: true });
    window.requestAnimationFrame(focusSourceInStage);
    frameCleanupRef.current = () => {
      documentNode.removeEventListener("pointermove", handlePointerMove);
      documentNode.removeEventListener("pointerdown", handlePointerDown);
      documentNode.removeEventListener("pointerup", handlePointerUp);
      documentNode.removeEventListener("pointercancel", handlePointerUp);
      documentNode.removeEventListener("pointerleave", handlePointerLeave);
      frameWindow.removeEventListener("scroll", hideLens);
    };
  }

  useEffect(() => {
    window.requestAnimationFrame(focusSourceInStage);
  }, [effectiveScale, focusedSrc, sourceTarget?.key, sourceTarget?.pinned]);

  useEffect(() => () => {
    clearTouchTimer();
    frameCleanupRef.current?.();
  }, []);

  function clearSourceFocus() {
    setFocusedSrc("");
    setSourceMatchStatus("");
    onClearSourceTarget?.();
  }
  const viewerSrc = sourceTarget && focusedSrc ? focusedSrc : src;
  const lensScale = effectiveScale * LENS_ZOOM;
  const lensTransform = `translate(${LENS_SIZE / 2 - lens.docX * lensScale}px, ${LENS_SIZE / 2 - lens.docY * lensScale}px) scale(${lensScale})`;
  return (
    <section className="html-document-viewer" aria-label={`${fileName} HTML görüntüleyici`}>
      <div className="html-viewer-toolbar document-viewer-toolbar">
        <div className="html-viewer-zoom-controls">
          <button className={fitMode === "page" ? "active" : ""} onClick={() => selectFitMode("page")} type="button">Sığdır</button>
          <button className={fitMode === "width" ? "active" : ""} onClick={() => selectFitMode("width")} type="button">Genişlik</button>
          <button className={fitMode === "content" ? "active" : ""} onClick={() => selectFitMode("content")} type="button">İçerik</button>
          <button className={fitMode === "custom" && Math.abs(effectiveScale - 1) < 0.01 ? "active" : ""} onClick={() => applyCustomZoom(1)} type="button">%100</button>
          <button onClick={() => applyCustomZoom(effectiveScale - 0.1)} type="button" aria-label="Uzaklaştır">−</button>
          <span>{Math.round(effectiveScale * 100)}%</span>
          <button onClick={() => applyCustomZoom(effectiveScale + 0.1)} type="button" aria-label="Yakınlaştır">+</button>
          <button aria-pressed={magnifierRequested} className={`magnifier-toggle${magnifierRequested ? " active" : ""}`} onClick={toggleMagnifier} title="İmlecin çevresini büyüt" type="button">Büyüteç</button>
        </div>
        {sourceTarget?.pinned ? (
          <div className="document-source-focus-controls">
            <span>{sourceMatchStatus || "Kaynak aranıyor…"}</span>
            <button onClick={clearSourceFocus} type="button">Vurguyu kaldır</button>
          </div>
        ) : null}
      </div>
      <div className="html-viewer-stage" onScroll={hideLens} ref={stageRef}>
        <div className="html-viewer-canvas" ref={canvasRef} style={{ height: `${viewportBounds.height * effectiveScale}px`, width: `${viewportBounds.width * effectiveScale}px` }}>
          <iframe
            className="html-viewer-frame"
            onLoad={handleFrameLoad}
            ref={frameRef}
            sandbox="allow-same-origin"
            src={viewerSrc}
            style={{
              height: `${documentSize.height}px`,
              left: `${-viewportBounds.left * effectiveScale}px`,
              top: `${-viewportBounds.top * effectiveScale}px`,
              transform: `scale(${effectiveScale})`,
              width: `${documentSize.width}px`,
            }}
            title={`${fileName} izole orijinal HTML`}
          />
        </div>
        {lens.visible && magnifierEnabled ? (
          <div
            aria-hidden="true"
            className="document-magnifier html-document-magnifier visible"
            style={{ height: LENS_SIZE, left: lens.left, top: lens.top, width: LENS_SIZE }}
          >
            <iframe
              className="html-document-lens-frame"
              onLoad={resetLensScroll}
              ref={lensFrameRef}
              sandbox="allow-same-origin"
              src={viewerSrc}
              style={{ height: documentSize.height, transform: lensTransform, width: documentSize.width }}
              tabIndex={-1}
              title=""
            />
          </div>
        ) : null}
      </div>
    </section>
  );
}
