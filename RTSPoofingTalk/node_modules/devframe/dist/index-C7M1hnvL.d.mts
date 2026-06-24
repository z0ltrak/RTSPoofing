import { C as RpcFunctionsCollector, S as RpcFunctionType, _ as RpcFunctionDefinitionAny, g as RpcFunctionDefinition, i as RpcArgsSchema, w as RpcReturnSchema, x as RpcFunctionSetupResult } from "./types-BkkQ0Txg.mjs";
import { a as getDefinitionsWithDumps$1, c as StaticRpcDumpManifest$1, d as StaticRpcDumpManifestValue$1, f as StaticRpcDumpSerialization$1, i as dumpFunctions$1, l as StaticRpcDumpManifestQueryEntry$1, n as serializeDumpError$1, o as StaticRpcDumpCollection$1, p as collectStaticRpcDump$1, r as createClientFromDump$1, s as StaticRpcDumpFile$1, t as reviveDumpError$1, u as StaticRpcDumpManifestStaticEntry$1 } from "./index-DH2sBIwd.mjs";

//#region src/rpc/cache.d.ts
interface RpcCacheOptions {
  functions: string[];
  keySerializer?: (args: unknown[]) => string;
}
/**
 * @experimental API is expected to change.
 */
declare class RpcCacheManager {
  private cacheMap;
  private options;
  private keySerializer;
  constructor(options: RpcCacheOptions);
  updateOptions(options: Partial<RpcCacheOptions>): void;
  cached<T>(m: string, a: unknown[]): T | undefined;
  apply(req: {
    m: string;
    a: unknown[];
  }, res: unknown): void;
  validate(m: string): boolean;
  clear(fn?: string): void;
}
//#endregion
//#region src/rpc/collector.d.ts
declare class RpcFunctionsCollectorBase<LocalFunctions extends Record<string, any>, SetupContext> implements RpcFunctionsCollector<LocalFunctions, SetupContext> {
  readonly context: SetupContext;
  readonly definitions: Map<string, RpcFunctionDefinition<string, any, any, any, any, any, SetupContext>>;
  readonly functions: LocalFunctions;
  private readonly _onChanged;
  constructor(context: SetupContext);
  register(fn: RpcFunctionDefinition<string, any, any, any, any, any, SetupContext>, force?: boolean): void;
  update(fn: RpcFunctionDefinition<string, any, any, any, any, any, SetupContext>, force?: boolean): void;
  onChanged(fn: (id?: string) => void): () => void;
  getHandler<T extends keyof LocalFunctions>(name: T): Promise<LocalFunctions[T]>;
  getSchema<T extends keyof LocalFunctions>(name: T): {
    args: RpcArgsSchema | undefined;
    returns: RpcReturnSchema | undefined;
  };
  has(name: string): boolean;
  get(name: string): RpcFunctionDefinition<string, any, any, any, any, any, SetupContext> | undefined;
  list(): string[];
}
//#endregion
//#region src/rpc/define.d.ts
declare function defineRpcFunction<NAME extends string, TYPE extends RpcFunctionType, ARGS extends any[], RETURN = void, const AS extends RpcArgsSchema | undefined = undefined, const RS extends RpcReturnSchema | undefined = undefined>(definition: RpcFunctionDefinition<NAME, TYPE, ARGS, RETURN, AS, RS>): RpcFunctionDefinition<NAME, TYPE, ARGS, RETURN, AS, RS>;
declare function createDefineWrapperWithContext<CONTEXT>(): <NAME extends string, TYPE extends RpcFunctionType, ARGS extends any[], RETURN = void, const AS extends RpcArgsSchema | undefined = undefined, const RS extends RpcReturnSchema | undefined = undefined>(definition: RpcFunctionDefinition<NAME, TYPE, ARGS, RETURN, AS, RS, CONTEXT>) => RpcFunctionDefinition<NAME, TYPE, ARGS, RETURN, AS, RS, CONTEXT>;
//#endregion
//#region src/rpc/handler.d.ts
declare function getRpcResolvedSetupResult<NAME extends string, TYPE extends RpcFunctionType, ARGS extends any[], RETURN = void, CONTEXT = undefined>(definition: RpcFunctionDefinition<NAME, TYPE, ARGS, RETURN, any, any, CONTEXT>, context: CONTEXT): Promise<RpcFunctionSetupResult<ARGS, RETURN>>;
declare function getRpcHandler<NAME extends string, TYPE extends RpcFunctionType, ARGS extends any[], RETURN = void, CONTEXT = undefined>(definition: RpcFunctionDefinition<NAME, TYPE, ARGS, RETURN, any, any, CONTEXT>, context: CONTEXT): Promise<(...args: ARGS) => RETURN>;
//#endregion
//#region src/rpc/serialization.d.ts
/**
 * Wire format used by the WS RPC transport.
 *
 * - **JSON (default, unprefixed):** payload is plain JSON text. Used when
 *   the dispatched method is declared `jsonSerializable: true`. Encoded
 *   via {@link strictJsonStringify} (rejects non-JSON values), decoded
 *   via `JSON.parse`.
 * - **Structured-clone (`s:` prefix):** payload is `s:` followed by
 *   `structured-clone-es` text. Used when the method is declared
 *   `jsonSerializable: false` (or omitted, the default). Round-trips
 *   `Map`, `Set`, `Date`, `BigInt`, cycles, and class instances.
 *
 * birpc envelopes always start with `{`, so a leading byte that is not
 * `s` is unambiguously JSON. Each direction independently chooses its
 * encoding from local definitions — request and response are not
 * coupled by a mirror rule.
 */
