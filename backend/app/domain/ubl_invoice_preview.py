from __future__ import annotations

from decimal import Decimal, InvalidOperation
from html import escape
import re
import xml.etree.ElementTree as ET

from app.domain.canonical_invoices import CanonicalInvoice, CanonicalVatSummaryLine
from app.domain.xml_invoices import build_xml_canonical_invoice


def _text(value: object) -> str:
    text = "" if value is None else str(value).strip()
    return text or "-"


def _detail_row(label: str, value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return f"<div><dt>{escape(label)}</dt><dd>{escape(text)}</dd></div>"


def _party_block(label: str, title: str, tax_id: str, tax_office: str, address: str) -> str:
    details = (
        _detail_row("Vergi/TCKN", tax_id)
        + _detail_row("Vergi dairesi", tax_office)
        + _detail_row("Adres", address)
    )
    return f"""
      <section class="party-block">
        <h2>{escape(label)}</h2>
        <strong>{escape(_text(title))}</strong>
        {f"<dl>{details}</dl>" if details else ""}
      </section>
    """


def _safe_anchor(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9]+", "-", str(value or "").strip())
    return normalized.strip("-") or "unknown"


def _money(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "-"
    compact = raw.replace(" ", "")
    if "," in compact:
        compact = compact.replace(".", "").replace(",", ".")
    try:
        amount = Decimal(compact).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return _text(value)
    whole, fraction = f"{amount:.2f}".split(".")
    return f"{int(whole):,}".replace(",", ".") + f",{fraction}"


def _money_sum(left: str, right: str) -> str:
    return _sum_money((left, right))


def _sum_money(values: tuple[str, ...]) -> str:
    try:
        parsed_values = []
        for value in values:
            compact = str(value or "").strip().replace(" ", "")
            if not compact:
                return ""
            if "," in compact:
                compact = compact.replace(".", "").replace(",", ".")
            parsed_values.append(Decimal(compact))
        return f"{sum(parsed_values):.2f}"
    except (InvalidOperation, ValueError):
        return ""


def _vat_group_label(group: CanonicalVatSummaryLine) -> str:
    label = f"KDV %{_text(group.rate)}"
    if str(group.exemption_reason_code or "").strip():
        label += f" — İstisna {group.exemption_reason_code.strip()}"
    return label


def _source_lines_html(source_lines: list[tuple[int, str]]) -> str:
    if not source_lines:
        return "-"
    visible = ", ".join(str(number) for number, _ in source_lines[:5])
    remaining = len(source_lines) - 5
    if remaining > 0:
        visible += f" +{remaining} satır"
    full_label = "Satırlar " + ", ".join(str(number) for number, _ in source_lines)
    links = ", ".join(
        f'<a href="#invoice-line-{anchor}" aria-label="Fatura satırı {number}">{number}</a>'
        for number, anchor in source_lines
    )
    return (
        f'<span class="source-lines" aria-label="{escape(full_label)}">'
        f'<span aria-hidden="true">Satırlar {escape(visible)}</span>'
        f'<span class="sr-only">{escape(full_label)}</span>'
        f'<span class="source-line-links">{links}</span>'
        "</span>"
    )


def _vat_mismatch_details(invoice: CanonicalInvoice, group: CanonicalVatSummaryLine) -> str:
    group_id = str(group.vat_group_id or "").strip()
    group_evidence = tuple(item for item in invoice.validation.evidence if group_id and group_id in item)
    reasons = tuple(reason for reason in invoice.validation.reason_codes if reason.startswith("vat_group_"))
    if not group_evidence or not reasons:
        return ""
    evidence = ", ".join(group_evidence or group.evidence) or "Kanıt yolu yok"
    reason_text = ", ".join(reasons)
    contributing_lines = tuple(
        line for line in invoice.line_items if line.canonical_line_id in group.contributing_line_ids
    )
    line_ids = ", ".join(line.canonical_line_id for line in contributing_lines) or "Yok"
    source_paths = ", ".join(line.source_position for line in contributing_lines if line.source_position) or evidence
    calculated_taxable = _money(_sum_money(tuple(line.taxable_amount for line in contributing_lines)))
    calculated_tax = _money(_sum_money(tuple(line.tax_amount for line in contributing_lines)))
    return (
        "<details class=\"vat-mismatch\">"
        "<summary>Kaynak doğrulama ayrıntısı</summary>"
        f"<p>Neden kodu: <code>{escape(reason_text)}</code></p>"
        f"<p>Canonical satırlar: <code>{escape(line_ids)}</code></p>"
        f"<p>UBL kaynakları: <code>{escape(source_paths)}</code></p>"
        f"<p>Beyan edilen matrah/KDV: {_money(group.taxable_amount)} / {_money(group.tax_amount)}</p>"
        f"<p>Hesaplanan satır matrahı/KDV: {calculated_taxable} / {calculated_tax}</p>"
        "</details>"
    )


def _vat_distribution_rows(invoice: CanonicalInvoice) -> str:
    line_number_by_id = {
        line.canonical_line_id: index
        for index, line in enumerate(invoice.line_items, start=1)
    }
    rows: list[str] = []
    for group in invoice.vat_summary:
        source_lines = [
            (line_number_by_id[line_id], _safe_anchor(line_id))
            for line_id in group.contributing_line_ids
            if line_id in line_number_by_id
        ]
        gross = _money_sum(group.taxable_amount, group.tax_amount)
        anchor_id = _safe_anchor(group.vat_group_id)
        mismatch_details = _vat_mismatch_details(invoice, group)
        rows.append(
            "<tr "
            f'id="vat-group-{anchor_id}">'
            f"<td>{escape(_vat_group_label(group))}</td>"
            f"<td>{_source_lines_html(source_lines)}</td>"
            f'<td class="number">{escape(_money(group.taxable_amount))}</td>'
            f'<td class="number">{escape(_money(group.tax_amount))}</td>'
            f'<td class="number">{escape(_money(gross))}</td>'
            "</tr>"
            + (f'<tr class="vat-mismatch-row"><td colspan="5">{mismatch_details}</td></tr>' if mismatch_details else "")
        )
    return "".join(rows)


def render_ubl_invoice_preview_html(xml_text: str) -> str:
    root = ET.fromstring(xml_text)
    invoice = build_xml_canonical_invoice(root)
    header = invoice.header
    supplier = invoice.supplier_party
    customer = invoice.customer_party
    totals = invoice.totals

    rows: list[str] = []
    for index, line in enumerate(invoice.line_items, start=1):
        line_anchor = _safe_anchor(line.canonical_line_id)
        group_anchor = _safe_anchor(line.vat_group_id)
        rows.append(
            f'<tr id="invoice-line-{line_anchor}">'
            f"<td>{index}</td>"
            f"<td>{escape(_text(line.description))}</td>"
            f"<td class=\"number\">{escape(_text(line.quantity))}</td>"
            f"<td class=\"number\">{escape(_text(line.unit_price))}</td>"
            f"<td class=\"number\">{escape(_text(line.taxable_amount))}</td>"
            f'<td class="number"><a class="vat-group-badge" href="#vat-group-{group_anchor}">KDV %{escape(_text(line.vat_rate))}</a></td>'
            f"<td class=\"number\">{escape(_text(line.tax_amount))}</td>"
            f"<td class=\"number\">{escape(_text(line.gross_amount))}</td>"
            "</tr>"
        )
    if not rows:
        rows.append("<tr><td colspan=\"8\" class=\"empty\">Satir bilgisi bulunamadi.</td></tr>")
    vat_distribution_rows = _vat_distribution_rows(invoice)

    return f"""<!doctype html>
<html lang="tr">
<head>
  <meta charset="utf-8" />
  <style>
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: #eef1f5;
      color: #111827;
      font-family: Arial, Helvetica, sans-serif;
      font-size: 12px;
      line-height: 1.35;
    }}
    .page {{
      width: 920px;
      max-width: calc(100vw - 28px);
      min-height: calc(100vh - 28px);
      margin: 14px auto;
      padding: 28px;
      background: #fff;
      box-shadow: 0 2px 12px rgba(15, 23, 42, .16);
    }}
    header {{
      display: flex;
      justify-content: space-between;
      gap: 28px;
      border-bottom: 2px solid #111827;
      padding-bottom: 14px;
    }}
    h1 {{
      margin: 0;
      font-size: 24px;
      font-weight: 700;
      letter-spacing: 0;
    }}
    h2 {{
      margin: 0 0 8px;
      font-size: 12px;
      color: #4b5563;
      letter-spacing: 0;
      text-transform: uppercase;
    }}
    .meta {{
      display: grid;
      grid-template-columns: auto auto;
      gap: 6px 18px;
      text-align: right;
    }}
    .meta span, dt {{ color: #6b7280; }}
    .parties {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 18px;
      margin: 22px 0;
    }}
    .party-block {{
      border: 1px solid #d1d5db;
      padding: 14px;
      min-height: 150px;
    }}
    .party-block strong {{
      display: block;
      min-height: 34px;
      font-size: 14px;
    }}
    dl {{
      display: grid;
      gap: 6px;
      margin: 10px 0 0;
    }}
    dd {{ margin: 0; }}
    table {{
      width: 100%;
      border-collapse: collapse;
      table-layout: fixed;
    }}
    th, td {{
      border: 1px solid #d1d5db;
      padding: 8px;
      vertical-align: top;
      overflow-wrap: anywhere;
    }}
    th {{
      background: #f8fafc;
      text-align: left;
      font-weight: 700;
    }}
    th:first-child, td:first-child {{ width: 42px; text-align: center; }}
    .number {{
      text-align: right;
      white-space: nowrap;
    }}
    .empty {{
      color: #6b7280;
      text-align: center;
    }}
    a {{ color: inherit; }}
    a:focus-visible, summary:focus-visible {{
      outline: 3px solid #111827;
      outline-offset: 2px;
      text-decoration: underline;
    }}
    .vat-group-badge {{
      display: inline-block;
      border: 1px solid #374151;
      border-radius: 999px;
      padding: 2px 6px;
      font-weight: 700;
      text-decoration: none;
    }}
    .vat-distribution {{ margin-top: 18px; }}
    .vat-distribution h2 {{ text-transform: none; }}
    .vat-distribution th:first-child, .vat-distribution td:first-child {{ width: auto; text-align: left; }}
    .table-scroll {{ overflow-x: auto; }}
    .source-line-links {{ display: block; margin-top: 4px; }}
    .source-line-links a {{ margin-right: 5px; }}
    .sr-only {{
      position: absolute;
      width: 1px;
      height: 1px;
      padding: 0;
      margin: -1px;
      overflow: hidden;
      clip: rect(0, 0, 0, 0);
      white-space: nowrap;
      border: 0;
    }}
    .vat-mismatch-row td {{ background: #fff; }}
    .vat-mismatch {{ padding: 4px 0; }}
    .vat-mismatch summary {{ cursor: pointer; font-weight: 700; }}
    .vat-mismatch p {{ margin: 6px 0 0; }}
    .totals {{
      width: 360px;
      max-width: 100%;
      margin: 18px 0 0 auto;
      border-top: 2px solid #111827;
    }}
    .totals div {{
      display: flex;
      justify-content: space-between;
      gap: 18px;
      border-bottom: 1px solid #e5e7eb;
      padding: 8px 0;
    }}
    .totals strong {{ font-size: 14px; }}
    @media (max-width: 760px) {{
      .page {{ padding: 16px; }}
      header, .parties {{ grid-template-columns: 1fr; display: grid; }}
      .meta {{ text-align: left; }}
      table {{ font-size: 11px; }}
      th, td {{ padding: 6px; }}
    }}
  </style>
</head>
<body>
  <main class="page">
    <header>
      <h1>Fatura</h1>
      <section class="meta" aria-label="Fatura bilgileri">
        <span>Fatura No</span><strong>{escape(_text(header.invoice_no))}</strong>
        <span>Tarih</span><strong>{escape(_text(header.issue_date))}</strong>
        <span>Senaryo</span><strong>{escape(_text(header.scenario))}</strong>
        <span>Tip</span><strong>{escape(_text(header.invoice_type))}</strong>
      </section>
    </header>
    <section class="parties">
      {_party_block("Satici", supplier.title, supplier.tax_id, supplier.tax_office, supplier.address)}
      {_party_block("Alici", customer.title, customer.tax_id, customer.tax_office, customer.address)}
    </section>
    <table aria-label="Fatura satirlari">
      <thead>
        <tr>
          <th>No</th><th>Mal Hizmet</th><th>Miktar</th><th>Birim Fiyat</th>
          <th>Matrah</th><th>KDV %</th><th>KDV</th><th>Toplam</th>
        </tr>
      </thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
    {f'''<section class="vat-distribution" aria-labelledby="vat-distribution-heading">
      <h2 id="vat-distribution-heading">KDV dağılımı</h2>
      <div class="table-scroll" tabindex="0" aria-label="KDV dağılımı tablosu">
        <table aria-label="KDV dağılımı">
          <thead><tr><th>KDV grubu</th><th>İlgili satırlar</th><th>Matrah</th><th>KDV</th><th>Grup toplamı</th></tr></thead>
          <tbody>{vat_distribution_rows}</tbody>
        </table>
      </div>
    </section>''' if vat_distribution_rows else ''}
    <section class="totals" aria-label="Fatura toplamlari">
      <div><span>Mal/Hizmet Toplami</span><span>{escape(_text(totals.goods_services_total))}</span></div>
      <div><span>KDV Toplami</span><span>{escape(_text(totals.vat_total))}</span></div>
      <div><span>Vergiler Dahil Toplam</span><span>{escape(_text(totals.tax_inclusive_total))}</span></div>
      <div><strong>Odenecek Tutar</strong><strong>{escape(_text(totals.payable_total))}</strong></div>
    </section>
  </main>
</body>
</html>"""
