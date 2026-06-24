import { connectRemoteDevframe as connectRemoteDevTools, getDevframeRpcClient as getDevToolsRpcClient, parseRemoteConnection } from "@devframes/hub/client";
//#region src/client/context.ts
const CLIENT_CONTEXT_KEY = "__VITE_DEVTOOLS_CLIENT_CONTEXT__";
/**
* Get the global DevTools client context, or `undefined` if not yet initialized.
*/
function getDevToolsClientContext() {
	return globalThis[CLIENT_CONTEXT_KEY];
}
//#endregion
export { CLIENT_CONTEXT_KEY, connectRemoteDevTools, getDevToolsClientContext, getDevToolsRpcClient, parseRemoteConnection };
