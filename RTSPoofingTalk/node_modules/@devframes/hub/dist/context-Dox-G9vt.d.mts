import { c as DevframeCommandsHost } from "./settings-Bp5Ax6Os.mjs";
import { CreateHostContextOptions } from "devframe/node";
import { ConnectionMeta, DevframeHost, DevframeNodeContext, EventEmitter } from "devframe/types";
import { ChildProcess } from "node:child_process";

//#region src/types/messages.d.ts
type DevframeMessageLevel = 'info' | 'warn' | 'error' | 'success' | 'debug';
type DevframeMessageEntryFrom = 'server' | 'browser';
interface DevframeMessageElementPosition {
  /** CSS selector for the element */
  selector?: string;
  /** Bounding box of the element */
  boundingBox?: {
    x: number;
    y: number;
    width: number;
    height: number;
  };
  /** Human-readable description of the element */
  description?: string;
}
interface DevframeMessageFilePosition {
  /** Absolute or relative file path */
  file: string;
  /** Line number (1-based) */
  line?: number;
  /** Column number (1-based) */
  column?: number;
}
interface DevframeMessageEntry {
  /**
   * Unique identifier for this message entry (auto-generated if not provided)
   */
  id: string;
  /**
   * Short title or summary of the message
   */
  message: string;
  /**
   * Optional detailed description or explanation
   */
  description?: string;
  /**
   * Severity level, determines color and icon
   */
  level: DevframeMessageLevel;
  /**
   * Optional stack trace string
   */
  stacktrace?: string;
  /**
   * Optional DOM element position info (e.g., for a11y issues)
   */
  elementPosition?: DevframeMessageElementPosition;
  /**
   * Optional source file position info (e.g., for lint errors)
   */
  filePosition?: DevframeMessageFilePosition;
  /**
   * Whether this message should also appear as a toast notification
   */
  notify?: boolean;
  /**
   * Origin of the message entry, automatically set by the context
   */
  from: DevframeMessageEntryFrom;
  /**
   * Grouping category (e.g., 'a11y', 'lint', 'runtime', 'test')
   */
  category?: string;
  /**
   * Optional tags/labels for filtering
   */
  labels?: string[];
  /**
   * Time in ms to auto-dismiss the toast notification (client-side)
   */
  autoDismiss?: number;
  /**
   * Time in ms to auto-delete this message entry (server-side)
   */
  autoDelete?: number;
  /**
   * Timestamp when the message was created (auto-generated if not provided)
   */
  timestamp: number;
  /**
   * Status of the message entry (e.g., 'loading' while an operation is in progress).
   * Defaults to 'idle' when not specified.
   */
  status?: 'loading' | 'idle';
}
/**
 * Input type for creating a message entry.
 * `id`, `timestamp`, and `from` are auto-filled by the host.
 */
