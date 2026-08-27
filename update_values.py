import json
import os
import re
import time
import base64
import requests

from datetime import datetime
from urllib.parse import urljoin, urlparse

from playwright.sync_api import (
    sync_playwright,
    TimeoutError as PlaywrightTimeoutError
)


# =========================================================
# CONFIG
# =========================================================

BASE_URL = "https://bloxfruitsvalues.com"

GITHUB_OWNER = "Helos-dev"
GITHUB_REPO = "combolab-src-repo"
GITHUB_FILE = "value.json"
GITHUB_BRANCH = "main"

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")

DEBUG_DUMP_ON_MISMATCH = True
DEBUG_DIR = "debug_dumps"

PAGE_TIMEOUT = 60000
PAGE_WAIT = 3000

MAX_PAGE_RETRIES = 3
MAX_SCRAPE_RETRIES = 2


# =========================================================
# TOKEN
# =========================================================

if not GITHUB_TOKEN:
    print("=" * 70)
    print("ERRORE: GITHUB_TOKEN NON TROVATO")
    print("=" * 70)
    raise SystemExit(1)


GITHUB_API_URL = (
    f"https://api.github.com/repos/"
    f"{GITHUB_OWNER}/"
    f"{GITHUB_REPO}/"
    f"contents/{GITHUB_FILE}"
)


# =========================================================
# UTILITY
# =========================================================

def clean(text):

    if text is None:
        return ""

    return re.sub(
        r"\s+",
        " ",
        str(text)
    ).strip()


def normalize_name(name):

    name = clean(name)

    if not name:
        return ""

    name = re.sub(
        r"\s*[-|]\s*Blox Fruits Values.*$",
        "",
        name,
        flags=re.IGNORECASE
    )

    name = re.sub(
        r"\s+Blox Fruits Values.*$",
        "",
        name,
        flags=re.IGNORECASE
    )

    name = re.sub(
        r"\s*[-|]\s*Bloxfruits.*$",
        "",
        name,
        flags=re.IGNORECASE
    )

    return clean(name)


def normalize_value(value):

    if not value:
        return "0"

    value = clean(value)
    value = value.replace(",", "")
    value = value.replace(" ", "")

    match = re.search(
        r"([0-9]+(?:\.[0-9]+)?)([KMBT]?)",
        value
    )

    if not match:
        return "0"

    return (
        match.group(1)
        + match.group(2).upper()
    )


# =========================================================
# VALUE EXTRACTION
# =========================================================

def extract_values(text):

    if not text:
        return []

    results = []

    matches = re.findall(
        r"\b[0-9]+(?:\.[0-9]+)?\s*[KMBT]\b",
        text,
        re.IGNORECASE
    )

    for match in matches:

        value = normalize_value(match)

        if value not in results:
            results.append(value)

    return results


# =========================================================
# DEMAND
# =========================================================

def get_demand(text):

    match = re.search(
        r"Demand\s*[:\-]?\s*"
        r"([0-9]+(?:\.[0-9]+)?\s*/\s*10)",
        text,
        re.IGNORECASE
    )

    if match:
        return clean(match.group(1))

    return "N/A"


# =========================================================
# TREND
# =========================================================

def get_trend(text):

    trends = [
        "Overpaid",
        "Underpaid",
        "Stable",
        "Increasing",
        "Decreasing"
    ]

    for trend in trends:

        if re.search(
            rf"\b{trend}\b",
            text,
            re.IGNORECASE
        ):
            return trend

    return "Stable"


# =========================================================
# RARITY
# =========================================================

def get_rarity(text):

    rarities = [
        "Mythical",
        "Legendary",
        "Rare",
        "Uncommon",
        "Common"
    ]

    for rarity in rarities:

        if re.search(
            rf"\b{rarity}\b",
            text,
            re.IGNORECASE
        ):
            return rarity

    return "Unknown"


