import { UnpluginInstance } from "unplugin";

//#region src/unplugin/dev-server-collector.d.ts
interface NosticsCollectorOptions {
  /**
  * Path to the log file.
  * @default '.nostics.log'
  */
  logFile?: string;
  /**
  * Enable debug logging for the plugin.
  * @default !!process.env.DEBUG
  */
  debug?: boolean;
  /**
  * Stack frames matching ANY of these patterns are removed from each
  * diagnostic's stack trace before it is written to the log file.
  * Forwarded to {@link createFileReporter}.
  */
  excludeStackFrames?: readonly RegExp[];
}
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
declare const nosticsCollector: UnpluginInstance<NosticsCollectorOptions | undefined>;
//#endregion
export { NosticsCollectorOptions, nosticsCollector };
//# sourceMappingURL=dev-server-collector.d.mts.map