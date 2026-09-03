// File: frontend/app/portal-next/portal-next-workspace-controls.tsx
// Summary: Provides next-generation accountant keyboard controls, shortcut help, and the desktop shortcut legend without bypassing existing review guards.
"use client";

import { useEffect, useState } from "react";

type WorkspaceControlsProps = {
  active: boolean;
  onNavigateDocument: (direction: 1 | -1) => void;
  onToggleSidebar: () => void;
  onUndoLastApproval: () => void | Promise<boolean>;
  undoAvailable: boolean;
};

function isEditableTarget(target: EventTarget | null) {
  const element = target instanceof HTMLElement ? target : null;
  if (!element) return false;
  return element.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(element.tagName);
}

function focusJournalEditor() {
  const input = document.querySelector<HTMLElement>(".portal-next-theme .journal-ledger input");
  input?.scrollIntoView({ block: "nearest", inline: "nearest" });
  input?.focus();
}function focusClientPeriod() {
  document.querySelector<HTMLSelectElement>(".portal-next-client-select")?.focus();
}

function approveCurrentDocument() {
  document.querySelector<HTMLButtonElement>(".portal-next-theme .journal-primary-approve button:not(:disabled)")?.click();
}

export function PortalNextWorkspaceControls({
  active,
  onNavigateDocument,
  onToggleSidebar,
  onUndoLastApproval,
  undoAvailable,
}: WorkspaceControlsProps) {
  const [helpOpen, setHelpOpen] = useState(false);
  const [legendVisible, setLegendVisible] = useState(true);

  useEffect(() => {
    if (!active) return;
    function onKeyDown(event: globalThis.KeyboardEvent) {
      if (event.defaultPrevented) return;
      const editable = isEditableTarget(event.target);
      if (event.key === "F1") {
        event.preventDefault();
        setHelpOpen(true);
        return;
      }      if (event.key === "F2") {
        event.preventDefault();
        focusJournalEditor();
        return;
      }
      if (event.key === "F3") {
        event.preventDefault();
        focusClientPeriod();
        return;
      }
      if (event.key === "F10") {
        event.preventDefault();
        onToggleSidebar();
        return;
      }
      if (!editable && (event.key === "ArrowUp" || event.key === "ArrowDown")) {
        event.preventDefault();
        onNavigateDocument(event.key === "ArrowDown" ? 1 : -1);
        return;
      }
      if (event.ctrlKey && event.key === "Enter") {
        event.preventDefault();
        approveCurrentDocument();
        return;
      }
      if (!editable && event.ctrlKey && event.key.toLowerCase() === "z" && undoAvailable) {
        event.preventDefault();
        void onUndoLastApproval();
        return;
      }      if (event.key === "Escape" && helpOpen) {
        event.preventDefault();
        setHelpOpen(false);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [active, helpOpen, onNavigateDocument, onToggleSidebar, onUndoLastApproval, undoAvailable]);

  if (!active) return null;
  return (
    <>
      {legendVisible ? (
        <div className="portal-next-shortcut-bar" aria-label="Klavye kısayolları">
          <strong>Klavye kısayolları</strong>
          <span><kbd>F1</kbd> Yardım</span>
          <span><kbd>F2</kbd> Fişi düzenle</span>
          <span><kbd>F3</kbd> Mükellef / dönem</span>
          <span><kbd>F10</kbd> Menüyü daralt / aç</span>
          <span><kbd>↑ ↓</kbd> Evrak değiştir</span>
          <span><kbd>Ctrl + Enter</kbd> Onayla</span>
          <span className={undoAvailable ? "undo-ready" : ""}><kbd>Ctrl + Z</kbd> Geri al</span>
          <span><kbd>Esc</kbd> Kapat</span>
          <button onClick={() => setLegendVisible(false)} type="button">Gizle</button>
        </div>
      ) : (
        <button className="portal-next-shortcut-show" onClick={() => setLegendVisible(true)} type="button">Kısayolları göster</button>
      )}      {helpOpen ? (
        <div className="portal-next-shortcut-modal" role="dialog" aria-modal="true" aria-label="Klavye kısayolları">
          <section>
            <div className="portal-next-shortcut-modal-heading">
              <div><span>Çalışma Masası</span><h2>Klavye kısayolları</h2></div>
              <button onClick={() => setHelpOpen(false)} type="button">Kapat</button>
            </div>
            <dl>
              <div><dt><kbd>F1</kbd></dt><dd>Klavye kısayolları ve yardım</dd></div>
              <div><dt><kbd>F2</kbd></dt><dd>Fiş düzenleme alanına geç</dd></div>
              <div><dt><kbd>F3</kbd></dt><dd>Mükellef ve dönem seçimine geç</dd></div>
              <div><dt><kbd>F10</kbd></dt><dd>Ana menüyü daralt veya aç</dd></div>
              <div><dt><kbd>↑ / ↓</kbd></dt><dd>Evraklar arasında geçiş yap</dd></div>
              <div><dt><kbd>Ctrl + Enter</kbd></dt><dd>Onayla ve sonraki evraka geç</dd></div>
              <div><dt><kbd>Ctrl + Z</kbd></dt><dd>Desteklenen son onayı 8 saniye içinde geri al</dd></div>
              <div><dt><kbd>Esc</kbd></dt><dd>Açık pencereyi veya düzenlemeyi kapat</dd></div>
            </dl>
          </section>
        </div>
      ) : null}
    </>
  );
}