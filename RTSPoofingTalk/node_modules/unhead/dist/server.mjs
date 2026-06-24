export { c as capoTagWeight, a as createHead, b as createServerRenderer, e as escapeHtml, p as propsToString, r as renderSSRHead, s as ssrRenderTags, t as tagToString } from './shared/unhead.yYqx02R-.mjs';
import { parseHtmlForUnheadExtraction, applyHeadToHtml, parseHtmlForIndexes } from './parser.mjs';
import './shared/unhead.CfgPMHXt.mjs';
import './shared/unhead.mB5lMBMV.mjs';
import 'hookable';
import './shared/unhead.Cdnk2khL.mjs';
import './shared/unhead.fg-0ge_u.mjs';

// @__NO_SIDE_EFFECTS__
function transformHtmlTemplate(head, html) {
  const template = parseHtmlForUnheadExtraction(html);
  head.push(template.input, { _index: 0 });
  return applyHeadToHtml(template, head.render());
}
// @__NO_SIDE_EFFECTS__
function transformHtmlTemplateRaw(head, html) {
  const template = parseHtmlForIndexes(html);
  return applyHeadToHtml(template, head.render());
}

export { transformHtmlTemplate, transformHtmlTemplateRaw };
