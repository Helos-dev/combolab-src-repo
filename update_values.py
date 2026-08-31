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

PAGE_TIMEOUT = 60000
PAGE_WAIT = 2500

MAX_PAGE_RETRIES = 3
MAX_ITEM_RETRIES = 3

DEBUG_DUMP_ON_ERROR = True
DEBUG_DIR = "debug_dumps"


# =========================================================
# GITHUB TOKEN
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
        r"\s+Bloxfruits.*$",
        "",
        name,
        flags=re.IGNORECASE
    )

    return clean(name)


def normalize_value(value):

    if value is None:
        return "0"

    value = clean(value)

    if not value:
        return "0"

    value = value.replace(",", "")
    value = value.replace(" ", "")

    # N/A, -, ecc.
    if value.lower() in (
        "n/a",
        "na",
        "-",
        "none"
    ):
        return "0"

    match = re.search(
        r"([0-9]+(?:\.[0-9]+)?)([KMBT])?",
        value,
        re.IGNORECASE
    )

    if not match:
        return "0"

    number = match.group(1)
    suffix = (
        match.group(2).upper()
        if match.group(2)
        else ""
    )

    return number + suffix


# =========================================================
# PAGE OPEN
# =========================================================

def open_page(page, url):

    print()
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
                f"{attempt}/{MAX_PAGE_RETRIES}"
            )

        except Exception as error:

            last_error = error

            print(
                f"      Errore "
                f"{attempt}/{MAX_PAGE_RETRIES}: "
                f"{error}"
            )

        time.sleep(2)

    print(
        f"      IMPOSSIBILE APRIRE LA PAGINA"
    )

    print(
        f"      {last_error}"
    )

    return False


# =========================================================
# GET REAL NAME
# =========================================================

def get_real_name(page, fallback):

    # H1
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

    # OG TITLE
    try:

        meta = page.locator(
            'meta[property="og:title"]'
        ).first

        if meta.count():

            content = meta.get_attribute(
                "content"
            )

            name = normalize_name(
                content
            )

            if name:
                return name

    except:
        pass

    # TITLE
    try:

        name = normalize_name(
            page.title()
        )

        if name:
            return name

    except:
        pass

    return normalize_name(
        fallback
    )


# =========================================================
# EXTRACT TEXT AFTER LABEL
# =========================================================

def extract_after_label(
    text,
    label
):

    if not text:
        return None

    pattern = (
        rf"{re.escape(label)}"
        rf"\s*[:\-]?\s*"
        rf"([^\n]+)"
    )

    match = re.search(
        pattern,
        text,
        re.IGNORECASE
    )

    if not match:
        return None

    return clean(
        match.group(1)
    )


# =========================================================
# VALUE EXTRACTION
# =========================================================

def extract_first_value(text):

    if not text:
        return "0"

    # Prima prova: valore con K/M/B/T
    matches = re.findall(
        r"\b[0-9]+(?:\.[0-9]+)?\s*[KMBT]\b",
        text,
        re.IGNORECASE
    )

    if matches:
        return normalize_value(
            matches[0]
        )

    return "0"


def extract_value_from_line(
    text,
    label
):

    if not text:
        return "0"

    pattern = (
        rf"{re.escape(label)}"
        rf"\s*[:\-]?\s*"
        rf"([0-9]+(?:\.[0-9]+)?\s*[KMBT])"
    )

    match = re.search(
        pattern,
        text,
        re.IGNORECASE
    )

    if match:

        return normalize_value(
            match.group(1)
        )

    return "0"


# =========================================================
# DEMAND
# =========================================================

def get_demand(text):

    if not text:
        return "N/A"

    match = re.search(
        r"\bDemand\b"
        r"\s*[:\-]?\s*"
        r"([0-9]+(?:\.[0-9]+)?\s*/\s*10)",
        text,
        re.IGNORECASE
    )

    if match:

        return clean(
            match.group(1)
        )

    return "N/A"


# =========================================================
# TREND
# =========================================================

