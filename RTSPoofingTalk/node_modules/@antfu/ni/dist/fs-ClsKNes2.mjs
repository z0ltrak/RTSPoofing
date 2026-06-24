import fs from "node:fs";
import { resolve } from "node:path";
import process from "node:process";
//#region src/fs.ts
function getPackageJSON(ctx) {
	const path = resolve(ctx?.cwd ?? process.cwd(), "package.json");
	if (fs.existsSync(path)) try {
		const raw = fs.readFileSync(path, "utf-8");
		return JSON.parse(raw);
	} catch (e) {
		if (!ctx?.programmatic) {
			console.warn("Failed to parse package.json");
			process.exit(1);
		}
		throw e;
	}
}
//#endregion
export { getPackageJSON as t };