# =========================================================
# OPEN PAGE
# =========================================================

def open_page(page, url):

    print(f"      GET {url}")

    last_error = None

    for attempt in range(
        1,
        MAX_PAGE_RETRIES + 1
    ):

        try:

            page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=PAGE_TIMEOUT
            )

            page.wait_for_timeout(
                PAGE_WAIT
            )

            return True

        except PlaywrightTimeoutError as error:

            last_error = error

            print(
                f"      Timeout "
                f"(tentativo {attempt}/{MAX_PAGE_RETRIES})"
            )

        except Exception as error:

            last_error = error

            print(
                f"      Errore pagina "
                f"(tentativo {attempt}/{MAX_PAGE_RETRIES}): "
                f"{error}"
            )

        time.sleep(2)

    print(
        f"      IMPOSSIBILE APRIRE: {url}"
    )

    print(
        f"      Ultimo errore: {last_error}"
    )

    return False


# =========================================================
# REAL NAME
# =========================================================

def get_real_name(
    page,
    fallback
):

    try:

        h1 = page.locator(
            "h1"
        ).first

        if h1.count():

            name = normalize_name(
                h1.inner_text()
            )

            if name:
                return name

    except:
        pass

    try:

        element = page.locator(
            'meta[property="og:title"]'
        )

        if element.count():

            content = element.get_attribute(
                "content"
            )

            if content:

                name = normalize_name(
                    content
                )

                if name:
                    return name

    except:
        pass

    try:

        title = normalize_name(
            page.title()
        )

        if title:
            return title

    except:
        pass

    return normalize_name(
        fallback
    )


# =========================================================
# FIND TABS
# =========================================================

def find_tab_candidates(
    page,
    name
):

    wanted = name.lower()

    selectors = [
        "button",
        '[role="button"]',
        '[role="tab"]',
        "a",
        "[onclick]"
    ]

    candidates = []

    for selector in selectors:

        try:

            elements = page.locator(
                selector
            )

            count = elements.count()

            for i in range(count):

                element = elements.nth(i)

                try:

                    if not element.is_visible():
                        continue

                    text = clean(
                        element.inner_text()
                    ).lower()

                    if text == wanted:
                        candidates.append(element)

                except:
                    continue

        except:
            continue

    return candidates


def find_tab(
    page,
    name
):

    candidates = find_tab_candidates(
        page,
        name
    )

    if candidates:
        return candidates[0]

    return None


# =========================================================
# READ VALUE
# =========================================================

def read_value_stat(page):

    try:

        value = page.evaluate(
            """
            () => {

                const clean = (s) =>
                    (s || "")
                    .replace(/\\s+/g, " ")
                    .trim();

                const regex =
                    /\\b[0-9]+(?:\\.[0-9]+)?\\s*[KMBT]\\b/i;

                const isVisible = (el) => {

                    const style =
                        window.getComputedStyle(el);

                    if (style.display === "none")
                        return false;

                    if (style.visibility === "hidden")
                        return false;

                    if (parseFloat(style.opacity) === 0)
                        return false;

                    return true;
                };

                const all = [
                    ...document.querySelectorAll("*")
                ];

                for (const el of all) {

                    if (el.children.length > 2)
                        continue;

                    if (!isVisible(el))
                        continue;

                    const text = clean(
                        el.textContent
                    );

                    if (
                        text.toLowerCase()
                        !== "value"
                    )
                        continue;

                    let sib =
                        el.nextElementSibling;

                    while (sib) {

                        if (isVisible(sib)) {

                            const sibText =
                                clean(
                                    sib.textContent
                                );

                            const match =
                                sibText.match(regex);

                            if (match)
                                return match[0];
                        }

                        sib =
                            sib.nextElementSibling;
                    }

                    const parent =
                        el.parentElement;

                    if (
                        parent &&
                        isVisible(parent)
                    ) {

                        const parentText =
                            clean(
                                parent.textContent
                            );

                        const stripped =
                            parentText.replace(
                                /value/i,
                                ""
                            );

                        const match =
                            stripped.match(regex);

                        if (match)
                            return match[0];
                    }
                }

                for (const el of all) {

                    if (el.children.length > 0)
                        continue;

                    if (!isVisible(el))
                        continue;

                    const text =
                        clean(el.textContent);

                    const match =
                        text.match(
                            /^Value\\s*([0-9]+(?:\\.[0-9]+)?\\s*[KMBT])$/i
                        );

                    if (match)
                        return match[1];
                }

                return null;
            }
            """
        )

        return value

    except Exception as error:

        print(
            f"      Errore lettura Value: {error}"
        )

        return None


