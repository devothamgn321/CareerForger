#!/usr/bin/env python3
"""Build a self-contained Playwright CLI function for the local extension fixture."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROFILE = ROOT / "extension" / "profile.default.json"
PACKAGE = ROOT / "examples" / "application-package.example.json"
CONTENT = ROOT / "extension" / "content.js"
OUTPUT = ROOT / "output" / "playwright" / "run_extension_dryrun.generated.js"

template = """async (page) => {{
  const profile = {profile};
  const pkg = {package};
  await page.evaluate((seed) => {{
    window.chrome = {{storage: {{local: {{get: (_key, callback) =>
      callback({{user_profile: seed}})}}}}}};
  }}, profile);
  await page.addScriptTag({{path: {content_path}}});
  await page.locator('#p1f-pkg').fill(JSON.stringify(pkg));
  await page.locator('#p1f-load').click();
  await page.locator('#p1f-run').click();
  await page.waitForTimeout(2500);
  return page.evaluate((expected) => {{
    const byName = (name) => document.querySelector(`[name="${{name}}"]`);
    return {{
      basic_identity_verified:
        byName('_systemfield_first_name').value === expected.first_name &&
        byName('_systemfield_last_name').value === expected.last_name &&
        byName('_systemfield_email').value === expected.email,
      phone_verified: byName('_systemfield_phone').value === expected.phone,
      linkedin_verified: byName('linkedin').value === expected.linkedin,
      why_company_filled: byName('why_company').value.length > 20,
      why_role_filled: byName('why_role').value.length > 20,
      resume_filename: byName('resume').files[0] && byName('resume').files[0].name,
      cover_letter_filename:
        byName('cover_letter').files[0] && byName('cover_letter').files[0].name,
      extension_submit_control_present: Boolean(document.querySelector('#p1f-submit')),
      native_submit_state: document.querySelector('#submitted').textContent,
      log_tail: document.querySelector('#p1f-log').textContent.trim().split('\\n').slice(-5)
    }};
  }}, profile);
}}"""

OUTPUT.parent.mkdir(parents=True, exist_ok=True)

OUTPUT.write_text(template.format(
    profile=json.dumps(json.loads(PROFILE.read_text())),
    package=json.dumps(json.loads(PACKAGE.read_text())),
    content_path=json.dumps(str(CONTENT)),
))
print(OUTPUT)
