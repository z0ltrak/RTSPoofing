import { C as KitNodeContext, S as CreateKitContextOptions, i as ClientScriptEntry, t as PluginWithDevTools, w as createKitContext } from "../vite-augment-hhsaFnWw.js";
import { DevframeCommandsHost as DevToolsCommandsHost, DevframeDocksHost as DevToolsDockHost, DevframeMessagesHost as DevToolsMessagesHost, DevframeTerminalsHost as DevToolsTerminalHost, mountDevframe } from "@devframes/hub/node";
import { DevframeCapabilities, DevframeViewIframe } from "@devframes/hub/types";
import { ResolvedConfig, ViteDevServer } from "vite";
import { DevframeDefinition, DevframeHost } from "devframe/types";

//#region src/node/create-plugin-from-devframe.d.ts
interface CreatePluginFromDevframeOptions {
  /**
   * Vite plugin name override. Defaults to `devframe:${d.id}`.
   */
  name?: string;
  /**
   * Mount path override. Defaults to `d.basePath` or `/__${d.id}/`.
   */
  base?: string;
  /**
   * Overrides for the auto-synthesized iframe dock entry. Use this to
   * customize the entry's `category`, override the icon, hide it via
   * `when`, etc. Cannot change `id`, `type`, or `url` — those are
   * derived from the devframe definition.
   */
  dock?: Partial<Omit<DevframeViewIframe, 'id' | 'type' | 'url'>>;
  /**
   * Capability flags forwarded onto the kit plugin's `devtools` slot.
   * Defaults to `d.capabilities`.
   */
  capabilities?: DevframeCapabilities | {
    dev?: DevframeCapabilities | boolean;
    build?: DevframeCapabilities | boolean;
  };
  /**
   * Additional kit-only setup hook. Runs after the devframe-level
   * `d.setup(ctx)` and after the auto-derived dock entry has been
   * registered. Use this for kit-specific behavior that should not
   * bleed into the portable {@link DevframeDefinition} — e.g.
   * registering terminals/commands/messages, or enriching the
   * synthesized dock entry.
   */
  setup?: (ctx: KitNodeContext) => void | Promise<void>;
}
/**
 * Wrap a {@link DevframeDefinition} as a Vite plugin that mounts inside
 * `@vitejs/devtools` (Vite DevTools). Delegates the mount work
 * (serving the SPA, registering the iframe dock entry, calling
 * `d.setup(ctx)`) to `@devframes/hub`'s `mountDevframe`, then runs the
 * optional kit-only `options.setup` hook.
 */
declare function createPluginFromDevframe(d: DevframeDefinition, options?: CreatePluginFromDevframeOptions): PluginWithDevTools;
//#endregion
//#region src/node/utils.d.ts
/**
 * Create a quick `ClientScriptEntry` from an inline function or
 * stringified code. Useful for prototyping `action` / `renderer`
 * dock entries without setting up a separate importable module.
 *
 * @experimental Prefer a proper importable module for production use.
 */
declare function createSimpleClientScript(fn: string | ((ctx: any) => void)): ClientScriptEntry;
//#endregion
//#region src/node/vite-host.d.ts
interface CreateViteDevToolsHostOptions {
  viteConfig: ResolvedConfig;
  viteServer?: ViteDevServer;
  /**
   * Workspace root used as the parent of the per-project storage
   * directory. Threaded in by the consumer (typically resolved via
   * `searchForWorkspaceRoot`). Defaults to `viteConfig.root`.
   */
  workspaceRoot?: string;
}
declare function createViteDevToolsHost(options: CreateViteDevToolsHostOptions): DevframeHost;
//#endregion
export { CreateKitContextOptions, CreatePluginFromDevframeOptions, CreateViteDevToolsHostOptions, DevToolsCommandsHost, DevToolsDockHost, DevToolsMessagesHost, DevToolsTerminalHost, KitNodeContext, createKitContext, createPluginFromDevframe, createSimpleClientScript, createViteDevToolsHost, mountDevframe };