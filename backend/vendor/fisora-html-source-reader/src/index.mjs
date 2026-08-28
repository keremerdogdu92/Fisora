// Public integration surface for the isolated Fisora HTML Source Reader.
// Internal detector helpers are intentionally not re-exported.

export {
  DEFAULT_MAX_INPUT_BYTES,
  HtmlSourceReaderError,
  readHtmlFile,
  readHtmlSource,
} from './html-source-reader.mjs';

export {
  SNAPSHOT_VERSION,
  validateDocumentSourceSnapshot,
} from './snapshot-contract.mjs';
