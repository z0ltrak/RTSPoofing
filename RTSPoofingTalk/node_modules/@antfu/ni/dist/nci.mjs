import { i as runCli, l as parseNi } from "./src-Dc2SIy_D.mjs";
//#region src/commands/nci.ts
runCli((agent, args, hasLock) => parseNi(agent, [...args, "--frozen-if-present"], hasLock), { autoInstall: true });
//#endregion
export {};
