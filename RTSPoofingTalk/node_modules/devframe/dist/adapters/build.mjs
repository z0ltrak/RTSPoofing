import { t as collectStaticRpcDump } from "../dump-9lKIJTLh.mjs";
import { n as colors } from "../diagnostics-reporter-CBBZwoMv.mjs";
import { DEVFRAME_CONNECTION_META_FILENAME, DEVFRAME_RPC_DUMP_DIRNAME, DEVFRAME_RPC_DUMP_MANIFEST_FILENAME } from "../constants.mjs";
import { n as strictJsonStringify } from "../serialization-BD_qXGjd.mjs";
import { n as structuredCloneStringify } from "../structured-clone-jegjz0hM.mjs";
import { n as createHostContext, t as createH3DevframeHost } from "../host-h3-Dgpgr1Ul.mjs";
import { n as resolveBasePath } from "../_shared-CUFqO4kJ.mjs";
import { existsSync } from "node:fs";
import process from "node:process";
import { dirname, resolve } from "pathe";
import fs$1 from "node:fs/promises";
//#region src/adapters/build.ts
/**
* Produce a self-contained static deploy of a devframe:
*
*   - Build a `mode: 'build'` context and run `devframe.setup(ctx)`.
*   - Copy the author's SPA dist into `<outDir>/`.
*   - Write `<outDir>/__connection.json` (`{ backend: 'static' }`) and the
*     sharded RPC dump under `<outDir>/__rpc-dump/` so the deployed SPA
*     discovers both via relative paths from `document.baseURI`.
*   - When `def.spa` is configured, also write `<outDir>/spa-loader.json`
*     describing the SPA's data-loader mode (`'query'` / `'upload'` /
*     `'none'`). The output is mount-path agnostic — the same bundle
*     works at `/`, `/devframe/`, or any base, no rewriting required.
*/
async function createBuild(d, options = {}) {
	const outDir = resolve(options.outDir ?? "dist-static");
	const distDir = options.distDir ?? d.cli?.distDir;
	if (!distDir) throw new Error(`[devframe] createBuild: no distDir for "${d.id}". Set \`cli.distDir\` on the definition or pass it as an option.`);
	if (existsSync(outDir)) await fs$1.rm(outDir, { recursive: true });
	await fs$1.mkdir(outDir, { recursive: true });
	console.log(colors.cyan`[devframe] copying SPA from ${distDir} -> ${outDir}`);
	await fs$1.cp(distDir, outDir, { recursive: true });
	const ctx = await createHostContext({
		cwd: process.cwd(),
		mode: "build",
		host: createH3DevframeHost({
			origin: "http://localhost",
			appName: d.id
		})
	});
	await d.setup(ctx);
	await fs$1.mkdir(resolve(outDir, DEVFRAME_RPC_DUMP_DIRNAME), { recursive: true });
	const jsonSerializableMethods = [];
	for (const def of ctx.rpc.definitions.values()) if (def.jsonSerializable === true) jsonSerializableMethods.push(def.name);
	await fs$1.writeFile(resolve(outDir, DEVFRAME_CONNECTION_META_FILENAME), JSON.stringify({
		backend: "static",
		jsonSerializableMethods
	}, null, 2), "utf-8");
	console.log(colors.cyan`[devframe] writing RPC dump to ${resolve(outDir, DEVFRAME_RPC_DUMP_MANIFEST_FILENAME)}`);
	const dump = await collectStaticRpcDump(ctx.rpc.definitions.values(), ctx);
	const indent = options.pretty ? 2 : void 0;
	for (const [filepath, file] of Object.entries(dump.files)) {
		const fullpath = resolve(outDir, filepath);
		await fs$1.mkdir(dirname(fullpath), { recursive: true });
		const text = file.serialization === "structured-clone" ? structuredCloneStringify(file.data) : strictJsonStringify(file.data, file.fnName);
		await fs$1.writeFile(fullpath, file.serialization === "json" && indent != null ? JSON.stringify(JSON.parse(text), null, indent) : text, "utf-8");
	}
	await fs$1.writeFile(resolve(outDir, DEVFRAME_RPC_DUMP_MANIFEST_FILENAME), JSON.stringify(dump.manifest, null, 2), "utf-8");
	if (d.spa) {
		const base = options.base ?? resolveBasePath(d, "standalone");
		const spaLoader = {
			version: 1,
			mode: d.spa.loader ?? "none",
			base
		};
		await fs$1.writeFile(resolve(outDir, "spa-loader.json"), JSON.stringify(spaLoader, null, 2), "utf-8");
	}
	console.log(colors.green`[devframe] built "${d.id}" -> ${outDir}`);
}
//#endregion
export { createBuild };
