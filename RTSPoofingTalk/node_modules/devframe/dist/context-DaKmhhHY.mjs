import { i as diagnostics, t as createSharedState } from "./shared-state-BlBNYziY.mjs";
import { n as revokeAuthToken, r as humanId, t as revokeActiveConnectionsForToken } from "./revoke-CL0LSAN9.mjs";
import fs from "node:fs";
import { dirname, join } from "pathe";
//#region ../../node_modules/.pnpm/perfect-debounce@2.1.0/node_modules/perfect-debounce/dist/index.mjs
const DEBOUNCE_DEFAULTS = { trailing: true };
/**
Debounce functions
@param fn - Promise-returning/async function to debounce.
@param wait - Milliseconds to wait before calling `fn`. Default value is 25ms
@returns A function that delays calling `fn` until after `wait` milliseconds have elapsed since the last time it was called.
@example
```
import { debounce } from 'perfect-debounce';
const expensiveCall = async input => input;
const debouncedFn = debounce(expensiveCall, 200);
for (const number of [1, 2, 3]) {
console.log(await debouncedFn(number));
}
//=> 1
//=> 2
//=> 3
```
*/
function debounce(fn, wait = 25, options = {}) {
	options = {
		...DEBOUNCE_DEFAULTS,
		...options
	};
	if (!Number.isFinite(wait)) throw new TypeError("Expected `wait` to be a finite number");
	let leadingValue;
	let timeout;
	let resolveList = [];
	let currentPromise;
	let trailingArgs;
	const applyFn = (_this, args) => {
		currentPromise = _applyPromised(fn, _this, args);
		currentPromise.finally(() => {
			currentPromise = null;
			if (options.trailing && trailingArgs && !timeout) {
				const promise = applyFn(_this, trailingArgs);
				trailingArgs = null;
				return promise;
			}
		});
		return currentPromise;
	};
	const debounced = function(...args) {
		if (options.trailing) trailingArgs = args;
		if (currentPromise) return currentPromise;
		return new Promise((resolve) => {
			const shouldCallNow = !timeout && options.leading;
			clearTimeout(timeout);
			timeout = setTimeout(() => {
				timeout = null;
				const promise = options.leading ? leadingValue : applyFn(this, args);
				trailingArgs = null;
				for (const _resolve of resolveList) _resolve(promise);
				resolveList = [];
			}, wait);
			if (shouldCallNow) {
				leadingValue = applyFn(this, args);
				resolve(leadingValue);
			} else resolveList.push(resolve);
		});
	};
	const _clearTimeout = (timer) => {
		if (timer) {
			clearTimeout(timer);
			timeout = null;
		}
	};
	debounced.isPending = () => !!timeout;
	debounced.cancel = () => {
		_clearTimeout(timeout);
		resolveList = [];
		trailingArgs = null;
	};
	debounced.flush = () => {
		_clearTimeout(timeout);
		if (!trailingArgs || currentPromise) return;
		const args = trailingArgs;
		trailingArgs = null;
		return applyFn(this, args);
	};
	return debounced;
}
async function _applyPromised(fn, _this, args) {
	return await fn.apply(_this, args);
}
//#endregion
//#region src/node/storage.ts
function createStorage(options) {
	const { mergeInitialValue = (initialValue, savedValue) => ({
		...initialValue,
		...savedValue
	}), debounce: debounceTime = 100 } = options;
	let initialValue = options.initialValue;
	if (fs.existsSync(options.filepath)) try {
		const savedValue = JSON.parse(fs.readFileSync(options.filepath, "utf-8"));
		initialValue = mergeInitialValue ? mergeInitialValue(options.initialValue, savedValue) : savedValue;
	} catch (error) {
		diagnostics.DF0012({
			filepath: options.filepath,
			cause: error
		}, { method: "warn" });
		initialValue = options.initialValue;
	}
	const state = createSharedState({
		initialValue,
		enablePatches: false
	});
	state.on("updated", debounce((newState) => {
		fs.mkdirSync(dirname(options.filepath), { recursive: true });
		fs.writeFileSync(options.filepath, `${JSON.stringify(newState, null, 2)}\n`);
	}, debounceTime));
	return state;
}
//#endregion
//#region src/node/hub-internals/context.ts
const internalContextMap = /* @__PURE__ */ new WeakMap();
function getInternalContext(context) {
	if (!internalContextMap.has(context)) {
		const storage = createStorage({
			filepath: join(context.host.getStorageDir("global"), "auth.json"),
			initialValue: { trusted: {} }
		});
		const remoteTokens = /* @__PURE__ */ new Map();
		function revokeRemoteToken(token) {
			if (!remoteTokens.delete(token)) return;
			revokeActiveConnectionsForToken(context, token);
		}
		const internalContext = {
			storage: { auth: storage },
			revokeAuthToken: (token) => revokeAuthToken(context, storage, token),
			remoteTokens,
			allocateRemoteToken(dockId, origin, originLock) {
				const token = humanId();
				remoteTokens.set(token, {
					dockId,
					origin,
					originLock
				});
				return token;
			},
			revokeRemoteToken,
			revokeRemoteTokensForDock(dockId) {
				const tokensToRevoke = [];
				for (const [token, record] of remoteTokens) if (record.dockId === dockId) tokensToRevoke.push(token);
				for (const token of tokensToRevoke) revokeRemoteToken(token);
			},
			isRemoteTokenTrusted(token, requestOrigin) {
				const record = remoteTokens.get(token);
				if (!record) return false;
				if (!record.originLock) return true;
				return !!requestOrigin && record.origin === requestOrigin;
			}
		};
		internalContextMap.set(context, internalContext);
	}
	return internalContextMap.get(context);
}
//#endregion
export { internalContextMap as n, createStorage as r, getInternalContext as t };
