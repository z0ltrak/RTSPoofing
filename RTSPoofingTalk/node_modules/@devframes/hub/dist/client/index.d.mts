import { E as RemoteConnectionInfo, R as DevframeMessagesClient, d as DevframeDockEntriesGrouped, f as DevframeDockEntry, g as DevframeDockUserEntry } from "../context-Dox-G9vt.mjs";
import { i as DevframeCommandEntry, n as DevframeClientCommand, o as DevframeCommandKeybinding, t as DevframeDocksUserSettings } from "../settings-Bp5Ax6Os.mjs";
import { DevframeClientRpcHost, DevframeRpcClient, DevframeRpcClientOptions, DevframeRpcContext, RpcClientEvents } from "devframe/client";
import { EventEmitter } from "devframe/types";
import { SharedState } from "devframe/utils/shared-state";
import { WhenContext } from "devframe/utils/when";
export * from "devframe/client";

//#region src/client/docks.d.ts
interface DockPanelStorage {
  mode: 'float' | 'edge';
  width: number;
  height: number;
  top: number;
  left: number;
  position: 'left' | 'right' | 'bottom' | 'top';
  open: boolean;
  inactiveTimeout: number;
}
type DockClientType = 'embedded' | 'standalone';
interface DocksContext extends DevframeRpcContext {
  /**
   * Type of the client environment
   *
   * 'embedded' - running inside an embedded floating panel
   * 'standalone' - running inside a standalone window (no user app)
   */
  readonly clientType: 'embedded' | 'standalone';
  /**
   * The panel context
   */
  readonly panel: DocksPanelContext;
  /**
   * The docks entries context
   */
  readonly docks: DocksEntriesContext;
  /**
   * The commands context for command palette and shortcuts
   */
  readonly commands: CommandsContext;
  /**
   * The when-clause context for conditional visibility
   */
  readonly when: WhenClauseContext;
}
interface WhenClauseContext {
  /**
   * Get the current when-clause context snapshot.
   * Returns a reactive object with built-in variables and any custom plugin variables.
   */
  readonly context: WhenContext;
}
type DevframeClientContext = DocksContext;
interface DocksPanelContext {
  store: DockPanelStorage;
  isDragging: boolean;
  isResizing: boolean;
  readonly isVertical: boolean;
}
interface DocksEntriesContext {
  selectedId: string | null;
  readonly selected: DevframeDockEntry | null;
  entries: DevframeDockEntry[];
  entryToStateMap: Map<string, DockEntryState>;
  groupedEntries: DevframeDockEntriesGrouped;
  settings: SharedState<DevframeDocksUserSettings>;
  /**
   * Get the state of a dock entry by its ID
   */
  getStateById: (id: string) => DockEntryState | undefined;
  /**
   * Switch to the selected dock entry, pass `null` to clear the selection
   *
   * @returns Whether the selection was changed successfully
   */
  switchEntry: (id?: string | null) => Promise<boolean>;
  /**
   * Toggle the selected dock entry
   *
   * @returns Whether the selection was changed successfully
   */
  toggleEntry: (id: string) => Promise<boolean>;
}
interface DockEntryState {
  entryMeta: DevframeDockEntry;
  readonly isActive: boolean;
  domElements: {
    iframe?: HTMLIFrameElement | null;
    panel?: HTMLDivElement | null;
  };
  events: EventEmitter<DockEntryStateEvents>;
}
interface DockEntryStateEvents {
  'entry:activated': () => void;
  'entry:deactivated': () => void;
  'entry:updated': (newMeta: DevframeDockUserEntry) => void;
  'dom:panel:mounted': (panel: HTMLDivElement) => void;
  'dom:iframe:mounted': (iframe: HTMLIFrameElement) => void;
}
interface CommandsContext {
  /**
   * All commands (server + client)
   */
  readonly commands: DevframeCommandEntry[];
  /**
   * Palette-visible commands only (filtered by `showInPalette !== false`)
   */
  readonly paletteCommands: DevframeCommandEntry[];
  /**
   * Register client-side command(s). Returns cleanup function.
   */
  register: (cmd: DevframeClientCommand | DevframeClientCommand[]) => () => void;
  /**
   * Execute a command by ID. Delegates to RPC for server commands.
   */
  execute: (id: string, ...args: any[]) => Promise<unknown>;
  /**
   * Get effective keybindings for a command (defaults merged with overrides)
   */
  getKeybindings: (id: string) => DevframeCommandKeybinding[];
  /**
   * User settings store (persisted, includes command shortcuts)
   */
  settings: SharedState<DevframeDocksUserSettings>;
  /**
   * Whether the command palette is open
   */
  paletteOpen: boolean;
}
//#endregion
//#region src/client/client-script.d.ts
/**
 * Context for client scripts running in dock entries
 */
interface DockClientScriptContext extends DocksContext {
  /**
   * The state of the current dock entry
   */
  current: DockEntryState;
  /**
   * Messages client scoped to this dock entry's source
   */
  messages: DevframeMessagesClient;
}
//#endregion
//#region src/client/context.d.ts
declare const CLIENT_CONTEXT_KEY = "__DEVFRAME_HUB_CLIENT_CONTEXT__";
/**
 * Get the global Devframe client context, or `undefined` if not yet initialized.
 */
declare function getDevframeClientContext(): DevframeClientContext | undefined;
//#endregion
//#region src/client/remote.d.ts
type ConnectRemoteDevframeOptions = Omit<DevframeRpcClientOptions, 'connectionMeta' | 'authToken'>;
/**
 * Parse a {@link RemoteConnectionInfo} descriptor from the current page's URL
 * (or a provided URL/string). Checks the URL fragment first, then the query.
 *
 * Returns `null` if no descriptor is present.
 * Throws if the descriptor is malformed or its schema version is unsupported.
 */
declare function parseRemoteConnection(input?: string): RemoteConnectionInfo | null;
/**
 * One-liner for a hosted Devframe page: reads the connection descriptor from
 * the current URL and returns a connected {@link DevframeRpcClient}.
 *
 * Pairs with `remote: true` on a `DevframeViewIframe` registered on the node
 * side — the hub injects the descriptor into the iframe URL.
 *
 * @throws if no descriptor is present in the URL.
 */
declare function connectRemoteDevframe(options?: ConnectRemoteDevframeOptions): Promise<DevframeRpcClient>;
//#endregion
export { CLIENT_CONTEXT_KEY, CommandsContext, ConnectRemoteDevframeOptions, DevframeClientContext, type DevframeClientRpcHost, DockClientScriptContext, DockClientType, DockEntryState, DockEntryStateEvents, DockPanelStorage, DocksContext, DocksEntriesContext, DocksPanelContext, type RpcClientEvents, WhenClauseContext, connectRemoteDevframe, getDevframeClientContext, parseRemoteConnection };