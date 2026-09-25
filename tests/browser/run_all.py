"""Browser regression suite for P1 Autofill (needs Playwright + Chromium; not part of unittest).

    python3 tests/browser/run_all.py

Loads each fixture page, injects extension/content.js with a stubbed chrome API and the fictional
example profile, clicks Run autofill, and checks every expected value. Nothing is submitted.
"""
import asyncio, json, sys
from pathlib import Path
from playwright.async_api import async_playwright

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
STUB = ("window.chrome={runtime:{lastError:null,getURL:x=>x,sendMessage:(m,cb)=>cb&&cb({ok:false})},"
        "storage:{local:{get:(k,cb)=>cb({user_profile:window.__P}),set:(o,cb)=>cb&&cb()}}};")

def profile(county=""):
    p = json.loads((ROOT / "extension" / "profile.example.json").read_text())
    p["address"].update(city="Baltimore", state="Maryland", zip="21210", country="United States", county=county)
    p.update(phone_country="United States", phone_country_code="+1")
    p["eeo"].update(gender=["Male"], veteran=["I am not a protected veteran"],
                    race=["Asian", "Asian (Not Hispanic or Latino)", "South Asian"])
    p["choices"].update(sponsorship=["Yes"])
    return p

VAL = ("e=>e.type==='checkbox'?String(e.checked):(e.tagName==='BUTTON'?e.textContent.trim():"
       "(e.value!==undefined?e.value:e.textContent))")
CASES = [
    ("oracle_cx_select.html", profile("Baltimore City"), None, {
        "country-codes-dropdownphoneNumber": "+1 (United States)", "country-14": "United States",
        "city-18": "Baltimore", "region1-20": "Baltimore City", "region2-21": "MD",
        "postalCode-22": "21210", "US-STANDARD-ORA_GENDER-STANDARD-7": "Male",
        "US-STANDARD-ORA_VETERAN_STATUS-STANDARD-10": "I am not a protected veteran"}),
    # Without a county the address rows tie: leave them for the human, never take the first.
    ("oracle_cx_select.html", profile(""), None, {
        "city-18": "", "region1-20": "", "postalCode-22": ""}),
    ("button_listbox.html", profile(), None, {
        "bg": "Male", "bv": "I am not a protected veteran", "bs": "Yes"}),
    ("react_select_and_portal.html", profile(), "()=>{const i=document.getElementById('s0x');"
     "i.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowDown',bubbles:true}))}", {
        "v1": "Yes", "v2": "Yes", "v3": "I am not a protected veteran"}),
    ("greenhouse_filtering.html", profile(), None, {
        "country-value": "United States +1", "q_worked-value": "No", "q_sql-value": "Yes",
        "q_lead-value": "", "q_trans-value": "I don't wish to answer", "q_priv-value": "I acknowledge",
        "q_emp-value": "No", "q_race-value": "Asian"}),
    ("text_labels.html", profile(), None, {
        "a": "Alex Example", "b": "F-1 OPT", "c": "", "d": "No", "e": "Yes", "pa": "true"}),
]

async def main():
    failures = 0
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        for page_name, prof, before, expected in CASES:
            page = await browser.new_page()
            await page.goto((HERE / page_name).as_uri())
            await page.evaluate("p=>{window.__P=p}", prof)
            await page.evaluate(STUB)
            if before:
                await page.evaluate(before)
            await page.add_script_tag(path=str(ROOT / "extension" / "content.js"))
            await page.wait_for_selector("#p1f-run", state="attached")
            await page.evaluate("()=>document.querySelector('#p1f-run').click()")
            await page.wait_for_function(
                "()=>document.querySelector('#p1f-log').textContent.includes('autofill done')", timeout=120000)
            for el_id, want in expected.items():
                got = await page.eval_on_selector("#" + el_id, VAL)
                ok = str(got).strip() == want
                failures += not ok
                print(("OK  " if ok else "BAD ") + f"{page_name:32} {el_id:45} {got!r}")
            submitted = await page.evaluate("()=>document.body.dataset.sub||'no'")
            if submitted != "no":
                failures += 1
                print("BAD form was submitted:", page_name)
            await page.close()
        await browser.close()
    print("failures:", failures)
    sys.exit(1 if failures else 0)

asyncio.run(main())
