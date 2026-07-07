from __future__ import annotations

from html import escape
import xml.etree.ElementTree as ET

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


def render_ubl_invoice_preview_html(xml_text: str) -> str:
    root = ET.fromstring(xml_text)
    invoice = build_xml_canonical_invoice(root)
    header = invoice.header
    supplier = invoice.supplier_party
    customer = invoice.customer_party
    totals = invoice.totals

    rows: list[str] = []
    for index, line in enumerate(invoice.line_items, start=1):
        rows.append(
            "<tr>"
            f"<td>{index}</td>"
            f"<td>{escape(_text(line.description))}</td>"
            f"<td class=\"number\">{escape(_text(line.quantity))}</td>"
            f"<td class=\"number\">{escape(_text(line.unit_price))}</td>"
            f"<td class=\"number\">{escape(_text(line.taxable_amount))}</td>"
            f"<td class=\"number\">{escape(_text(line.vat_rate))}</td>"
            f"<td class=\"number\">{escape(_text(line.tax_amount))}</td>"
            f"<td class=\"number\">{escape(_text(line.gross_amount))}</td>"
            "</tr>"
        )
    if not rows:
        rows.append("<tr><td colspan=\"8\" class=\"empty\">Satir bilgisi bulunamadi.</td></tr>")

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
    <section class="totals" aria-label="Fatura toplamlari">
      <div><span>Mal/Hizmet Toplami</span><span>{escape(_text(totals.goods_services_total))}</span></div>
      <div><span>KDV Toplami</span><span>{escape(_text(totals.vat_total))}</span></div>
      <div><span>Vergiler Dahil Toplam</span><span>{escape(_text(totals.tax_inclusive_total))}</span></div>
      <div><strong>Odenecek Tutar</strong><strong>{escape(_text(totals.payable_total))}</strong></div>
    </section>
  </main>
</body>
</html>"""
