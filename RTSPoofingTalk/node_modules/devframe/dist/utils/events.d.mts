import { ct as EventsMap, ot as EventEmitter } from "../devframe-BuR6n9ZD.mjs";

//#region src/utils/events.d.ts
/**
 * Create event emitter.
 */
declare function createEventEmitter<Events extends EventsMap>(): EventEmitter<Events>;
//#endregion
export { createEventEmitter };