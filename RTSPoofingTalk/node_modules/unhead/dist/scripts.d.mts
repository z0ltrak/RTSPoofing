import { R as RecordingEntry } from './shared/unhead.rdR8o82F.mjs';
export { a as AsVoidFunctions, j as EventHandlerOptions, u as ScriptInstance, z as UseFunctionType, B as UseScriptContext, F as UseScriptInput, G as UseScriptOptions, I as UseScriptResolvedInput, J as UseScriptReturn, K as UseScriptStatus, W as WarmupStrategy } from './shared/unhead.rdR8o82F.mjs';
export { u as useScript } from './shared/unhead.DTAcYAas.mjs';
import 'hookable';
import './shared/unhead.B8_fLxlB.mjs';

declare function createSpyProxy<T extends Record<string, any> | any[]>(target: T, onApply: (stack: RecordingEntry[][]) => void): T;

export { RecordingEntry, createSpyProxy };
