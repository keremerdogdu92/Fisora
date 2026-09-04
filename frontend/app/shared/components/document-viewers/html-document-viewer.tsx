// File: frontend/app/shared/components/document-viewers/html-document-viewer.tsx
// Summary: Renders sandboxed HTML invoices with a cursor magnifier and deterministic source-evidence highlighting.
"use client";

import { useEffect, useRef, useState } from "react";
import { findTokenSequence, sourceTokenValues, tokenizeSourceText } from "./document-source-match";
import type { DocumentSourceFocus } from "./document-inspector-types";

type HighlightRect = { height: number; left: number; top: number; width: number };
type LensState = { clientX: number; clientY: number; left: number; top: number; visible: boolean };
type IndexedDomToken = { end: number; node: Text; start: number; value: string };

const LENS_SIZE = 230;
const LENS_ZOOM = 2.2;
const TOUCH_HOLD_MS = 420;

function searchableTextNode(node: Text) {
  const parent = node.parentElement;
  if (!parent) return false;
  return !parent.closest("script, style, noscript, template");
}

function findSourceRange(documentNode: Document, sourceText: string) {
  const needle = sourceTokenValues(sourceText);
  if (!needle.length) return null;
  const tokens: IndexedDomToken[] = [];
  const walker = documentNode.createTreeWalker(documentNode.body || documentNode.documentElement, NodeFilter.SHOW_TEXT);
  let current = walker.nextNode();
  while (current) {
    const textNode = current as Text;
    if (searchableTextNode(textNode)) {
      tokenizeSourceText(textNode.data).forEach((token) => {
        tokens.push({ ...token, node: textNode });
      });
    }
    current = walker.nextNode();
  }
  const values = tokens.map((token) => token.value);
  let fromIndex = 0;
  while (fromIndex < values.length) {
    const match = findTokenSequence(values, needle, fromIndex);
    if (!match) return null;
    const startToken = tokens[match.start];
    const endToken = tokens[match.end];
    const range = documentNode.createRange();
    range.setStart(startToken.node, startToken.start);
    range.setEnd(endToken.node, endToken.end);
    if (range.getClientRects().length) return range;
    fromIndex = match.start + 1;
  }
  return null;
}

