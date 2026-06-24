import { ActiveHeadEntry } from 'unhead/types';
export { ActiveHeadEntry, AriaAttributes, BodyAttributesWithoutEvents, BodyEvents, DataKeys, GenericLink, GenericScript, GlobalAttributes, HeadEntryOptions, HeadTag, HttpEventAttributes, MetaFlat, MetaFlat as MetaFlatInput, RawInput, RenderSSRHeadOptions, ResolvableHead, SerializableHead, SpeculationRules, Unhead } from 'unhead/types';
import { V as VueHeadClient, U as UseHeadInput, o as UseHeadOptions, p as UseSeoMetaInput } from './shared/vue.utlLo3Bi.js';
export { B as BodyAttr, D as DeepResolvableProperties, R as Head, H as HtmlAttr, M as MaybeFalsy, R as ReactiveHead, a as ResolvableArray, b as ResolvableBase, c as ResolvableBodyAttributes, d as ResolvableHtmlAttributes, e as ResolvableLink, f as ResolvableMeta, g as ResolvableNoscript, h as ResolvableProperties, i as ResolvableScript, j as ResolvableStyle, k as ResolvableTitle, l as ResolvableTitleTemplate, m as ResolvableUnion, n as ResolvableValue } from './shared/vue.utlLo3Bi.js';
import { UseHeadSafeInput } from './types.js';
export { Base, BodyAttributes, HeadSafe, HtmlAttributes, Link, MergeHead, Meta, Noscript, SafeBodyAttr, SafeHtmlAttr, SafeLink, SafeMeta, SafeNoscript, SafeScript, SafeStyle, Script, Style } from './types.js';
export { AsVoidFunctions, EventHandlerOptions, RecordingEntry, ScriptInstance, UseFunctionType, UseScriptResolvedInput, UseScriptStatus, WarmupStrategy, createSpyProxy } from 'unhead/scripts';
export { UseScriptContext, UseScriptInput, UseScriptOptions, UseScriptReturn, VueScriptInstance, useScript } from './scripts.js';
export { resolveUnrefHeadInput } from './utils.js';
export { V as VueHeadMixin } from './shared/vue.DnywREVF.js';
export { createUnhead, defineLink, defineScript } from 'unhead';
import 'vue';
import 'unhead/utils';

declare const unheadVueComposablesImports: {
    '@unhead/vue': string[];
};

declare function injectHead(): VueHeadClient;
declare function useHead<I = UseHeadInput>(input?: UseHeadInput, options?: UseHeadOptions): ActiveHeadEntry<I>;
declare function useHeadSafe(input?: UseHeadSafeInput, options?: UseHeadOptions): ActiveHeadEntry<UseHeadSafeInput>;
declare function useSeoMeta(input?: UseSeoMetaInput, options?: UseHeadOptions): ActiveHeadEntry<UseSeoMetaInput>;

/** @deprecated Use `useHead` instead. */
declare const useServerHead: typeof useHead;
/** @deprecated Use `useHeadSafe` instead. */
declare const useServerHeadSafe: typeof useHeadSafe;
/** @deprecated Use `useSeoMeta` instead. */
declare const useServerSeoMeta: typeof useSeoMeta;

declare const headSymbol = "usehead";

export { UseHeadInput, UseHeadOptions, UseHeadSafeInput, UseSeoMetaInput, VueHeadClient, headSymbol, injectHead, unheadVueComposablesImports, useHead, useHeadSafe, useSeoMeta, useServerHead, useServerHeadSafe, useServerSeoMeta };