type DevframeMessageEntryInput = Omit<DevframeMessageEntry, 'id' | 'timestamp' | 'from'> & {
  id?: string;
  timestamp?: number;
};
interface DevframeMessageHandle {
  /** The underlying message entry data */
  readonly entry: DevframeMessageEntry;
  /** Shortcut to entry.id */
  readonly id: string;
  /** Partial update of this message entry */
  update: (patch: Partial<DevframeMessageEntryInput>) => Promise<DevframeMessageEntry | undefined>;
  /** Remove this message entry */
  dismiss: () => Promise<void>;
}
interface DevframeMessagesClient {
  /**
   * Add a message entry. Returns a Promise resolving to a handle for subsequent updates/dismissal.
   * Can be used without `await` for fire-and-forget usage.
   */
  add: (input: DevframeMessageEntryInput) => Promise<DevframeMessageHandle>;
  /** Remove a message entry by id */
  remove: (id: string) => Promise<void>;
  /** Clear all message entries */
  clear: () => Promise<void>;
}
interface DevframeMessagesHost {
  readonly entries: Map<string, DevframeMessageEntry>;
  readonly events: EventEmitter<{
    'message:added': (entry: DevframeMessageEntry) => void;
    'message:updated': (entry: DevframeMessageEntry) => void;
    'message:removed': (id: string) => void;
    'message:cleared': () => void;
  }>;
  /**
   * Add a new message entry. If an entry with the same `id` already exists, it will be updated instead.
   * Returns a handle for subsequent updates/dismissal. Can be used without `await` for fire-and-forget.
   */
  add: (entry: DevframeMessageEntryInput) => Promise<DevframeMessageHandle>;
  /**
   * Update an existing message entry by id (partial update)
   */
  update: (id: string, patch: Partial<DevframeMessageEntryInput>) => Promise<DevframeMessageEntry | undefined>;
  /**
   * Remove a message entry by id
   */
  remove: (id: string) => Promise<void>;
  /**
   * Clear all message entries
   */
  clear: () => Promise<void>;
}
//#endregion
//#region src/types/json-render.d.ts
interface JsonRenderElement {
  type: string;
  props?: Record<string, unknown>;
  children?: string[];
  /** json-render event bindings (e.g. `{ press: { action: "my:action" } }`) */
  on?: Record<string, unknown>;
  /** json-render visibility condition */
  visible?: unknown;
  /** json-render repeat binding */
  repeat?: unknown;
  /** Allow additional json-render element fields */
  [key: string]: unknown;
}
interface JsonRenderSpec {
  root: string;
  elements: Record<string, JsonRenderElement>;
  /** Initial client-side state model for $state/$bindState expressions */
  state?: Record<string, unknown>;
}
interface JsonRenderer {
  /** Replace the entire spec */
  updateSpec: (spec: JsonRenderSpec) => void | Promise<void>;
  /** Update json-render state values (shallow merge into spec.state) */
  updateState: (state: Record<string, unknown>) => void | Promise<void>;
  /** Internal: shared state key used by the client to subscribe */
  readonly _stateKey: string;
}
//#endregion
//#region src/types/docks.d.ts
interface DevframeDocksHost {
  readonly views: Map<string, DevframeDockUserEntry>;
  readonly events: EventEmitter<{
    'dock:entry:updated': (entry: DevframeDockUserEntry) => void;
  }>;
  register: <T extends DevframeDockUserEntry>(entry: T, force?: boolean) => {
    update: (patch: Partial<T>) => void;
  };
  update: (entry: DevframeDockUserEntry) => void;
  values: (options?: {
    includeBuiltin?: boolean;
  }) => DevframeDockEntry[];
}
type DevframeDockEntryCategory = 'app' | 'framework' | 'web' | 'advanced' | 'default' | '~builtin' | (string & {});
type DevframeDockEntryIcon = string | {
  light: string;
  dark: string;
};
interface DevframeDockEntryBase {
  id: string;
  title: string;
  icon: DevframeDockEntryIcon;
  /**
   * The default order of the entry in the dock.
   * The higher the number the earlier it appears.
   * @default 0
   */
  defaultOrder?: number;
  /**
   * The category of the entry
   * @default 'default'
   */
  category?: DevframeDockEntryCategory;
  /**
   * Conditional visibility expression.
   * When set, the dock entry is only visible when the expression evaluates to true.
   * Uses the same syntax as command `when` clauses.
   *
   * Set to `'false'` to unconditionally hide the entry.
   *
   * @example 'clientType == embedded'
   * @see {@link import('devframe/utils/when').evaluateWhen}
   */
  when?: string;
  /**
   * Badge text to display on the dock icon (e.g., unread count)
   */
  badge?: string;
  /**
   * Id of the group this entry belongs to. When set, hosts collapse this entry
   * under the matching group's button instead of showing it directly on the
   * dock bar.
   *
   * This is a flat pointer — membership, not containment. The entry stays an
   * independently-registered, top-level entry; only its rendering is grouped
   * downstream. If the referenced group is never registered, the entry renders
   * as a normal top-level entry (orphan tolerance).
   *
   * @see {@link DevframeViewGroup}
   */
  groupId?: string;
}
interface ClientScriptEntry {
  /**
   * The filepath or module name to import from
   */
  importFrom: string;
  /**
   * The name to import the module as
   *
   * @default 'default'
   */
  importName?: string;
}
interface DevframeViewIframe extends DevframeDockEntryBase {
  type: 'iframe';
  url: string;
  /**
   * The id of the iframe, if multiple tabs is assigned with the same id, the iframe will be shared.
   *
   * When not provided, it would be treated as a unique frame.
   */
  frameId?: string;
  /**
   * Optional client script to import into the iframe
   */
  clientScript?: ClientScriptEntry;
  /**
   * Enable remote-UI mode: the hub injects a connection descriptor
   * (WS URL + pre-approved auth token) into the iframe URL so a hosted
   * page can connect back via `connectRemoteDevframe()` from
   * `@devframes/hub/client` — without needing to ship a dist with the
   * plugin.
   *
   * Requires dev mode (no effect in build mode — no WS server exists).
   * When enabled, the dock is automatically hidden in build mode unless
   * the author provides an explicit `when` clause.
   */
  remote?: boolean | RemoteDockOptions;
}
interface RemoteDockOptions {
  /**
   * How to pass the connection descriptor to the hosted page.
   *
   * - `'fragment'` (default): appended as a URL fragment.
   *   Not sent in HTTP requests or Referer headers — safest for auth tokens.
   * - `'query'`: appended as a URL query parameter. Use when your hosting
   *   platform rewrites fragments or your SPA router repurposes the fragment
   *   for navigation. The token will appear in server access logs and
   *   outbound Referer headers.
   *
   * @default 'fragment'
   */
  transport?: 'fragment' | 'query';
  /**
   * Reject WS handshakes whose `Origin` header doesn't match the dock URL
   * origin. Turn off when the same hosted app is served from multiple
   * origins (e.g. preview deploys).
   *
   * @default true
   */
  originLock?: boolean;
}
interface RemoteConnectionInfo extends ConnectionMeta {
  backend: 'websocket';
  websocket: string;
  v: 1;
  authToken: string;
  origin: string;
}
type DevframeViewLauncherStatus = 'idle' | 'loading' | 'success' | 'error';
interface DevframeViewLauncher extends DevframeDockEntryBase {
  type: 'launcher';
  launcher: {
    icon?: DevframeDockEntryIcon;
    title: string;
    status?: DevframeViewLauncherStatus;
    error?: string;
    description?: string;
    buttonStart?: string;
    buttonLoading?: string;
    onLaunch: () => Promise<void>;
  };
}
interface DevframeViewAction extends DevframeDockEntryBase {
  type: 'action';
  action: ClientScriptEntry;
}
interface DevframeViewCustomRender extends DevframeDockEntryBase {
  type: 'custom-render';
  renderer: ClientScriptEntry;
}
interface DevframeViewBuiltin extends DevframeDockEntryBase {
  type: '~builtin';
  id: '~terminals' | '~messages' | '~client-auth-notice' | '~settings' | '~popup';
}
interface DevframeViewJsonRender extends DevframeDockEntryBase {
  type: 'json-render';
  /** JsonRenderer handle created by ctx.createJsonRenderer() */
  ui: JsonRenderer;
}
/**
 * A dock group: a single dock-bar button that collapses every entry whose
 * {@link DevframeDockEntryBase.groupId} matches this group's `id`.
 *
 * A group carries its own `title`/`icon`/`category`/`defaultOrder`/`when`
 * (inherited from {@link DevframeDockEntryBase}) and has no view payload of its
 * own — hosts render its members in a popover / sub-navigation. It flows
 * through the same `register`/`update`/`values` machinery as every other entry,
 * keyed by `id`.
 *
 * Grouping is one level deep: a group entry must not itself set `groupId`.
 */
