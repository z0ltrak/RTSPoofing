import { createDefineWrapperWithContext } from "devframe/rpc";
//#region src/define.ts
const defineHubRpcFunction = createDefineWrapperWithContext();
function defineCommand(command) {
	return command;
}
function defineDockEntry(entry) {
	return entry;
}
function defineJsonRenderSpec(spec) {
	return spec;
}
//#endregion
export { defineJsonRenderSpec as i, defineDockEntry as n, defineHubRpcFunction as r, defineCommand as t };
