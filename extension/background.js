// background.js — MV3 service worker.
// Seeds the master profile into chrome.storage.local on install and brokers messages.
// No external network calls: the "speculative AI co-processor" is intentionally OMITTED.
// Tailored per-application answers arrive via the pasted application-package (pipeline output),
// so nothing about the user ever leaves the machine.

async function loadSeedProfile() {
  for (const filename of ['profile.local.json', 'profile.default.json']) {
    try {
      const response = await fetch(chrome.runtime.getURL(filename));
      if (response.ok) return await response.json();
    } catch (error) {}
  }
  throw new Error('no local or default profile available');
}

async function seedProfile() {
  try {
    const profile = await loadSeedProfile();
    const existing = await chrome.storage.local.get('user_profile');
    if (!existing.user_profile ||
        Number(existing.user_profile._profile_version || 0) < Number(profile._profile_version || 0)) {
      await chrome.storage.local.set({ user_profile: profile });
      console.log('[P1] seeded/migrated default profile into storage');
    }
  } catch (e) {
    console.error('[P1] profile seed failed', e);
  }
}

chrome.runtime.onInstalled.addListener(seedProfile);
chrome.runtime.onStartup.addListener(seedProfile);

// Recovery path for pages that were already open when the unpacked extension was
// reloaded. Clicking the extension toolbar icon explicitly injects the same
// local-only UI and stylesheet. content.js is idempotent, so this is safe even
// when declarative content-script injection already succeeded.
chrome.action.onClicked.addListener(async (tab) => {
  if (!tab.id || !/^https:\/\//.test(tab.url || '')) return;
  try {
    await chrome.scripting.insertCSS({
      target: { tabId: tab.id, allFrames: true },
      files: ['sidebar.css']
    });
    await chrome.scripting.executeScript({
      target: { tabId: tab.id, allFrames: true },
      files: ['content.js']
    });
  } catch (error) {
    console.error('[P1] explicit injection failed', error);
  }
});

// Package bridge: CareerForger publishes packages/<app_id>.json + packages/index.json into this
// folder. Match strictly on the job's own URL or job id, never on company name alone, so the
// wrong tailored resume can never be attached.
function jobTokens(url) {
  const tokens = new Set();
  const text = String(url || '');
  const uuid = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/gi;
  for (const m of text.matchAll(uuid)) tokens.add(m[0].toLowerCase());
  // Whole numeric ids only (Greenhouse 7773680003, gh_jid=...), never digit runs inside a UUID.
  for (const m of text.replace(uuid, ' ').matchAll(/(?<![0-9A-Za-z])\d{6,}(?![0-9A-Za-z])/g)) tokens.add(m[0]);
  return tokens;
}
function packageMatches(entry, pageUrl) {
  let page;
  try { page = new URL(pageUrl); } catch (e) { return false; }
  const pagePath = page.pathname.replace(/\/(apply|application)\/?$/i, '').replace(/\/$/, '');
  if (entry.host && entry.host === page.host.toLowerCase() && entry.path &&
      (pagePath === entry.path || pagePath.startsWith(entry.path + '/'))) return true;
  const pageTokens = jobTokens(pageUrl);
  for (const t of jobTokens(entry.apply_url)) if (pageTokens.has(t)) return true;
  return false;
}
async function findPackage(pageUrl) {
  const res = await fetch(chrome.runtime.getURL('packages/index.json'), { cache: 'no-store' });
  if (!res.ok) return null;
  const index = await res.json();
  const entry = (index.packages || []).find((e) => packageMatches(e, pageUrl));
  if (!entry) return null;
  const pkgRes = await fetch(chrome.runtime.getURL(entry.file), { cache: 'no-store' });
  return pkgRes.ok ? await pkgRes.json() : null;
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.action === 'FIND_PACKAGE') {
    findPackage(msg.url).then((p) => sendResponse({ package: p }))
      .catch(() => sendResponse({ package: null }));
    return true; // async
  }
  if (msg.action === 'GET_PROFILE') {
    chrome.storage.local.get('user_profile', (d) => sendResponse(d.user_profile || null));
    return true; // async
  }
  if (msg.action === 'SET_PROFILE') {
    chrome.storage.local.set({ user_profile: msg.payload }, () => sendResponse({ ok: true }));
    return true;
  }
  if (msg.action === 'SELECT_REACT_OPTION') {
    (async () => {
      if (!sender.tab?.id || !msg.elementId) {
        sendResponse({ ok: false, error: 'missing tab or element id' });
        return;
      }
      try {
        const [{ result }] = await chrome.scripting.executeScript({
          target: {
            tabId: sender.tab.id,
            frameIds: [sender.frameId || 0]
          },
          world: 'MAIN',
          func: (elementId, wanted) => {
            const input = document.getElementById(elementId);
            if (!input) return { ok: false, error: 'combobox missing' };
            const norm = (value) => String(value || '')
              .replace(/\s+/g, ' ').trim().toLowerCase();
            const target = norm(wanted);
            const options = Array.from(document.querySelectorAll(
              '[role=option], .select__option, [data-option-index]'
            )).filter((node) => node.getClientRects().length > 0);
            const option = options.find((node) => norm(node.textContent) === target) ||
              options.find((node) => norm(node.textContent).startsWith(target));
            if (!option) {
              return {
                ok: false,
                error: 'option missing',
                options: options.map((node) => norm(node.textContent)).slice(0, 20)
              };
            }
            const propsKey = Object.keys(option)
              .find((key) => key.startsWith('__reactProps$'));
            const props = propsKey && option[propsKey];
            if (typeof props?.onMouseDown === 'function') {
              props.onMouseDown({
                type: 'mousedown',
                button: 0,
                buttons: 1,
                target: option,
                currentTarget: option,
                preventDefault() {},
                stopPropagation() {},
                nativeEvent: new MouseEvent('mousedown')
              });
              return { ok: true, method: 'react-main-world', chosen: norm(option.textContent) };
            }
            option.dispatchEvent(new MouseEvent('mousedown', {
              bubbles: true,
              cancelable: true,
              view: window,
              button: 0,
              buttons: 1
            }));
            return { ok: true, method: 'mousedown-main-world', chosen: norm(option.textContent) };
          },
          args: [msg.elementId, msg.wanted]
        });
        sendResponse(result || { ok: false, error: 'no main-world result' });
      } catch (error) {
        sendResponse({ ok: false, error: String(error) });
      }
    })();
    return true;
  }
  if (msg.action === 'TRUSTED_OPTION_CLICK') {
    (async () => {
      const tabId = sender.tab?.id;
      const tabUrl = String(sender.tab?.url || '');
      let x = Number(msg.x);
      let y = Number(msg.y);
      const wanted = String(msg.wanted || '').replace(/\s+/g, ' ').trim().toLowerCase();
      const targetKind = msg.targetKind === 'control' ? 'control' : 'option';
      const allowedAts = /^https:\/\/(([^/]+\.)?(greenhouse\.io|ashbyhq\.com|lever\.co)\/|[a-z0-9-]+\.fa(\.[a-z0-9-]+)?\.oraclecloud\.com\/hcmUI\/CandidateExperience\/)/i;
      if (!allowedAts.test(tabUrl)) {
        sendResponse({ ok: false, error: 'trusted input blocked outside approved ATS domains' });
        return;
      }
      if (!tabId || !Number.isFinite(x) || !Number.isFinite(y)) {
        sendResponse({ ok: false, error: 'missing tab or option coordinates' });
        return;
      }
      const target = { tabId };
      let attached = false;
      try {
        const [{ result: verifiedTarget }] = await chrome.scripting.executeScript({
          target: { tabId, frameIds: [sender.frameId || 0] },
          world: 'MAIN',
          func: (clientX, clientY, expected, kind) => {
            const hit = document.elementFromPoint(clientX, clientY);
            const isSubmit = Boolean(hit?.closest?.(
              'button[type=submit], input[type=submit], #submit_app'
            ));
            if (kind === 'control') {
              const expectedCombobox = document.getElementById(expected);
              const hitControl = hit?.closest?.(
                '[role=combobox], button[aria-label="Toggle flyout"], ' +
                'button[aria-haspopup=listbox], .select__control'
              );
              const shell = expectedCombobox?.closest?.('.select-shell');
              const ownsHit = Boolean(expectedCombobox && hit &&
                (hit === expectedCombobox || expectedCombobox.contains(hit) || shell?.contains(hit)));
              return {
                ok: Boolean(expectedCombobox?.isConnected) &&
                  expectedCombobox?.getAttribute?.('role') === 'combobox' &&
                  ownsHit &&
                  !isSubmit,
                text: expectedCombobox?.id || '',
                isSubmit,
                hitControl: Boolean(hitControl)
              };
            }
            let option = hit?.closest?.(
              '[role=option], .select__option, [data-option-index], ' +
              '[id^="react-select-"][id*="-option-"]'
            );
            let text = String(option?.textContent || '')
              .replace(/\s+/g, ' ').trim().toLowerCase();
            if (!option || text !== expected) {
              option = Array.from(document.querySelectorAll(
                '[role=option], .select__option, [data-option-index], ' +
                '[id^="react-select-"][id*="-option-"], .select__menu-list > div'
              )).find((node) => {
                const candidate = String(node.textContent || '')
                  .replace(/\s+/g, ' ').trim().toLowerCase();
                return node.getClientRects().length > 0 && candidate === expected;
              });
              text = String(option?.textContent || '')
                .replace(/\s+/g, ' ').trim().toLowerCase();
            }
            const rect = option?.getBoundingClientRect?.();
            return {
              ok: Boolean(option) && !isSubmit && text === expected,
              text,
              isSubmit,
              point: rect ? { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 } : null
            };
          },
          args: [x, y, wanted, targetKind]
        });
        if (!verifiedTarget?.ok) {
          sendResponse({
            ok: false,
            error: 'trusted click target failed exact option verification',
            target: verifiedTarget
          });
          return;
        }
        if (targetKind === 'option' && verifiedTarget.point) {
          x = Number(verifiedTarget.point.x);
          y = Number(verifiedTarget.point.y);
        }
        await chrome.debugger.attach(target, '1.3');
        attached = true;
        await chrome.debugger.sendCommand(target, 'Input.dispatchMouseEvent', {
          type: 'mouseMoved',
          x,
          y
        });
        await chrome.debugger.sendCommand(target, 'Input.dispatchMouseEvent', {
          type: 'mousePressed',
          x,
          y,
          button: 'left',
          buttons: 1,
          clickCount: 1
        });
        await chrome.debugger.sendCommand(target, 'Input.dispatchMouseEvent', {
          type: 'mouseReleased',
          x,
          y,
          button: 'left',
          buttons: 0,
          clickCount: 1
        });
        sendResponse({
          ok: true,
          method: targetKind === 'control'
            ? 'trusted-cdp-control-click'
            : 'trusted-cdp-option-click'
        });
      } catch (error) {
        sendResponse({ ok: false, error: String(error) });
      } finally {
        if (attached) {
          try { await chrome.debugger.detach(target); } catch (error) {}
        }
      }
    })();
    return true;
  }
  if (msg.action === 'TRUSTED_COMBOBOX_TEXT') {
    (async () => {
      const tabId = sender.tab?.id;
      const tabUrl = String(sender.tab?.url || '');
      const elementId = String(msg.elementId || '');
      const text = String(msg.text || '');
      const allowedAts = /^https:\/\/(([^/]+\.)?(greenhouse\.io|ashbyhq\.com|lever\.co)\/|[a-z0-9-]+\.fa(\.[a-z0-9-]+)?\.oraclecloud\.com\/hcmUI\/CandidateExperience\/)/i;
      if (!allowedAts.test(tabUrl) || !tabId || !elementId || !text || text.length > 200) {
        sendResponse({ ok: false, error: 'trusted text blocked by ATS/input guard' });
        return;
      }
      const target = { tabId };
      let attached = false;
      try {
        const [{ result: verified }] = await chrome.scripting.executeScript({
          target: { tabId, frameIds: [sender.frameId || 0] },
          world: 'MAIN',
          func: (id) => {
            const el = document.getElementById(id);
            const ok = Boolean(el?.isConnected &&
              (el.getAttribute('role') === 'combobox' || el.getAttribute('aria-autocomplete') === 'list') &&
              !el.closest('button[type=submit], input[type=submit], #submit_app'));
            if (ok) el.focus();
            return ok;
          },
          args: [elementId]
        });
        if (!verified) {
          sendResponse({ ok: false, error: 'trusted text target is not a connected combobox' });
          return;
        }
        await chrome.debugger.attach(target, '1.3');
        attached = true;
        await chrome.debugger.sendCommand(target, 'Input.dispatchKeyEvent', {
          type: 'rawKeyDown', key: 'a', code: 'KeyA', modifiers: 4
        });
        await chrome.debugger.sendCommand(target, 'Input.dispatchKeyEvent', {
          type: 'keyUp', key: 'a', code: 'KeyA', modifiers: 4
        });
        await chrome.debugger.sendCommand(target, 'Input.dispatchKeyEvent', {
          type: 'rawKeyDown', key: 'Backspace', code: 'Backspace'
        });
        await chrome.debugger.sendCommand(target, 'Input.dispatchKeyEvent', {
          type: 'keyUp', key: 'Backspace', code: 'Backspace'
        });
        for (const char of text) {
          await chrome.debugger.sendCommand(target, 'Input.dispatchKeyEvent', {
            type: 'keyDown', key: char, text: char, unmodifiedText: char
          });
          await chrome.debugger.sendCommand(target, 'Input.dispatchKeyEvent', {
            type: 'keyUp', key: char
          });
        }
        sendResponse({ ok: true, method: 'trusted-cdp-text-keys' });
      } catch (error) {
        sendResponse({ ok: false, error: String(error) });
      } finally {
        if (attached) {
          try { await chrome.debugger.detach(target); } catch (error) {}
        }
      }
    })();
    return true;
  }
});
