import { t as DevToolsDocksUserSettings } from "./settings-CbzpSCWB.js";
import { DEFAULT_STATE_USER_SETTINGS } from "@devframes/hub/constants";
import { DEVFRAME_CONNECTION_META_FILENAME as DEVTOOLS_CONNECTION_META_FILENAME, DEVFRAME_DOCK_IMPORTS_FILENAME as DEVTOOLS_DOCK_IMPORTS_FILENAME, DEVFRAME_RPC_DUMP_DIRNAME as DEVTOOLS_RPC_DUMP_DIRNAME, DEVFRAME_RPC_DUMP_MANIFEST_FILENAME as DEVTOOLS_RPC_DUMP_MANIFEST_FILENAME, REMOTE_CONNECTION_KEY } from "devframe/constants";

//#region src/constants.d.ts
declare const DEVTOOLS_MOUNT_PATH = "/__devtools/";
declare const DEVTOOLS_MOUNT_PATH_NO_TRAILING_SLASH = "/__devtools";
declare const DEVTOOLS_DIRNAME = "__devtools";
declare const DEVTOOLS_DOCK_IMPORTS_VIRTUAL_ID = "/__devtools-client-imports.js";
/**
 * Id of the built-in dock group that collects Vite Plus integrations
 * (Rolldown, etc.) under a single "Vite+" dock button. Vite DevTools seeds
 * this group; integrations join it by setting `groupId` to this value.
 */
declare const DEVTOOLS_VITEPLUS_GROUP_ID = "~viteplus";
declare const DEFAULT_CATEGORIES_ORDER: Record<string, number>;
//#endregion
export { DEFAULT_CATEGORIES_ORDER, DEFAULT_STATE_USER_SETTINGS, DEVTOOLS_CONNECTION_META_FILENAME, DEVTOOLS_DIRNAME, DEVTOOLS_DOCK_IMPORTS_FILENAME, DEVTOOLS_DOCK_IMPORTS_VIRTUAL_ID, DEVTOOLS_MOUNT_PATH, DEVTOOLS_MOUNT_PATH_NO_TRAILING_SLASH, DEVTOOLS_RPC_DUMP_DIRNAME, DEVTOOLS_RPC_DUMP_MANIFEST_FILENAME, DEVTOOLS_VITEPLUS_GROUP_ID, type DevToolsDocksUserSettings, REMOTE_CONNECTION_KEY };