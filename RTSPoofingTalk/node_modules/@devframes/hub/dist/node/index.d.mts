import { I as DevframeMessageHandle, M as DevframeMessageEntry, P as DevframeMessageEntryInput, S as DevframeViewIframe, _ as DevframeDocksHost$1, a as DevframeChildProcessTerminalSession, f as DevframeDockEntry, g as DevframeDockUserEntry, i as DevframeChildProcessExecuteOptions, l as DevframeTerminalsHost$1, n as DevframeHubContext, o as DevframeTerminalSession, r as createHubContext, s as DevframeTerminalSessionBase, t as CreateHubContextOptions, u as ClientScriptEntry, z as DevframeMessagesHost$1 } from "../context-Dox-G9vt.mjs";
import { a as DevframeCommandHandle, c as DevframeCommandsHost$1, d as DevframeServerCommandInput, t as DevframeDocksUserSettings, u as DevframeServerCommandEntry } from "../settings-Bp5Ax6Os.mjs";
import * as _$devframe_rpc0 from "devframe/rpc";
import { RpcFunctionDefinitionAny } from "devframe/rpc";
import { DevframeDefinition } from "devframe/types";
import { SharedState } from "devframe/utils/shared-state";
import * as _$devframe from "devframe";

//#region src/node/host-commands.d.ts
declare class DevframeCommandsHost implements DevframeCommandsHost$1 {
  readonly context: DevframeHubContext;
  readonly commands: DevframeCommandsHost$1['commands'];
  readonly events: DevframeCommandsHost$1['events'];
  constructor(context: DevframeHubContext);
  register(command: DevframeServerCommandInput): DevframeCommandHandle;
  unregister(id: string): boolean;
  execute(id: string, ...args: any[]): Promise<unknown>;
  list(): DevframeServerCommandEntry[];
  private findCommand;
  private toSerializable;
}
//#endregion
//#region src/node/host-docks.d.ts
declare class DevframeDocksHost implements DevframeDocksHost$1 {
  readonly context: DevframeHubContext;
  readonly views: DevframeDocksHost$1['views'];
  readonly events: DevframeDocksHost$1['events'];
  userSettings: SharedState<DevframeDocksUserSettings>;
  /** Dock-id → allocated remote token + resolved options. */
  private readonly remoteDocks;
  constructor(context: DevframeHubContext);
  init(): Promise<void>;
  values({
    includeBuiltin
  }?: {
    includeBuiltin?: boolean;
  }): DevframeDockEntry[];
  private projectView;
  private resolveDevServerOrigin;
  register<T extends DevframeDockUserEntry>(view: T, force?: boolean): {
    update: (patch: Partial<T>) => void;
  };
  update(view: DevframeDockUserEntry): void;
  private validateGroupMembership;
  private prepareRemoteRegistration;
}
//#endregion
//#region src/node/host-messages.d.ts
declare class DevframeMessagesHost implements DevframeMessagesHost$1 {
  readonly context: DevframeHubContext;
  readonly entries: DevframeMessagesHost$1['entries'];
  readonly events: DevframeMessagesHost$1['events'];
  /** Tracks when each entry was last added or updated (monotonic) */
  readonly lastModified: Map<string, number>;
  /** Tracks recently removed entry IDs with their removal time */
  readonly removals: Array<{
    id: string;
    time: number;
  }>;
  private _autoDeleteTimers;
  private _clock;
  private _tick;
  constructor(context: DevframeHubContext);
  add(input: DevframeMessageEntryInput): Promise<DevframeMessageHandle>;
  update(id: string, patch: Partial<DevframeMessageEntryInput>): Promise<DevframeMessageEntry | undefined>;
  remove(id: string): Promise<void>;
  clear(): Promise<void>;
  private _createHandle;
}
//#endregion
//#region src/node/host-terminals.d.ts
type PartialWithoutId<T extends {
  id: string;
}> = Partial<T> & {
  id: string;
};
declare class DevframeTerminalsHost implements DevframeTerminalsHost$1 {
  readonly context: DevframeHubContext;
  readonly sessions: DevframeTerminalsHost$1['sessions'];
  readonly events: DevframeTerminalsHost$1['events'];
  private _boundStreams;
  private _channel?;
  constructor(context: DevframeHubContext);
  /**
   * Lazily acquire the streaming channel — `context.rpc` isn't assigned
   * until after every host is constructed, so we can't grab it in the
   * constructor.
   */
  private getStreamingChannel;
  register(session: DevframeTerminalSession): DevframeTerminalSession;
  update(patch: PartialWithoutId<DevframeTerminalSession>): void;
  remove(session: DevframeTerminalSession): void;
  private bindStream;
  startChildProcess(executeOptions: DevframeChildProcessExecuteOptions, terminal: Omit<DevframeTerminalSessionBase, 'status'>): Promise<DevframeChildProcessTerminalSession>;
}
//#endregion
//#region src/node/mount-devframe.d.ts
interface MountDevframeOptions {
  /**
   * Mount path override. Defaults to `d.basePath` or `/__${d.id}/`.
   */
  base?: string;
  /**
   * Overrides for the auto-synthesized iframe dock entry. Use this to
   * customize the entry's `category`, override the icon, hide it via
   * `when`, etc. Cannot change `id`, `type`, or `url` — those are
   * derived from the devframe definition.
   */
  dock?: Partial<Omit<DevframeViewIframe, 'id' | 'type' | 'url'>>;
}
/**
 * Framework-neutral primitive — mounts a {@link DevframeDefinition} as a
 * dock inside a hub-aware context: serves the devframe's SPA at the
 * resolved base path, synthesizes an iframe dock entry from the
 * definition's metadata, and runs the definition's `setup(ctx)`.
 *
 * Framework kits wrap this with their own plugin/middleware machinery —
 * e.g. `@vitejs/devtools-kit`'s `createPluginFromDevframe` returns a
 * Vite `Plugin` whose `devtools.setup` ultimately delegates here.
 */
