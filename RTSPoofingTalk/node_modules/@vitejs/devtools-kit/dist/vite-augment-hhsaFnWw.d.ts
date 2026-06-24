import { CreateHubContextOptions, DevframeHubContext } from "@devframes/hub/node";
import { ClientScriptEntry, DevframeCapabilities, DevframeDockEntriesGrouped as DevToolsDockEntriesGrouped, DevframeDockEntry as DevToolsDockEntry, DevframeDockEntryBase as DevToolsDockEntryBase, DevframeDockEntryCategory, DevframeDockEntryIcon as DevToolsDockEntryIcon, DevframeDockUserEntry as DevToolsDockUserEntry, DevframeDocksHost as DevToolsDockHost, DevframeViewAction as DevToolsViewAction, DevframeViewBuiltin as DevToolsViewBuiltin, DevframeViewCustomRender as DevToolsViewCustomRender, DevframeViewGroup as DevToolsViewGroup, DevframeViewIframe as DevToolsViewIframe, DevframeViewJsonRender as DevToolsViewJsonRender, DevframeViewLauncher as DevToolsViewLauncher, DevframeViewLauncherStatus as DevToolsViewLauncherStatus, RemoteConnectionInfo, RemoteDockOptions } from "@devframes/hub/types";
import { Plugin, ResolvedConfig, ViteDevServer } from "vite";

//#region src/node/context.d.ts
/**
 * Kit-augmented node context — the framework-neutral hub context from
 * `@devframes/hub`, plus the Vite-specific slots surfaced when kit hosts
 * the devtool inside Vite DevTools.
 */
interface KitNodeContext extends DevframeHubContext {
  readonly viteConfig?: ResolvedConfig;
  readonly viteServer?: ViteDevServer;
}
interface CreateKitContextOptions extends CreateHubContextOptions {
  /** Optional Vite resolved config to surface on the context (for Vite-mounted hubs). */
  viteConfig?: ResolvedConfig;
  /** Optional Vite dev server to surface on the context. */
  viteServer?: ViteDevServer;
}
/**
 * Create a kit-level node context: wraps `@devframes/hub`'s
 * `createHubContext` (which itself wraps devframe's `createHostContext`)
 * and attaches the Vite-specific slots. The hub layer owns the
 * docks/terminals/messages/commands subsystems and seeds the shared-state
 * sync the unified client UI consumes.
 */
declare function createKitContext(options: CreateKitContextOptions): Promise<KitNodeContext>;
//#endregion
//#region src/types/docks.d.ts
/**
 * The kit's dock-entry category union. Vite Plus integrations are collected
 * under a dedicated dock group (see `DEVTOOLS_VITEPLUS_GROUP_ID`) rather than
 * a category, so this mirrors hub's framework-neutral set directly.
 */
type DevToolsDockEntryCategory = DevframeDockEntryCategory;
//#endregion
//#region src/types/vite-plugin.d.ts
interface DevToolsPluginOptions {
  capabilities?: {
    dev?: DevframeCapabilities | boolean;
    build?: DevframeCapabilities | boolean;
  };
  setup: (context: ViteDevToolsNodeContext) => void | Promise<void>;
}
/**
 * Vite-extended node context — kit-augmented context with the four hub
 * subsystems (`docks`, `terminals`, `messages`, `commands`) plus the
 * Vite-specific slots (`viteConfig`, `viteServer`). Plugins running
 * under `@vitejs/devtools` rely on this surface; portable devframe
 * apps should target {@link KitNodeContext} or the framework-neutral
 * `DevframeNodeContext` from `devframe/types`.
 */
interface ViteDevToolsNodeContext extends KitNodeContext {
  readonly viteConfig: ResolvedConfig;
  readonly viteServer?: ViteDevServer;
}
//#endregion
//#region src/types/vite-augment.d.ts
declare module 'vite' {
  interface Plugin {
    devtools?: DevToolsPluginOptions;
  }
}
interface PluginWithDevTools extends Plugin {
  devtools?: DevToolsPluginOptions;
}
//#endregion
export { KitNodeContext as C, CreateKitContextOptions as S, DevToolsViewJsonRender as _, DevToolsDockEntriesGrouped as a, RemoteConnectionInfo as b, DevToolsDockEntryCategory as c, DevToolsDockUserEntry as d, DevToolsViewAction as f, DevToolsViewIframe as g, DevToolsViewGroup as h, ClientScriptEntry as i, DevToolsDockEntryIcon as l, DevToolsViewCustomRender as m, DevToolsPluginOptions as n, DevToolsDockEntry as o, DevToolsViewBuiltin as p, ViteDevToolsNodeContext as r, DevToolsDockEntryBase as s, PluginWithDevTools as t, DevToolsDockHost as u, DevToolsViewLauncher as v, createKitContext as w, RemoteDockOptions as x, DevToolsViewLauncherStatus as y };