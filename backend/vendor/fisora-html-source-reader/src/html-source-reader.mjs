import fs from 'node:fs';
import * as cheerio from 'cheerio';
import { SNAPSHOT_VERSION } from './snapshot-contract.mjs';

const BLOCKED_TAGS = 'script,style,noscript,svg,canvas,iframe,object,embed';
const SUMMARY_LABEL = /^(?:ara\s+)?toplam\b|^hesaplanan\s+kdv\b|^kdv\s+dahil\b|^odenecek\b|^fatura\s+tutari\b|^vergiler?\s+toplami\b|^yuvarlama\b|^yalniz\b/i;
const MONEY_LIKE = /[-+]?(?:\d{1,3}(?:[., ]\d{3})+|\d+)(?:(?:[.,]\d{2,6})(?:\s*(?:TL|TRY))?|\s*(?:TL|TRY)\b)/i;
const PURE_MONEY_LIKE = /^:?\s*[-+]?(?:\d{1,3}(?:[., ]\d{3})+|\d+)(?:(?:[.,]\d{2,6})(?:\s*(?:TL|TRY))?|\s*(?:TL|TRY))\s*$/i;
const LETTER = /[A-Za-z\u00c0-\u024f\u1e00-\u1eff]/;
const MAX_TABLE_SPAN = 64;
export const DEFAULT_MAX_INPUT_BYTES = 8 * 1024 * 1024;

export class HtmlSourceReaderError extends Error {
  constructor(code, message, details = {}) {
    super(message);
    this.name = 'HtmlSourceReaderError';
    this.code = code;
    this.details = details;
  }
}

function assertInputSize(bytes, maxInputBytes) {
  if (bytes <= maxInputBytes) return;
  throw new HtmlSourceReaderError(
    'INPUT_TOO_LARGE',
    `HTML input exceeds ${maxInputBytes} byte limit`,
    { bytes, maxInputBytes },
  );
}

