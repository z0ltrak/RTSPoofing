import { a as __toESM } from "./chunk-CMuxRQOh.mjs";
import { A as require_prompts, f as parseNun, i as runCli, w as exclude } from "./src-Dc2SIy_D.mjs";
import { t as getPackageJSON } from "./fs-ClsKNes2.mjs";
import process from "node:process";
import { Fzf } from "fzf";
//#region src/commands/nun.ts
var import_prompts = /* @__PURE__ */ __toESM(require_prompts(), 1);
runCli(async (agent, args, ctx) => {
	const isMultiple = args[0] === "-m";
	const isGlobal = args.includes("-g");
	if ((!args.length && !ctx?.programmatic || isMultiple) && !isGlobal) {
		const pkg = getPackageJSON(ctx);
		const allDependencies = {
			...pkg.dependencies,
			...pkg.devDependencies
		};
		const raw = Object.entries(allDependencies);
		if (!raw.length) {
			console.error("No dependencies found");
			return;
		}
		const fzf = new Fzf(raw, {
			selector: ([dep, version]) => `${dep} ${version}`,
			casing: "case-insensitive"
		});
		const choices = raw.map(([dependency, version]) => ({
			title: dependency,
			value: dependency,
			description: version
		}));
		if (isMultiple) args = exclude(args, "-m");
		try {
			const { depsToRemove } = await (0, import_prompts.default)({
				type: "autocompleteMultiselect",
				name: "depsToRemove",
				choices,
				min: 1,
				instructions: false,
				message: "remove dependencies",
				async suggest(input, choices) {
					return fzf.find(input).map((r) => choices.find((c) => c.value === r.item[0]));
				}
			});
			if (Array.isArray(depsToRemove)) args.push(...depsToRemove);
		} catch {
			process.exit(1);
		}
	}
	return parseNun(agent, args, ctx);
});
//#endregion
export {};