interface DevframeViewGroup extends DevframeDockEntryBase {
  type: 'group';
  /**
   * Member id auto-opened when the group button is activated. When unset,
   * activating the group only reveals its members (popover-only); no view
   * opens until a member is chosen.
   */
  defaultChildId?: string;
}
type DevframeDockUserEntry = DevframeViewIframe | DevframeViewAction | DevframeViewCustomRender | DevframeViewLauncher | DevframeViewJsonRender | DevframeViewGroup;
type DevframeDockEntry = DevframeDockUserEntry | DevframeViewBuiltin;
type DevframeDockEntriesGrouped = [category: string, entries: DevframeDockEntry[]][];
//#endregion
//#region src/types/terminals.d.ts
interface DevframeTerminalsHost {
  readonly sessions: Map<string, DevframeTerminalSession>;
  readonly events: EventEmitter<{
    'terminal:session:updated': (session: DevframeTerminalSession) => void;
  }>;
  register: (session: DevframeTerminalSession) => DevframeTerminalSession;
  update: (session: DevframeTerminalSession) => void;
  startChildProcess: (executeOptions: DevframeChildProcessExecuteOptions, terminal: Omit<DevframeTerminalSessionBase, 'status'>) => Promise<DevframeChildProcessTerminalSession>;
}
type DevframeTerminalStatus = 'running' | 'stopped' | 'error';
interface DevframeTerminalSessionBase {
  id: string;
  title: string;
  description?: string;
  status: DevframeTerminalStatus;
  icon?: DevframeDockEntryIcon;
}
interface DevframeTerminalSession extends DevframeTerminalSessionBase {
  buffer?: string[];
  stream?: ReadableStream<string>;
}
interface DevframeChildProcessExecuteOptions {
  command: string;
  args: string[];
  cwd?: string;
  env?: Record<string, string>;
}
interface DevframeChildProcessTerminalSession extends DevframeTerminalSession {
  type: 'child-process';
  executeOptions: DevframeChildProcessExecuteOptions;
  getChildProcess: () => ChildProcess | undefined;
  terminate: () => Promise<void>;
  restart: () => Promise<void>;
}
//#endregion
//#region src/node/context.d.ts
/**
 * Hub-augmented node context — extends devframe's framework-neutral
 * `DevframeNodeContext` with the hub-level subsystems (`docks`,
 * `terminals`, `messages`, `commands`) and the `createJsonRenderer`
 * factory.
 *
 * Framework kits further extend this with their own slots (e.g.
 * `viteConfig`, `viteServer`). Host-specific capabilities (editor open,
 * filesystem reveal, etc.) ship as kit-registered RPC functions rather
 * than as part of this surface.
 */
