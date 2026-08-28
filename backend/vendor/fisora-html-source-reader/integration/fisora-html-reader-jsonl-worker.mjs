// File: integration/fisora-html-reader-jsonl-worker.mjs
// Summary: Keeps one Node process alive and serves path-confined HTML Source Reader requests over newline-delimited JSON on stdin/stdout.

import readline from 'node:readline';
import {
  bridgeErrorPayload,
  readConfinedHtmlFile,
} from './fisora-html-reader-bridge.mjs';

function argument(name) {
  const index = process.argv.indexOf(name);
  if (index < 0 || index + 1 >= process.argv.length) return '';
  return String(process.argv[index + 1] || '').trim();
}

function write(payload) {
  process.stdout.write(`${JSON.stringify(payload)}\n`);
}

const rootInput = argument('--root');
if (!rootInput) {
  write({ ok: false, error: { code: 'HTML_SOURCE_CLI_ARGUMENT_REQUIRED', message: 'Reader root is required.' } });
  process.exit(1);
}

const input = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
for await (const line of input) {
  if (!line.trim()) continue;
  let request;
  try {
    request = JSON.parse(line);
  } catch {
    write({ ok: false, error: { code: 'HTML_SOURCE_REQUEST_INVALID', message: 'Request must be valid JSON.' } });
    continue;
  }

  const id = request?.id ?? null;
  const fileInput = String(request?.file || '').trim();
  try {
    const result = readConfinedHtmlFile(rootInput, fileInput);
    write({ id, ok: true, ...result });
  } catch (error) {
    write({ id, ok: false, error: bridgeErrorPayload(error) });
  }
}
