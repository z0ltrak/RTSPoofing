import { DevframeCommandsHost as DevToolsCommandsHost, DevframeDocksHost as DevToolsDockHost, DevframeMessagesHost as DevToolsMessagesHost, DevframeTerminalsHost as DevToolsTerminalHost, createHubContext, mountDevframe, mountDevframe as mountDevframe$1 } from "@devframes/hub/node";
import { toDataURL } from "mlly";
import { homedir } from "node:os";
import { join } from "node:path";
import { serveStaticNodeMiddleware } from "devframe/utils/serve-static";
//#region src/node/context.ts
/**
* Create a kit-level node context: wraps `@devframes/hub`'s
* `createHubContext` (which itself wraps devframe's `createHostContext`)
* and attaches the Vite-specific slots. The hub layer owns the
* docks/terminals/messages/commands subsystems and seeds the shared-state
* sync the unified client UI consumes.
*/
async function createKitContext(options) {
	const context = await createHubContext(options);
	if (options.viteConfig) Object.defineProperty(context, "viteConfig", {
		value: options.viteConfig,
		enumerable: true
	});
	if (options.viteServer) Object.defineProperty(context, "viteServer", {
		value: options.viteServer,
		enumerable: true
	});
	return context;
}
//#endregion
//#region src/node/create-plugin-from-devframe.ts
/**
* Wrap a {@link DevframeDefinition} as a Vite plugin that mounts inside
* `@vitejs/devtools` (Vite DevTools). Delegates the mount work
* (serving the SPA, registering the iframe dock entry, calling
* `d.setup(ctx)`) to `@devframes/hub`'s `mountDevframe`, then runs the
* optional kit-only `options.setup` hook.
*/
function createPluginFromDevframe(d, options = {}) {
	return {
		name: options.name ?? `devframe:${d.id}`,
		devtools: {
			capabilities: options.capabilities ?? d.capabilities,
			async setup(rawCtx) {
				const ctx = rawCtx;
				await mountDevframe$1(ctx, d, {
					base: options.base,
					dock: options.dock
				});
				if (options.setup) await options.setup(ctx);
			}
		}
	};
}
//#endregion
//#region src/node/utils.ts
/**
* Create a quick `ClientScriptEntry` from an inline function or
* stringified code. Useful for prototyping `action` / `renderer`
* dock entries without setting up a separate importable module.
*
* @experimental Prefer a proper importable module for production use.
*/
function createSimpleClientScript(fn) {
	return {
		importFrom: toDataURL(`const fn = ${fn.toString()}; export default fn`),
		importName: "default"
	};
}
//#endregion
//#region src/node/vite-host.ts
function createViteDevToolsHost(options) {
	const { viteConfig, viteServer } = options;
	const workspaceRoot = options.workspaceRoot ?? viteConfig.root;
	return {
		mountStatic(base, distDir) {
			if (viteConfig.command !== "serve") return;
			if (!viteServer) throw new Error("viteServer is required to mount static assets in dev mode");
			viteServer.middlewares.use(base, serveStaticNodeMiddleware(distDir));
		},
		resolveOrigin() {
			const resolved = viteServer?.resolvedUrls?.local?.[0];
			if (resolved) return new URL(resolved).origin;
			const https = !!viteConfig.server.https;
			const host = typeof viteConfig.server.host === "string" ? viteConfig.server.host : "localhost";
			const port = viteConfig.server.port ?? (https ? 443 : 80);
			return `${https ? "https" : "http"}://${host === "0.0.0.0" || host === "::" || !host ? "localhost" : host}:${port}`;
		},
		getStorageDir(scope) {
			return scope === "workspace" ? join(workspaceRoot, "node_modules/.vite/devtools") : join(homedir(), ".vite/devtools");
		}
	};
}
//#endregion
export { DevToolsCommandsHost, DevToolsDockHost, DevToolsMessagesHost, DevToolsTerminalHost, createKitContext, createPluginFromDevframe, createSimpleClientScript, createViteDevToolsHost, mountDevframe };
