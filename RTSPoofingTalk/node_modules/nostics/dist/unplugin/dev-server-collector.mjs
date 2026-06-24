import { createFileReporter } from "../reporters/node.mjs";
import { createUnplugin } from "unplugin";
import { existsSync, writeFileSync } from "node:fs";
import { relative, resolve } from "node:path";
//#region src/unplugin/dev-server-collector.ts
/**
* Dev-server collector that forwards browser diagnostics to a log file.
*
* Listens on the Vite dev-server WebSocket for diagnostics emitted by
* `devReporter` in the browser and appends them as NDJSON to a local log
* file via `createFileReporter`.
*
* ```ts
* // vite.config.ts
* import { nosticsCollector } from 'nostics/unplugin/dev-server-collector'
* export default defineConfig({ plugins: [nosticsCollector.vite()] })
* ```
*
* Note: Vite only. Other unplugin adapters are no-ops.
*/
const nosticsCollector = createUnplugin((options) => {
	const logFile = options?.logFile ?? ".nostics.log";
	const log = options?.debug ?? !!process.env.DEBUG ? (...args) => console.log("[nostics]", ...args) : () => {};
	const reporter = createFileReporter({
		logFile,
		excludeStackFrames: options?.excludeStackFrames
	});
	return {
		name: "nostics-collector",
		enforce: "pre",
		vite: { configureServer(server) {
			const resolvedLogFile = resolve(server.config.root, logFile);
			if (!existsSync(resolvedLogFile)) writeFileSync(resolvedLogFile, "");
			const displayPath = relative(process.cwd(), resolvedLogFile) || logFile;
			server.config.logger.info(`📋 nostics ··· saving logs to ${displayPath}`);
			log("listening for diagnostics on ws");
			server.ws.on("nostics:report", (data) => {
				log("received diagnostic", data.name ?? data);
				reporter(data, {});
				log("wrote diagnostic to", displayPath);
			});
		} }
	};
});
//#endregion
export { nosticsCollector };

//# sourceMappingURL=dev-server-collector.mjs.map