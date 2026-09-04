// File: frontend/app/shared/components/document-viewers/html-document-viewer.tsx
// Summary: Renders sandboxed HTML with shared fit controls and safe source-text locator highlighting.
"use client";

import { useEffect, useRef, useState } from "react";
import type { DocumentSourceTarget } from "../../../portal-types";
import { findTokenSequence, sourceTokenValues } from "./document-source-match";

type FitMode = "page" | "width" | "custom";
type HtmlDocumentViewerProps = {
  fileName: string;
  src: string;
  sourceTarget?: DocumentSourceTarget | null;
  onClearSourceTarget?: () => void;
};
type LensState = { docX: number; docY: number; left: number; top: number; visible: boolean };

const MIN_ZOOM = 0.35;
const MAX_ZOOM = 3;
const VIRTUAL_SOURCE_WIDTH = 960;
const VIRTUAL_SOURCE_HEIGHT = 1280;
const SOURCE_TARGET_ID = "fisora-source-target";
const LENS_SIZE = 230;
const LENS_ZOOM = 2.2;
const PINNED_FOCUS_ZOOM = 1.2;
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

function findBestSourceElement(document: Document, target: DocumentSourceTarget) {
  const needle = sourceTokenValues(target.text);
  const tableRows = Array.from(document.querySelectorAll<HTMLTableRowElement>("tr"))
    .filter((row) => row.querySelector("td"));
  const sourceIndex = Number.parseInt(String(target.sourcePosition || ""), 10);

  if (needle.length) {
    const exactRows = tableRows.filter((element) => containsExactTokenSequence(elementText(element), needle));
    if (exactRows.length === 1) return exactRows[0];
    if (exactRows.length > 1) {
      const indexedRow = Number.isInteger(sourceIndex) && sourceIndex > 0 ? tableRows[sourceIndex - 1] : undefined;
      return indexedRow && exactRows.includes(indexedRow) ? indexedRow : null;
    }
  }

  if (!needle.length) return null;

  const selectors = "td,th,p,li,span,strong,b,div";
  const matches = Array.from(document.querySelectorAll<HTMLElement>(selectors))
    .filter((element) => containsExactTokenSequence(elementText(element), needle));
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
  const [fitMode, setFitMode] = useState<FitMode>("page");
  const [customZoom, setCustomZoom] = useState(1);
  const [stageSize, setStageSize] = useState({ width: 0, height: 0 });
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
  }, [sourceTarget?.key, sourceTarget?.text, src]);

  const availableWidth = Math.max(stageSize.width - 24, 120);
  const availableHeight = Math.max(stageSize.height - 24, 160);
  const fitPageScale = Math.min(1, availableWidth / VIRTUAL_SOURCE_WIDTH, availableHeight / VIRTUAL_SOURCE_HEIGHT);
  const fitWidthScale = Math.min(1, availableWidth / VIRTUAL_SOURCE_WIDTH);
  const focusZoomMultiplier = sourceTarget?.pinned ? PINNED_FOCUS_ZOOM : 1;
  const baseScale = fitMode === "page" ? fitPageScale : fitMode === "width" ? fitWidthScale : customZoom;
  const effectiveScale = clampZoom(baseScale * focusZoomMultiplier);

  function applyCustomZoom(nextEffectiveScale: number) {
    setFitMode("custom");
    setCustomZoom(clampZoom(nextEffectiveScale / focusZoomMultiplier));
  }

  function hideLens() {
    clearTouchTimer();
    touchActiveRef.current = false;
    setLens((current) => ({ ...current, visible: false }));
  }

  function syncLensScroll() {
    const sourceWindow = frameRef.current?.contentWindow;
    const lensWindow = lensFrameRef.current?.contentWindow;
    if (!sourceWindow || !lensWindow) return;
    lensWindow.scrollTo(sourceWindow.scrollX, sourceWindow.scrollY);
  }

  function updateLens(event: PointerEvent) {
    const canvas = canvasRef.current;
    if (!canvas) return;
    syncLensScroll();
    setLens({
      docX: event.clientX,
      docY: event.clientY,
      left: canvas.offsetLeft + event.clientX * effectiveScale,
      top: canvas.offsetTop + event.clientY * effectiveScale,
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
    const left = canvas.offsetLeft + (rect.left + frameWindow.scrollX) * effectiveScale;
    const top = canvas.offsetTop + (rect.top + frameWindow.scrollY) * effectiveScale;
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
    setFitMode("page");
    onClearSourceTarget?.();
  }
  const viewerSrc = sourceTarget && focusedSrc ? focusedSrc : src;
  const lensScale = effectiveScale * LENS_ZOOM;
  const lensTransform = `translate(${LENS_SIZE / 2 - lens.docX * lensScale}px, ${LENS_SIZE / 2 - lens.docY * lensScale}px) scale(${lensScale})`;
  return (
    <section className="html-document-viewer" aria-label={`${fileName} HTML görüntüleyici`}>
      <div className="html-viewer-toolbar document-viewer-toolbar">
        <div className="html-viewer-zoom-controls">
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
      <div className="html-viewer-stage" onScroll={hideLens} ref={stageRef}>
        <div className="html-viewer-canvas" ref={canvasRef} style={{ height: `${VIRTUAL_SOURCE_HEIGHT * effectiveScale}px`, width: `${VIRTUAL_SOURCE_WIDTH * effectiveScale}px` }}>
          <iframe
            className="html-viewer-frame"
            onLoad={handleFrameLoad}
            ref={frameRef}
            sandbox="allow-same-origin"
            src={viewerSrc}
            style={{ height: `${VIRTUAL_SOURCE_HEIGHT}px`, transform: `scale(${effectiveScale})`, width: `${VIRTUAL_SOURCE_WIDTH}px` }}
            title={`${fileName} izole orijinal HTML`}
          />
        </div>
        {lens.visible ? (
          <div
            aria-hidden="true"
            className="document-magnifier html-document-magnifier visible"
            style={{ height: LENS_SIZE, left: lens.left, top: lens.top, width: LENS_SIZE }}
          >
            <iframe
              className="html-document-lens-frame"
              onLoad={syncLensScroll}
              ref={lensFrameRef}
              sandbox="allow-same-origin"
              src={viewerSrc}
              style={{ height: VIRTUAL_SOURCE_HEIGHT, transform: lensTransform, width: VIRTUAL_SOURCE_WIDTH }}
              tabIndex={-1}
              title=""
            />
          </div>
        ) : null}
      </div>
    </section>
  );
}
