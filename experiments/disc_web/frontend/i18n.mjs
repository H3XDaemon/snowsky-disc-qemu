const storageKey = 'disc-web.language';
let locale = 'ru';
let messages = {};
export const normalizeLocale = value => ['ru','en'].includes(value) ? value : 'ru';
export const getLocale = () => locale;

export function message(dictionary, language, key, values={}) {
  let value = dictionary[key];
  if (value && typeof value === 'object') value = value[new Intl.PluralRules(language).select(values.count)] ?? value.other;
  if (typeof value !== 'string') throw new Error(`Missing locale message: ${language}/${key}`);
  return value.replace(/\{(\w+)\}/g, (_, name) => String(values[name] ?? `{${name}}`));
}
export const t = (key, values={}) => message(messages[locale], locale, key, values);

export function translateStatic(root=document) {
  for (const node of root.querySelectorAll('[data-i18n]')) node.textContent=t(node.dataset.i18n);
  for (const attribute of ['aria-label','title','placeholder']) {
    for (const node of root.querySelectorAll(`[data-i18n-${attribute}]`)) node.setAttribute(attribute,t(node.getAttribute(`data-i18n-${attribute}`)));
  }
  document.documentElement.lang=locale;
  document.title=locale==='ru' ? 'DISC — ваша музыка' : 'DISC — your music';
}
export function setLocale(value, persist=true) {
  locale=normalizeLocale(value);
  if (persist) {try {localStorage.setItem(storageKey,locale);} catch { /* Session-only preferences still work. */ }}
  translateStatic();
  window.dispatchEvent(new CustomEvent('disc-language-change'));
}
export async function initLocale() {
  const loaded=await Promise.all(['ru','en'].map(async language => {
    const response=await fetch(`/locales/${language}.json`);
    if (!response.ok) throw new Error('Locale resources unavailable');
    return [language,await response.json()];
  }));
  messages=Object.fromEntries(loaded);
  let value=navigator.language.toLowerCase().startsWith('en') ? 'en' : 'ru';
  try {value=localStorage.getItem(storageKey) || value;} catch { /* Keep the browser default. */ }
  locale=normalizeLocale(value);
  translateStatic();
  window.addEventListener('storage',event=>{if(event.key===storageKey) setLocale(event.newValue,false);});
}