interface DevframeHubContext extends DevframeNodeContext {
  readonly host: DevframeHost;
  docks: DevframeDocksHost;
  terminals: DevframeTerminalsHost;
  messages: DevframeMessagesHost;
  commands: DevframeCommandsHost;
  /**
   * Create a JsonRenderer handle for building json-render powered UIs.
   */
  createJsonRenderer: (spec: JsonRenderSpec) => JsonRenderer;
}
interface CreateHubContextOptions extends CreateHostContextOptions {}
/**
 * Create a hub-level node context: wraps devframe's `createHostContext`,
 * attaches the hub hosts (`docks`, `terminals`, `messages`, `commands`),
 * registers the hub's built-in RPC commands, and wires the shared-state
 * synchronization that powers a hub-aware client UI.
 */
declare function createHubContext(options: CreateHubContextOptions): Promise<DevframeHubContext>;
//#endregion
export { JsonRenderer as A, DevframeViewJsonRender as C, RemoteDockOptions as D, RemoteConnectionInfo as E, DevframeMessageFilePosition as F, DevframeMessageHandle as I, DevframeMessageLevel as L, DevframeMessageEntry as M, DevframeMessageEntryFrom as N, JsonRenderElement as O, DevframeMessageEntryInput as P, DevframeMessagesClient as R, DevframeViewIframe as S, DevframeViewLauncherStatus as T, DevframeDocksHost as _, DevframeChildProcessTerminalSession as a, DevframeViewCustomRender as b, DevframeTerminalStatus as c, DevframeDockEntriesGrouped as d, DevframeDockEntry as f, DevframeDockUserEntry as g, DevframeDockEntryIcon as h, DevframeChildProcessExecuteOptions as i, DevframeMessageElementPosition as j, JsonRenderSpec as k, DevframeTerminalsHost as l, DevframeDockEntryCategory as m, DevframeHubContext as n, DevframeTerminalSession as o, DevframeDockEntryBase as p, createHubContext as r, DevframeTerminalSessionBase as s, CreateHubContextOptions as t, ClientScriptEntry as u, DevframeViewAction as v, DevframeViewLauncher as w, DevframeViewGroup as x, DevframeViewBuiltin as y, DevframeMessagesHost as z };