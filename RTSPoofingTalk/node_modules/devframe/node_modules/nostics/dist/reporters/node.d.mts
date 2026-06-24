import { s as DiagnosticReporter } from "../diagnostic-BnyAp9xF.mjs";

//#region src/reporters/node.d.ts
interface FileReporterOptions {
  /**
  * Path to the log file.
  * @default '.nostics.log'
  */
  logFile?: string;
}
/**
* Creates a reporter that appends diagnostics as NDJSON to a local file.
* Each diagnostic is written as a single JSON line.
*
* @example
* ```ts
* import { defineDiagnostics } from 'nostics'
* import { createFileReporter } from 'nostics/reporters/node'
*
* const diagnostics = defineDiagnostics({
*   codes: { ... },
*   reporters: [createFileReporter()],
* })
* ```
*/
declare function createFileReporter(options?: FileReporterOptions): DiagnosticReporter;
//#endregion
export { FileReporterOptions, createFileReporter };
//# sourceMappingURL=node.d.mts.map