export function normalizeText(value = '') {
  return String(value)
    .replace(/\u00a0/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function norm(value = '') {
  return normalizeText(value)
    .toLowerCase()
    .replace(/\u0131/g, 'i')
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '');
}
function categories(text) {
  const s = norm(text);
  const result = new Set();
  if (/mal\s*\/?\s*hizmet|mal\s*kodu|mal\s*tanimi|mal(?:in)?\s+cinsi|malzeme|urun|hizmet|aciklama|stok|barkod/.test(s)) result.add('item');
  if (/miktar|mktr|\bmik\b|adet|tuketim/.test(s)) result.add('qty');
  if (/birim\s*fiyat|net\s*fiyat|fiyat/.test(s)) result.add('price');
  if (/iskonto|indirim/.test(s)) result.add('discount');
  if (/kdv\s*(orani|oran|%)|vergi\s*(orani|oran)/.test(s)) result.add('taxrate');
  if (/kdv\s*tutari|vergi\s*tutari/.test(s)) result.add('taxamt');
  if (/tutar|bedel|net toplam|brut toplam|brut tutar/.test(s)) result.add('amount');
  if (/fatura ayrintilari|fatura detayi/.test(s)) result.add('detail');
  return result;
}

function safeCellText($, cell) {
  const root = $(cell);
  if (!root.find('table').length) return normalizeText(root.text());
  const leafCells = root.find('td,th').filter((_, node) => $(node).find('td,th').length === 0).toArray();
  if (!leafCells.length) return normalizeText(root.text());
  return normalizeText(leafCells.map(node => normalizeText($(node).text())).filter(Boolean).join(' '));
}

function directRows($, table) {
  return $(table)
    .find('tr')
    .filter((_, tr) => $(tr).parents('table').first()[0] === table)
    .toArray();
}

function leafTables($) {
  return $('table').filter((_, table) => $(table).find('table').length === 0).toArray();
}

function structuralTables($) {
  return $('table').filter((_, table) => {
    const rows = directRows($, table);
    if (!rows.length) return false;
    return rows.some(tr => {
      const width = $(tr).children('th,td').length;
      return width >= 3 && width <= 30;
    });
  }).toArray();
}
function parseSpan(value) {
  const parsed = Number.parseInt(value ?? '1', 10);
  if (!Number.isFinite(parsed) || parsed <= 0) return 1;
  return Math.min(parsed, MAX_TABLE_SPAN);
}

function tableGrid($, table) {
  const rows = directRows($, table);
  const spans = new Map();
  const grid = [];

  for (const tr of rows) {
    const row = [];
    let col = 0;
    const consumeCarry = () => {
      while (spans.has(col)) {
        row[col] = '';
        const next = spans.get(col) - 1;
        if (next <= 0) spans.delete(col); else spans.set(col, next);
        col += 1;
      }
    };

    consumeCarry();
    for (const cell of $(tr).children('th,td').toArray()) {
      consumeCarry();
      const colspan = parseSpan($(cell).attr('colspan'));
      const rowspan = parseSpan($(cell).attr('rowspan'));
      row[col] = safeCellText($, cell);
      for (let offset = 1; offset < colspan; offset += 1) row[col + offset] = '';
      if (rowspan > 1) {
        for (let offset = 0; offset < colspan; offset += 1) spans.set(col + offset, rowspan - 1);
      }
      col += colspan;
    }

    const maxCarry = spans.size ? Math.max(...spans.keys()) : -1;
    while (col <= maxCarry) {
      if (spans.has(col)) {
        row[col] = '';
        const next = spans.get(col) - 1;
        if (next <= 0) spans.delete(col); else spans.set(col, next);
      }
      col += 1;
    }
    while (row.length && row.at(-1) === '') row.pop();
    if (row.some(Boolean)) grid.push(row);
  }
  return grid;
}

function numericCount(row) {
  return row.filter(value => /\d/.test(value)).length;
}

function nonEmptyCount(row) {
  return row.filter(Boolean).length;
}

function looksLikeSummary(row) {
  const values = row.filter(Boolean);
  if (!values.length) return false;
  const first = norm(values[0]);
  return SUMMARY_LABEL.test(first) && numericCount(row) <= 3;
}
function headerCandidate($, table, tableIndex) {
  const grid = tableGrid($, table);
  let best = null;

  grid.forEach((row, rowIndex) => {
    if (row.length < 2 || row.some(value => value.length > 240)) return;
    const found = categories(row.join(' | '));
    const core = ['qty', 'price', 'taxrate', 'taxamt', 'amount'].filter(key => found.has(key)).length;
    const valid =
      (found.has('item') && core >= 2) ||
      (found.has('qty') && found.has('price') && found.has('amount')) ||
      (found.has('amount') && found.has('discount') && row.length >= 3) ||
      (found.has('detail') && found.has('amount'));
    if (!valid) return;

    const later = grid.slice(rowIndex + 1);
    const numericRows = later.filter(candidate => numericCount(candidate) > 0 && !looksLikeSummary(candidate));
    if (!numericRows.length) return;
    const score = found.size * 10 + Math.min(row.length, 18) + Math.min(numericRows.length, 30);
    if (!best || score > best.score) best = { tableIndex, rowIndex, grid, headers: row, score };
  });

  return best;
}
function extractHeadered(candidate) {
  const { grid, rowIndex, headers, tableIndex } = candidate;
  const targetWidth = headers.length;
  const minimumCells = Math.max(2, Math.ceil(nonEmptyCount(headers) * 0.3));
  const rows = [];

  for (const sourceRow of grid.slice(rowIndex + 1)) {
    const row = sourceRow.slice(0, targetWidth);
    while (row.length < targetWidth) row.push('');
    if (!row.some(Boolean) || numericCount(row) === 0) continue;
    if (looksLikeSummary(row)) continue;
    if (nonEmptyCount(row) < minimumCells) continue;
    rows.push(row);
  }

  return {
    mode: 'table',
    confidence: rows.length ? 0.99 : 0.55,
    sections: [{ kind: 'table', title: null, columns: headers, rows, meta: { tableIndex, headerRowIndex: rowIndex } }],
    warnings: rows.length ? [] : ['header_found_but_no_data_rows'],
  };
}

function headerlessCandidate($, table, tableIndex) {
  const grid = tableGrid($, table);
  const usable = grid.filter(row => row.length >= 3 && LETTER.test(row.join(' ')) && numericCount(row) >= 2 && !looksLikeSummary(row));
  const widths = new Map();
  for (const row of usable) widths.set(row.length, (widths.get(row.length) || 0) + 1);
  const [width, count] = [...widths.entries()].sort((a, b) => b[1] - a[1])[0] || [0, 0];
  if (count < 2 || width < 3) return null;

  const rows = usable.filter(row => row.length === width).map(row => row.slice());
  return { tableIndex, width, count, rows, score: count * 10 + width };
}

function extractHeaderless(candidate) {
  return {
    mode: 'table',
    confidence: candidate.count >= 3 ? 0.92 : 0.86,
    sections: [{
      kind: 'table',
      title: null,
      columns: [],
      columnCount: candidate.width,
      rows: candidate.rows,
      meta: { tableIndex: candidate.tableIndex, sourceHadHeaders: false },
    }],
    warnings: ['source_table_has_no_detected_header'],
  };
}

function moneyValue(text) {
  const match = normalizeText(text).match(MONEY_LIKE);
  return match ? match[0] : null;
}
function labelValuePairs($) {
  const rows = [];
  const seen = new Set();
  const cue = /ucret|tutar|bedel|paket|internet|telefon|gsm|kdv|oiv|ozel\s+iletisim\s+vergisi|indirim|devir|yuvarlama|toplam|aylik|tuketim|enerji/i;

  $('tr').each((_, tr) => {
    const directCells = $(tr).children('th,td');
    if (directCells.find('table').length > 0) return;
    const values = directCells.toArray().map(cell => safeCellText($, cell)).filter(Boolean);
    if (values.length < 2 || values.length > 4) return;
    const label = normalizeText(values[0]);
    const value = normalizeText(values.at(-1));
    if (!LETTER.test(label) || label.length > 220 || value.length > 100 || !moneyValue(value)) return;
    const normalizedLabel = norm(label);
    const shortServiceLabel = label.length <= 60 && /internet|telefon|gsm/.test(normalizedLabel);
    const financialLabel = /ucret|tutar|bedel|paket|kdv|oiv|ozel\s+iletisim\s+vergisi|indirim|devir|yuvarlama|toplam|aylik|tuketim|enerji/.test(normalizedLabel);
    if (!financialLabel && !shortServiceLabel) return;
    if (!/(?:TL|TRY)\b/i.test(value) && /\d{1,2}[./-]\d{1,2}[./-]\d{2,4}/.test(value)) return;
    const key = `${label}\u0000${value}`;
    if (!seen.has(key)) { seen.add(key); rows.push([label, value]); }
  });
  return rows;
}

function headingValuePairs($) {
  const rows = [];
  const seen = new Set();
  const headings = $('h1,h2,h3,h4,h5,h6').toArray();

  for (const valueHeading of headings) {
    const rawValue = safeCellText($, valueHeading);
    if (!PURE_MONEY_LIKE.test(rawValue)) continue;

    let block = $(valueHeading).parent();
    let parts = [];
    for (let depth = 0; depth < 5 && block.length; depth += 1) {
      parts = block.find('h1,h2,h3,h4,h5,h6').toArray()
        .map(node => safeCellText($, node)).filter(Boolean);
      const prior = parts.slice(0, -1).filter(value => value !== ':');
      if (parts.length >= 2 && parts.length <= 6 && prior.some(value => LETTER.test(value))) break;
      block = block.parent();
    }

    if (parts.length < 2 || parts.length > 6) continue;
    const labelParts = parts.slice(0, -1).filter(value => value !== ':');
    if (!labelParts.length || !labelParts.some(value => LETTER.test(value))) continue;
    const label = normalizeText(labelParts.join(' '));
    if (!label || label.length > 260) continue;
    const value = rawValue.replace(/^:\s*/, '');
    const key = `${label}\\u0000${value}`;
    if (!seen.has(key)) { seen.add(key); rows.push([label, value]); }
  }
  return rows;
}

function trailingAmountBlocks($) {
  const rows = [];
  const seen = new Set();
  const selector = 'td,th,p,li,span,div';
  const cue = /ucret|tutar|bedel|paket|internet|telefon|gsm|kdv|oiv|indirim|devir|yuvarlama|toplam|aylik|tuketim|enerji/i;

  $(selector).each((_, element) => {
    const text = safeCellText($, element);
    if (!text || text.length > 260 || !cue.test(norm(text))) return;
    const match = text.match(/^(.*?\D)\s+([-+]?\d{1,3}(?:[. ]\d{3})*(?:[,.]\d{2,6})|[-+]?\d+[,.]\d{2,6})(?:\s*(TL|TRY))?$/i);
    if (!match) return;
    const label = normalizeText(match[1]);
    const value = normalizeText(`${match[2]}${match[3] ? ` ${match[3]}` : ''}`);
    if (!label || label.length > 220) return;
    const key = `${label}\u0000${value}`;
    if (!seen.has(key)) { seen.add(key); rows.push([label, value]); }
  });
  return rows;
}

function conciseNumericRows($) {
  const rows = [];
  const seen = new Set();
  $('tr').each((_, tr) => {
    const values = $(tr).children('th,td').toArray().map(cell => safeCellText($, cell)).filter(Boolean);
    if (values.length < 2 || values.length > 8) return;
    if (!LETTER.test(values.join(' ')) || numericCount(values) < 1) return;
    if (values.some(value => value.length > 300)) return;
    const key = values.join('\u0000');
    if (!seen.has(key)) { seen.add(key); rows.push(values); }
  });
  return rows;
}

function bodySignature($) {
  return norm($('body').text());
}
function extractServiceSummary($) {
  let rows = labelValuePairs($);
  const warnings = [];
  if (rows.length < 2) {
    rows = headingValuePairs($);
    warnings.push('service_summary_used_heading_pair_fallback');
  }
  if (rows.length < 2) {
    rows = trailingAmountBlocks($);
    warnings.push('service_summary_used_text_block_fallback');
  }
  if (rows.length < 2) {
    rows = conciseNumericRows($);
    warnings.push('service_summary_used_numeric_row_fallback');
  }
  return {
    mode: 'section',
    confidence: rows.length >= 3 ? 0.88 : rows.length ? 0.68 : 0.25,
    sections: [{ kind: 'key_value', title: null, columns: [], rows }],
    warnings: rows.length ? warnings : [...warnings, 'service_summary_no_rows_extracted'],
  };
}

function extractFragmentedEnergy($) {
  const rows = conciseNumericRows($).filter(row => {
    const joined = row.join(' ');
    return MONEY_LIKE.test(joined) && /enerji|tuketim|kdv|bedel|tutar|toplam/i.test(norm(joined));
  });
  return {
    mode: 'section',
    confidence: rows.length ? 0.78 : 0.3,
    sections: [{ kind: 'fragmented', title: null, columns: [], rows }],
    warnings: rows.length ? ['fragmented_layout_preserved_as_source_rows'] : ['fragmented_layout_no_rows_extracted'],
  };
}

function extractGenericPairs($) {
  const rows = labelValuePairs($);
  return {
    mode: 'section',
    confidence: rows.length >= 3 ? 0.72 : rows.length ? 0.55 : 0.2,
    sections: [{ kind: 'key_value', title: null, columns: [], rows }],
    warnings: ['generic_label_value_fallback'],
  };
}
export function readHtmlSource(html, meta = {}, options = {}) {
  const sourceHtml = String(html);
  const bytes = Buffer.byteLength(sourceHtml);
  const maxInputBytes = options.maxInputBytes ?? DEFAULT_MAX_INPUT_BYTES;
  assertInputSize(bytes, maxInputBytes);
  const $ = cheerio.load(sourceHtml, { xml: false });
  $(BLOCKED_TAGS).remove();

  const tables = structuralTables($);
  const leafs = leafTables($);
  let bestHeader = null;
  tables.forEach((table, index) => {
    const candidate = headerCandidate($, table, index);
    if (candidate && (!bestHeader || candidate.score > bestHeader.score)) bestHeader = candidate;
  });

  let result;
  if (bestHeader) {
    result = extractHeadered(bestHeader);
  } else {
    const signature = bodySignature($);
    const summaryLike = /fatura ozeti/.test(signature) && /net tutar|tutar|bedel/.test(signature);
    const serviceLike = (/ucret|tarife|paket|internet|telefon|gsm/.test(signature) && /fatura tutari|odenecek/.test(signature)) || summaryLike;
    const energyLike = /enerji/.test(signature) && /tuketim/.test(signature) && /fatura tutari|odenecek/.test(signature);

    if (energyLike) result = extractFragmentedEnergy($);
    else if (serviceLike) result = extractServiceSummary($);
    else {
      let bestHeaderless = null;
      const headerlessTables = [...new Set([...leafs, ...tables])];
      headerlessTables.forEach((table, index) => {
        const candidate = headerlessCandidate($, table, index);
        if (candidate && (!bestHeaderless || candidate.score > bestHeaderless.score)) bestHeaderless = candidate;
      });
      result = bestHeaderless ? extractHeaderless(bestHeaderless) : extractGenericPairs($);
    }
  }
  const rowCount = result.sections.reduce((sum, section) => sum + section.rows.length, 0);
  return {
    version: SNAPSHOT_VERSION,
    source: {
      file: meta.file ?? null,
      folder: meta.folder ?? null,
      bytes,
    },
    mode: result.mode,
    confidence: result.confidence,
    sections: result.sections,
    warnings: result.warnings,
    metrics: {
      sectionCount: result.sections.length,
      rowCount,
      columnCount: Math.max(0, ...result.sections.map(section => section.columns?.length || section.columnCount || 0)),
    },
  };
}

export function readHtmlFile(filePath, options = {}) {
  const bytes = fs.statSync(filePath).size;
  const maxInputBytes = options.maxInputBytes ?? DEFAULT_MAX_INPUT_BYTES;
  assertInputSize(bytes, maxInputBytes);
  const html = fs.readFileSync(filePath, 'utf8');
  return readHtmlSource(html, {
    file: filePath,
    folder: null,
    bytes,
  }, options);
}




