import { $ as AgentResource, K as DevframeHost, P as SharedState, Q as AgentManifest, U as DevframeRpcClientFunctions, W as DevframeRpcServerFunctions, X as DevframeDiagnosticsLogger, Y as DevframeDiagnosticsHost$1, Z as AgentHandle, at as DevframeAgentHostEvents, d as DevframeNodeContext, et as AgentResourceContent, f as DevframeNodeRpcSession, g as RpcSharedStateHost, it as DevframeAgentHost$1, m as RpcFunctionsHost$1, nt as AgentTool, ot as EventEmitter, p as RpcBroadcastOptions, rt as AgentToolInput, tt as AgentResourceInput, y as RpcStreamingHost, z as DevframeViewHost$1 } from "../devframe-BuR6n9ZD.mjs";
import { _ as RpcFunctionDefinitionAny } from "../types-BkkQ0Txg.mjs";
import { S as RpcFunctionsCollectorBase } from "../index-C7M1hnvL.mjs";
import { t as DevframeNodeRpcSessionMeta } from "../ws-server-C1LjmRnp.mjs";
import { n as StartedServer, r as startHttpAndWs, t as StartHttpAndWsOptions } from "../server-wHlpcdZ9.mjs";
import { BirpcGroup } from "birpc";
import { AsyncLocalStorage } from "node:async_hooks";

//#region src/node/context.d.ts
interface CreateHostContextOptions {
  cwd: string;
  workspaceRoot?: string;
  mode: 'dev' | 'build';
  host: DevframeHost;
  /**
   * Built-in RPC declarations to register on the host. Framework
   * adapters (vite, rolldown, cli) can pass the ones they need; the
   * host itself has no opinions about the built-in set.
   */
  builtinRpcDeclarations?: readonly RpcFunctionDefinitionAny[];
}
/**
 * Framework- and build-tool-agnostic core of the Devframe node context.
 * Wires the RPC host, view (HTTP file-serving) host, diagnostics, and
 * agent subsystems. Host adapters can wrap this to augment `ctx` with
 * extra surfaces — for example, `@vitejs/devtools-kit`'s
 * `createKitContext` attaches `docks`, `terminals`, `messages`,
 * `commands`, and `createJsonRenderer` when mounted into Vite DevTools.
 */
declare function createHostContext(options: CreateHostContextOptions): Promise<DevframeNodeContext>;
//#endregion
//#region src/node/host-agent.d.ts
/**
 * Framework-neutral host aggregating the agent-exposed surface of a
 * devframe. Auto-discovers RPC functions with an `agent` field from
 * `ctx.rpc.definitions`, and accepts plugin-registered tools /
 * resources via `registerTool` / `registerResource`.
 *
 * @experimental
 */
