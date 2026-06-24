import { c as createUnhead, r as registerPlugin } from './unhead.CfgPMHXt.mjs';
import { c as callHook, a as createHooks } from './unhead.mB5lMBMV.mjs';
import { r as resolveTags } from './unhead.Cdnk2khL.mjs';
import { b as TagPriorityAliases, c as TagsWithInnerContent, a as SelfClosingTags } from './unhead.fg-0ge_u.mjs';

const TAG_WEIGHTS = { base: -10, title: 10 };
const LINK_WEIGHTS = { "preconnect": 20, "stylesheet": 60, "preload": 70, "modulepreload": 70, "prefetch": 90, "dns-prefetch": 90, "prerender": 90 };
const ImportStyleRe = /@import/;
const isTruthy = (v) => v === "" || v === true;
function capoTagWeight(tag) {
  if (typeof tag.tagPriority === "number")
    return tag.tagPriority;
  let weight = 100;
  const offset = TagPriorityAliases[tag.tagPriority] || 0;
  if (tag.tag in TAG_WEIGHTS) {
    weight = TAG_WEIGHTS[tag.tag];
  } else if (tag.tag === "meta") {
    weight = tag.props["http-equiv"] === "content-security-policy" ? -30 : tag.props.charset ? -20 : tag.props.name === "viewport" ? -15 : weight;
  } else if (tag.tag === "link" && tag.props.rel) {
    weight = LINK_WEIGHTS[tag.props.rel];
  } else if (tag.tag === "script") {
    const type = String(tag.props.type);
    const json = type.endsWith("json");
    if (type === "importmap")
      weight = 25;
    else if (type === "speculationrules")
      weight = 90;
    else if (isTruthy(tag.props.async))
      weight = 30;
    else if (tag.props.src && !isTruthy(tag.props.defer) && type !== "module" && !json || (tag.innerHTML || tag.textContent) && !json)
      weight = 50;
    else if (isTruthy(tag.props.defer) && tag.props.src || type === "module")
      weight = 80;
  } else if (tag.tag === "style") {
    weight = tag.innerHTML && ImportStyleRe.test(tag.innerHTML) ? 40 : 60;
  }
  return (weight || 100) + offset;
}

const DOUBLE_QUOTE_RE = /"/g;
function encodeAttribute(value) {
  const s = typeof value === "string" ? value : String(value);
  return s.includes('"') ? s.replace(DOUBLE_QUOTE_RE, "&quot;") : s;
}
function propsToString(props) {
  let attrs = "";
  for (const key in props) {
    if (!Object.hasOwn(props, key))
      continue;
    let value = props[key];
    if ((key === "class" || key === "style") && typeof value !== "string") {
      value = key === "class" ? [...value].join(" ") : Array.from(value, ([k, v]) => `${k}:${v}`).join(";");
    }
    if (value !== false && value !== null) {
      attrs += value === true ? ` ${key}` : ` ${key}="${encodeAttribute(value)}"`;
    }
  }
  return attrs;
}