# =========================================================
# CLICK TAB
# =========================================================

def _try_click_variants(
    page,
    tab,
    tab_name,
    attempt_index
):

    variants = [
        "playwright_click",
        "playwright_force_click",
        "manual_mouse_sequence",
        "keyboard_enter",
        "js_dispatch_mouse_event"
    ]

    variant = variants[
        attempt_index % len(variants)
    ]

    try:

        if variant == "playwright_click":

            tab.scroll_into_view_if_needed(
                timeout=3000
            )

            tab.click(
                timeout=5000
            )

        elif variant == "playwright_force_click":

            tab.scroll_into_view_if_needed(
                timeout=3000
            )

            tab.click(
                force=True,
                timeout=5000
            )

        elif variant == "manual_mouse_sequence":

            box = tab.bounding_box()

            if not box:
                return False

            x = (
                box["x"]
                + box["width"] / 2
            )

            y = (
                box["y"]
                + box["height"] / 2
            )

            page.mouse.move(
                x,
                y
            )

            page.wait_for_timeout(
                80
            )

            page.mouse.down()

            page.wait_for_timeout(
                80
            )

            page.mouse.up()

        elif variant == "keyboard_enter":

            tab.scroll_into_view_if_needed(
                timeout=3000
            )

            tab.focus()

            page.keyboard.press(
                "Enter"
            )

            page.wait_for_timeout(
                100
            )

            page.keyboard.press(
                "Space"
            )

        elif variant == "js_dispatch_mouse_event":

            tab.evaluate(
                """
                (el) => {

                    const rect =
                        el.getBoundingClientRect();

                    const opts = {
                        bubbles: true,
                        cancelable: true,
                        view: window,
                        clientX:
                            rect.x
                            + rect.width / 2,
                        clientY:
                            rect.y
                            + rect.height / 2
                    };

                    el.dispatchEvent(
                        new MouseEvent(
                            "pointerdown",
                            opts
                        )
                    );

                    el.dispatchEvent(
                        new MouseEvent(
                            "mousedown",
                            opts
                        )
                    );

                    el.dispatchEvent(
                        new MouseEvent(
                            "pointerup",
                            opts
                        )
                    );

                    el.dispatchEvent(
                        new MouseEvent(
                            "mouseup",
                            opts
                        )
                    );

                    el.dispatchEvent(
                        new MouseEvent(
                            "click",
                            opts
                        )
                    );
                }
                """
            )

        print(
            f"      {tab_name}: "
            f"click '{variant}'"
        )

        return True

    except Exception as error:

        print(
            f"      {tab_name}: "
            f"'{variant}' fallito: {error}"
        )

        return False


def click_tab_and_wait(
    page,
    tab,
    tab_name,
    baseline_value
):

    max_attempts = 5

    for attempt in range(
        max_attempts
    ):

        ok = _try_click_variants(
            page,
            tab,
            tab_name,
            attempt
        )

        if not ok:
            continue

        deadline = (
            time.time()
            + 3
        )

        current = None

        while time.time() < deadline:

            current = read_value_stat(
                page
            )

            if current:

                if baseline_value is None:
                    return current

                if (
                    normalize_value(current)
                    != normalize_value(
                        baseline_value
                    )
                ):
                    return current

            page.wait_for_timeout(
                150
            )

        print(
            f"      {tab_name}: "
            f"nessun cambiamento "
            f"({attempt + 1}/{max_attempts})"
        )

    return read_value_stat(page)


