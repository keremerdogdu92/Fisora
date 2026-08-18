-- Persist only the opaque configured Gemini credential slot on provider receipts.

alter table document_ai_artifacts
    add column if not exists credential_slot text not null default '';
