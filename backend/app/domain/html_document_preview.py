# File: backend/app/domain/html_document_preview.py
# Summary: Builds an isolated original-appearance HTML preview with restrictive CSP and inactive browser behaviors.
from __future__ import annotations

import re


HTML_PREVIEW_CSP = (
    "default-src 'none'; "
    "script-src 'none'; "
    "connect-src 'none'; "
    "object-src 'none'; "
    "frame-src 'none'; "
    "child-src 'none'; "
    "base-uri 'none'; "
    "form-action 'none'; "
    "style-src 'unsafe-inline'; "
    "img-src data: blob:; "
    "font-src data:; "
    "media-src data: blob:"
)

_SCRIPT_BLOCK_RE = re.compile(r"<script\b[^>]*>.*?</script\s*>", re.IGNORECASE | re.DOTALL)
_BASE_TAG_RE = re.compile(r"<base\b[^>]*>", re.IGNORECASE)
_META_REFRESH_RE = re.compile(
    r"<meta\b(?=[^>]*http-equiv\s*=\s*['\"]?refresh\b)[^>]*>",
    re.IGNORECASE,
)

_PREVIEW_HEAD = f"""
<meta http-equiv="Content-Security-Policy" content="{HTML_PREVIEW_CSP}">
<meta name="referrer" content="no-referrer">
<style>
  a, form, button, input, select, textarea {{ pointer-events: none !important; }}
</style>
""".strip()


def build_isolated_html_preview(source: bytes | str) -> str:
    """Preserve the source's visual markup while removing active execution/navigation paths."""

    html = source.decode("utf-8-sig", errors="replace") if isinstance(source, bytes) else str(source)
    html = _SCRIPT_BLOCK_RE.sub("", html)
    html = _BASE_TAG_RE.sub("", html)
    html = _META_REFRESH_RE.sub("", html)

    head_match = re.search(r"<head\b[^>]*>", html, re.IGNORECASE)
    if head_match:
        insert_at = head_match.end()
        return f"{html[:insert_at]}\n{_PREVIEW_HEAD}\n{html[insert_at:]}"

    html_match = re.search(r"<html\b[^>]*>", html, re.IGNORECASE)
    if html_match:
        insert_at = html_match.end()
        return f"{html[:insert_at]}\n<head>{_PREVIEW_HEAD}</head>\n{html[insert_at:]}"

    return f"<!doctype html><html><head>{_PREVIEW_HEAD}</head><body>{html}</body></html>"


def html_preview_response_headers() -> dict[str, str]:
    """Return defense-in-depth headers for direct preview responses before blob isolation."""

    return {
        "Cache-Control": "private, no-store",
        "Content-Security-Policy": HTML_PREVIEW_CSP,
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
    }