declare function mountDevframe(ctx: DevframeHubContext, d: DevframeDefinition, options?: MountDevframeOptions): Promise<void>;
//#endregion
//#region src/node/rpc-builtins.d.ts
/**
 * `hub:commands:execute` — Invoke a registered server command by id. The
 * arguments after `id` are forwarded to the command's `handler(...)`.
 * Returns whatever the handler returns.
 *
 * Pairs with the `devframe:commands` shared state: clients read the list
 * from the shared state and dispatch by id via this RPC.
 */
declare const hubCommandsExecute: {
  name: "hub:commands:execute";
  type?: "action" | undefined;
  cacheable?: boolean;
  args?: undefined;
  returns?: undefined;
  jsonSerializable?: boolean;
  agent?: _$devframe.RpcFunctionAgentOptions;
  setup?: ((context: DevframeHubContext) => _$devframe_rpc0.Thenable<_$devframe_rpc0.RpcFunctionSetupResult<[id: string, ...args: any[]], Promise<unknown>>>) | undefined;
  handler?: ((id: string, ...args: any[]) => Promise<unknown>) | undefined;
  dump?: _$devframe_rpc0.RpcDump<[id: string, ...args: any[]], Promise<unknown>, DevframeHubContext> | undefined;
  snapshot?: boolean;
  __cache?: WeakMap<object, _$devframe_rpc0.Thenable<_$devframe_rpc0.RpcFunctionSetupResult<[id: string, ...args: any[]], Promise<unknown>>>> | undefined;
  __promise?: _$devframe_rpc0.Thenable<_$devframe_rpc0.RpcFunctionSetupResult<[id: string, ...args: any[]], Promise<unknown>>> | undefined;
};
/**
 * Framework-neutral RPC declarations auto-registered by
 * {@link createHubContext}. Provide additional RPCs by passing your own
 * array via `CreateHubContextOptions.builtinRpcDeclarations`; the hub's
 * list is prepended automatically.
 */
declare const builtinHubRpcDeclarations: readonly RpcFunctionDefinitionAny[];
//#endregion
//#region src/node/utils.d.ts
/**
 * Create a quick `ClientScriptEntry` from an inline function or
 * stringified code. Useful for prototyping `action` / `renderer`
 * dock entries without setting up a separate importable module.
 *
 * @experimental Prefer a proper importable module for production use.
 */
declare function createSimpleClientScript(fn: string | ((ctx: any) => void)): ClientScriptEntry;
//#endregion
export { CreateHubContextOptions, DevframeCommandsHost, DevframeDocksHost, DevframeHubContext, DevframeMessagesHost, DevframeTerminalsHost, MountDevframeOptions, builtinHubRpcDeclarations, createHubContext, createSimpleClientScript, hubCommandsExecute, mountDevframe };