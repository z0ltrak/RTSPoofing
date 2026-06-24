import { REMOTE_CONNECTION_KEY } from "devframe/constants";
import { getDevframeRpcClient } from "devframe/client";
export * from "devframe/client";
//#region src/client/context.ts
const CLIENT_CONTEXT_KEY = "__DEVFRAME_HUB_CLIENT_CONTEXT__";
/**
* Get the global Devframe client context, or `undefined` if not yet initialized.
*/
function getDevframeClientContext() {
	return globalThis[CLIENT_CONTEXT_KEY];
}
//#endregion
//#region src/client/remote.ts
function base64UrlDecode(value) {
	const padLen = (4 - value.length % 4) % 4;
	const padded = value.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat(padLen);
	const binary = atob(padded);
	const bytes = new Uint8Array(binary.length);
	for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
	return new TextDecoder().decode(bytes);
}
function extractKeyFromFragment(hash) {
	if (!hash) return null;
	const raw = hash.startsWith("#") ? hash.slice(1) : hash;
	const queryIdx = raw.indexOf("?");
	if (queryIdx !== -1) {
		const value = new URLSearchParams(raw.slice(queryIdx + 1)).get(REMOTE_CONNECTION_KEY);
		if (value) return value;
	}
	for (const part of raw.split("&")) {
		const [k, v = ""] = part.split("=");
		if (k === REMOTE_CONNECTION_KEY) return decodeURIComponent(v);
	}
	return null;
}
function extractKeyFromQuery(search) {
	if (!search) return null;
	return new URLSearchParams(search.startsWith("?") ? search.slice(1) : search).get(REMOTE_CONNECTION_KEY);
}
/**
* Parse a {@link RemoteConnectionInfo} descriptor from the current page's URL
* (or a provided URL/string). Checks the URL fragment first, then the query.
*
* Returns `null` if no descriptor is present.
* Throws if the descriptor is malformed or its schema version is unsupported.
*/
function parseRemoteConnection(input) {
	let hash = "";
	let search = "";
	if (input === void 0) {
		if (typeof location === "undefined") return null;
		hash = location.hash;
		search = location.search;
	} else try {
		const parsed = new URL(input, "http://_");
		hash = parsed.hash;
		search = parsed.search;
	} catch {
		if (input.startsWith("#")) hash = input;
		else if (input.startsWith("?")) search = input;
		else return null;
	}
	const encoded = extractKeyFromFragment(hash) ?? extractKeyFromQuery(search);
	if (!encoded) return null;
	let payload;
	try {
		payload = JSON.parse(base64UrlDecode(encoded));
	} catch (cause) {
		throw new Error("[@devframes/hub] Failed to decode remote connection descriptor.", { cause });
	}
	if (!payload || typeof payload !== "object") throw new Error("[@devframes/hub] Remote connection descriptor must be an object.");
	const info = payload;
	if (info.v !== 1) throw new Error(`[@devframes/hub] Unsupported remote connection descriptor version: ${String(info.v)}`);
	if (info.backend !== "websocket" || typeof info.websocket !== "string" || !info.websocket) throw new Error("[@devframes/hub] Remote connection descriptor must carry a websocket URL.");
	if (typeof info.authToken !== "string" || !info.authToken) throw new Error("[@devframes/hub] Remote connection descriptor must carry an auth token.");
	if (typeof info.origin !== "string") throw new Error("[@devframes/hub] Remote connection descriptor must carry an origin.");
	return info;
}
/**
* One-liner for a hosted Devframe page: reads the connection descriptor from
* the current URL and returns a connected {@link DevframeRpcClient}.
*
* Pairs with `remote: true` on a `DevframeViewIframe` registered on the node
* side — the hub injects the descriptor into the iframe URL.
*
* @throws if no descriptor is present in the URL.
*/
async function connectRemoteDevframe(options = {}) {
	const info = parseRemoteConnection();
	if (!info) throw new Error("[@devframes/hub] No remote connection descriptor found in the URL. Open this page through a hub-registered dock with `remote: true`.");
	return getDevframeRpcClient({
		...options,
		connectionMeta: info,
		authToken: info.authToken
	});
}
//#endregion
export { CLIENT_CONTEXT_KEY, connectRemoteDevframe, getDevframeClientContext, parseRemoteConnection };