# =========================================================
# DEBUG DUMP
# =========================================================

def debug_dump(
    page,
    fruit_slug,
    reason
):

    if not DEBUG_DUMP_ON_MISMATCH:
        return

    try:

        os.makedirs(
            DEBUG_DIR,
            exist_ok=True
        )

        html_path = os.path.join(
            DEBUG_DIR,
            f"{fruit_slug}.html"
        )

        png_path = os.path.join(
            DEBUG_DIR,
            f"{fruit_slug}.png"
        )

        with open(
            html_path,
            "w",
            encoding="utf-8"
        ) as f:

            f.write(
                page.content()
            )

        page.screenshot(
            path=png_path,
            full_page=True
        )

        info_path = os.path.join(
            DEBUG_DIR,
            f"{fruit_slug}_tabs.json"
        )

        dump = {}

        for name in (
            "Regular",
            "Permanent"
        ):

            candidates = find_tab_candidates(
                page,
                name
            )

            entries = []

            for candidate in candidates:

                try:

                    attrs = candidate.evaluate(
                        """
                        (el) => {

                            const out = {};

                            for (
                                const a
                                of el.attributes
                            ) {
                                out[a.name] =
                                    a.value;
                            }

                            return {
                                tag:
                                    el.tagName,

                                attrs:
                                    out,

                                outerHTML:
                                    el.outerHTML
                                    .slice(0, 400)
                            };
                        }
                        """
                    )

                    entries.append(
                        attrs
                    )

                except:
                    continue

            dump[name] = entries

        with open(
            info_path,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                dump,
                f,
                indent=2,
                ensure_ascii=False
            )

        print(
            f"      [DEBUG] "
            f"Dump salvato per {fruit_slug}"
        )

    except Exception as error:

        print(
            f"      [DEBUG] "
            f"dump fallito: {error}"
        )


# =========================================================
# SCRAPE FRUIT
# =========================================================

def scrape_fruit(
    page,
    url,
    fallback_name
):

    if not open_page(
        page,
        url
    ):
        raise RuntimeError(
            "Pagina non caricata"
        )

    name = get_real_name(
        page,
        fallback_name
    )

    text = page.locator(
        "body"
    ).inner_text()

    rarity = get_rarity(text)
    demand = get_demand(text)
    trend = get_trend(text)

    slug = (
        urlparse(url)
        .path
        .rstrip("/")
        .split("/")[-1]
    )

    regular_tab = find_tab(
        page,
        "Regular"
    )

    permanent_tab = find_tab(
        page,
        "Permanent"
    )

    if (
        regular_tab is None
        or permanent_tab is None
    ):

        print(
            "      Tab Regular/Permanent "
            "non trovati"
        )

        current = read_value_stat(
            page
        )

        current = (
            normalize_value(current)
            if current
            else "0"
        )

        return {
            "name": name,
            "rarity": rarity,
            "value_normal": current,
            "value_permanent": current,
            "demand": demand,
            "trend": trend
        }

    print(
        "      Lettura Regular..."
    )

    baseline = read_value_stat(
        page
    )

    normal = click_tab_and_wait(
        page,
        regular_tab,
        "Regular",
        None
    )

    normal = (
        normalize_value(normal)
        if normal
        else normalize_value(baseline)
    )

    print(
        f"      Regular: {normal}"
    )

    print(
        "      Lettura Permanent..."
    )

    permanent = click_tab_and_wait(
        page,
        permanent_tab,
        "Permanent",
        normal
    )

    permanent = (
        normalize_value(permanent)
        if permanent
        else normal
    )

    print(
        f"      Permanent: {permanent}"
    )

    if permanent == normal:

        print(
            "      ATTENZIONE: "
            "Regular == Permanent"
        )

        click_tab_and_wait(
            page,
            regular_tab,
            "Regular",
            None
        )

        page.wait_for_timeout(
            500
        )

        retry = click_tab_and_wait(
            page,
            permanent_tab,
            "Permanent",
            normal
        )

        retry = (
            normalize_value(retry)
            if retry
            else permanent
        )

        if retry != normal:

            permanent = retry

        else:

            print(
                "      Valore ancora identico."
            )

            debug_dump(
                page,
                slug,
                "Regular == Permanent"
            )

    return {
        "name": name,
        "rarity": rarity,
        "value_normal": normal,
        "value_permanent": permanent,
        "demand": demand,
        "trend": trend
    }