export function HtmlDocumentViewer({
  fileName,
  sourceFocus,
  src,
}: {
  fileName: string;
  sourceFocus?: DocumentSourceFocus | null;
  src: string;
}) {
  const stageRef = useRef<HTMLDivElement | null>(null);
  const frameRef = useRef<HTMLIFrameElement | null>(null);
  const lensFrameRef = useRef<HTMLIFrameElement | null>(null);
  const frameCleanupRef = useRef<(() => void) | null>(null);
  const touchTimerRef = useRef<number | null>(null);
  const touchActiveRef = useRef(false);
  const touchStartRef = useRef({ clientX: 0, clientY: 0 });
  const focusRef = useRef<DocumentSourceFocus | null | undefined>(sourceFocus);
  const [frameSize, setFrameSize] = useState({ height: 0, width: 0 });
  const [highlightRects, setHighlightRects] = useState<HighlightRect[]>([]);
  const [lens, setLens] = useState<LensState>({ clientX: 0, clientY: 0, left: 0, top: 0, visible: false });

  focusRef.current = sourceFocus;

  function clearTouchTimer() {
    if (touchTimerRef.current !== null) window.clearTimeout(touchTimerRef.current);
    touchTimerRef.current = null;
  }

  function syncLensScroll() {
    const sourceWindow = frameRef.current?.contentWindow;
    const lensWindow = lensFrameRef.current?.contentWindow;
    if (!sourceWindow || !lensWindow) return;
    lensWindow.scrollTo(sourceWindow.scrollX, sourceWindow.scrollY);
  }

  function updateHighlight(focus: DocumentSourceFocus | null | undefined, allowScroll: boolean) {
    const stage = stageRef.current;
    const frame = frameRef.current;
    const documentNode = frame?.contentDocument;
    const frameWindow = frame?.contentWindow;
    if (!stage || !frame || !documentNode || !frameWindow || !focus?.sourceText) {
      setHighlightRects([]);
      return;
    }
    const range = findSourceRange(documentNode, focus.sourceText);
    if (!range) {
      setHighlightRects([]);
      return;
    }
    const firstRect = range.getBoundingClientRect();
    const outsideViewport = firstRect.bottom < 8 || firstRect.top > frameWindow.innerHeight - 8;
    if (allowScroll && (focus.pinned || outsideViewport)) {
      const targetTop = frameWindow.scrollY + firstRect.top - frameWindow.innerHeight / 2 + firstRect.height / 2;
      frameWindow.scrollTo({ left: frameWindow.scrollX, top: Math.max(0, targetTop), behavior: "auto" });
      window.requestAnimationFrame(() => updateHighlight(focusRef.current, false));
      return;
    }
    const stageRect = stage.getBoundingClientRect();
    const frameRect = frame.getBoundingClientRect();
    setHighlightRects(Array.from(range.getClientRects()).map((rect) => ({
      height: rect.height,
      left: frameRect.left - stageRect.left + rect.left,
      top: frameRect.top - stageRect.top + rect.top,
      width: rect.width,
    })));
  }

  function updateLens(event: PointerEvent) {
    const stage = stageRef.current;
    const frame = frameRef.current;
    if (!stage || !frame) return;
    const stageRect = stage.getBoundingClientRect();
    const frameRect = frame.getBoundingClientRect();
    setLens({
      clientX: event.clientX,
      clientY: event.clientY,
      left: frameRect.left - stageRect.left + event.clientX,
      top: frameRect.top - stageRect.top + event.clientY,
      visible: true,
    });
    syncLensScroll();
  }

  function hideLens() {
    clearTouchTimer();
    touchActiveRef.current = false;
    setLens((current) => ({ ...current, visible: false }));
  }

  function handleFrameLoad() {
    frameCleanupRef.current?.();
    const frame = frameRef.current;
    const frameWindow = frame?.contentWindow;
    const documentNode = frame?.contentDocument;
    if (!frame || !frameWindow || !documentNode) return;

    const measure = () => setFrameSize({ height: frame.clientHeight, width: frame.clientWidth });
    const handleScroll = () => {
      syncLensScroll();
      updateHighlight(focusRef.current, false);
    };
    const handlePointerMove = (event: PointerEvent) => {
      if (event.pointerType === "touch" && !touchActiveRef.current) {
        const distance = Math.hypot(event.clientX - touchStartRef.current.clientX, event.clientY - touchStartRef.current.clientY);
        if (distance > 10) clearTouchTimer();
        return;
      }
      updateLens(event);
    };
    const handlePointerLeave = (event: PointerEvent) => {
      if (event.pointerType !== "touch") hideLens();
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
      if (event.pointerType !== "touch") return;
      hideLens();
    };
    const resizeObserver = new ResizeObserver(measure);
    resizeObserver.observe(frame);
    documentNode.addEventListener("pointermove", handlePointerMove);
    documentNode.addEventListener("pointerleave", handlePointerLeave);
    documentNode.addEventListener("pointerdown", handlePointerDown);
    documentNode.addEventListener("pointerup", handlePointerUp);
    documentNode.addEventListener("pointercancel", handlePointerUp);
    frameWindow.addEventListener("scroll", handleScroll, { passive: true });
    measure();
    syncLensScroll();
    updateHighlight(focusRef.current, true);

    frameCleanupRef.current = () => {
      resizeObserver.disconnect();
      documentNode.removeEventListener("pointermove", handlePointerMove);
      documentNode.removeEventListener("pointerleave", handlePointerLeave);
      documentNode.removeEventListener("pointerdown", handlePointerDown);
      documentNode.removeEventListener("pointerup", handlePointerUp);
      documentNode.removeEventListener("pointercancel", handlePointerUp);
      frameWindow.removeEventListener("scroll", handleScroll);
    };
  }

  useEffect(() => {
    updateHighlight(sourceFocus, true);
  }, [sourceFocus?.key, sourceFocus?.pinned, sourceFocus?.sourceText]);

  useEffect(() => () => {
    clearTouchTimer();
    frameCleanupRef.current?.();
  }, []);

  const lensTransform = `translate(${LENS_SIZE / 2 - lens.clientX * LENS_ZOOM}px, ${LENS_SIZE / 2 - lens.clientY * LENS_ZOOM}px) scale(${LENS_ZOOM})`;

  return (
    <section className="html-document-viewer" aria-label={`${fileName} HTML görüntüleyici`}>
      <div className="html-viewer-stage" ref={stageRef}>
        <iframe
          className="html-document-frame"
          onLoad={handleFrameLoad}
          ref={frameRef}
          sandbox="allow-same-origin"
          src={src}
          title={`${fileName} izole HTML belge`}
        />
        {highlightRects.map((rect, index) => (
          <span
            aria-hidden="true"
            className={`document-source-highlight${sourceFocus?.pinned ? " pinned" : ""}`}
            key={`${sourceFocus?.key || "source"}-${index}`}
            style={{ height: rect.height, left: rect.left, top: rect.top, width: rect.width }}
          />
        ))}
        {lens.visible && frameSize.width > 0 && frameSize.height > 0 ? (
          <div
            aria-hidden="true"
            className="document-magnifier html-document-magnifier"
            style={{ height: LENS_SIZE, left: lens.left, top: lens.top, width: LENS_SIZE }}
          >
            <iframe
              className="html-document-lens-frame"
              onLoad={syncLensScroll}
              ref={lensFrameRef}
              sandbox="allow-same-origin"
              src={src}
              style={{
                height: frameSize.height,
                transform: lensTransform,
                width: frameSize.width,
              }}
              tabIndex={-1}
              title=""
            />
          </div>
        ) : null}
      </div>
    </section>
  );
}
