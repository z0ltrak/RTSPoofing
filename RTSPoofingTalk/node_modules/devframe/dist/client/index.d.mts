import { T as StreamSink, U as DevframeRpcClientFunctions, W as DevframeRpcServerFunctions, g as RpcSharedStateHost, l as ConnectionMeta, ot as EventEmitter, w as StreamReader } from "../devframe-BuR6n9ZD.mjs";
import { C as RpcFunctionsCollector } from "../types-BkkQ0Txg.mjs";
import { C as RpcCacheManager, w as RpcCacheOptions } from "../index-C7M1hnvL.mjs";
import { t as WsRpcChannelOptions } from "../ws-client-CVYX9niP.mjs";
import { BirpcOptions, BirpcReturn } from "birpc";

//#region src/client/rpc-streaming.d.ts
interface StreamingSubscribeOptions {
  /** Maximum buffered chunks before the oldest is dropped. Default 256. */
  highWaterMark?: number;
}
interface RpcStreamingClientHost {
  /**
   * Subscribe to a server-side stream by channel + id. Returns a reader
   * that's both an `AsyncIterable<T>` (`for await`) and exposes
   * `readable: ReadableStream<T>` for `pipeTo`-style consumption.
   */
  subscribe: <T = unknown>(channel: string, id: string, options?: StreamingSubscribeOptions) => StreamReader<T>;
  /**
   * Open the client side of a client-to-server upload. The id is
   * typically obtained from a prior action call that ran
   * `channel.openInbound()` on the server. Returns a `StreamSink<T>`
   * that mirrors the server-side producer surface (write / close /
   * error / writable / signal).
   *
   * The sink's `signal` aborts when the server cancels the upload.
   */
  upload: <T = unknown>(channel: string, id: string) => StreamSink<T>;
}
/**
 * Client-side streaming host. Mirrors `createRpcSharedStateClientHost`:
 * registers the two `:chunk` / `:end` event handlers once, then per-stream
 * state lives in a `Map<streamKey, StreamReader>`.
 */
declare function createRpcStreamingClientHost(rpc: DevframeRpcClient): RpcStreamingClientHost;
//#endregion
//#region src/client/rpc.d.ts
interface DevframeRpcContext {
  /**
   * The RPC client to interact with the server
   */
  readonly rpc: DevframeRpcClient;
}
type DevframeClientRpcHost = RpcFunctionsCollector<DevframeRpcClientFunctions, DevframeRpcContext>;
interface RpcClientEvents {
  'rpc:is-trusted:updated': (isTrusted: boolean) => void;
}
interface DevframeRpcClientOptions {
  connectionMeta?: ConnectionMeta;
  baseURL?: string | string[];
  /**
   * The auth token to use for the client
   */
  authToken?: string;
  wsOptions?: Partial<WsRpcChannelOptions>;
  rpcOptions?: Partial<BirpcOptions<DevframeRpcServerFunctions, DevframeRpcClientFunctions, boolean>>;
  cacheOptions?: boolean | Partial<RpcCacheOptions>;
}
type DevframeRpcClientCall = BirpcReturn<DevframeRpcServerFunctions, DevframeRpcClientFunctions>['$call'];
type DevframeRpcClientCallEvent = BirpcReturn<DevframeRpcServerFunctions, DevframeRpcClientFunctions>['$callEvent'];
type DevframeRpcClientCallOptional = BirpcReturn<DevframeRpcServerFunctions, DevframeRpcClientFunctions>['$callOptional'];
interface DevframeRpcClient {
  /**
   * The events of the client
   */
  events: EventEmitter<RpcClientEvents>;
  /**
   * Whether the client is trusted
   */
  readonly isTrusted: boolean | null;
  /**
   * The connection meta
   */
  readonly connectionMeta: ConnectionMeta;
  /**
   * Return a promise that resolves when the client is trusted
   *
   * Rejects with an error if the timeout is reached
   *
   * @param timeout - The timeout in milliseconds, default to 60 seconds
   */
  ensureTrusted: (timeout?: number) => Promise<boolean>;
  /**
   * Request trust from the server
   */
  requestTrust: () => Promise<boolean>;
  /**
   * Request trust from the server using a specific auth token.
   * Updates the stored token and re-requests trust without reloading the page.
   */
  requestTrustWithToken: (token: string) => Promise<boolean>;
  /**
   * Call a RPC function on the server
   */
  call: DevframeRpcClientCall;
  /**
   * Call a RPC event on the server, and does not expect a response
   */
  callEvent: DevframeRpcClientCallEvent;
  /**
   * Call a RPC optional function on the server
   */
  callOptional: DevframeRpcClientCallOptional;
  /**
   * The client RPC host
   */
  client: DevframeClientRpcHost;
  /**
   * The shared state host
   */
  sharedState: RpcSharedStateHost;
  /**
   * The streaming channel host. Subscribe to a server-side stream by
   * channel + id; the returned reader is both `AsyncIterable<T>` and
   * exposes `.readable: ReadableStream<T>` for `pipeTo` consumption.
   */
  streaming: RpcStreamingClientHost;
  /**
   * The RPC cache manager
   */
  cacheManager: RpcCacheManager;
}
interface DevframeRpcClientMode {
  readonly isTrusted: boolean;
  ensureTrusted: DevframeRpcClient['ensureTrusted'];
  requestTrust: DevframeRpcClient['requestTrust'];
  requestTrustWithToken: DevframeRpcClient['requestTrustWithToken'];
  call: DevframeRpcClient['call'];
  callEvent: DevframeRpcClient['callEvent'];
  callOptional: DevframeRpcClient['callOptional'];
}
declare function getDevframeRpcClient(options?: DevframeRpcClientOptions): Promise<DevframeRpcClient>;
//#endregion
//#region src/client/index.d.ts
declare const connectDevframe: typeof getDevframeRpcClient;
//#endregion
export { DevframeClientRpcHost, DevframeRpcClient, DevframeRpcClientCall, DevframeRpcClientCallEvent, DevframeRpcClientCallOptional, DevframeRpcClientMode, DevframeRpcClientOptions, DevframeRpcContext, RpcClientEvents, RpcStreamingClientHost, StreamingSubscribeOptions, connectDevframe, createRpcStreamingClientHost, getDevframeRpcClient };