# =========================================================
# SCRAPE GAMEPASS / LIMITED
# =========================================================

def scrape_item(
    page,
    url,
    fallback_name
):

    if not open_page(
        page,
        url
    ):
        raise RuntimeError(
            "Pagina non caricata"
        )

    name = get_real_name(
        page,
        fallback_name
    )

    text = page.locator(
        "body"
    ).inner_text()

    values = extract_values(
        text
    )

    value = (
        values[0]
        if values
        else "0"
    )

    return {
        "name": name,
        "value": value,
        "demand": get_demand(text),
        "trend": get_trend(text)
    }


# =========================================================
# LOAD ALL LINKS
# =========================================================

def load_all_items(
    page,
    category
):

    url = (
        f"{BASE_URL}/values/{category}"
    )

    print()
    print("=" * 70)
    print(
        f"OPEN: {url}"
    )
    print("=" * 70)

    if not open_page(
        page,
        url
    ):
        raise RuntimeError(
            f"Impossibile aprire {url}"
        )

    old_height = 0
    stable = 0

    for _ in range(100):

        try:

            page.evaluate(
                """
                window.scrollTo(
                    0,
                    document.body.scrollHeight
                );
                """
            )

        except:
            pass

        page.wait_for_timeout(
            1000
        )

        try:

            height = page.evaluate(
                "document.body.scrollHeight"
            )

        except:

            height = old_height

        if height == old_height:

            stable += 1

        else:

            stable = 0

        old_height = height

        if stable >= 5:
            break

    elements = page.locator(
        "a[href]"
    )

    total = elements.count()

    print(
        f"Link totali pagina: {total}"
    )

    prefix = (
        f"/values/{category}/"
    )

    found = {}

    for i in range(total):

        try:

            element = elements.nth(i)

            href = element.get_attribute(
                "href"
            )

            if not href:
                continue

            full_url = urljoin(
                BASE_URL,
                href
            )

            path = (
                urlparse(full_url)
                .path
                .rstrip("/")
            )

            if not path.startswith(
                prefix
            ):
                continue

            slug = path[
                len(prefix):
            ]

            if not slug:
                continue

            if "/" in slug:
                continue

            name = clean(
                element.inner_text()
            )

            if (
                not name
                or len(name) > 80
                or "Blox Fruits Values"
                in name
                or "Value List"
                in name
            ):

                name = slug.replace(
                    "-",
                    " "
                ).title()

            name = normalize_name(
                name
            )

            if not name:
                continue

            found[
                full_url
            ] = name

        except:
            continue

    print(
        f"{category}: "
        f"{len(found)} link trovati"
    )

    return found


# =========================================================
# SCRAPE CATEGORY
# =========================================================

