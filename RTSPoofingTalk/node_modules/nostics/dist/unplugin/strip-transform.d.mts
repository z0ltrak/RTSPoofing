import { UnpluginInstance } from "unplugin";
import MagicString from "magic-string";

//#region src/unplugin/transform.d.ts
interface TransformOptions {
  /**
  * The package name to detect imports from.
  * @default 'nostics'
  */
  packageName?: string;
}
//#endregion
//#region src/unplugin/strip-transform.d.ts
type NosticsStripOptions = TransformOptions;
/**
* Build-time AST transform that strips diagnostics from production bundles.
*
* Marks `defineDiagnostics()` calls as `/*#__PURE__*\/` and wraps diagnostic
* call sites with a `NODE_ENV !== 'production'` guard so they tree-shake out
* of production builds.
*
* This is an [unplugin](https://github.com/unjs/unplugin) instance. Call the
* adapter for your bundler (`.vite()`, `.rolldown()`, `.rollup()`, `.webpack()`,
* `.rspack()`, `.esbuild()`, `.farm()`) to obtain the actual plugin:
*
* ```ts
* // vite.config.ts
* import { nosticsStrip } from 'nostics/unplugin/strip-transform'
* export default defineConfig({ plugins: [nosticsStrip.vite()] })
* ```
*/
declare const nosticsStrip: UnpluginInstance<NosticsStripOptions | undefined>;
//#endregion
export { NosticsStripOptions, nosticsStrip };
//# sourceMappingURL=strip-transform.d.mts.map