def get_trend(text):

    if not text:
        return "Stable"

    # Nuovo sito può avere anche SOON
    trends = [
        "Overpaid",
        "Underpaid",
        "Stable",
        "Increasing",
        "Decreasing",
        "SOON"
    ]

    for trend in trends:

        if re.search(
            rf"\b{re.escape(trend)}\b",
            text,
            re.IGNORECASE
        ):
            return trend

    return "Stable"


# =========================================================
# RARITY
# =========================================================

def get_rarity(text):

    if not text:
        return "Unknown"

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
# FIND LINKS
# =========================================================

def collect_item_links(
    page,
    category
):

    url = (
        f"{BASE_URL}/values/{category}"
    )

    print()
    print("=" * 70)
    print(
        f"CARICAMENTO {category.upper()}"
    )
    print(
        url
    )
    print("=" * 70)

    if not open_page(
        page,
        url
    ):
        raise RuntimeError(
            f"Impossibile caricare {url}"
        )

    # -----------------------------------------------------
    # Scroll per caricare eventuali elementi dinamici
    # -----------------------------------------------------

    last_height = 0
    stable_count = 0

    for _ in range(80):

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
            800
        )

        try:

            height = page.evaluate(
                "document.body.scrollHeight"
            )

        except:

            height = last_height

        if height == last_height:

            stable_count += 1

        else:

            stable_count = 0

        last_height = height

        if stable_count >= 5:
            break

    # -----------------------------------------------------
    # Trova tutti i link
    # -----------------------------------------------------

    elements = page.locator(
        "a[href]"
    )

    total = elements.count()

    print(
        f"Link trovati: {total}"
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

            parsed = urlparse(
                full_url
            )

            path = (
                parsed.path
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

            # Evita duplicati
            if full_url in found:
                continue

            name = clean(
                element.inner_text()
            )

            if not name:

                name = (
                    slug
                    .replace("-", " ")
                    .title()
                )

            name = normalize_name(
                name
            )

            if not name:
                continue

            # Evita testi palesemente non-item
            if len(name) > 100:
                continue

            found[
                full_url
            ] = name

        except:
            continue

    print(
        f"{category.upper()}: "
        f"{len(found)} item trovati"
    )

    return found


# =========================================================
# FRUIT VALUE
# =========================================================

def read_fruit_regular_value(
    page,
    body_text,
    label="Regular value"
):

    # Metodo 1: cerca direttamente
    # "Regular value 600M" oppure "Permanent value 600M"
    value = extract_value_from_line(
        body_text,
        label
    )

    if value != "0":
        return value

    # Metodo 2: DOM
    try:

        value = page.evaluate(
            """
            () => {

                const clean = (s) =>
                    (s || "")
                    .replace(/\\s+/g, " ")
                    .trim();

                const regex =
                    /([0-9]+(?:\\.[0-9]+)?\\s*[KMBT])/i;

                const elements =
                    [...document.querySelectorAll("*")];

                for (const el of elements) {

                    const text =
                        clean(el.textContent);

                    if (
                        !text ||
                        el.children.length > 3
                    )
                        continue;

                    const lower =
                        text.toLowerCase();

                    const index =
                        lower.indexOf(
                            LABEL.toLowerCase()
                        );

                    if (index === -1)
                        continue;

                    const after =
                        text.substring(
                            index
                            + LABEL.length
                        );

                    const match =
                        after.match(regex);

                    if (match)
                        return match[1];
                }

                return null;
            }
            """
            .replace("LABEL", json.dumps(label))
        )

        if value:

            return normalize_value(
                value
            )

    except Exception as error:

        print(
            f"      DOM Value errore: {error}"
        )

    return "0"


# =========================================================
# FIND PERMANENT BUTTON
# =========================================================

def find_permanent_button(page):

    selectors = [
        "button",
        '[role="button"]',
        '[role="tab"]',
        "a"
    ]

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
                    )

                    if text.lower() == "permanent":
                        return element

                except:
                    continue

        except:
            continue

    return None


# =========================================================
# READ CURRENT FRUIT VALUE
# =========================================================

def read_current_fruit_value(
    page,
    label="Regular value"
):

    body_text = clean(
        page.locator(
            "body"
        ).inner_text()
    )

    # Cerca il valore della modalità richiesta
    value = read_fruit_regular_value(
        page,
        body_text,
        label
    )

    if value != "0":
        return value

    # Fallback: cerca elementi "value"
    try:

        value = page.evaluate(
            """
            () => {

                const regex =
                    /([0-9]+(?:\\.[0-9]+)?\\s*[KMBT])/i;

                const clean = (s) =>
                    (s || "")
                    .replace(/\\s+/g, " ")
                    .trim();

                const elements =
                    [...document.querySelectorAll("*")];

                for (const el of elements) {

                    if (el.children.length > 2)
                        continue;

                    const text =
                        clean(el.textContent);

                    if (
                        text.toLowerCase()
                        !== "value"
                    )
                        continue;

                    let sibling =
                        el.nextElementSibling;

                    while (sibling) {

                        const siblingText =
                            clean(
                                sibling.textContent
                            );

                        const match =
                            siblingText.match(
                                regex
                            );

                        if (match)
                            return match[1];

                        sibling =
                            sibling.nextElementSibling;
                    }
                }

                return null;
            }
            """
        )

        if value:

            return normalize_value(
                value
            )

    except:
        pass

    return "0"


# =========================================================
# CLICK PERMANENT
# =========================================================

def click_permanent(
    page,
    button
):

    if button is None:
        return False

    try:

        button.scroll_into_view_if_needed(
            timeout=5000
        )

        button.click(
            timeout=5000
        )

        page.wait_for_timeout(
            1200
        )

        return True

    except:

        pass

    # Force click
    try:

        button.click(
            force=True,
            timeout=5000
        )

        page.wait_for_timeout(
            1200
        )

        return True

    except:

        pass

    # JS click
    try:

        button.evaluate(
            "(el) => el.click()"
        )

        page.wait_for_timeout(
            1200
        )

        return True

    except:

        return False


def wait_for_fruit_mode(
    page,
    label,
    timeout=5000
):

    deadline = time.time() + (timeout / 1000)

    while time.time() < deadline:

        try:

            text = clean(
                page.locator(
                    "body"
                ).inner_text()
            )

            if re.search(
                rf"\b{re.escape(label)}\b",
                text,
                re.IGNORECASE
            ):
                return True

        except:
            pass

        page.wait_for_timeout(150)

    return False


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

    body_text = clean(
        page.locator(
            "body"
        ).inner_text()
    )

    rarity = get_rarity(
        body_text
    )

    demand = get_demand(
        body_text
    )

    trend = get_trend(
        body_text
    )

    # -----------------------------------------------------
    # REGULAR
    # -----------------------------------------------------

    print(
        "      Lettura Regular..."
    )

    normal = read_fruit_regular_value(
        page,
        body_text
    )

    if normal == "0":

        normal = read_current_fruit_value(
            page
        )

    print(
        f"      Regular: {normal}"
    )

    # -----------------------------------------------------
    # PERMANENT
    # -----------------------------------------------------

    permanent = normal

    permanent_button = find_permanent_button(
        page
    )

    if permanent_button:

        print(
            "      Lettura Permanent..."
        )

        success = click_permanent(
            page,
            permanent_button
        )

        if success:

            # Sul nuovo sito il click deve cambiare anche
            # l'etichetta mostrata da "Regular value" a
            # "Permanent value". Aspettiamo questo cambio
            # prima di leggere il numero, altrimenti il parser
            # rilegge il valore Regular.
            mode_changed = wait_for_fruit_mode(
                page,
                "Permanent value",
                timeout=5000
            )

            permanent_text = clean(
                page.locator(
                    "body"
                ).inner_text()
            )

            if mode_changed:

                permanent = read_fruit_regular_value(
                    page,
                    permanent_text,
                    "Permanent value"
                )

            else:

                print(
                    "      Permanent value non comparso, "
                    "provo la lettura DOM..."
                )

                permanent = read_current_fruit_value(
                    page,
                    "Permanent value"
                )

            if permanent == "0":

                permanent = read_current_fruit_value(
                    page,
                    "Permanent value"
                )

            print(
                f"      Permanent: {permanent}"
            )

        else:

            print(
                "      Click Permanent fallito"
            )

    else:

        print(
            "      Pulsante Permanent non trovato"
        )

    # -----------------------------------------------------
    # Se il Permanent resta 0, non lo lasciamo a 0
    # -----------------------------------------------------

    if permanent == "0":

        permanent = normal

    return {

        "name":
            name,

        "rarity":
            rarity,

        "value_normal":
            normal,

        "value_permanent":
            permanent,

        "demand":
            demand,

        "trend":
            trend
    }


# =========================================================
# SCRAPE LIMITED / GAMEPASS
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

    text = clean(
        page.locator(
            "body"
        ).inner_text()
    )

    # Nuovo sito:
    # "Value 6.97B"
    value = extract_value_from_line(
        text,
        "Value"
    )

    if value == "0":

        value = extract_first_value(
            text
        )

    demand = get_demand(
        text
    )

    trend = get_trend(
        text
    )

    return {

        "name":
            name,

        "value":
            value,

        "demand":
            demand,

        "trend":
            trend
    }


# =========================================================
# DEBUG
# =========================================================

def save_debug(
    page,
    name,
    url,
    error
):

    if not DEBUG_DUMP_ON_ERROR:
        return

    try:

        os.makedirs(
            DEBUG_DIR,
            exist_ok=True
        )

        safe_name = re.sub(
            r"[^a-zA-Z0-9_-]+",
            "_",
            name
        )

        html_path = os.path.join(
            DEBUG_DIR,
            f"{safe_name}.html"
        )

        png_path = os.path.join(
            DEBUG_DIR,
            f"{safe_name}.png"
        )

        txt_path = os.path.join(
            DEBUG_DIR,
            f"{safe_name}.txt"
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

        with open(
            txt_path,
            "w",
            encoding="utf-8"
        ) as f:

            f.write(
                f"URL: {url}\n"
            )

            f.write(
                f"ERROR: {error}\n"
            )

        print(
            f"      [DEBUG] "
            f"Salvati dump per {name}"
        )

    except Exception as debug_error:

        print(
            f"      [DEBUG] "
            f"Errore dump: {debug_error}"
        )


# =========================================================
# SCRAPE CATEGORY
# =========================================================

def scrape_category(
    page,
    category
):

    links = collect_item_links(
        page,
        category
    )

    total = len(
        links
    )

    results = []

    failed = []

    print()
    print("=" * 70)
    print(
        f"SCRAPING {category.upper()}: "
        f"{total}"
    )
    print("=" * 70)

    for index, (
        url,
        fallback_name
    ) in enumerate(
        links.items(),
        start=1
    ):

        print()
        print(
            f"[{index}/{total}] "
            f"{fallback_name}"
        )

        success = False
        last_error = None

        for attempt in range(
            1,
            MAX_ITEM_RETRIES + 1
        ):

            try:

                if category == "fruits":

                    item = scrape_fruit(
                        page,
                        url,
                        fallback_name
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
                        fallback_name
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

                last_error = error

                print(
                    f"      ERRORE "
                    f"{attempt}/{MAX_ITEM_RETRIES}: "
                    f"{error}"
                )

                time.sleep(2)

        if not success:

            print(
                f"      FALLITO: "
                f"{fallback_name}"
            )

            failed.append({
                "name":
                    fallback_name,

                "url":
                    url,

                "error":
                    str(last_error)
            })

            save_debug(
                page,
                fallback_name,
                url,
                last_error
            )

        time.sleep(
            0.15
        )

    print()
    print(
        f"{category.upper()} COMPLETATO"
    )

    print(
        f"Riusciti: {len(results)}"
    )

    print(
        f"Falliti: {len(failed)}"
    )

    return results, failed


# =========================================================
# VALIDATION
# =========================================================

def validate_results(
    fruits,
    limited,
    gamepasses
):

    print()
    print("=" * 70)
    print(
        "VALIDAZIONE"
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

    # Il sito attualmente mostra 42 fruits,
    # 9 gamepasses e 35 limiteds nella lista.
    #
    # Non imponiamo numeri esatti perché il sito
    # potrebbe aggiungere/rimuovere item.
    #
    # Ma se una categoria dovrebbe avere elementi
    # e restituisce ZERO, blocchiamo l'upload.

    if len(fruits) == 0:

        print(
            "ERRORE: nessun fruit trovato"
        )

        return False

    if len(gamepasses) == 0:

        print(
            "ERRORE: nessun gamepass trovato"
        )

        return False

    if len(limited) == 0:

        print(
            "ERRORE: nessun limited trovato"
        )

        return False

    return True


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
            "ERRORE LETTURA GITHUB"
        )

        print(
            response.status_code
        )

        print(
            response.text
        )

        response.raise_for_status()

    return response.json()


def upload_to_github(data):

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
        content.encode(
            "utf-8"
        )
    ).decode(
        "utf-8"
    )

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
# RUN SCRAPER
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

        # -------------------------------------------------
        # FRUITS
        # -------------------------------------------------

        fruits, fruit_failed = scrape_category(
            page,
            "fruits"
        )

        # -------------------------------------------------
        # GAMEPASSES
        # -------------------------------------------------

        gamepasses, gamepass_failed = scrape_category(
            page,
            "gamepasses"
        )

        # -------------------------------------------------
        # LIMITEDS
        # -------------------------------------------------

        limited, limited_failed = scrape_category(
            page,
            "limiteds"
        )

        browser.close()

    return (
        fruits,
        limited,
        gamepasses,
        fruit_failed,
        limited_failed,
        gamepass_failed
    )


# =========================================================
# MAIN
# =========================================================

def main():

    print()
    print("=" * 70)
    print(
        " BLOXFRUITS VALUES UPDATER"
    )
    print(
        " NEW COSMIC VALUES SCRAPER"
    )
    print("=" * 70)

    try:

        (
            fruits,
            limited,
            gamepasses,
            fruit_failed,
            limited_failed,
            gamepass_failed
        ) = run_scraper()

    except Exception as error:

        print()
        print("=" * 70)
        print(
            "SCRAPING FALLITO COMPLETAMENTE"
        )
        print("=" * 70)

        print(
            error
        )

        raise SystemExit(1)

    # -----------------------------------------------------
    # VALIDATION
    # -----------------------------------------------------

    if not validate_results(
        fruits,
        limited,
        gamepasses
    ):

        print()
        print(
            "I DATI NON SONO STATI CARICATI SU GITHUB."
        )

        raise SystemExit(1)

    # -----------------------------------------------------
    # WARNING FALLITI
    # -----------------------------------------------------

    total_failed = (
        len(fruit_failed)
        + len(limited_failed)
        + len(gamepass_failed)
    )

    if total_failed:

        print()
        print("=" * 70)
        print(
            f"ATTENZIONE: "
            f"{total_failed} ITEM NON LETTI"
        )
        print("=" * 70)

    # -----------------------------------------------------
    # JSON
    # -----------------------------------------------------

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

    # -----------------------------------------------------
    # LOCAL SAVE
    # -----------------------------------------------------

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
        "VALUE.JSON SALVATO"
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

    # -----------------------------------------------------
    # GITHUB
    # -----------------------------------------------------

    if not upload_to_github(
        data
    ):

        print(
            "GitHub NON aggiornato."
        )

        raise SystemExit(1)

    print()
    print("=" * 70)
    print(
        " OPERAZIONE COMPLETATA"
    )
    print("=" * 70)


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":
    main()
