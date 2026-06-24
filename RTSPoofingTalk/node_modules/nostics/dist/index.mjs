//#region src/utils.ts
/**
* Transforms a value or a function that returns a value to a value.
*
* @param valFn either a value or a function that returns a value
* @param args  arguments to pass to the function if `valFn` is a function
*
* @internal
*/
function toValueWithArgs(valFn, ...args) {
	return typeof valFn === "function" ? valFn(...args) : valFn;
}
//#endregion
//#region src/diagnostic.ts
/**
* Renders a diagnostic into a multi-line, unicode-decorated string suitable
* for terminal output. The first line is `[<name>] <message>`; optional
* details (`fix`, `sources`, `docs`) follow with `├▶`/`╰▶` connectors.
*/
function formatDiagnostic(diagnostic) {
	const header = `[${diagnostic.name}] ${diagnostic.message}`;
	const details = [];
	if (diagnostic.fix) details.push(`fix: ${diagnostic.fix}`);
	if (diagnostic.sources?.length) details.push(`sources: ${diagnostic.sources.join(", ")}`);
	if (diagnostic.docs) details.push(`see: ${diagnostic.docs}`);
	if (details.length === 0) return header;
	return [header, ...details.map((detail, i) => {
		return `${i < details.length - 1 ? "├▶" : "╰▶"} ${detail}`;
	})].join("\n");
}
function reporterError(diagnostic) {
	console.error(formatDiagnostic(diagnostic));
}
function reporterLog(diagnostic, { method = "warn" } = {}) {
	console[method](formatDiagnostic(diagnostic));
}
const captureStackTrace = Error.captureStackTrace;
var Diagnostic = class Diagnostic extends Error {
	name = "Diagnostic";
	/**
	* URL to extended documentation for this diagnostic code.
	* Auto-generated from {@link DefineDiagnosticsOptions.docsBase}.
	*/
	docs;
	/**
	* Optional actionable instructions on how to resolve the problem.
	*/
	fix;
	/**
	* Locations in user code that contributed to this diagnostic, in
	* `file:line:column` format.
	*/
	sources;
	/**
	* Alias for {@link Error.message}: the reason this diagnostic was raised.
	*/
	get why() {
		return this.message;
	}
	/**
	* @param init        structured initializer; `why` is required
	* @param captureFrom V8 stack-cutoff frame. Defaults to {@link Diagnostic}
	* so the top of the trace is the `new Diagnostic(...)` call site.
	* `defineDiagnostics` passes its action method to strip its own frames too.
	* Ignored on engines without `Error.captureStackTrace`.
	*/
	constructor(init, captureFrom = Diagnostic) {
		super(init.why, { cause: init.cause });
		this.fix = init.fix;
		this.docs = init.docs;
		this.sources = init.sources;
		captureStackTrace?.(this, captureFrom);
	}
	/**
	* Converts the diagnostic into a serializable structured object.
	*/
	toJSON() {
		return {
			name: this.name,
			why: this.why,
			fix: this.fix,
			docs: this.docs,
			sources: this.sources,
			cause: this.cause,
			stack: this.stack
		};
	}
	devOnly;
};
if (process.env.NODE_ENV !== "production") Diagnostic.prototype.devOnly = function devOnly() {
	console.log("This is a dev-only diagnostic");
};
/**
* Creates a typed diagnostics object from a set of code definitions. Each
* code becomes a callable {@link DiagnosticHandle}: invoke to report, or
* `throw` the result to raise. No `new` required, no proxy.
*/
function defineDiagnostics(options) {
	const reporters = options.reporters ?? [];
	const result = {};
	const { docsBase } = options;
	for (const code of Object.keys(options.codes)) {
		const def = options.codes[code];
		const docs = def.docs === false ? void 0 : def.docs || (typeof docsBase === "string" ? `${docsBase}/${code.toLowerCase()}` : docsBase?.(code));
		const handle = (params = {}, reporterOptions = {}) => {
			const diagnostic = new Diagnostic({
				why: toValueWithArgs(def.why, params),
				fix: toValueWithArgs(def.fix, params),
				docs,
				cause: params.cause,
				sources: params.sources
			}, handle);
			diagnostic.name = code;
			for (const reporter of reporters) reporter(diagnostic, reporterOptions);
			return diagnostic;
		};
		result[code] = handle;
	}
	return result;
}
//#endregion
export { Diagnostic, defineDiagnostics, formatDiagnostic, reporterError, reporterLog };

//# sourceMappingURL=index.mjs.map