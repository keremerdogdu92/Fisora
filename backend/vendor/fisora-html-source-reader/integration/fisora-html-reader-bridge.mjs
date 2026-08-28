// File: integration/fisora-html-reader-bridge.mjs
// Summary: Provides a reusable, path-confined bridge around the frozen public HTML Source Reader API for Fisora integration experiments.

import fs from 'node:fs';
import path from 'node:path';
import {
  DEFAULT_MAX_INPUT_BYTES,
  HtmlSourceReaderError,
  readHtmlSource,
  validateDocumentSourceSnapshot,
} from '../src/index.mjs';

const HTML_SUFFIXES = new Set(['.html', '.htm']);

export class HtmlReaderBridgeError extends Error {
  constructor(code, message) {
    super(message);
    this.name = 'HtmlReaderBridgeError';
    this.code = code;
  }
}

function bridgeError(code, message) {
  return new HtmlReaderBridgeError(code, message);
}

function realPath(value, code) {
  try {
    return fs.realpathSync(value);
  } catch {
    throw bridgeError(code, code);
  }
}

export function readConfinedHtmlFile(rootInput, fileInput) {
  if (!rootInput || !fileInput) {
    throw bridgeError('HTML_SOURCE_CLI_ARGUMENT_REQUIRED', 'Reader root and file are required.');
  }
  const root = realPath(rootInput, 'HTML_SOURCE_ROOT_NOT_FOUND');
  const file = realPath(fileInput, 'HTML_SOURCE_FILE_NOT_FOUND');
  const relative = path.relative(root, file);
  if (!relative || relative === '.') {
    throw bridgeError('HTML_SOURCE_FILE_REQUIRED', 'A source HTML file is required.');
  }
  if (relative.startsWith(`..${path.sep}`) || relative === '..' || path.isAbsolute(relative)) {
    throw bridgeError('HTML_SOURCE_FILE_OUTSIDE_ROOT', 'Source file is outside the allowed storage root.');
  }
  if (!HTML_SUFFIXES.has(path.extname(file).toLowerCase())) {
    throw bridgeError('HTML_SOURCE_FILE_TYPE_UNSUPPORTED', 'Only .html and .htm source files are supported.');
  }
  const stat = fs.statSync(file);
  if (!stat.isFile()) {
    throw bridgeError('HTML_SOURCE_FILE_REQUIRED', 'A source HTML file is required.');
  }
  if (stat.size > DEFAULT_MAX_INPUT_BYTES) {
    throw new HtmlSourceReaderError(
      'INPUT_TOO_LARGE',
      `HTML input exceeds ${DEFAULT_MAX_INPUT_BYTES} byte limit`,
      { bytes: stat.size, maxInputBytes: DEFAULT_MAX_INPUT_BYTES },
    );
  }
  const html = fs.readFileSync(file, 'utf8');
  const snapshot = readHtmlSource(html, {
    file: path.basename(relative),
    folder: null,
    bytes: stat.size,
  });
  const contract = validateDocumentSourceSnapshot(snapshot);
  if (!contract.valid) {
    throw bridgeError('HTML_SOURCE_SNAPSHOT_INVALID', 'HTML source snapshot failed contract validation.');
  }
  return { relativePath: relative, snapshot };
}

export function bridgeErrorPayload(error) {
  if (error instanceof HtmlSourceReaderError) {
    return {
      code: error.code || 'HTML_SOURCE_READER_ERROR',
      message: error.message || 'HTML source reader failed.',
    };
  }
  if (error instanceof HtmlReaderBridgeError) {
    return { code: error.code, message: error.message };
  }
  return { code: 'HTML_SOURCE_BRIDGE_FAILED', message: 'HTML source bridge failed.' };
}
