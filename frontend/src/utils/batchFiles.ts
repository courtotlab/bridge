export const SUPPORTED_BATCH_EXTENSIONS = ['.csv', '.tsv', '.xlsx'] as const;

export const BATCH_FILE_ACCEPT = [
  '.csv',
  '.tsv',
  '.xlsx',
  'text/csv',
  'text/tab-separated-values',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
].join(',');

export const UNSUPPORTED_BATCH_FILE_MESSAGE =
  'Unsupported file type. Upload a CSV, TSV, or XLSX file.';

function extensionFor(filename: string): string {
  const dotIndex = filename.lastIndexOf('.');
  if (dotIndex < 0) return '';
  return filename.slice(dotIndex).toLowerCase();
}

export function isSupportedBatchFile(file: File): boolean {
  const extension = extensionFor(file.name);
  return (SUPPORTED_BATCH_EXTENSIONS as readonly string[]).includes(extension);
}
