// content.js — P1 One-Click Autofill Engine (v0.6.2)
// Deterministic, local-only. Deep DOM walk (shadow + same-origin iframe) -> classify ->
// framework-bypass inject. Typeahead picks an exact visible match first to prevent partial-match errors.
// One "Autofill" button fills the whole form in a single pass. This extension never submits:
// Phase A requires the human to review the portal and click its native Submit button.
(function () {
  if (window.__P1_AUTOFILL_LOADED__) return;
  window.__P1_AUTOFILL_LOADED__ = true;
  const IS_TOP = window.top === window.self;

  const getProfile = (pkg) => new Promise((resolve, reject) => {
    if (pkg?.profile) {
      resolve(pkg.profile);
      return;
    }
    if (!globalThis.chrome?.storage?.local) {
      reject(new Error('profile unavailable: package has no embedded profile and chrome.storage is unavailable'));
      return;
    }
    chrome.storage.local.get('user_profile', async (data) => {
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message));
        return;
      }
      if (data.user_profile) {
        resolve(data.user_profile);
        return;
      }
      try {
        const response = await fetch(chrome.runtime.getURL('profile.default.json'));
        const profile = await response.json();
        await chrome.storage.local.set({ user_profile: profile });
        resolve(profile);
      } catch (error) {
        reject(new Error(`profile recovery failed: ${error}`));
      }
    });
  });

  // ---------------------------------------------------------------- DOM walker
  function queryAllFields(root) {
    let nodes = [];
    try {
      nodes = Array.from(root.querySelectorAll(
        'input:not([type=hidden]):not([type=submit]):not([type=button]), textarea, select, [role=combobox], [contenteditable="true"]'));
    } catch (e) {}
    let all = [];
    try { all = Array.from(root.querySelectorAll('*')); } catch (e) {}
    for (const el of all) if (el.shadowRoot) nodes = nodes.concat(queryAllFields(el.shadowRoot));
    let iframes = [];
    try { iframes = Array.from(root.querySelectorAll('iframe')); } catch (e) {}
    for (const f of iframes) { try { if (f.contentDocument) nodes = nodes.concat(queryAllFields(f.contentDocument)); } catch (e) {} }
    return nodes;
  }

  // ------------------------------------------------------ application detector
  // Cheap, deterministic trigger: no screenshots, network calls, or LLM. The
  // detector deliberately uses several independent signals so a generic form
  // or newsletter signup does not activate the application workflow.
  function detectJobApplication(root = document) {
    const path = `${location.hostname}${location.pathname}`.toLowerCase();
    const urlSignal = /(greenhouse|lever|ashby|workday|smartrecruiters|jobvite|icims|careers?|jobs?|apply)/i.test(path);
    const fields = queryAllFields(root);
    const labels = fields.map((field) => labelTextFor(field)).join(' ').toLowerCase();
    const hasIdentity = /first name|last name|full name|e-?mail/.test(labels);
    const hasResume = fields.some((field) =>
      field.matches?.('input[type="file"]') ||
      /resume|curriculum vitae|\bcv\b/.test(labelTextFor(field).toLowerCase()));
    const hasApplicationLanguage = /apply|application|work authorization|sponsorship|cover letter/.test(labels);
    const score = Number(urlSignal) + Number(hasIdentity) + Number(hasResume) + Number(hasApplicationLanguage);
    return {
      detected: score >= 2 && (hasResume || hasApplicationLanguage),
      score,
      signals: { urlSignal, hasIdentity, hasResume, hasApplicationLanguage }
    };
  }

  // ---------------------------------------------------------------- adapters
  const ADAPTERS = {
    ashby: {
      test: () => /ashbyhq\.com$/.test(location.hostname),
      selectors: {
        first_name: 'input[name="_systemfield_first_name"]',
        last_name: 'input[name="_systemfield_last_name"]',
        full_name: 'input[name="_systemfield_name"]',
        email: 'input[name="_systemfield_email"], input[type=email]',
        phone: 'input[name="_systemfield_phone"], input[type=tel]',
        location: '[data-field-path="_systemfield_location"] input[role=combobox]',
        resume: 'input#_systemfield_resume'
      },
      submit: 'button[type="submit"]'
    },
    greenhouse: {
      test: () => /greenhouse\.io$/.test(location.hostname),
      selectors: {
        first_name: '#first_name', last_name: '#last_name', email: '#email', phone: '#phone',
        phone_country: '#country', location: '#candidate-location',
        resume: '#resume', cover_letter: '#cover_letter',
        gender: '#gender', hispanic: '#hispanic_ethnicity',
        veteran: '#veteran_status', disability: '#disability_status'
      },
      submit: '#submit_app, button[type="submit"]'
    },
    lever: {
      test: () => /lever\.co$/.test(location.hostname),
      selectors: {
        full_name: 'input[name="name"]',
        email: 'input[name="email"]',
        phone: 'input[name="phone"]',
        location: 'input[name="location"]',
        current_company: 'input[name="org"]',
        linkedin: 'input[name="urls[LinkedIn]"]',
        portfolio: 'input[name="urls[Portfolio]"], input[name="urls[Website]"]'
      },
      submit: 'button[type="submit"], .postings-btn[type="submit"]'
    }
  };
  const activeAdapter = () => {
    for (const [name, a] of Object.entries(ADAPTERS)) if (a.test()) return { name, ...a };
    return { name: 'generic', selectors: {}, submit: 'button[type="submit"]' };
  };

  // ---------------------------------------------------------------- matcher
  const FIELD_PATTERNS = {
    first_name: [/first\s*name/i, /given\s*name/i, /^fname$/i],
    last_name: [/last\s*name/i, /family\s*name/i, /surname/i, /^lname$/i],
    full_name: [/^(full\s*)?name$/i, /your\s*name/i],
    email: [/e-?mail/i],
    phone: [/phone|mobile|tel(ephone)?/i],
    address: [/street|address(?!.*email)/i],
    apartment: [/\bapartment\b|\bapt\.?\b\s*(number|no\.?|#)?|\bunit\b\s*(number|no\.?|#)?|address\s*line\s*2/i],
    city: [/city|town/i],
    location: [/^\s*(current\s+|home\s+)?location\s*\*?\s*$/i],
    preferred_location: [
      /preferred\s+location/i,
      /desired\s+location/i,
      /location\s+preference/i,
      /where\s+.*(relocate|work)/i
    ],
    state: [/\bstate\b|province|region/i],
    zip: [/zip|postal/i],
    phone_country: [/phone\s*country|country\s*code|dial(ing)?\s*code/i],
    citizenship_country: [/country\s+of\s+citizenship|citizenship\s+country|nationality/i],
    residence_country: [
      /country\s+of\s+(current\s+)?residence/i,
      /current\s+country/i,
      /^country$/i
    ],
    located_us: [/located\s+in\s+the\s+u\.?s\.?/i, /currently\s+in\s+the\s+united\s+states/i],
    country: [/country/i],
    linkedin: [/linked\s*-?in/i],
    portfolio: [/portfolio|personal\s*(web)?site|website/i],
    github: [/github/i],
    current_company: [
      /current\s*(company|employer)/i,
      /current\s+or\s+(most\s+)?recent\s+(company|employer)/i,
      /(most\s+)?recent\s+(company|employer)/i,
      /present\s*employer/i
    ],
    work_auth: [/authorized\s*to\s*work|work\s*authorization|legally\s*(able|authorized)/i],
    us_citizen: [/u\.?s\.?\s+citizen|citizen\s+of\s+the\s+united\s+states/i],
    permanent_resident: [/permanent\s+resident|green\s+card/i],
    security_clearance: [/security\s+clearance|active\s+clearance|government\s+clearance/i],
    company_referral: [
      /know\s+any(one|body).*(work|employ).*(company|here|us)/i,
      /(relative|family|friend).*(work|employ).*(company|here|us)/i,
      /employee\s+referral|referred\s+by\s+(an\s+)?employee/i
    ],
    prior_company_employment: [
      /currently,?\s+or\s+have\s+you\s+previously,?\s+worked\s+for/i,
      /have\s+you\s+(ever\s+)?(previously\s+)?worked\s+for/i
    ],
    sms_updates: [/text\s+me\s+updates|sms\s+updates|application\s+updates.*text/i],
    eligible_state: [/resident\s+of\s+the\s+following\s+states|state(s)?\s+in\s+which.*employ/i],
    truth_declaration: [/declare.*(true|truth)|true\s+to\s+the\s+best\s+of\s+my\s+knowledge/i],
    employment_eligibility_ack: [
      /provide\s+documents.*(identity|employment\s+eligibility)/i,
      /documents\s+establishing.*employment\s+eligibility/i
    ],
    immediate_sponsorship: [/immediate\s+sponsor|sponsorship\s+immediately|require\s+sponsorship\s+to\s+start/i],
    authorized_without_sponsorship: [
      /authorized\s+to\s+work\s+without\s+(company\s+)?sponsorship/i,
      /work\s+without\s+(now\s+or\s+future\s+)?sponsorship/i
    ],
    sponsorship: [/sponsor|visa\s*(sponsorship|support)/i],
    visa_status: [/visa\s+status|immigration\s+status|current\s+status/i],
    onsite: [
      /in-?office|on-?site|5\s*days\s*a\s*week/i,
      /work\s+from.*office|office.*days?\s+per\s+week/i
    ],
    relocate: [/relocat/i],
    salary: [/salary|compensation|pay\s*(range|expectation)/i],
    start_date: [/start\s*date|available\s*to\s*start|earliest|when\s+can\s+you\s+start/i],
    how_heard: [/how\s*did\s*you\s*(hear|discover|find)|hear\s*about\s*us|discover\s*us|where\s*did\s*you\s*(hear|find|learn)|referral\s*source/i],
    why_company: [/why\s*(do\s*you\s*want|are\s*you\s*interested)|why\s+\w+\?/i],
    why_role: [/why\s*(this|the)\s*(role|position)|interest(ed)?\s*in\s*(this|the)\s*(role|position)/i],
    gender: [/gender/i],
    race: [/race|ethnicit/i],
    hispanic: [/hispanic|latino/i],
    sexual_orientation: [/sexual\s+orientation/i],
    lgbtq_identity: [/lgbt2?qia|lgbtq|member\s+of\s+the\s+lgbt/i],
    veteran: [/veteran/i],
    disability: [/disabilit/i],
    school: [/school|university|institution/i],
    degree: [/degree/i],
    major: [/major|discipline|field\s*of\s*study/i],
    gpa: [/gpa|grade\s*point/i]
  };
  const AUTOCOMPLETE_MAP = {
    'given-name': 'first_name', 'family-name': 'last_name', 'name': 'full_name',
    'email': 'email', 'tel': 'phone', 'street-address': 'address', 'address-line2': 'apartment',
    'address-level2': 'city', 'address-level1': 'state', 'postal-code': 'zip',
    'country-name': 'country', 'organization': 'current_company'
  };

  function labelTextFor(el) {
    const labelledBy = el.getAttribute && el.getAttribute('aria-labelledby');
    if (labelledBy) {
      const text = labelledBy.split(/\s+/).map((id) => {
        try { return el.getRootNode().getElementById(id)?.textContent?.trim() || ''; } catch (e) { return ''; }
      }).filter(Boolean).join(' ');
      if (text) return text;
    }
    if (el.id) {
      try { const lab = el.getRootNode().querySelector(`label[for="${CSS.escape(el.id)}"]`); if (lab) return lab.textContent.trim(); } catch (e) {}
    }
    const wrap = el.closest && el.closest('label');
    if (wrap) return wrap.textContent.trim();
    const c = el.closest && el.closest(
      '[data-field-path], div[class*="field" i], div[class*="question" i], fieldset, li, div'
    );
    if (c) { const lab = c.querySelector('label, legend, [class*="label" i]'); if (lab) return lab.textContent.trim(); }
    // Lever renders custom-card prompts as bare text nodes inside <li> containers, with no
    // label/for relationship. The containing card is the authoritative question text.
    if (/lever\.co$/.test(location.hostname) && el.closest) {
      const card = el.closest('li');
      if (card) {
        const text = String(card.innerText || card.textContent || '').trim();
        if (text) return text;
      }
    }
    return '';
  }

  // ---------------------------------------------------------------- eligibility intent
  // One classifier for every work-authorization / sponsorship question, used by field
  // classification, the eligibility guard, and the button fallback. Order matters: the most
  // specific meaning wins. "Now or in the future" is a FUTURE question; "without sponsorship"
  // is its own question whose honest answer differs from plain "authorized to work".
  const ELIGIBILITY_FIELDS = new Set([
    'manual_legal', 'authorized_without_sponsorship', 'sponsorship', 'immediate_sponsorship',
    'opt_cpt_status', 'employment_eligibility_ack', 'work_auth'
  ]);
  function eligibilityIntent(raw) {
    const t = String(raw || '').replace(/\s+/g, ' ').toLowerCase();
    if (!t) return null;
    // Legally ambiguous for F-1/OPT candidates: always left to the human.
    if (/without\s+(any\s+)?restriction|for\s+any\s+employer|any\s+u\.?s\.?\s+employer|stem\s+opt\s+extension|\bi-?983\b|e-?verify/.test(t)) {
      return 'manual_legal';
    }
    const mentionsSponsor = /sponsor/.test(t);
    if (/without\s+(the\s+)?(need\s+(for|of)\s+|requiring\s+|needing\s+)?(any\s+)?(current\s+or\s+future\s+)?(visa\s+|company\s+|employer\s+|employment\s+|immigration\s+)*sponsor/.test(t) ||
        /(authori[sz]ed|eligible|able)\s+to\s+work\b.{0,80}\bwithout\b.{0,40}sponsor/.test(t)) {
      return 'authorized_without_sponsorship';
    }
    if (mentionsSponsor) {
      const future = /\bfuture\b|\bever\b|\bat\s+any\s+(point|time)\b|\bnow\s+or\b|\bor\s+will\s+you\b|\bwill\s+you\s+(now\s+or\s+)?(in\s+the\s+future\s+)?(need|require)\s+(h-?1b|sponsorship\s+for\s+(an?\s+)?h-?1b)|h-?1b/.test(t);
      const immediate = /\b(now|currently|immediately|immediate|today|at\s+this\s+time)\b|to\s+(begin|start|commence)|at\s+(the\s+)?(time\s+of\s+)?(hire|start|onboarding)|upon\s+hire/.test(t);
      if (immediate && !future) return 'immediate_sponsorship';
      return 'sponsorship';
    }
    if (/\b(opt|cpt)\b|optional\s+practical\s+training|curricular\s+practical\s+training/.test(t)) {
      return 'opt_cpt_status';
    }
    if (/(proof|document(s|ation)?|evidence)\b.{0,60}\b(right|eligib\w*|authori[sz]\w*)\s+to\s+work|employment\s+eligibility/.test(t)) {
      return 'employment_eligibility_ack';
    }
    if (/authori[sz]ed\s+to\s+work|work\s+authori[sz]ation|legally\s+(able|authori[sz]ed|eligible)\s+to\s+work|eligible\s+to\s+work\s+in/.test(t)) {
      return 'work_auth';
    }
    return null;
  }

  function classify(el, adapterSelectors) {
    const cand = {};
    const add = (f, s) => { if (f && (!(f in cand) || s > cand[f])) cand[f] = s; };
    const visibleLabel = labelTextFor(el);
    // Some custom portals expose a misleading internal "last_name" selector for a single
    // combined legal-name input. The human-visible label is authoritative in this case.
    if (/(legal\s+)?first\s+(and|&)\s+last\s+name|first\s+and\s+last\s+name/i.test(visibleLabel)) {
      return { field: 'full_name', score: 120 };
    }
    const eligibility = eligibilityIntent(visibleLabel);
    if (eligibility) return { field: eligibility, score: 125 };
    const exactQuestionOverrides = [
      ['apartment', /address\s*line\s*2|\bapartment\b|\bapt\.?\b\s*(number|no\.?|#)?|\bunit\b\s*(number|no\.?|#)?/i],
      ['located_us', /(?:are\s+you\s+)?(?:currently\s+)?located\s+in\s+(?:the\s+)?(?:u\.?s\.?|united\s+states)/i],
      ['current_job_location', /confirm\s+you\s+are\s+located\s+where\s+the\s+role\s+is\s+advertised|currently\s+located.*role.*advertised/i],
      // A work-authorization question whose text contains "country" (e.g. "authorized to
      // work in country listed") must not fall to the generic country matcher (AF-013).
      ['authorized_without_sponsorship', /authorized\s+to\s+work\s+without\s+(company\s+)?sponsorship|work\s+without\s+(now\s+or\s+future\s+)?sponsorship/i],
      ['work_auth', /authorized\s+to\s+work|work\s+authorization|legally\s+(able|authorized)\s+to\s+work/i],
      ['citizenship_country', /country\s+of\s+citizenship|citizenship\s+country|nationality/i],
      ['residence_country', /country\s+of\s+(current\s+)?residence|current\s+country/i],
      // Resolve intent before the generic city matcher sees "town" in "Midtown".
      ['onsite', /commute.*office|office.*(times|days).*week|days?\s+(in|per).*office|in-?office/i],
      ['salary_ack', /budgeted\s+salary.*acknowledge|salary.*align.*expectations/i],
      ['eligible_state', /resident\s+of\s+the\s+following\s+states|states?\s+in\s+which.*employ/i],
      ['truth_declaration', /declare.*(true|truth)|true\s+to\s+the\s+best\s+of\s+my\s+knowledge/i],
      ['employment_eligibility_ack', /provide\s+documents.*(identity|employment\s+eligibility)/i],
      ['prior_company_employment', /currently,?\s+or\s+have\s+you\s+previously,?\s+worked\s+for|have\s+you\s+(ever\s+)?(previously\s+)?worked\s+for/i],
      ['lgbtq_identity', /lgbt2?qia|lgbtq|member\s+of\s+the\s+lgbt/i]
    ];
    for (const [field, pattern] of exactQuestionOverrides) {
      if (pattern.test(visibleLabel)) return { field, score: 120 };
    }
    const ac = (el.getAttribute && (el.getAttribute('autocomplete') || '')).toLowerCase();
    if (AUTOCOMPLETE_MAP[ac]) add(AUTOCOMPLETE_MAP[ac], 100);
    if (adapterSelectors) for (const [f, sel] of Object.entries(adapterSelectors)) {
      try { if (el.matches(sel)) add(f, 95); } catch (e) {}
    }
    const sources = [
      [visibleLabel, 85],
      [el.getAttribute && el.getAttribute('aria-label') || '', 80],
      [el.getAttribute && el.getAttribute('placeholder') || '', 70],
      [((el.name || '') + ' ' + (el.id || '')), 60]
    ];
    for (const [text, score] of sources) {
      if (!text) continue;
      for (const [f, pats] of Object.entries(FIELD_PATTERNS)) if (pats.some((p) => p.test(text))) add(f, score);
    }
    if (el.type === 'file') {
      if (/cover/i.test(visibleLabel)) add('cover_letter', 90);
      else if (/resume|\bcv\b/i.test(visibleLabel)) add('resume', 90);
      // Unlabeled, non-required upload controls are commonly ATS "parse my resume"
      // helpers. Uploading there can overwrite canonical fields after we fill them.
      else if (el.required || el.getAttribute('aria-required') === 'true') add('resume', 55);
    }
    let best = null, bs = -1;
    for (const [f, s] of Object.entries(cand)) if (s > bs) { best = f; bs = s; }
    return best ? { field: best, score: bs } : null;
  }

  // ---------------------------------------------------------------- injector
  const inputSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
  const taSetter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
  const fire = (el, t, extra) => el.dispatchEvent(new Event(t, Object.assign({ bubbles: true, cancelable: true }, extra || {})));
  const keyseq = (el) => {
    const o = { bubbles: true, cancelable: true, key: 'Enter', keyCode: 13 };
    el.dispatchEvent(new KeyboardEvent('keydown', o));
    el.dispatchEvent(new KeyboardEvent('keyup', o));
  };

  function setText(el, value) {
    el.focus();
    if (el.tagName === 'TEXTAREA') taSetter.call(el, value);
    else if (el.tagName === 'INPUT') inputSetter.call(el, value);
    else if (el.isContentEditable) el.textContent = value;
    fire(el, 'input'); fire(el, 'change'); el.blur();
    return String(readBack(el)).trim() === String(value).trim();
  }
  function readBack(el) { return el.isContentEditable ? el.textContent : el.value; }

  function setSelect(el, wantedArr) {
    const opts = Array.from(el.options || []);
    // exact match first, then startsWith, then includes
    for (const pass of ['exact', 'starts', 'incl']) {
      for (const w of wantedArr) {
        const lw = String(w).toLowerCase();
        const hit = opts.find((o) => {
          const t = o.textContent.trim().toLowerCase();
          return pass === 'exact' ? t === lw : pass === 'starts' ? t.startsWith(lw) : t.includes(lw);
        });
        if (hit) { el.value = hit.value; fire(el, 'change'); return { ok: true, chosen: hit.textContent.trim() }; }
      }
    }
    return { ok: false, options: opts.map((o) => o.textContent.trim()).slice(0, 25) };
  }

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  function activateControl(el) {
    // A synthetic pointer+mouse+click sequence can toggle React Select twice:
    // pointerdown opens it and the later click closes it. Native HTMLElement.click()
    // matches the successful P1/portal interaction and fires one activation only.
    if (typeof el.focus === 'function') el.focus();
    el.click();
  }
  function comboboxShell(el) {
    return el.closest(
      '.select-shell, [data-field-path], div[class*="field" i], ' +
      'div[class*="question" i], fieldset, li'
    ) || el.parentElement;
  }
  function comboboxToggle(el, shell) {
    const explicit = shell && shell.querySelector(
      'button[aria-label="Toggle flyout"], button[aria-haspopup=listbox], ' +
      'button[aria-expanded], [role=button][aria-haspopup=listbox]'
    );
    if (explicit) return explicit;
    const sibling = el.parentElement && Array.from(el.parentElement.children)
      .find((node) => node !== el && node.matches && node.matches('button,[role=button]'));
    return sibling || null;
  }
  function visibleComboboxOptions(el) {
    const controlled = el && el.getAttribute && el.getAttribute('aria-controls');
    const controlledRoot = controlled && document.getElementById(controlled);
    const roots = controlledRoot
      ? [controlledRoot]
      : Array.from(document.querySelectorAll(
          '[role=listbox], .select__menu, [id^="react-select-"][id$="-listbox"]'
        ))
          .filter((listbox) => listbox.getClientRects().length > 0);
    const scope = roots.length === 1 ? roots[0] : document;
    return Array.from(scope.querySelectorAll(
      '[role=option], [role=listbox] li, .select__option, [data-option-index], ' +
      '[id^="react-select-"][id*="-option-"], .select__menu-list > div'
    )).filter((option) => option.getClientRects().length > 0);
  }
  async function waitForComboboxOptions(el, timeoutMs) {
    const deadline = Date.now() + timeoutMs;
    let options = visibleComboboxOptions(el);
    while (!options.length && Date.now() < deadline) {
      await sleep(100);
      options = visibleComboboxOptions(el);
    }
    return options;
  }
  function comboboxCommitted(el, shell, wanted, chosen) {
    const selectedNode = shell && shell.querySelector(
      '[aria-selected=true], [aria-checked=true], .select__single-value, ' +
      '[class*="singleValue"], [class*="single-value"]'
    );
    const probes = [
      readBack(el),
      el.getAttribute && el.getAttribute('aria-valuetext'),
      selectedNode && selectedNode.textContent,
      shell && shell.innerText,
      shell && shell.querySelector('button[aria-label]')?.getAttribute('aria-label'),
      shell && shell.querySelector('input[aria-hidden=true]')?.value
    ].map((value) => String(value || '').replace(/\s+/g, ' ').trim().toLowerCase());
    const wantedText = String(wanted || '').trim().toLowerCase();
    const chosenText = String(chosen || '').trim().toLowerCase();
    const wantedCity = wantedText.split(',')[0].trim();
    if (el.id === 'country') {
      const selected = String(selectedNode?.textContent || '')
        .replace(/\s+/g, ' ').trim().toLowerCase();
      return selected === '+1' || selected === 'united states +1' ||
        selected === 'united states (+1)';
    }
    return probes.some((probe) =>
      probe &&
      (
        probe === wantedText ||
        probe === chosenText ||
        probe.startsWith(wantedText) ||
        (wantedCity.length >= 3 && probe.startsWith(wantedCity)) ||
        (chosenText.length >= 3 && probe.includes(chosenText)) ||
        (chosenText.length >= 2 && probe.endsWith(` ${chosenText}`))
      )
    );
  }
  function chooseComboboxOption(options, wanted, typed) {
    const lw = String(wanted).trim().toLowerCase();
    const city = String(typed).trim().toLowerCase().split(',')[0];
    const rows = options.map((el) => ({
      el,
      text: String(el.textContent || '').replace(/\s+/g, ' ').trim()
    })).filter((row) => row.text);
    const comparable = (value) => String(value).toLowerCase()
      .replace(/^\([^)]{1,12}\)\s*/, '').trim();
    return rows.find((row) => comparable(row.text) === lw) ||
      rows.find((row) => comparable(row.text).startsWith(lw)) ||
      rows.find((row) => lw.length >= 3 && comparable(row.text).endsWith(lw)) ||
      (city.length >= 3
        ? rows.find((row) => comparable(row.text).startsWith(city))
        : null);
  }
  function commitComboboxOption(option) {
    // React keeps the current handler closure on the DOM node. Calling that closure
    // is the deterministic fallback for portals that ignore untrusted synthetic
    // pointer events. It updates React state through the component's own code path.
    const reactPropsKey = Object.keys(option)
      .find((key) => key.startsWith('__reactProps$'));
    const reactProps = reactPropsKey && option[reactPropsKey];
    if (typeof reactProps?.onMouseDown === 'function') {
      reactProps.onMouseDown({
        type: 'mousedown',
        button: 0,
        buttons: 1,
        target: option,
        currentTarget: option,
        preventDefault() {},
        stopPropagation() {},
        nativeEvent: new MouseEvent('mousedown')
      });
      if (!option.isConnected) return;
    }
    // react-select commits an option from its onMouseDown handler. HTMLElement.click()
    // alone skips that handler; focusing the option first unmounts the menu. Dispatch
    // mousedown directly while the option is still mounted, then click only if the
    // portal kept the node connected.
    option.dispatchEvent(new MouseEvent('mousedown', {
      bubbles: true,
      cancelable: true,
      view: window,
      button: 0,
      buttons: 1
    }));
    if (option.isConnected) option.click();
  }
  function enterComboboxTextWithTrustedInput(el, text) {
    return new Promise((resolve) => {
      if (!el.id) {
        resolve({ ok: false, error: 'combobox has no id' });
        return;
      }
      chrome.runtime.sendMessage({
        action: 'TRUSTED_COMBOBOX_TEXT',
        elementId: el.id,
        text: String(text || '')
      }, (result) => resolve(result || {
        ok: false,
        error: chrome.runtime.lastError?.message || 'no response'
      }));
    });
  }
  function commitComboboxInMainWorld(el, wanted) {
    return new Promise((resolve) => {
      if (!el.id) {
        resolve({ ok: false, error: 'combobox has no id' });
        return;
      }
      chrome.runtime.sendMessage({
        action: 'SELECT_REACT_OPTION',
        elementId: el.id,
        wanted
      }, (result) => resolve(result || {
        ok: false,
        error: chrome.runtime.lastError?.message || 'no response'
      }));
    });
  }
  function commitComboboxWithTrustedClick(option) {
    return new Promise((resolve) => {
      const rect = option.getBoundingClientRect();
      if (!rect.width || !rect.height) {
        resolve({ ok: false, error: 'option is not visible' });
        return;
      }
      chrome.runtime.sendMessage({
        action: 'TRUSTED_OPTION_CLICK',
        targetKind: 'option',
        x: rect.left + rect.width / 2,
        y: rect.top + rect.height / 2,
        wanted: String(option.textContent || '').replace(/\s+/g, ' ').trim()
      }, (result) => resolve(result || {
        ok: false,
        error: chrome.runtime.lastError?.message || 'no response'
      }));
    });
  }
  function openComboboxWithTrustedClick(target, comboboxId) {
    return new Promise((resolve) => {
      const rect = target.getBoundingClientRect();
      if (!rect.width || !rect.height) {
        resolve({ ok: false, error: 'combobox control is not visible' });
        return;
      }
      chrome.runtime.sendMessage({
        action: 'TRUSTED_OPTION_CLICK',
        targetKind: 'control',
        x: rect.left + rect.width / 2,
        y: rect.top + rect.height / 2,
        wanted: comboboxId
      }, (result) => resolve(result || {
        ok: false,
        error: chrome.runtime.lastError?.message || 'no response'
      }));
    });
  }
  // Generic React/Ashby/Greenhouse typeahead. An option is successful only after
  // the committed value is read back. One bounded retry handles delayed hydration.
  async function setTypeahead(el, wantedArr) {
    const shell = comboboxShell(el);
    for (const w of wantedArr) {
      const typed = el.id === 'candidate-location'
        ? String(w).split(',')[0].trim()
        : String(w).trim();
      for (let attempt = 0; attempt < 2; attempt += 1) {
        // A failed React Select must not leave a stale menu open. Otherwise the next
        // question reads the previous control's options and every later dropdown fails.
        for (const other of document.querySelectorAll(
          'input[role=combobox][aria-expanded=true], input[aria-autocomplete=list][aria-expanded=true]'
        )) {
          if (other === el) continue;
          const otherShell = comboboxShell(other);
          const otherToggle = comboboxToggle(other, otherShell);
          const trustedClose = await openComboboxWithTrustedClick(
            otherToggle || other, other.id
          );
          if (!trustedClose.ok) activateControl(otherToggle || other);
        }
        await sleep(100);
        const toggle = comboboxToggle(el, shell);
        let trustedOpen = { ok: true, method: 'already-open' };
        if (el.getAttribute('aria-expanded') !== 'true') {
          trustedOpen = await openComboboxWithTrustedClick(toggle || el, el.id);
          if (!trustedOpen.ok) activateControl(toggle || el);
        }
        el.dataset.p1TrustedOpen = JSON.stringify(trustedOpen);
        log(`[trusted-open:${el.id || 'anonymous'}] ${JSON.stringify(trustedOpen)}`);
        let options = await waitForComboboxOptions(el, 2200);
        let hit = chooseComboboxOption(options, w, typed);

        if (!hit) {
          el.focus();
          inputSetter.call(el, typed);
          try {
            el.dispatchEvent(new InputEvent('input', {
              bubbles: true,
              cancelable: true,
              inputType: 'insertText',
              data: typed
            }));
          } catch (e) { fire(el, 'input'); }
          options = await waitForComboboxOptions(
            el, el.id === 'candidate-location' ? 3000 : 2400
          );
          hit = chooseComboboxOption(options, w, typed);
        }
        if (!hit && el.id === 'candidate-location') {
          inputSetter.call(el, '');
          fire(el, 'input');
          const trustedText = await enterComboboxTextWithTrustedInput(el, typed);
          log(`[trusted-text:${el.id}] ${JSON.stringify(trustedText)}`);
          if (trustedText.ok) {
            options = await waitForComboboxOptions(el, 3500);
            hit = chooseComboboxOption(options, w, typed);
          }
        }
        if (!hit) {
          log(
            `[trusted-options:${el.id || 'anonymous'}] ` +
            JSON.stringify(options.map((option) =>
              String(option.textContent || '').replace(/\s+/g, ' ').trim()
            ).filter(Boolean).slice(0, 25))
          );
        }

        if (hit) {
          // The trusted-input worker is allowlisted to approved ATS domains and
          // clicks only this already-matched visible option. The worker detaches
          // immediately; committed-value read-back remains mandatory.
          const trustedResult = await commitComboboxWithTrustedClick(hit.el);
          el.dataset.p1TrustedResult = JSON.stringify(trustedResult);
          log(`[trusted:${el.id || 'anonymous'}] ${JSON.stringify(trustedResult)}`);
          await sleep(300);
          if (trustedResult.ok && comboboxCommitted(el, shell, w, hit.text)) {
            return {
              ok: true,
              chosen: hit.text,
              attempts: attempt + 1,
              method: trustedResult.method
            };
          }
          commitComboboxOption(hit.el);
          await sleep(300);
          if (comboboxCommitted(el, shell, w, hit.text)) {
            return { ok: true, chosen: hit.text, attempts: attempt + 1 };
          }
          const mainWorldResult = await commitComboboxInMainWorld(el, hit.text);
          await sleep(300);
          if (mainWorldResult.ok && comboboxCommitted(el, shell, w, hit.text)) {
            return {
              ok: true,
              chosen: hit.text,
              attempts: attempt + 1,
              method: mainWorldResult.method
            };
          }
        }
        fire(el, 'change');
        await sleep(150);
      }
    }
    if (el.getAttribute('aria-expanded') === 'true') {
      const toggle = comboboxToggle(el, shell);
      activateControl(toggle || el);
    }
    return {
      ok: false,
      options: visibleComboboxOptions(el)
        .map((option) => String(option.textContent || '').trim())
        .filter(Boolean)
        .slice(0, 25)
    };
  }

  // Yes/No (and similar) rendered as buttons OR radios inside a question container.
  function choiceTargetSelected(target, wanted) {
    const input = target.matches && target.matches('input') ? target : target.querySelector && target.querySelector('input');
    if (input && (input.type === 'radio' || input.type === 'checkbox')) return input.checked;
    if (target.getAttribute && target.getAttribute('aria-checked') === 'true') return true;
    if (target.getAttribute && target.getAttribute('aria-pressed') === 'true') return true;
    if (String(target.className || '').includes('_active_')) return true;
    // Ashby Yes/No buttons store state in a hidden checkbox beside the buttons.
    const hiddenCheck = target.parentElement && target.parentElement.querySelector('input[type=checkbox]');
    if (hiddenCheck) return /^yes$/i.test(String(wanted)) ? hiddenCheck.checked : !hiddenCheck.checked;
    return false;
  }

  // AF-016: resolve an option control's HUMAN-VISIBLE text. Ashby/EEO checkboxes and radios keep
  // their label in a sibling `<label for=id>` (not a wrapping <label>), so el.textContent is empty.
  function optionText(el) {
    if (!el) return '';
    if (el.tagName === 'INPUT') {
      let t = '';
      if (el.id) { try { const l = el.getRootNode().querySelector(`label[for="${CSS.escape(el.id)}"]`); if (l) t = l.textContent; } catch (e) {} }
      if (!t) { const wrap = el.closest('label'); if (wrap) t = wrap.textContent; }
      if (!t) t = el.getAttribute('aria-label') || '';
      if (!t) { const sib = el.nextElementSibling; if (sib) t = sib.textContent || ''; }
      if (!t && el.parentElement) t = el.parentElement.textContent || '';
      if (!t) t = el.value || '';
      return String(t).replace(/\s+/g, ' ').trim();
    }
    return String((el.getAttribute && el.getAttribute('aria-label')) || el.textContent || '').replace(/\s+/g, ' ').trim();
  }
  // Handles Yes/No, EEO, and multi-option "how did you hear" groups rendered as buttons, radios,
  // role=option, checkboxes, or styled sibling-labels. Idempotent; exact -> prefix -> contains.
  function setButtonChoice(container, wantedArr) {
    if (!container || !wantedArr || !wantedArr.length) return { ok: false };
    const opts = Array.from(container.querySelectorAll(
      'button, [role=radio], [role=option], input[type=radio], input[type=checkbox], label'
    )).map((el) => ({ el, t: optionText(el).toLowerCase() })).filter((o) => o.t && o.t.length < 80);
    for (const pass of ['exact', 'starts', 'incl']) {
      for (const w of wantedArr) {
        const lw = String(w).toLowerCase();
        const hit = opts.find((o) => {
          if (pass === 'exact') return o.t === lw;
          // Never fuzzy-match short answers. "No" previously matched the final
          // letters of "Latino" and selected the opposite EEO answer.
          if (lw.length <= 3) return false;
          return pass === 'starts' ? o.t.startsWith(lw) : o.t.includes(lw);
        });
        if (hit) {
          let target = hit.el;
          if (target.tagName !== 'INPUT') {
            target = target.querySelector('input') ||
              (target.htmlFor && (target.getRootNode().getElementById ? target.getRootNode().getElementById(target.htmlFor) : null)) ||
              target;
          }
          if (!choiceTargetSelected(target, w)) target.click();
          return {
            ok: choiceTargetSelected(target, w),
            chosen: optionText(hit.el)
          };
        }
      }
    }
    return { ok: false };
  }

  // AF-018: Ashby native-radio groups must be resolved group-by-group. A broad
  // label/div search can bind an EEO or location question to a neighboring
  // question container and falsely report success without selecting anything.
  async function fillAshbyRequiredFields(p, pkg, plan) {
    if (!/ashbyhq\.com$/.test(location.hostname)) return;

    const groups = new Map();
    for (const radio of document.querySelectorAll('input[type=radio]')) {
      if (!radio.name) continue;
      if (!groups.has(radio.name)) groups.set(radio.name, []);
      groups.get(radio.name).push(radio);
    }
    const specs = [
      {
        field: 'relocate',
        question: /come in to the .*office|hybrid basis|need to relocate/i,
        wanted: ['Yes, but I will need to relocate']
      },
      { field: 'gender', question: /what gender/i, wanted: p.eeo.gender },
      { field: 'race', question: /^\s*race\b|race.*ethnicity/i, wanted: p.eeo.race },
      { field: 'hispanic', question: /hispanic|latino/i, wanted: p.eeo.hispanic },
      { field: 'veteran', question: /protected veteran/i, wanted: p.eeo.veteran },
      { field: 'disability', question: /disability status/i, wanted: p.eeo.disability },
      { field: 'work_auth', question: /legally authorized to work/i, wanted: p.choices.work_auth },
      { field: 'sponsorship', question: /require sponsorship/i, wanted: p.choices.sponsorship }
    ];
    for (const radios of groups.values()) {
      const container = radios[0].closest(
        '[data-field-path], div[class*="field" i], div[class*="question" i], fieldset'
      ) || radios[0].parentElement?.parentElement;
      const question = String(container?.innerText || '');
      const groupKey = String(radios[0].name || radios[0].id || '').toLowerCase();
      const fieldFromKey = /eeoc[_-]?race/.test(groupKey) ? 'race'
        : /eeoc[_-]?gender/.test(groupKey) ? 'gender'
        : /veteran/.test(groupKey) ? 'veteran'
        : /disabilit/.test(groupKey) ? 'disability'
        : null;
      const spec = (fieldFromKey && specs.find((candidate) => candidate.field === fieldFromKey)) ||
        specs.find((candidate) => candidate.question.test(question));
      if (!spec) continue;
      const result = setButtonChoice(container, spec.wanted);
      await sleep(80);
      const selected = radios.find((radio) => radio.checked);
      plan.push({
        f: `${spec.field}_ashby`,
        label: question.replace(/\s+/g, ' ').slice(0, 100),
        ok: Boolean(selected),
        chosen: selected ? optionText(selected) : result.chosen
      });
    }

    const smsQuestion = Array.from(document.querySelectorAll(
      '[data-field-path], div[class*="field" i], div[class*="question" i], fieldset'
    )).find((node) => /text me updates|sms updates|text.*application/i.test(
      String(node.innerText || '')
    ));
    if (smsQuestion) {
      const result = setButtonChoice(smsQuestion, p.choices.sms_updates || ['Yes']);
      plan.push({
        f: 'sms_updates_ashby',
        label: 'Application text-message updates',
        ok: result.ok,
        chosen: result.chosen
      });
    }

    const locationInput = Array.from(document.querySelectorAll(
      'input[role=combobox], input[aria-autocomplete=list]'
    )).find((el) => {
      const container = el.closest(
        '[data-field-path], div[class*="field" i], div[class*="question" i], fieldset'
      ) || el.parentElement?.parentElement;
      return /^\s*location\b/i.test(String(container?.innerText || ''));
    });
    if (locationInput && !String(readBack(locationInput) || '').trim()) {
      const wanted = [applicationLocation(p, pkg)];
      const result = await setTypeahead(locationInput, wanted);
      plan.push({
        f: 'location_ashby',
        label: 'Ashby application location',
        ok: result.ok && Boolean(String(readBack(locationInput) || '').trim()),
        chosen: result.chosen
      });
    }
  }

  function setFile(el, filename, bytes, mime) {
    const file = new File([bytes], filename, { type: mime || 'application/pdf' });
    const dt = new DataTransfer(); dt.items.add(file);
    el.files = dt.files; fire(el, 'change');
    return el.files.length === 1 && el.files[0].name === filename;
  }
  function isFileAttached(el, filename) {
    if (el.files && el.files.length) return !filename || el.files[0].name === filename;
    // React ATS widgets often consume the File object and clear input.files while
    // retaining the successful attachment in the visible field container.
    const container = el.closest('div[class*="field" i], div[class*="question" i], fieldset, li') ||
      el.parentElement?.parentElement;
    const text = String(container && container.innerText || '');
    return Boolean(filename && text.includes(filename) && /replace|remove|attached|uploaded/i.test(text));
  }

  // ---------------------------------------------------------------- value resolution
  function applicationLocation(p, pkg) {
    const home = p.address &&
      [p.address.city, p.address.state, p.address.country].filter(Boolean).join(', ');
    const job = String(pkg && pkg.job_location || '').trim();
    if (!job || /\bremote\b/i.test(job)) return home;
    return job;
  }
  function simpleValue(p, field, pkg) {
    const a = (pkg && pkg.answers) || {};
    const map = {
      first_name: p.first_name, last_name: p.last_name, full_name: p.full_name || `${p.first_name} ${p.last_name}`,
      email: p.email, phone: p.phone, address: p.address && p.address.street,
      apartment: p.address && p.address.apartment, city: p.address && p.address.city,
      location: applicationLocation(p, pkg),
      preferred_location: applicationLocation(p, pkg),
      state: p.address && p.address.state, zip: p.address && p.address.zip,
      country: p.address && p.address.country,
      phone_country: p.phone_country || (p.address && p.address.country),
      residence_country: p.address && p.address.country,
      citizenship_country: p.citizenship_country || '',
      linkedin: p.linkedin, portfolio: p.portfolio, github: p.github, current_company: p.current_company,
      start_date: p.earliest_start, salary: a.salary || '', how_heard: a.how_heard || 'Company careers page',
      why_company: a.why_company || '', why_role: a.why_role || ''
    };
    return map[field];
  }
  const normalizeQuestion = (value) => String(value || '').toLowerCase()
    .replace(/[^a-z0-9]+/g, ' ').trim();
  const QUESTION_STOPWORDS = new Set([
    'a', 'an', 'and', 'are', 'at', 'be', 'do', 'for', 'from', 'have', 'how',
    'in', 'is', 'of', 'on', 'or', 'our', 'the', 'this', 'to', 'us', 'what',
    'why', 'with', 'would', 'you', 'your'
  ]);
  function questionTokens(value) {
    return new Set(normalizeQuestion(value).split(' ')
      .filter((token) => token.length > 2 && !QUESTION_STOPWORDS.has(token)));
  }
  function questionSimilarity(a, b) {
    const left = questionTokens(a), right = questionTokens(b);
    if (!left.size || !right.size) return 0;
    const overlap = [...left].filter((token) => right.has(token)).length;
    return overlap / Math.max(left.size, right.size);
  }
  function customAnswer(el, pkg) {
    const label = normalizeQuestion(labelTextFor(el));
    if (!label || !pkg || !pkg.answers || !Array.isArray(pkg.answers.custom)) return null;
    let hit = pkg.answers.custom.find((item) => normalizeQuestion(item.question) === label);
    if (!hit) hit = pkg.answers.custom.find((item) => {
      const q = normalizeQuestion(item.question);
      return q.length >= 12 && (label.includes(q) || q.includes(label));
    });
    if (!hit) {
      const ranked = pkg.answers.custom
        .map((item) => ({ item, score: questionSimilarity(label, item.question) }))
        .sort((a, b) => b.score - a.score);
      if (ranked[0] && ranked[0].score >= 0.72) hit = ranked[0].item;
    }
    return hit && hit.answer ? hit.answer : null;
  }
  // US state dropdowns vary: "MD", "Maryland", "(US) Maryland". Derive every variant from the
  // profile's own state instead of hard-coding one candidate's state.
  const US_STATES = {AL:'Alabama',AK:'Alaska',AZ:'Arizona',AR:'Arkansas',CA:'California',CO:'Colorado',
    CT:'Connecticut',DE:'Delaware',DC:'District of Columbia',FL:'Florida',GA:'Georgia',HI:'Hawaii',ID:'Idaho',
    IL:'Illinois',IN:'Indiana',IA:'Iowa',KS:'Kansas',KY:'Kentucky',LA:'Louisiana',ME:'Maine',MD:'Maryland',
    MA:'Massachusetts',MI:'Michigan',MN:'Minnesota',MS:'Mississippi',MO:'Missouri',MT:'Montana',NE:'Nebraska',
    NV:'Nevada',NH:'New Hampshire',NJ:'New Jersey',NM:'New Mexico',NY:'New York',NC:'North Carolina',
    ND:'North Dakota',OH:'Ohio',OK:'Oklahoma',OR:'Oregon',PA:'Pennsylvania',RI:'Rhode Island',SC:'South Carolina',
    SD:'South Dakota',TN:'Tennessee',TX:'Texas',UT:'Utah',VT:'Vermont',VA:'Virginia',WA:'Washington',
    WV:'West Virginia',WI:'Wisconsin',WY:'Wyoming'};
  function stateVariants(raw) {
    const value = String(raw || '').trim();
    if (!value) return [];
    let code = value.toUpperCase();
    let name = US_STATES[code];
    if (!name) {
      const hit = Object.entries(US_STATES).find(([, n]) => n.toLowerCase() === value.toLowerCase());
      if (!hit) return [value];
      [code, name] = hit;
    }
    return [value, code, name, `(US) ${name}`].filter((v, i, all) => all.indexOf(v) === i);
  }
  function choiceValue(p, field) {
    const map = {
      phone_country: [p.phone_country_code, `${p.phone_country} (${p.phone_country_code})`, p.phone_country].filter(Boolean),
      state: stateVariants(p.address && p.address.state),
      work_auth: p.choices.work_auth,
      located_us: p.choices.located_us || ['Yes'],
      authorized_without_sponsorship: p.choices.authorized_without_sponsorship,
      sponsorship: p.choices.sponsorship, relocate: p.choices.relocate,
      onsite: ['Yes'], salary_ack: ['Yes'],
      immediate_sponsorship: p.choices.immediate_sponsorship, visa_status: p.choices.visa_status,
      opt_cpt_status: (p.choices.opt_cpt_status && p.choices.opt_cpt_status.length) ? p.choices.opt_cpt_status : null,
      manual_legal: null,
      us_citizen: p.choices.us_citizen, permanent_resident: p.choices.permanent_resident,
      security_clearance: p.choices.security_clearance, company_referral: p.choices.company_referral,
      prior_company_employment: ['No'],
      sms_updates: p.choices.sms_updates,
      eligible_state: ['Yes'], truth_declaration: ['Yes'], employment_eligibility_ack: ['Yes'],
      gender: p.eeo.gender, race: p.eeo.race, hispanic: p.eeo.hispanic, veteran: p.eeo.veteran, disability: p.eeo.disability,
      sexual_orientation: p.eeo && p.eeo.sexual_orientation,
      lgbtq_identity: p.eeo && p.eeo.lgbtq_identity,
      current_job_location: null,
      how_heard: (p.choices && p.choices.how_heard) || ['Company careers page', 'Company website', 'Website', 'Other']
    };
    return map[field] || null;
  }

  function fillLeverHowHeard(pkg, plan) {
    if (!/lever\.co$/.test(location.hostname)) return;
    const source = String(pkg?.answers?.how_heard || 'Company careers page');
    const wanted = /linked\s*in/i.test(source) ? ['LinkedIn']
      : /referr/i.test(source) ? ['Employee Referral']
      : ['Other'];
    const prompt = Array.from(document.querySelectorAll('li, div'))
      .find((node) => node.childElementCount <= 20 &&
        /how\s*did\s*you\s*hear\s*about\s*us/i.test(String(node.innerText || '')));
    if (!prompt) {
      plan.push({ f: 'how_heard', label: 'How did you hear about us?', ok: false });
      return;
    }
    const container = prompt.closest('li') || prompt;
    const result = setButtonChoice(container, wanted);
    plan.push({ f: 'how_heard', label: 'How did you hear about us?', ok: result.ok, chosen: result.chosen });
  }

  function leverQuestionContainer(pattern) {
    if (!/lever\.co$/.test(location.hostname)) return null;
    return Array.from(document.querySelectorAll('li')).find((node) =>
      pattern.test(String(node.innerText || node.textContent || ''))) || null;
  }

  function fillLeverRequiredFields(p, pkg, plan) {
    if (!/lever\.co$/.test(location.hostname)) return;

    const locationInput = document.querySelector('input[name="location"]') ||
      leverQuestionContainer(/current\s+location/i)?.querySelector('input');
    if (locationInput) {
      const value = applicationLocation(p, pkg);
      const ok = setText(locationInput, value);
      plan.push({ f: 'location_guard', label: 'Current location', ok, el: locationInput, value, type: 'text' });
    } else {
      plan.push({ f: 'location_guard', label: 'Current location', ok: false });
    }

    const locatedUsCard = leverQuestionContainer(
      /(?:are\s+you\s+)?(?:currently\s+)?located\s+in\s+(?:the\s+)?(?:u\.?s\.?|united\s+states)/i
    );
    if (locatedUsCard) {
      const result = setButtonChoice(locatedUsCard, p.choices.located_us || ['Yes']);
      plan.push({
        f: 'located_us_guard',
        label: 'Currently located in the United States',
        ok: result.ok,
        chosen: result.chosen
      });
    } else {
      plan.push({ f: 'located_us_guard', label: 'Currently located in the United States', ok: false });
    }

    const sponsorshipCard = leverQuestionContainer(
      /(?:require|need).*(?:work\s+visa|sponsor)|(?:work\s+visa|sponsor).*(?:require|need)/i
    );
    const sponsorshipSelect = sponsorshipCard && sponsorshipCard.querySelector('select');
    if (sponsorshipSelect) {
      const result = setSelect(sponsorshipSelect, p.choices.sponsorship);
      plan.push({
        f: 'sponsorship_guard',
        label: 'Future visa sponsorship',
        ok: result.ok,
        chosen: result.chosen,
        el: sponsorshipSelect,
        value: sponsorshipSelect.value
      });
    } else if (sponsorshipCard) {
      const result = setButtonChoice(sponsorshipCard, p.choices.sponsorship);
      plan.push({
        f: 'sponsorship_guard',
        label: 'Future visa sponsorship',
        ok: result.ok,
        chosen: result.chosen
      });
    } else {
      plan.push({ f: 'sponsorship_guard', label: 'Future visa sponsorship', ok: false });
    }
  }

  function fillLocationCommitment(p, pkg, plan) {
    const radioGroups = Array.from(document.querySelectorAll('input[type=radio]'))
      .reduce((groups, radio) => {
        const name = radio.name || radio.id;
        if (!groups.has(name)) groups.set(name, []);
        groups.get(name).push(radio);
        return groups;
      }, new Map());
    const handledNames = new Set();
    for (const [name, radios] of radioGroups.entries()) {
      const container = radios[0].closest(
        '[data-field-path], div[class*="field" i], div[class*="question" i], fieldset, li'
      ) || radios[0].parentElement?.parentElement;
      const question = String(container && container.innerText || '');
      if (!/tied to the office location|based in this location.*relocat/i.test(question)) continue;
      const homeCity = String(p.address && p.address.city || '').toLowerCase();
      const jobLocation = String(pkg && pkg.job_location || '').toLowerCase();
      const alreadyLocal = homeCity && jobLocation.includes(homeCity);
      const desired = alreadyLocal
        ? /yes.*based in this location/i
        : /no.*not based in this location.*willing to relocate/i;
      const target = radios.find((radio) => {
        const label = radio.id && document.querySelector(`label[for="${CSS.escape(radio.id)}"]`);
        return desired.test(String(label && label.textContent || ''));
      });
      if (target) {
        if (!target.checked) target.click();
        handledNames.add(name);
        plan.push({
          f: 'location_commitment',
          label: 'Office-location commitment',
          ok: target.checked,
          chosen: String(document.querySelector(`label[for="${CSS.escape(target.id)}"]`)?.textContent || '').trim()
        });
      }
    }
    return handledNames;
  }

  function fillOfficeLocationCheckboxes(pkg, plan) {
    const jobCity = String(pkg?.job_location || '').split(',')[0].trim();
    if (!jobCity) return;
    const choices = Array.from(document.querySelectorAll('input[type=checkbox]'))
      .filter((input) => {
        const container = input.closest(
          '[data-field-path], div[class*="field" i], div[class*="question" i], fieldset'
        ) || input.parentElement?.parentElement;
        const pageQuestion = String(container?.parentElement?.innerText || container?.innerText || '');
        return /which .*office|workplace could you work from|office\/workplace/i.test(pageQuestion);
      });
    const target = choices.find((input) =>
      String(input.name || input.getAttribute('aria-label') || '')
        .trim().toLowerCase() === jobCity.toLowerCase()
    );
    if (!target) return;
    if (!target.checked) target.click();
    plan.push({
      f: 'office_location',
      label: 'Office/workplace',
      ok: target.checked,
      chosen: jobCity
    });
  }

  // ---------------------------------------------------------------- education (best-effort, per-block)
  async function fillEducation(p, log, step) {
    if (!p.education || !p.education.length) return;
    step('education', 'running', 'Finding education fields');
    const fields = queryAllFields(document).map((el) => ({ el, c: classify(el, {}) }));
    const schools = fields.filter((f) => f.c && f.c.field === 'school').map((f) => f.el);
    if (!schools.length) {
      log('education: no school field found (add an Education block, then Autofill again)');
      step('education', 'manual', 'No education block detected');
      return;
    }
    for (let i = 0; i < schools.length && i < p.education.length; i++) {
      const ed = p.education[i];
      const block = schools[i].closest('div[class*="education" i]') ||
        schools[i].closest('fieldset, section, li') || schools[i].parentElement.parentElement;
      // school typeahead
      const r = await setTypeahead(schools[i], ed.school);
      log(`education[${i}] school: ${r.ok ? '✔ ' + r.chosen : 'NEEDS-MANUAL (' + ed.school[0] + ')'}`);
      const inBlock = queryAllFields(block).map((el) => ({ el, c: classify(el, {}) }));
      const degree = inBlock.find((f) => f.c && f.c.field === 'degree');
      const major = inBlock.find((f) => f.c && f.c.field === 'major');
      if (degree) setText(degree.el, ed.degree[0]);
      if (major) setText(major.el, ed.major[0]);
      const selects = inBlock.filter((f) => f.el.tagName === 'SELECT').map((f) => f.el);
      const isMonth = (s) => Array.from(s.options).some((o) => /january/i.test(o.textContent));
      const isYear = (s) => Array.from(s.options).some((o) => /^(19|20)\d\d$/.test(o.textContent.trim()));
      const months = selects.filter(isMonth), years = selects.filter(isYear);
      if (months[0]) setSelect(months[0], [ed.start_month]);
      if (years[0]) setSelect(years[0], [ed.start_year]);
      if (months[1]) setSelect(months[1], [ed.end_month]);
      if (years[1]) setSelect(years[1], [ed.end_year]);
    }
    step('education', 'done', `${Math.min(schools.length, p.education.length)} education block(s) processed`);
  }

  async function enforceCanonicalName(p, adapter, plan, log, step) {
    const exactFullName = String(p.full_name || `${p.first_name} ${p.last_name}`).trim();
    step('name_guard', 'running', 'Checking exact legal name after ATS processing');
    // ATS resume parsers can update fields asynchronously. Wait until those updates settle,
    // then restore the PDS-authoritative value and verify it survives.
    await sleep(1800);
    const nameField = queryAllFields(document).find((el) => {
      if (el.closest && el.closest('#p1f-sidebar')) return false;
      const c = classify(el, adapter.selectors);
      return c && c.field === 'full_name';
    });
    if (!nameField) {
      step('name_guard', 'manual', 'Combined legal-name field not detected');
      return;
    }
    if (String(readBack(nameField) || '').trim() !== exactFullName) {
      setText(nameField, exactFullName);
      await sleep(350);
    }
    const ok = String(readBack(nameField) || '').trim() === exactFullName;
    plan.push({
      f: 'full_name_guard',
      label: 'Exact legal full name',
      ok,
      el: nameField,
      value: exactFullName,
      type: 'text'
    });
    log(`${ok ? 'canonical name verified' : 'canonical name mismatch'}: ${readBack(nameField) || '(empty)'}`);
    step(
      'name_guard',
      ok ? 'done' : 'failed',
      ok ? exactFullName : `Expected: ${exactFullName}`
    );
  }

  async function enforceEligibilityChoices(p, pkg, plan, step) {
    step('eligibility_guard', 'running', 'Verifying work authorization, sponsorship, and relocation');
    const questions = Array.from(document.querySelectorAll(
      '[data-field-path], div[class*="field" i], div[class*="question" i], fieldset'
    ));
    // AF-015: broadened so Ashby (and other) Yes/No button-pairs for sponsorship, relocation,
    // and on-site all fill. Old sponsorship regex required a specific "now or future require"
    // ordering and missed Mercor's "require work sponsorship now and/or in the future".
    const specs = [
      { field: 'authorized_without_sponsorship', intent: true, wanted: p.choices.authorized_without_sponsorship },
      { field: 'work_auth', intent: true, wanted: p.choices.work_auth },
      { field: 'sponsorship', intent: true, wanted: p.choices.sponsorship },
      { field: 'immediate_sponsorship', intent: true, wanted: p.choices.immediate_sponsorship },
      { field: 'relocate', question: /willing to relocate|open to relocat|located in .*(relocat|or nyc)/i, wanted: p.choices.relocate },
      { field: 'onsite', question: /work on-?site|on-?site in our|in-?office|in person|days a week|work from.*office/i, wanted: (p.choices.onsite || ['Yes']) }
    ];
    let verified = 0;
    for (const spec of specs) {
      const alreadyVerified = plan.some((item) =>
        item.ok && String(item.f || '').replace(/_(guard|ashby)$/, '') === spec.field
      );
      if (alreadyVerified) continue;
      if (!spec.wanted || !spec.wanted.length) continue;
      const container = questions.find((node) => {
        const text = String(node.innerText || '');
        if (spec.intent) {
          // Judge the question by its own prompt, not a wrapper that holds many questions.
          const prompt = node.querySelector && node.querySelector('label, legend, [class*="label" i]');
          const promptText = String((prompt && prompt.textContent) || text).slice(0, 400);
          return eligibilityIntent(promptText) === spec.field;
        }
        return spec.question.test(text) && !(spec.exclude && spec.exclude.test(text));
      });
      if (!container) continue;
      const result = setButtonChoice(container, spec.wanted);
      await sleep(100);
      plan.push({
        f: `${spec.field}_guard`,
        label: `${spec.field} exact answer`,
        ok: result.ok,
        chosen: result.chosen
      });
      if (result.ok) verified += 1;
    }
    const verifiedFields = new Set(
      plan.filter((item) => item.ok).map((item) => String(item.f).replace(/_guard$/, ''))
    );
    verified = Number(verifiedFields.has('work_auth')) +
      Number(verifiedFields.has('sponsorship')) +
      Number(
        verifiedFields.has('eligible_state') ||
        verifiedFields.has('location_commitment') ||
        verifiedFields.has('onsite') ||
        verifiedFields.has('relocate')
      );
    step(
      'eligibility_guard',
      verified >= 3 ? 'done' : 'manual',
      `${verified}/3 eligibility choices verified`
    );
  }

  // ---------------------------------------------------------------- orchestrator
  async function autofill(pkg, log, step) {
    const p = await getProfile(pkg);
    if (!p) {
      log('no profile in storage — reload the extension');
      step('profile', 'failed', 'Profile unavailable');
      return [];
    }
    step('profile', 'done', `Loaded ${p.full_name}`);
    const adapter = activeAdapter();
    const fields = queryAllFields(document);
    step('scan', 'done', `${fields.length} form controls detected`);
    const plan = [];
    const done = new Set();
    const handledRadioNames = fillLocationCommitment(p, pkg, plan);
    fillOfficeLocationCheckboxes(pkg, plan);
    step('identity', 'running', 'Filling identity, contact, employer, and location');
    for (const el of fields) {
      if (el.closest && el.closest('#p1f-sidebar')) continue;
      if (el.type === 'radio' && handledRadioNames.has(el.name || el.id)) continue;
      const c = classify(el, adapter.selectors);
      if (!c) {
        const answer = customAnswer(el, pkg);
        if (answer && ['INPUT', 'TEXTAREA'].includes(el.tagName)) {
          const ok = setText(el, answer);
          plan.push({ f: 'custom_answer', label: labelTextFor(el), ok, el,
                      value: answer, type: 'text' });
        }
        continue;
      }
      const f = c.field;
      if (['school', 'degree', 'major'].includes(f)) continue; // handled by fillEducation
      const tag = el.tagName;
      try {
        if (f === 'resume' || f === 'cover_letter') {
          const bytesKey = f === 'resume' ? 'resumeBytes' : 'clBytes';
          const fname = f === 'resume' ? (pkg && pkg.resume_filename) : (pkg && pkg.cover_letter_filename);
          if (pkg && pkg[bytesKey] && fname) {
            step(f, 'running', `Uploading ${fname}`);
            const ok = setFile(el, fname, pkg[bytesKey]);
            plan.push({ f, label: fname, ok, type: 'file', el, filename: fname });
            await sleep(1200);
            step(f, ok ? 'done' : 'failed', ok ? `${fname} attached` : `${fname} upload failed`);
          }
          else plan.push({ f, label: f, ok: false, type: 'file', skip: true });
        } else if (f === 'manual_legal' || (f === 'opt_cpt_status' && !choiceValue(p, f))) {
          plan.push({ f, label: labelTextFor(el) || f, ok: false, manual: true,
                      note: 'Work-authorization wording left for human review' });
          continue;
        } else if (tag === 'SELECT') {
          const w = choiceValue(p, f) || [simpleValue(p, f, pkg)].filter(Boolean);
          if (!w || !w.length) continue;
          const r = setSelect(el, w); plan.push({ f, label: f, ok: r.ok, chosen: r.chosen, el, value: w[0] });
        } else if (el.getAttribute && (
          el.getAttribute('role') === 'combobox' ||
          el.getAttribute('aria-autocomplete') === 'list'
        )) {
          const w = choiceValue(p, f) || [simpleValue(p, f, pkg)].filter(Boolean);
          if (!w || !w.length) continue;
          const r = await setTypeahead(el, w);
          plan.push({ f, label: f, ok: r.ok, chosen: r.chosen, el, wanted: w, type: 'combobox' });
        } else {
          const tailored = customAnswer(el, pkg);
          if (tailored && ['INPUT', 'TEXTAREA'].includes(tag)) {
            const ok = setText(el, tailored);
            plan.push({ f: 'custom_answer', label: labelTextFor(el), ok, el,
                        value: tailored, type: 'text' });
            continue;
          }
          const cv = choiceValue(p, f);
          if (cv) { // Yes/No or EEO rendered as buttons/radios
            const container = el.closest('div[class*="field" i], div[class*="question" i], fieldset, li') || el.parentElement;
            const r = setButtonChoice(container, cv);
            if (r.ok) { plan.push({ f, label: f, ok: true, chosen: r.chosen }); continue; }
          }
          const v = simpleValue(p, f, pkg);
          if (v == null || v === '') { plan.push({ f, label: f, ok: false, skip: true }); continue; }
          if (done.has(f)) continue; done.add(f);
          const ok = setText(el, v); plan.push({ f, label: f, ok, el, value: v, type: 'text' });
        }
      } catch (err) { plan.push({ f, label: f, ok: false, err: err.message }); }
    }
    const coreFields = ['full_name', 'first_name', 'last_name', 'email', 'phone', 'current_company', 'location'];
    const coreOk = plan.filter((s) => coreFields.includes(s.f) && s.ok).length;
    step('identity', coreOk ? 'done' : 'manual', `${coreOk} core field mapping(s) verified`);
    // Yes/No button questions not caught above (onsite, sponsorship rendered as standalone buttons w/ label text)
    for (const f of [
      'sponsorship', 'immediate_sponsorship', 'authorized_without_sponsorship', 'opt_cpt_status',
      'onsite', 'work_auth', 'relocate',
      'located_us',
      'eligible_state', 'truth_declaration', 'employment_eligibility_ack',
      'us_citizen', 'permanent_resident', 'security_clearance', 'company_referral', 'prior_company_employment',
      'sms_updates',
      'how_heard', 'gender', 'race', 'hispanic', 'sexual_orientation', 'lgbtq_identity', 'veteran', 'disability'
    ]) {
      if (plan.some((s) => s.f === f && s.ok)) continue;
      const cvFallback = choiceValue(p, f);
      if (!cvFallback || !cvFallback.length) continue;
      const q = Array.from(document.querySelectorAll('label, legend, p, div'))
        .find((n) => {
          if (n.childElementCount > 3) return false;
          const text = n.textContent || '';
          if (ELIGIBILITY_FIELDS.has(f)) return eligibilityIntent(text) === f;
          if (eligibilityIntent(text) === 'manual_legal') return false;
          return FIELD_PATTERNS[f].some((re) => re.test(text));
        });
      if (q) {
        const container = q.closest('div[class*="field" i], div[class*="question" i], fieldset, li') || q.parentElement;
        const r = setButtonChoice(container, choiceValue(p, f));
        if (r.ok) plan.push({ f, label: f, ok: true, chosen: r.chosen });
      }
    }
    await fillAshbyRequiredFields(p, pkg, plan);
    fillLeverRequiredFields(p, pkg, plan);
    fillLeverHowHeard(pkg, plan);
    await fillEducation(p, log, step);
    await enforceCanonicalName(p, adapter, plan, log, step);
    await enforceEligibilityChoices(p, pkg, plan, step);
    // React Select can render its committed chip/single-value after the click
    // promise resolves. Validate the settled DOM, not the transient menu state.
    await sleep(750);
    const unresolvedRequired = queryAllFields(document).filter((el) => {
      if (el.closest && el.closest('#p1f-sidebar')) return false;
      if (el.getAttribute('aria-hidden') === 'true' || el.tabIndex === -1) return false;
      if (!el.required && el.getAttribute('aria-required') !== 'true') return false;
      if (el.type === 'file') return !isFileAttached(el, pkg && pkg.resume_filename);
      if (
        el.getAttribute('role') === 'combobox' ||
        el.getAttribute('aria-autocomplete') === 'list'
      ) {
        const shell = comboboxShell(el);
        const selectedText = String(shell?.innerText || '').trim();
        const hiddenValue = String(
          shell?.querySelector('input[aria-hidden=true]')?.value || ''
        ).trim();
        const directValue = String(readBack(el) || '').trim();
        return !directValue &&
          (!selectedText || /^select\.\.\.$/i.test(selectedText)) &&
          !hiddenValue;
      }
      return !String(readBack(el) || '').trim();
    });
    for (const el of unresolvedRequired) {
      plan.push({
        f: 'required_unmapped',
        label: labelTextFor(el) || el.name || el.id || 'required field',
        ok: false
      });
    }
    const failedAshbyRequired = plan.filter(
      (item) => /_ashby$/.test(String(item.f || '')) && !item.ok
    );
    const unresolvedCount = unresolvedRequired.length + failedAshbyRequired.length;
    step(
      'validation',
      unresolvedCount ? 'manual' : 'done',
      unresolvedCount
        ? `${unresolvedCount} required field(s) remain empty or unverified`
        : 'No empty required fields detected'
    );
    return plan;
  }

  function validate(plan) {
    const canonicalField = (field) => String(field || '').replace(/_(guard|ashby)$/, '');
    const successful = new Set(plan.filter((s) => s.ok).map((s) => canonicalField(s.f)));
    const seen = new Set();
    return plan.filter((s) => {
      const field = canonicalField(s.f);
      if (!s.ok && successful.has(field)) return false;
      const key = `${field}:${s.label}:${s.ok ? 'ok' : 'bad'}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    }).map((s) => {
      if (s.skip) return { label: s.label, status: 'skip' };
      if (s.el && s.type === 'file') return {
        label: s.label,
        status: isFileAttached(s.el, s.filename) ? 'ok' : 'MISMATCH'
      };
      if (s.el && s.type === 'text') {
        const actual = String(readBack(s.el)).trim();
        const expected = String(s.value).trim();
        const phoneLike = s.f === 'phone';
        const matches = phoneLike
          ? actual.replace(/\D/g, '').slice(-10) === expected.replace(/\D/g, '').slice(-10)
          : actual === expected;
        return { label: s.label, status: matches ? 'ok' : 'MISMATCH' };
      }
      if (s.el && s.type === 'combobox') {
        const shell = comboboxShell(s.el);
        const selected = shell && shell.querySelector(
          '.select__single-value, [class*="singleValue"], [class*="single-value"], ' +
          '.select__multi-value, [class*="multiValue"], [class*="multi-value"]'
        );
        const selectedText = String(selected?.textContent || '')
          .replace(/\s+/g, ' ').trim().toLowerCase();
        const wanted = (s.wanted || []).map((value) => String(value).trim().toLowerCase());
        const matches = wanted.some((value) =>
          selectedText === value || selectedText.startsWith(value) ||
          selectedText.endsWith(value) || value === '+1' && selectedText === '+1'
        );
        return { label: s.label, status: matches ? 'ok' : 'MISMATCH' };
      }
      if (s.el && (s.f === 'country' || s.f === 'phone_country')) {
        const shellText = String(s.el.closest('.select-shell')?.innerText || '').trim();
        if (shellText === '+1') return { label: s.label, status: 'ok' };
      }
      return { label: s.label, status: s.ok ? 'ok' : 'MISMATCH' };
    });
  }

  // ---------------------------------------------------------------- sidebar UI (top frame only)
  if (!IS_TOP) return;
  let pkg = null;

  const box = document.createElement('div');
  box.id = 'p1f-sidebar';
  box.dataset.p1Version = '0.6.13';
  box.classList.add('p1f-collapsed');
  box.innerHTML = `
    <div class="p1f-head">
      <span class="p1f-title">P1 Autofill v0.6.13</span>
      <span id="p1f-ats"></span>
      <span class="p1f-head-actions">
        <button id="p1f-min" type="button" title="Open P1 Autofill" aria-label="Open P1 Autofill">⚡</button>
      </span>
    </div>
    <div class="p1f-body">
      <div class="p1f-hint">Paste the application-package JSON (from the pipeline), then Autofill.</div>
      <textarea id="p1f-pkg" placeholder="Paste package JSON here (optional — identity/education fill without it)"></textarea>
      <button id="p1f-load">Load package</button>
      <div id="p1f-info">No package loaded — identity + education will still fill from profile.</div>
      <button id="p1f-run" class="p1f-primary">⚡ Autofill now</button>
      <div class="p1f-progress-title">Run progress</div>
      <div id="p1f-progress" aria-live="polite"></div>
      <div class="p1f-hint">Review every field, then use the portal's native Submit button yourself.</div>
      <pre id="p1f-log"></pre>
    </div>`;
  // Do not mutate the document during React/Remix hydration. Greenhouse hydrates
  // the page after document_idle; mounting against <html> can trigger React 418
  // and cause the framework to discard the injected panel. Prepare the detached
  // UI immediately, then mount it as a body sibling once hydration has settled.
  const mountSidebar = () => {
    if (!box.isConnected) (document.body || document.documentElement).appendChild(box);
  };
  if (document.readyState === 'complete') setTimeout(mountSidebar, 1200);
  else window.addEventListener('load', () => setTimeout(mountSidebar, 1200), { once: true });
  const log = (m) => { const el = box.querySelector('#p1f-log'); el.textContent += m + '\n'; el.scrollTop = 1e9; };
  const STEP_LABELS = {
    package: 'Application package',
    profile: 'Personal profile',
    scan: 'Portal scan',
    identity: 'Identity, employer & location',
    name_guard: 'Exact legal-name guard',
    eligibility_guard: 'Eligibility-answer guard',
    resume: 'Resume upload',
    cover_letter: 'Cover letter upload',
    education: 'Education',
    validation: 'Final validation'
  };
  const step = (id, status, detail) => {
    const host = box.querySelector('#p1f-progress');
    let row = host.querySelector(`[data-step="${id}"]`);
    if (!row) {
      row = document.createElement('div');
      row.className = 'p1f-step';
      row.dataset.step = id;
      row.innerHTML = '<span class="p1f-step-icon"></span><span class="p1f-step-copy"><strong></strong><small></small></span>';
      host.appendChild(row);
    }
    row.className = `p1f-step p1f-${status}`;
    row.querySelector('strong').textContent = STEP_LABELS[id] || id;
    row.querySelector('small').textContent = detail || '';
    row.querySelector('.p1f-step-icon').textContent =
      status === 'done' ? '✓' : status === 'running' ? '…' : status === 'manual' ? '!' : '×';
  };
  box.querySelector('#p1f-ats').textContent = `[${activeAdapter().name}]`;
  box.querySelector('#p1f-min').onclick = () => {
    box.classList.toggle('p1f-collapsed');
    const collapsed = box.classList.contains('p1f-collapsed');
    box.querySelector('#p1f-min').textContent = collapsed ? '⚡' : '–';
    box.querySelector('#p1f-min').title = collapsed ? 'Open P1 Autofill' : 'Minimize P1 Autofill';
    box.querySelector('#p1f-min').setAttribute(
      'aria-label', collapsed ? 'Open P1 Autofill' : 'Minimize P1 Autofill'
    );
  };

  const applyDetectionState = () => {
    const result = detectJobApplication();
    box.dataset.applicationDetected = result.detected ? 'true' : 'false';
    box.querySelector('#p1f-ats').textContent =
      `[${activeAdapter().name}] ${result.detected ? 'application detected' : 'waiting for application form'}`;
    return result;
  };
  applyDetectionState();
  let detectionTimer = null;
  const detectionObserver = new MutationObserver(() => {
    clearTimeout(detectionTimer);
    detectionTimer = setTimeout(() => {
      if (applyDetectionState().detected) detectionObserver.disconnect();
    }, 250);
  });
  if (box.dataset.applicationDetected !== 'true') {
    detectionObserver.observe(document.documentElement, { childList: true, subtree: true });
  }

  box.querySelector('#p1f-load').onclick = () => {
    try {
      pkg = JSON.parse(box.querySelector('#p1f-pkg').value);
      if (pkg.resume_data_base64) {
        const bin = atob(pkg.resume_data_base64);
        pkg.resumeBytes = Uint8Array.from(bin, (c) => c.charCodeAt(0)).buffer;
      }
      if (pkg.cover_letter_data_base64) {
        const bin = atob(pkg.cover_letter_data_base64);
        pkg.clBytes = Uint8Array.from(bin, (c) => c.charCodeAt(0)).buffer;
      }
      box.querySelector('#p1f-info').textContent =
        `${pkg.company} — ${pkg.role} | approved=${pkg.approved === true} | ` +
        `resume=${pkg.resume_filename || 'none'} | ` +
        `AJOS=${pkg.resume_qa?.ats_alignment_score ?? 'legacy package'}`;
      log(`package loaded; approved=${pkg.approved === true}`);
      if (pkg.resume_qa) {
        log(
          `resume QA: passed=${pkg.resume_qa.passed === true}; ` +
          `AJOS=${pkg.resume_qa.ats_alignment_score}; ` +
          `keywords=${pkg.resume_qa.keyword_coverage}; pages=${pkg.resume_qa.pages}`
        );
      }
      step(
        'package',
        pkg.resumeBytes ? 'done' : 'manual',
        pkg.resumeBytes
          ? `Tailored resume ready: ${pkg.resume_filename}`
          : 'Package loaded, but no embedded resume was found'
      );
    } catch (e) {
      log('package JSON parse error: ' + e.message);
      step('package', 'failed', e.message);
    }
  };

  box.querySelector('#p1f-run').onclick = async () => {
    const runButton = box.querySelector('#p1f-run');
    const qaScore = Number(pkg?.resume_qa?.ats_alignment_score);
    if (pkg?.resume_qa && (
      pkg.resume_qa.passed !== true ||
      !Number.isFinite(qaScore) ||
      qaScore < 90
    )) {
      step(
        'package',
        'failed',
        `Resume blocked: AJOS alignment ${Number.isFinite(qaScore) ? qaScore : 'missing'}; 90 required`
      );
      log('autofill blocked: staged resume did not pass the locked AJOS >=90 guardrail');
      return;
    }
    runButton.disabled = true;
    runButton.textContent = 'Autofilling…';
    // Greenhouse places form controls beneath the fixed sidebar. Trusted CDP
    // clicks must reach the portal control, not the transparent sidebar layer.
    // Keep progress visible while making the sidebar click-through for the run.
    box.style.pointerEvents = 'none';
    box.querySelector('#p1f-progress').innerHTML = '';
    step(
      'package',
      pkg ? (pkg.resumeBytes ? 'done' : 'manual') : 'manual',
      pkg
        ? (pkg.resumeBytes ? `Tailored resume ready: ${pkg.resume_filename}` : 'No embedded resume')
        : 'No package loaded; profile fields only'
    );
    log('--- autofill start ---');
    try {
      const plan = await autofill(pkg, log, step);
      const rep = validate(plan);
      rep.forEach((r) => log(`${r.status === 'ok' ? '✔' : r.status === 'skip' ? '·' : '✘'} ${r.label}`));
      const bad = rep.filter((r) => r.status === 'MISMATCH').length;
      log(bad ? `${bad} field(s) need manual attention` : 'all mapped fields verified ✔');
      log('--- autofill done --- REVIEW before submit');
      if (pkg && pkg.approved === true) log('approval recorded; human Submit still required');
    } catch (error) {
      log(`autofill failed: ${error?.stack || error}`);
      step('validation', 'failed', String(error?.message || error));
    } finally {
      box.style.pointerEvents = '';
      runButton.disabled = false;
      runButton.textContent = '↻ Run autofill again';
    }
  };
})();
