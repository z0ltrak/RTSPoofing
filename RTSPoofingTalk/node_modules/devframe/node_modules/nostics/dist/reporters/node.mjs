import { appendFileSync } from "node:fs";
//#region src/reporters/node.ts
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
function createFileReporter(options) {
	const logFile = options?.logFile ?? ".nostics.log";
	return (diagnostic) => {
		try {
			appendFileSync(logFile, `${JSON.stringify(diagnostic)}\n`);
		} catch (err) {
			console.error(`[nostics]: Failed to write log to "${logFile}":`, err);
		}
	};
}
//#endregion
export { createFileReporter };

//# sourceMappingURL=node.mjs.map