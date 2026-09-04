// File: frontend/app/shared/components/document-viewers/html-document-viewer.tsx
// Summary: Renders sandboxed HTML with shared fit controls and safe source-text locator highlighting.
"use client";

import { useEffect, useRef, useState } from "react";
import type { DocumentSourceTarget } from "../../../portal-types";

type FitMode = "page" | "width" | "custom";
type HtmlDocumentViewerProps = {
  fileName: string;
  src: string;
  sourceTarget?: DocumentSourceTarget | null;
  onClearSourceTarget?: () => void;
};

const MIN_ZOOM = 0.35;
const MAX_ZOOM = 3;
const VIRTUAL_SOURCE_WIDTH = 960;
const VIRTUAL_SOURCE_HEIGHT = 1280;
const SOURCE_TARGET_ID = "fisora-source-target";

function clampZoom(value: number) {
  return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, value));
}

function normalizeLocatorText(value: string) {
  return String(value || "")
    .normalize("NFKC")
    .toLocaleLowerCase("tr-TR")
    .replace(/\u00a0/g, " ")
    .replace(/\s+/g, " ")
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .trim();
}
function locatorTextForElement(element: HTMLElement) {
  if (element.tagName === "TR") {
    return normalizeLocatorText(Array.from(element.querySelectorAll("th,td")).map((cell) => cell.textContent || "").join(" "));
  }
  return normalizeLocatorText(element.textContent || "");
}

function tokenOverlapScore(candidate: string, needle: string) {
  const targetTokens = new Set(needle.split(" ").filter((token) => token.length > 1));
  if (!targetTokens.size) return 0;
  const candidateTokens = new Set(candidate.split(" "));
  const overlap = [...targetTokens].filter((token) => candidateTokens.has(token)).length;
  return overlap / targetTokens.size;
}

function findBestSourceElement(document: Document, target: DocumentSourceTarget) {
  const needle = normalizeLocatorText(target.text);
  if (!needle) return null;
  const tableRows = Array.from(document.querySelectorAll<HTMLTableRowElement>("tr"))
    .filter((row) => row.querySelector("td"));
  const exactRow = tableRows
    .map((element) => ({ element, text: locatorTextForElement(element) }))
    .filter((candidate) => candidate.text.includes(needle) || needle.includes(candidate.text))
    .sort((a, b) => a.text.length - b.text.length)[0];
  if (exactRow) return exactRow.element;

  const scoredRows = tableRows
    .map((element) => ({ element, text: locatorTextForElement(element) }))
    .map((candidate) => ({ ...candidate, score: tokenOverlapScore(candidate.text, needle) }))
    .filter((candidate) => candidate.score >= 0.55)
    .sort((a, b) => b.score - a.score || a.text.length - b.text.length);
  if (scoredRows.length) return scoredRows[0].element;

  const sourceIndex = Number.parseInt(String(target.sourcePosition || ""), 10);
  if (Number.isInteger(sourceIndex) && sourceIndex > 0 && tableRows[sourceIndex - 1]) {
    return tableRows[sourceIndex - 1];
  }

  const selectors = "td,th,p,li,span,strong,b,div";
  const candidates = Array.from(document.querySelectorAll<HTMLElement>(selectors))
    .map((element) => ({ element, text: locatorTextForElement(element) }))
    .filter((candidate) => candidate.text)
    .map((candidate) => ({ ...candidate, score: tokenOverlapScore(candidate.text, needle) }))
    .filter((candidate) => candidate.text.includes(needle) || candidate.score >= 0.6)
    .sort((a, b) => b.score - a.score || a.text.length - b.text.length);
  return candidates[0]?.element ?? null;
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
  const [fitMode, setFitMode] = useState<FitMode>("page");
  const [customZoom, setCustomZoom] = useState(1);
  const [stageSize, setStageSize] = useState({ width: 0, height: 0 });
  const [focusedSrc, setFocusedSrc] = useState("");
  const [sourceMatchStatus, setSourceMatchStatus] = useState("");

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
    if (!sourceTarget) {
      setFocusedSrc("");
      setSourceMatchStatus("");
      return undefined;
    }
    let active = true;
    let objectUrl = "";
    setFitMode("custom");
    setCustomZoom(1);
    void (async () => {
      try {
        const response = await fetch(src, { cache: "no-store" });
        const rawHtml = await response.text();
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
  }, [sourceTarget?.key, src]);

  const availableWidth = Math.max(stageSize.width - 24, 120);
  const availableHeight = Math.max(stageSize.height - 24, 160);
  const fitPageScale = Math.min(1, availableWidth / VIRTUAL_SOURCE_WIDTH, availableHeight / VIRTUAL_SOURCE_HEIGHT);
  const fitWidthScale = Math.min(1, availableWidth / VIRTUAL_SOURCE_WIDTH);
  const effectiveScale = fitMode === "page" ? fitPageScale : fitMode === "width" ? fitWidthScale : customZoom;

  function applyCustomZoom(nextScale: number) {
    setFitMode("custom");
    setCustomZoom(clampZoom(nextScale));
  }

  function clearSourceFocus() {
    setFocusedSrc("");
    setSourceMatchStatus("");
    setFitMode("page");
    onClearSourceTarget?.();
  }
  const viewerSrc = sourceTarget && focusedSrc ? `${focusedSrc}#${SOURCE_TARGET_ID}` : src;
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
        {sourceTarget ? (
          <div className="document-source-focus-controls">
            <span>{sourceMatchStatus || "Kaynak aranıyor…"}</span>
            <button onClick={clearSourceFocus} type="button">Tam belgeye dön</button>
          </div>
        ) : null}
      </div>
      <div className="html-viewer-stage" ref={stageRef}>
        <div className="html-viewer-canvas" style={{ height: `${VIRTUAL_SOURCE_HEIGHT * effectiveScale}px`, width: `${VIRTUAL_SOURCE_WIDTH * effectiveScale}px` }}>
          <iframe
            className="html-viewer-frame"
            sandbox=""
            src={viewerSrc}
            style={{ height: `${VIRTUAL_SOURCE_HEIGHT}px`, transform: `scale(${effectiveScale})`, width: `${VIRTUAL_SOURCE_WIDTH}px` }}
            title={`${fileName} izole orijinal HTML`}
          />
        </div>
      </div>
    </section>
  );
}
