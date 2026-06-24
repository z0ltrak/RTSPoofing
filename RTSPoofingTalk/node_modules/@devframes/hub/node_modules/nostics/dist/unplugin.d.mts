import { UnpluginInstance } from "unplugin";
import MagicString from "magic-string";

//#region src/code-transform/transform.d.ts
interface TransformOptions {
  /**
  * The package name to detect imports from.
  * @default 'nostics'
  */
  packageName?: string;
}
//#endregion
//#region src/code-transform/server-plugin.d.ts
interface NosticsServerOptions {
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
}
declare const nosticsServer: UnpluginInstance<NosticsServerOptions | undefined>;
//#endregion
//#region src/code-transform/unplugin.d.ts
type NosticsPluginOptions = TransformOptions;
declare const nostics: UnpluginInstance<NosticsPluginOptions | undefined>;
//#endregion
export { NosticsPluginOptions, type NosticsServerOptions, nostics as default, nostics, nosticsServer };
//# sourceMappingURL=unplugin.d.mts.map