import { a as createRpcStreamingServerHost, c as DevframeAgentHost, i as RpcFunctionsHost, n as createHostContext, o as createRpcSharedStateServerHost, r as DevframeViewHost, s as DevframeDiagnosticsHost, t as createH3DevframeHost } from "../host-h3-Dgpgr1Ul.mjs";
import { r as createStorage } from "../context-DaKmhhHY.mjs";
import { t as startHttpAndWs } from "../server-BBaBJaUL.mjs";
import { isIP } from "node:net";
//#region src/node/utils.ts
function isObject(value) {
	return Object.prototype.toString.call(value) === "[object Object]";
}
function normalizeHttpServerUrl(host, port) {
	return `http://${host === "127.0.0.1" ? "localhost" : isIP(host) === 6 ? `[${host}]` : host}:${port}`;
}
//#endregion
export { DevframeAgentHost, DevframeDiagnosticsHost, DevframeViewHost, RpcFunctionsHost, createH3DevframeHost, createHostContext, createRpcSharedStateServerHost, createRpcStreamingServerHost, createStorage, isObject, normalizeHttpServerUrl, startHttpAndWs };
