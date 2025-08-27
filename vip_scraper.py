"""
VIP Volunteer Scraper - Extract Volunteer Names, Roles, and Program into CSV
"""

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.keys import Keys
from webdriver_manager.chrome import ChromeDriverManager
import time
import csv
from flask import Flask, jsonify


def setup_browser():
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")   # ✅ important for Render
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("--start-maximized")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    return driver


def manual_login_phase(driver):
    print("=== MANUAL LOGIN PHASE ===")
    driver.get("https://vip.fca.org")
    print("Please log in manually...")

    wait = WebDriverWait(driver, 300)  # give up to 5 minutes to log in
    wait.until(EC.url_contains("/admin/dashboard"))  # wait for dashboard URL

    print("✅ Login detected, continuing in 3 seconds...")
    time.sleep(3)  # small buffer for page to fully load
    return True


def navigate_to_programs(driver):
    wait = WebDriverWait(driver, 15)
    print("Navigating to Programs...")
    programs_label = wait.until(
        EC.element_to_be_clickable((By.XPATH, "//span[@class='navigation__subnav-label' and normalize-space(text())='Programs']"))
    )
    programs_label.click()
    programs_link = wait.until(
        EC.element_to_be_clickable((By.XPATH, "//a[@href='/admin/event/events' and contains(text(),'Programs')]"))
    )
    programs_link.click()


def search_for_program(driver, program_name):
    wait = WebDriverWait(driver, 15)
    try:
        clear_filters = driver.find_element(By.XPATH, "//a[@class='text-primary-on-white' and contains(text(),'Clear current filters')]")
        if clear_filters.is_displayed():
            clear_filters.click()
            time.sleep(2)
    except:
        pass

    search_box = wait.until(EC.presence_of_element_located((By.XPATH, "//input[@type='text' and @placeholder='Search']")))
    search_box.clear()
    search_box.send_keys(program_name + "\n")
    time.sleep(3)

    program_entry = wait.until(EC.element_to_be_clickable((By.XPATH, f"//*[contains(text(), '{program_name}')]")))
    program_entry.click()


def extract_volunteers_from_roles(driver, program_name):
    wait = WebDriverWait(driver, 15)
    roles = wait.until(EC.presence_of_all_elements_located((By.XPATH, "//tr[contains(@class,'grid-list__row')]")))
    print(f"Found {len(roles)} roles")

    data = []

    for idx in range(len(roles)):
        try:
            # Re-fetch roles each time (DOM refreshes after navigation)
            roles = wait.until(EC.presence_of_all_elements_located((By.XPATH, "//tr[contains(@class,'grid-list__row')]")))
            role = roles[idx]

            role_title_elem = role.find_element(By.XPATH, ".//div[contains(@class,'shift-name')]")
            role_title = role_title_elem.text.strip() if role_title_elem else f"Role {idx+1}"

            print(f"\n➡️ Extracting volunteers for role: {role_title}")
            view_button = role.find_element(By.XPATH, ".//button[@title='View Volunteers']")
            driver.execute_script("arguments[0].scrollIntoView(true);", view_button)
            view_button.click()

            # Wait for volunteer table
            table = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "table[id^='grid-list:table']")))

            # --- Find the column index for "Volunteer Name" ---
            headers = table.find_elements(By.CSS_SELECTOR, "thead th")
            name_col_index = None
            for i, h in enumerate(headers, start=1):
                if "Volunteer Name" in h.text.strip():
                    name_col_index = i
                    break
            if not name_col_index:
                raise Exception("Could not find 'Volunteer Name' column")

            # --- Pagination loop ---
            page_num = 1
            max_pages = 100  # safety net
            while page_num <= max_pages:
                # Retry loop: wait up to 10s for data rows
                rows = []
                end_time = time.time() + 10
                while time.time() < end_time:
                    rows = table.find_elements(By.CSS_SELECTOR, "tbody tr")
                    if rows and "There are no records to show" not in rows[0].text:
                        break
                    time.sleep(1)

                if not rows or "There are no records to show" in rows[0].text:
                    print("⚠️ No volunteers found for this role (after waiting 10s)")
                    break

                # Process rows
                for row in rows:
                    try:
                        name_cell = row.find_element(By.CSS_SELECTOR, f"td:nth-child({name_col_index})")
                        volunteer_name = name_cell.text.strip()
                    except:
                        volunteer_name = "UNKNOWN"

                    data.append({
                        "Program": program_name,
                        "Role": role_title,
                        "Volunteer Name": volunteer_name
                    })
                    print(f"   - {volunteer_name}")

                # Look for Next button
                try:
                    next_btn = driver.find_element(By.XPATH, "//button[contains(., 'Next') and not(@disabled)]")
                    driver.execute_script("arguments[0].click();", next_btn)
                    page_num += 1
                    print(f"➡️ Moving to page {page_num} for {role_title}")

                    WebDriverWait(driver, 10).until(EC.staleness_of(rows[0]))
                    table = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "table[id^='grid-list:table']")))

                except:
                    break

            # ✅ Navigate back to Roles breadcrumb
            roles_link = wait.until(
                EC.element_to_be_clickable((By.XPATH, "//nav[contains(@class,'breadcrumb')]//a[normalize-space()='Roles']"))
            )
            roles_link.click()

            wait.until(EC.presence_of_all_elements_located((By.XPATH, "//tr[contains(@class,'grid-list__row')]")))
            time.sleep(1)

        except Exception as e:
            print(f"⚠️ Error with role {idx+1}: {e}")
            continue

    return data


def save_to_csv(data, filename="volunteers.csv"):
    keys = ["Program", "Role", "Volunteer Name"]
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(data)
    print(f"\n✅ Data saved to {filename}")


def main():
    program_names = [
        "Edgewood High Multi-Sport Huddle (Harford County)",
        "Signing Day 2025- Harford County, MD"
    ]

    driver = setup_browser()
    all_data = []

    try:
        manual_login_phase(driver)
        navigate_to_programs(driver)

        for program_name in program_names:
            print(f"\n===== 📌 Now scraping program: {program_name} =====")
            
            # Search and open program
            search_for_program(driver, program_name)

            # Scrape all roles & volunteers
            data = extract_volunteers_from_roles(driver, program_name)
            all_data.extend(data)

            # ✅ Navigate back to Programs breadcrumb
            wait = WebDriverWait(driver, 15)
            programs_link = wait.until(
                EC.element_to_be_clickable((By.XPATH, "//nav[contains(@class,'breadcrumb')]//a[normalize-space()='Programs']"))
            )
            programs_link.click()

            # Wait for Programs list to reload
            wait.until(EC.presence_of_element_located((By.XPATH, "//input[@type='text' and @placeholder='Search']")))
            time.sleep(1)

        # Save everything into one CSV
        save_to_csv(all_data)

        print("\n🏁 Extraction complete for ALL programs!")

    finally:
        driver.quit()


# ✅ Flask app for Render
app = Flask(__name__)

@app.route("/run", methods=["GET"])
def run_scraper_endpoint():
    try:
        main()
        return jsonify({"status": "success", "message": "Scraper finished"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
