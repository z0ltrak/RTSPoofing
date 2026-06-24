import { i as DevframeDeploymentKind, r as DevframeDefinition } from "../devframe-BuR6n9ZD.mjs";
import { a as internalContextMap, i as getInternalContext, n as InternalAnonymousAuthStorage, r as RemoteTokenRecord, t as DevframeInternalContext } from "../context-DTRcO_UH.mjs";

//#region src/adapters/_shared.d.ts
/**
 * Resolve the mount base path for a devframe's SPA. Hosted adapters
 * (`vite`, `embedded`) default to `/__<id>/` so they don't collide
 * with the host app; standalone adapters (`cli`, `spa`, `build`)
 * default to `/` because they own the origin.
 *
 * The devframe author can override with `basePath` on the definition.
 */
declare function resolveBasePath(def: DevframeDefinition, kind: DevframeDeploymentKind): string;
declare function normalizeBasePath(base: string): string;
//#endregion
export { type DevframeInternalContext, type InternalAnonymousAuthStorage, type RemoteTokenRecord, getInternalContext, internalContextMap, normalizeBasePath, resolveBasePath };