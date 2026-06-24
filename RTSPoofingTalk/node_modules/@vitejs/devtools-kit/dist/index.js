import { createDefineWrapperWithContext } from "devframe/rpc";
import { defineCommand, defineDockEntry, defineJsonRenderSpec } from "@devframes/hub";
//#region src/define.ts
const defineRpcFunction = createDefineWrapperWithContext();
//#endregion
export { defineCommand, defineDockEntry, defineJsonRenderSpec, defineRpcFunction };
