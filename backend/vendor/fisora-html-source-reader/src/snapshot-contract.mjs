export const SNAPSHOT_VERSION = '1.0.0';

const TOP_KEYS = ['version', 'source', 'mode', 'confidence', 'sections', 'warnings', 'metrics'];
const SOURCE_KEYS = ['file', 'folder', 'bytes'];
const METRIC_KEYS = ['sectionCount', 'rowCount', 'columnCount'];
const SECTION_KEYS = ['kind', 'title', 'columns', 'columnCount', 'rows', 'meta'];
const MODES = new Set(['table', 'section']);
const KINDS = new Set(['table', 'key_value', 'fragmented']);

function isObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function extraKeys(value, allowed) {
  return Object.keys(value).filter(key => !allowed.includes(key));
}

function isNonNegativeInteger(value) {
  return Number.isInteger(value) && value >= 0;
}

function validateStringArray(value) {
  return Array.isArray(value) && value.every(item => typeof item === 'string');
}

export function validateDocumentSourceSnapshot(snapshot) {
  const errors = [];
  if (!isObject(snapshot)) return { valid: false, errors: ['snapshot must be an object'] };
  for (const key of TOP_KEYS) if (!(key in snapshot)) errors.push(`missing top-level key: ${key}`);
  for (const key of extraKeys(snapshot, TOP_KEYS)) errors.push(`unexpected top-level key: ${key}`);

  if (snapshot.version !== SNAPSHOT_VERSION) errors.push(`version must be ${SNAPSHOT_VERSION}`);
  if (!MODES.has(snapshot.mode)) errors.push('mode must be table or section');
  if (typeof snapshot.confidence !== 'number' || snapshot.confidence < 0 || snapshot.confidence > 1) {
    errors.push('confidence must be a number between 0 and 1');
  }

  if (!isObject(snapshot.source)) errors.push('source must be an object');
  else {
    for (const key of SOURCE_KEYS) if (!(key in snapshot.source)) errors.push(`missing source key: ${key}`);
    for (const key of extraKeys(snapshot.source, SOURCE_KEYS)) errors.push(`unexpected source key: ${key}`);
    if (!(typeof snapshot.source.file === 'string' || snapshot.source.file === null)) errors.push('source.file invalid');
    if (!(typeof snapshot.source.folder === 'string' || snapshot.source.folder === null)) errors.push('source.folder invalid');
    if (!isNonNegativeInteger(snapshot.source.bytes)) errors.push('source.bytes invalid');
  }

  if (!Array.isArray(snapshot.sections) || snapshot.sections.length === 0) errors.push('sections must be a non-empty array');
  else snapshot.sections.forEach((section, index) => {
    if (!isObject(section)) { errors.push(`sections[${index}] must be an object`); return; }
    for (const key of ['kind', 'title', 'columns', 'rows']) if (!(key in section)) errors.push(`sections[${index}] missing ${key}`);
    for (const key of extraKeys(section, SECTION_KEYS)) errors.push(`sections[${index}] unexpected key: ${key}`);
    if (!KINDS.has(section.kind)) errors.push(`sections[${index}].kind invalid`);
    if (!(typeof section.title === 'string' || section.title === null)) errors.push(`sections[${index}].title invalid`);
    if (!validateStringArray(section.columns)) errors.push(`sections[${index}].columns invalid`);
    if ('columnCount' in section && !isNonNegativeInteger(section.columnCount)) errors.push(`sections[${index}].columnCount invalid`);
    if (!Array.isArray(section.rows) || !section.rows.every(row => validateStringArray(row))) errors.push(`sections[${index}].rows invalid`);
    if ('meta' in section && !isObject(section.meta)) errors.push(`sections[${index}].meta invalid`);
  });

  if (!validateStringArray(snapshot.warnings)) errors.push('warnings must be an array of strings');
  if (!isObject(snapshot.metrics)) errors.push('metrics must be an object');
  else {
    for (const key of METRIC_KEYS) if (!(key in snapshot.metrics)) errors.push(`missing metrics key: ${key}`);
    for (const key of extraKeys(snapshot.metrics, METRIC_KEYS)) errors.push(`unexpected metrics key: ${key}`);
    for (const key of METRIC_KEYS) if (!isNonNegativeInteger(snapshot.metrics[key])) errors.push(`metrics.${key} invalid`);
  }

  if (Array.isArray(snapshot.sections) && isObject(snapshot.metrics)) {
    const expectedRows = snapshot.sections.reduce((sum, section) => sum + (Array.isArray(section.rows) ? section.rows.length : 0), 0);
    const expectedColumns = Math.max(0, ...snapshot.sections.map(section => Array.isArray(section.columns) && section.columns.length
      ? section.columns.length
      : (Number.isInteger(section.columnCount) ? section.columnCount : 0)));
    if (snapshot.metrics.sectionCount !== snapshot.sections.length) errors.push('metrics.sectionCount mismatch');
    if (snapshot.metrics.rowCount !== expectedRows) errors.push('metrics.rowCount mismatch');
    if (snapshot.metrics.columnCount !== expectedColumns) errors.push('metrics.columnCount mismatch');
  }

  return { valid: errors.length === 0, errors };
}