def scrape_category(
    page,
    category
):

    links = load_all_items(
        page,
        category
    )

    results = []

    total = len(links)

    print()
    print(
        f"{category.upper()}: {total}"
    )

    failed = []

    for index, (
        url,
        name
    ) in enumerate(
        links.items(),
        start=1
    ):

        print()
        print(
            f"[{index}/{total}] {name}"
        )

        success = False

        for attempt in range(
            1,
            MAX_PAGE_RETRIES + 1
        ):

            try:

                if category == "fruits":

                    item = scrape_fruit(
                        page,
                        url,
                        name
                    )

                    print(
                        f"      Normal: "
                        f"{item['value_normal']}"
                    )

                    print(
                        f"      Permanent: "
                        f"{item['value_permanent']}"
                    )

                else:

                    item = scrape_item(
                        page,
                        url,
                        name
                    )

                    print(
                        f"      Value: "
                        f"{item['value']}"
                    )

                print(
                    f"      Demand: "
                    f"{item['demand']}"
                )

                print(
                    f"      Trend: "
                    f"{item['trend']}"
                )

                results.append(
                    item
                )

                success = True

                break

            except Exception as error:

                print(
                    f"      ERRORE "
                    f"(tentativo "
                    f"{attempt}/"
                    f"{MAX_PAGE_RETRIES}): "
                    f"{error}"
                )

                time.sleep(2)

        if not success:

            print(
                f"      FALLITO: {name}"
            )

            failed.append({
                "name": name,
                "url": url
            })

        time.sleep(
            0.2
        )

    print()
    print(
        f"{category}: "
        f"{len(results)} riusciti"
    )

    print(
        f"{category}: "
        f"{len(failed)} falliti"
    )

    if failed:

        print()
        print(
            "ELEMENTI FALLITI:"
        )

        for item in failed:

            print(
                f" - {item['name']}"
            )

    return results


# =========================================================
# GITHUB
# =========================================================

def github_headers():

    return {
        "Accept":
            "application/vnd.github+json",

        "Authorization":
            f"Bearer {GITHUB_TOKEN}",

        "X-GitHub-Api-Version":
            "2022-11-28"
    }


def get_github_file():

    response = requests.get(
        GITHUB_API_URL,
        headers=github_headers(),
        timeout=30
    )

    if response.status_code != 200:

        print(
            "ERRORE LETTURA GITHUB:"
        )

        print(
            response.status_code
        )

        print(
            response.text
        )

        response.raise_for_status()

    return response.json()


def upload_to_github(
    data
):

    print()
    print("=" * 70)
    print(
        "AGGIORNAMENTO GITHUB"
    )
    print("=" * 70)

    current = get_github_file()

    sha = current.get(
        "sha"
    )

    content = json.dumps(
        data,
        indent=2,
        ensure_ascii=False
    )

    encoded = base64.b64encode(
        content.encode("utf-8")
    ).decode("utf-8")

    payload = {

        "message":
            "Auto update Blox Fruits values",

        "content":
            encoded,

        "sha":
            sha,

        "branch":
            GITHUB_BRANCH
    }

    response = requests.put(
        GITHUB_API_URL,
        headers=github_headers(),
        json=payload,
        timeout=60
    )

    if response.status_code in (
        200,
        201
    ):

        result = response.json()

        commit = result.get(
            "commit",
            {}
        )

        print()
        print(
            "GITHUB AGGIORNATO!"
        )

        print(
            f"Commit: "
            f"{commit.get('sha', 'N/A')}"
        )

        print()

        return True

    print()
    print(
        "ERRORE AGGIORNAMENTO GITHUB"
    )

    print(
        response.status_code
    )

    print(
        response.text
    )

    return False


# =========================================================
# VALIDAZIONE
# =========================================================

def validate_scraped_data(
    fruits,
    limited,
    gamepasses
):

    print()
    print("=" * 70)
    print(
        "VALIDAZIONE DATI"
    )
    print("=" * 70)

    print(
        f"Fruits:    {len(fruits)}"
    )

    print(
        f"Limited:   {len(limited)}"
    )

    print(
        f"Gamepass:  {len(gamepasses)}"
    )

    if len(fruits) == 0:
        print(
            "ERRORE: 0 fruits trovati"
        )
        return False

    if len(limited) == 0:
        print(
            "ATTENZIONE: 0 limited trovati"
        )

    if len(gamepasses) == 0:
        print(
            "ATTENZIONE: 0 gamepasses trovati"
        )

    return True


