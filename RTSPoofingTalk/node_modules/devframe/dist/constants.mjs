//#region src/constants.ts
const DEVFRAME_MOUNT_PATH = "/__devframe/";
const DEVFRAME_MOUNT_PATH_NO_TRAILING_SLASH = "/__devframe";
const DEVFRAME_DIRNAME = "__devframe";
const DEVFRAME_CONNECTION_META_FILENAME = "__connection.json";
const DEVFRAME_RPC_DUMP_MANIFEST_FILENAME = "__rpc-dump/index.json";
const DEVFRAME_DOCK_IMPORTS_FILENAME = "__client-imports.js";
const DEVFRAME_DOCK_IMPORTS_VIRTUAL_ID = "/__devframe-client-imports.js";
const DEVFRAME_RPC_DUMP_DIRNAME = "__rpc-dump";
/**
* URL fragment / query parameter name carrying the remote dock
* connection descriptor (defined as `RemoteConnectionInfo` in
* `@vitejs/devtools-kit`) injected into remote-UI iframe dock URLs.
*/
const REMOTE_CONNECTION_KEY = "devframe-remote-connection";
//#endregion
export { DEVFRAME_CONNECTION_META_FILENAME, DEVFRAME_DIRNAME, DEVFRAME_DOCK_IMPORTS_FILENAME, DEVFRAME_DOCK_IMPORTS_VIRTUAL_ID, DEVFRAME_MOUNT_PATH, DEVFRAME_MOUNT_PATH_NO_TRAILING_SLASH, DEVFRAME_RPC_DUMP_DIRNAME, DEVFRAME_RPC_DUMP_MANIFEST_FILENAME, REMOTE_CONNECTION_KEY };