declare class DevframeAgentHost implements DevframeAgentHost$1 {
  readonly context: DevframeNodeContext;
  readonly events: EventEmitter<DevframeAgentHostEvents>;
  private readonly tools;
  private readonly resources;
  private _rpcUnsubscribe;
  constructor(context: DevframeNodeContext);
  registerTool(input: AgentToolInput): AgentHandle;
  unregisterTool(id: string): boolean;
  registerResource(input: AgentResourceInput): AgentHandle;
  unregisterResource(id: string): boolean;
  list(): AgentManifest;
  getTool(id: string): AgentTool | undefined;
  getResource(id: string): AgentResource | undefined;
  invoke(id: string, args: unknown): Promise<unknown>;
  read(id: string): Promise<AgentResourceContent>;
  /** @internal */
  _dispose(): void;
  private _validateToolId;
  private _projectTool;
  private _collectRpcTools;
  private _findRpcDefinition;
  private _coercePositionalArgs;
}
//#endregion
//#region src/node/host-diagnostics.d.ts
declare class DevframeDiagnosticsHost implements DevframeDiagnosticsHost$1 {
  readonly context: DevframeNodeContext;
  private _registry;
  readonly logger: DevframeDiagnosticsLogger;
  readonly defineDiagnostics: DevframeDiagnosticsHost$1['defineDiagnostics'];
  constructor(context: DevframeNodeContext, initialDefinitions?: Array<Record<string, unknown>>);
  register(diagnostics: Record<string, unknown>): void;
}
//#endregion
//#region src/node/host-functions.d.ts
declare class RpcFunctionsHost extends RpcFunctionsCollectorBase<DevframeRpcServerFunctions, DevframeNodeContext> implements RpcFunctionsHost$1 {
  /**
   * @internal
   */
  _rpcGroup: BirpcGroup<DevframeRpcClientFunctions, DevframeRpcServerFunctions, false>;
  _asyncStorage: AsyncLocalStorage<DevframeNodeRpcSession>;
  constructor(context: DevframeNodeContext);
  sharedState: RpcSharedStateHost;
  streaming: RpcStreamingHost;
  /**
   * Adapters call this from their WS `onDisconnected` hook so downstream
   * hosts (streaming, …) can free per-session state. Public-ish because
   * tests / custom adapters may want to mirror it.
   *
   * @internal
   */
  _emitSessionDisconnected(meta: DevframeNodeRpcSessionMeta): void;
  invokeLocal<T extends keyof DevframeRpcServerFunctions, Args extends Parameters<DevframeRpcServerFunctions[T]>>(method: T, ...args: Args): Promise<Awaited<ReturnType<DevframeRpcServerFunctions[T]>>>;
  broadcast<T extends keyof DevframeRpcClientFunctions, Args extends Parameters<DevframeRpcClientFunctions[T]>>(options: RpcBroadcastOptions<T, Args>): Promise<void>;
  getCurrentRpcSession(): DevframeNodeRpcSession | undefined;
}
//#endregion
//#region src/node/host-h3.d.ts
interface CreateH3DevframeHostOptions {
  /** The h3 app instance — registered once the CLI adapter lands. */
  app?: unknown;
  /**
   * Host the standalone server listens on, e.g. `http://localhost:9999`.
   * Consumed by `resolveOrigin` for dock entries that need an absolute URL.
   */
  origin: string;
  /**
   * Register a static-file handler at `base` serving files from `distDir`.
   * Wired into the h3 app once the CLI adapter lands (commit 5). For now
   * the CLI isn't running, so the default is a no-op.
   */
  mount?: (base: string, distDir: string) => void | Promise<void>;
  /**
   * Namespace for storage paths returned by `getStorageDir`. Workspace
   * state lives under `${workspaceRoot}/node_modules/.<appName>/devframe/`
   * and global state under `${homedir()}/.<appName>/devframe/`. Pick the
   * devtool's id (or another stable, filesystem-safe identifier) so the
   * standalone host doesn't collide with other tools' storage.
   */
  appName: string;
  /**
   * Workspace root used as the parent of the per-project storage
   * directory. Defaults to `process.cwd()`.
   */
  workspaceRoot?: string;
}
/**
 * h3-backed {@link DevframeHost} — used by the standalone CLI adapter.
 */
declare function createH3DevframeHost(options: CreateH3DevframeHostOptions): DevframeHost;
//#endregion
//#region src/node/host-views.d.ts
declare class DevframeViewHost implements DevframeViewHost$1 {
  readonly context: DevframeNodeContext;
  /**
   * @internal
   */
  buildStaticDirs: {
    baseUrl: string;
    distDir: string;
  }[];
  constructor(context: DevframeNodeContext);
  hostStatic(baseUrl: string, distDir: string): void;
}
//#endregion
//#region src/node/rpc-shared-state.d.ts
declare function createRpcSharedStateServerHost(rpc: RpcFunctionsHost$1): RpcSharedStateHost;
//#endregion
//#region src/node/rpc-streaming.d.ts
/**
 * Build the server-side streaming host. Mirrors the layout of
 * `createRpcSharedStateServerHost` — registers a fixed set of internal
 * RPC methods (`subscribe` / `unsubscribe` / `cancel`) once, then per-channel
 * state lives in a `Map<channelName, ChannelState>`.
 */
declare function createRpcStreamingServerHost(rpc: RpcFunctionsHost$1): RpcStreamingHost;
//#endregion
//#region src/node/storage.d.ts
interface CreateStorageOptions<T extends object> {
  filepath: string;
  initialValue: T;
  mergeInitialValue?: false | ((initialValue: T, savedValue: T) => T);
  debounce?: number;
}
declare function createStorage<T extends object>(options: CreateStorageOptions<T>): SharedState<T>;
//#endregion
//#region src/node/utils.d.ts
declare function isObject(value: unknown): value is Record<string, any>;
declare function normalizeHttpServerUrl(host: string, port: number | string): string;
//#endregion
export { CreateH3DevframeHostOptions, CreateHostContextOptions, CreateStorageOptions, DevframeAgentHost, DevframeDiagnosticsHost, DevframeViewHost, RpcFunctionsHost, StartHttpAndWsOptions, StartedServer, createH3DevframeHost, createHostContext, createRpcSharedStateServerHost, createRpcStreamingServerHost, createStorage, isObject, normalizeHttpServerUrl, startHttpAndWs };