declare const STRUCTURED_CLONE_PREFIX = "s:";
/**
 * `JSON.stringify` with a single-pass strict replacer.
 *
 * Throws `DF0020` synchronously when the value contains a type JSON
 * cannot round-trip losslessly: `Map`, `Set`, `Date`, `BigInt`, class
 * instances, or `undefined` inside an array (silently becomes `null`).
 *
 * Native pass-throughs (no extra work needed):
 *   - circular references — `JSON.stringify` raises `TypeError`.
 *   - `BigInt` at top level — caught here for a friendlier error path.
 *
 * Lenient cases (allowed without throwing):
 *   - `undefined` as an object property — legitimate optional field;
 *     JSON.stringify just omits it.
 *   - `undefined` at the root — legitimate "action returned nothing".
 *   - `Symbol` / `Function` values — semantically "drop me" in JSON.
 *
 * `fnName` is used only for the diagnostic message — pass the RPC
 * function name when calling from a wire serializer / dump writer so
 * the error points at the offending function.
 */
declare function strictJsonStringify(value: unknown, fnName?: string): string;
//#endregion
//#region src/rpc/validation.d.ts
/**
 * Validates RPC function definitions.
 * Action and event functions cannot have dumps (side effects should not be cached).
 *
 * @throws {Error} If an action or event function has a dump configuration
 */
declare function validateDefinitions(definitions: readonly RpcFunctionDefinitionAny[]): void;
/**
 * Validates a single RPC function definition.
 *
 * @throws {Error} If an action or event function has a dump configuration
 */
declare function validateDefinition(definition: RpcFunctionDefinitionAny): void;
//#endregion
//#region src/rpc/index.d.ts
/** @deprecated Import from `devframe/rpc/dump` instead. */
declare const collectStaticRpcDump: typeof collectStaticRpcDump$1;
/** @deprecated Import from `devframe/rpc/dump` instead. */
declare const createClientFromDump: typeof createClientFromDump$1;
/** @deprecated Import from `devframe/rpc/dump` instead. */
declare const dumpFunctions: typeof dumpFunctions$1;
/** @deprecated Import from `devframe/rpc/dump` instead. */
declare const getDefinitionsWithDumps: typeof getDefinitionsWithDumps$1;
/** @deprecated Import from `devframe/rpc/dump` instead. */
declare const reviveDumpError: typeof reviveDumpError$1;
/** @deprecated Import from `devframe/rpc/dump` instead. */
declare const serializeDumpError: typeof serializeDumpError$1;
/** @deprecated Import from `devframe/rpc/dump` instead. */
type StaticRpcDumpCollection = StaticRpcDumpCollection$1;
/** @deprecated Import from `devframe/rpc/dump` instead. */
type StaticRpcDumpFile = StaticRpcDumpFile$1;
/** @deprecated Import from `devframe/rpc/dump` instead. */
type StaticRpcDumpManifest = StaticRpcDumpManifest$1;
/** @deprecated Import from `devframe/rpc/dump` instead. */
type StaticRpcDumpManifestQueryEntry = StaticRpcDumpManifestQueryEntry$1;
/** @deprecated Import from `devframe/rpc/dump` instead. */
type StaticRpcDumpManifestStaticEntry = StaticRpcDumpManifestStaticEntry$1;
/** @deprecated Import from `devframe/rpc/dump` instead. */
type StaticRpcDumpManifestValue = StaticRpcDumpManifestValue$1;
/** @deprecated Import from `devframe/rpc/dump` instead. */
type StaticRpcDumpSerialization = StaticRpcDumpSerialization$1;
//#endregion
export { RpcCacheManager as C, RpcFunctionsCollectorBase as S, strictJsonStringify as _, StaticRpcDumpManifestStaticEntry as a, createDefineWrapperWithContext as b, collectStaticRpcDump as c, getDefinitionsWithDumps as d, reviveDumpError as f, STRUCTURED_CLONE_PREFIX as g, validateDefinitions as h, StaticRpcDumpManifestQueryEntry as i, createClientFromDump as l, validateDefinition as m, StaticRpcDumpFile as n, StaticRpcDumpManifestValue as o, serializeDumpError as p, StaticRpcDumpManifest as r, StaticRpcDumpSerialization as s, StaticRpcDumpCollection as t, dumpFunctions as u, getRpcHandler as v, RpcCacheOptions as w, defineRpcFunction as x, getRpcResolvedSetupResult as y };