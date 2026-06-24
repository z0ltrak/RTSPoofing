import { R as RecordingEntry } from './shared/unhead.71V9w6oU.js';
export { a as AsVoidFunctions, j as EventHandlerOptions, u as ScriptInstance, z as UseFunctionType, B as UseScriptContext, F as UseScriptInput, G as UseScriptOptions, I as UseScriptResolvedInput, J as UseScriptReturn, K as UseScriptStatus, W as WarmupStrategy } from './shared/unhead.71V9w6oU.js';
export { u as useScript } from './shared/unhead.HonJKaMo.js';
import 'hookable';
import './shared/unhead.B8_fLxlB.js';

declare function createSpyProxy<T extends Record<string, any> | any[]>(target: T, onApply: (stack: RecordingEntry[][]) => void): T;

export { RecordingEntry, createSpyProxy };