const ESCAPE_HTML_RE = /[&<>"'/]/g;
const CLOSE_TAG_RE = {};
const ESCAPE_HTML_MAP = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#x27;", "/": "&#x2F;" };
function escapeHtml(str) {
  return str.replace(ESCAPE_HTML_RE, (c) => ESCAPE_HTML_MAP[c]);
}
function tagToString(tag) {
  const attrs = propsToString(tag.props);
  const openTag = `<${tag.tag}${attrs}>`;
  if (!TagsWithInnerContent.has(tag.tag))
    return SelfClosingTags.has(tag.tag) ? openTag : `${openTag}</${tag.tag}>`;
  let content = String(tag.textContent || tag.innerHTML || "");
  content = tag.tag === "title" ? escapeHtml(content) : content.replace(CLOSE_TAG_RE[tag.tag] ||= new RegExp(`</${tag.tag}`, "gi"), `<\\/${tag.tag}`);
  return SelfClosingTags.has(tag.tag) ? openTag : `${openTag}${content}</${tag.tag}>`;
}

function ssrRenderTags(tags, options) {
  const schema = { htmlAttrs: {}, bodyAttrs: {}, tags: { head: "", bodyClose: "", bodyOpen: "" } };
  const lineBreaks = !options?.omitLineBreaks ? "\n" : "";
  for (const tag of tags) {
    if (tag.tag === "htmlAttrs" || tag.tag === "bodyAttrs") {
      Object.assign(schema[tag.tag], tag.props);
      continue;
    }
    const s = tagToString(tag);
    const tagPosition = tag.tagPosition || "head";
    schema.tags[tagPosition] += schema.tags[tagPosition] ? `${lineBreaks}${s}` : s;
  }
  return {
    headTags: schema.tags.head,
    bodyTags: schema.tags.bodyClose,
    bodyTagsOpen: schema.tags.bodyOpen,
    htmlAttrs: propsToString(schema.htmlAttrs),
    bodyAttrs: propsToString(schema.bodyAttrs)
  };
}

// @__NO_SIDE_EFFECTS__
function createServerRenderer(options = {}) {
  return (head) => {
    const beforeRenderCtx = { shouldRender: true };
    callHook(head, "ssr:beforeRender", beforeRenderCtx);
    if (!beforeRenderCtx.shouldRender)
      return ssrRenderTags([]);
    const ctx = {
      tags: options.resolvedTags || resolveTags(head, { tagWeight: options.tagWeight ?? capoTagWeight }),
      options: { ...options }
    };
    callHook(head, "ssr:render", ctx);
    const html = ssrRenderTags(ctx.tags, ctx.options);
    const renderCtx = { tags: ctx.tags, html };
    callHook(head, "ssr:rendered", renderCtx);
    return renderCtx.html;
  };
}
// @__NO_SIDE_EFFECTS__
function renderSSRHead(head, options) {
  return (/* @__PURE__ */ createServerRenderer(options))(head);
}

// @__NO_SIDE_EFFECTS__
function createHead(options = {}) {
  const tagWeight = options.tagWeight || capoTagWeight;
  const render = createServerRenderer({ tagWeight, omitLineBreaks: options.omitLineBreaks });
  const core = createUnhead(render, {
    _tagWeight: tagWeight,
    // @ts-expect-error untyped
    document: false,
    experimentalStreamKey: options.experimentalStreamKey,
    propResolvers: [
      ...options.propResolvers || [],
      (k, v) => {
        if (k && k.startsWith("on") && typeof v === "function") {
          return `this.dataset.${k}fired = true`;
        }
        return v;
      }
    ],
    init: [
      options.disableDefaults ? void 0 : {
        htmlAttrs: {
          lang: "en"
        },
        meta: [
          {
            charset: "utf-8"
          },
          {
            name: "viewport",
            content: "width=device-width, initial-scale=1"
          }
        ]
      },
      ...options.init || []
    ]
  });
  const hooks = createHooks(options.hooks);
  const head = {
    ...core,
    hooks,
    render: () => render(head),
    use: (p) => registerPlugin(head, p)
  };
  options.plugins?.forEach((p) => registerPlugin(head, p));
  head._ssrPayload = {};
  const payloadHook = (ctx) => {
    let payload = {};
    if (Object.keys(head._ssrPayload || {}).length > 0) {
      payload = { ...head._ssrPayload };
    }
    if (Object.values(payload).some(Boolean)) {
      ctx.tags.push({
        tag: "script",
        innerHTML: JSON.stringify(payload),
        props: { id: "unhead:payload", type: "application/json" }
      });
    }
  };
  payloadHook._nonMutating = true;
  registerPlugin(head, {
    key: "server",
    hooks: {
      "tags:resolve": payloadHook
    }
  });
  return head;
}

export { createHead as a, createServerRenderer as b, capoTagWeight as c, escapeHtml as e, propsToString as p, renderSSRHead as r, ssrRenderTags as s, tagToString as t };