# =========================================================
# MAIN SCRAPE
# =========================================================

def run_scraper():

    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu"
            ]
        )

        context = browser.new_context(

            viewport={
                "width": 1440,
                "height": 1000
            },

            user_agent=(
                "Mozilla/5.0 "
                "(X11; Linux x86_64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/151.0.0.0 "
                "Safari/537.36"
            ),

            locale="en-US",

            ignore_https_errors=True
        )

        page = context.new_page()

        fruits = scrape_category(
            page,
            "fruits"
        )

        print()
        print(
            f"FRUITS: {len(fruits)}"
        )

        gamepasses = scrape_category(
            page,
            "gamepasses"
        )

        print()
        print(
            f"GAMEPASSES: {len(gamepasses)}"
        )

        limited = scrape_category(
            page,
            "limiteds"
        )

        print()
        print(
            f"LIMITED: {len(limited)}"
        )

        browser.close()

    return (
        fruits,
        limited,
        gamepasses
    )


# =========================================================
# MAIN
# =========================================================

def main():

    print()
    print("=" * 70)
    print(
        " BLOXFRUITVALUES JSON UPDATER"
    )
    print("=" * 70)

    fruits = []
    limited = []
    gamepasses = []

    completed = False

    for attempt in range(
        1,
        MAX_SCRAPE_RETRIES + 1
    ):

        print()
        print(
            "=" * 70
        )

        print(
            f"SCRAPING GENERALE "
            f"TENTATIVO "
            f"{attempt}/{MAX_SCRAPE_RETRIES}"
        )

        print(
            "=" * 70
        )

        try:

            (
                fruits,
                limited,
                gamepasses
            ) = run_scraper()

            if validate_scraped_data(
                fruits,
                limited,
                gamepasses
            ):

                completed = True
                break

        except Exception as error:

            print()
            print(
                "ERRORE SCRAPING GENERALE:"
            )

            print(
                error
            )

        if attempt < MAX_SCRAPE_RETRIES:

            print()
            print(
                "Riprovo tra 10 secondi..."
            )

            time.sleep(10)

    if not completed:

        print()
        print("=" * 70)
        print(
            "SCRAPING FALLITO"
        )
        print("=" * 70)

        print(
            "Il value.json NON verra' "
            "sovrascritto."
        )

        raise SystemExit(1)

    # =====================================================
    # JSON
    # =====================================================

    data = {

        "source":
            BASE_URL,

        "last_updated":
            datetime.now().strftime(
                "%Y-%m-%d"
            ),

        "currency_note":
            "Trading values from BloxfruitsValues.com",

        "Valuefruits":
            fruits,

        "Limited":
            limited,

        "Gamepass":
            gamepasses
    }

    # =====================================================
    # LOCAL SAVE
    # =====================================================

    with open(
        "value.json",
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            data,
            file,
            indent=2,
            ensure_ascii=False
        )

    print()
    print("=" * 70)
    print(
        "VALUE.JSON LOCALE SALVATO"
    )
    print("=" * 70)

    print(
        f"Fruits:    {len(fruits)}"
    )

    print(
        f"Limited:   {len(limited)}"
    )

    print(
        f"Gamepass:  {len(gamepasses)}"
    )

    # =====================================================
    # GITHUB
    # =====================================================

    success = upload_to_github(
        data
    )

    print()
    print("=" * 70)

    if success:

        print(
            " OPERAZIONE COMPLETATA"
        )

    else:

        print(
            " SCRAPING OK - "
            "GITHUB NON AGGIORNATO"
        )

        raise SystemExit(1)

    print("=" * 70)


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":
    main()
