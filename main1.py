from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from webdriver_manager.chrome import ChromeDriverManager
from datetime import datetime, timedelta
import time
import os
import re

# Настройки Selenium
chrome_options = Options()
chrome_options.add_argument("--headless")
chrome_options.add_argument("--disable-gpu")
chrome_options.add_argument("--no-sandbox")
chrome_options.add_argument("--disable-dev-shm-usage")
chrome_options.add_argument("--log-level=3")

# Устанавливаем ChromeDriver
service = Service(ChromeDriverManager().install())
driver = webdriver.Chrome(service=service, options=chrome_options)

# Даты
current_date = datetime.now().strftime("%Y-%m-%d")
next_date = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

# URL матчей
URLS = {
    "football": "https://www.championat.com/stat/football/",
    "football_night": f"https://www.championat.com/stat/football/#{next_date}",
    "hockey": f"https://www.championat.com/stat/hockey/#{current_date}",
    "hockey_night": f"https://www.championat.com/stat/hockey/#{next_date}",
    "tennis": "https://www.championat.com/stat/tennis/",
    "basketball": "https://www.championat.com/stat/basketball/",
    "basketball_night": f"https://www.championat.com/stat/basketball/#{next_date}"
}

SHEET_NAMES = {
    "football": "Лист1",
    "hockey": "Лист2",
    "tennis": "Лист3",
    "basketball": "Лист4"
}

FILE_NAMES = {
    "football": "f1.txt",
    "hockey": "h1.txt",
    "tennis": "t1.txt",
    "basketball": "b1.txt"
}

def parse_team_sport(url, night_games=False):
    print(f"🔄 Загружаем страницу: {url}")
    driver.get(url)
    time.sleep(3)

    try:
        wait = WebDriverWait(driver, 30)
        wait.until(EC.presence_of_element_located((By.CLASS_NAME, "results-item")))
    except:
        print(f"❌ Данные не загрузились с {url}!")
        return []

    # Если это ночные матчи, переключаемся на вкладку "Завтра"
    if night_games:
        try:
            tomorrow_button = driver.find_element(By.XPATH, "//div[@data-option='tomorrow']")
            tomorrow_button.click()
            print("✅ Переключились на вкладку 'Завтра'")

            WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.CLASS_NAME, "mc-tab-data.tomorrow._selected"))
            )
            match_container = driver.find_element(By.CLASS_NAME, "mc-tab-data.tomorrow._selected")
        except Exception as e:
            print(f"⚠️ Не удалось переключиться на 'Завтра': {e}")
            return []
    else:
        match_container = driver.find_element(By.CLASS_NAME, "mc-tab-data._selected")

    matches = []
    match_elements = match_container.find_elements(By.CLASS_NAME, "results-item")

    for match in match_elements:
        try:
            status_element = match.find_element(By.CLASS_NAME, "results-item__status")
            status = status_element.text.strip()

            if status.lower() == "не начался":
                time_element = match.find_element(By.CLASS_NAME, "results-item__title-date").text.strip()
                match_time = datetime.strptime(time_element, "%H:%M")

                teams = match.find_elements(By.CLASS_NAME, "table-item__name")
                if len(teams) >= 2:
                    home_team = teams[0].text.strip()
                    away_team = teams[1].text.strip()

                    if night_games and (0 <= match_time.hour < 11):
                        match_date = next_date
                        print(f"✅ Найден ночной матч: {home_team} - {away_team} в {time_element}")
                        matches.append((f"{home_team} - {away_team}", f"{match_date} {time_element}"))
                    elif not night_games:
                        match_date = current_date
                        print(f"✅ Найден матч: {home_team} - {away_team} в {time_element}")
                        matches.append((f"{home_team} - {away_team}", f"{match_date} {time_element}"))
        except Exception as e:
            print(f"⚠️ Ошибка при обработке матча: {e}")
            continue

    return matches

def parse_tennis():
    print(f"🔄 Загружаем страницу: {URLS['tennis']}")
    driver.get(URLS["tennis"])
    time.sleep(3)

    try:
        wait = WebDriverWait(driver, 30)
        # Страница тенниса рендерится JS-ом: надёжнее ждать сами матчи.
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".tennis-results.js-match-item")))
    except:
        print("❌ Данные по теннису не загрузились!")
        return []

    time_re = re.compile(r"\b(\d{1,2}):(\d{2})\b")

    def _norm_text(s) -> str:
        return " ".join(s.split()) if s else ""

    def _safe_text(el) -> str:
        """
        Selenium `.text` возвращает только «видимый» текст и на Championat
        иногда бывает пустым из-за оптимизаций рендера. `textContent` стабильнее.
        """
        try:
            tc = el.get_attribute("textContent")
        except Exception:
            tc = None
        tc = _norm_text(tc)
        if tc:
            return tc
        try:
            return _norm_text(el.text)
        except Exception:
            return ""

    def _extract_time(match_el) -> str:
        # Актуальная разметка: время лежит в `.tennis-results__item._time`.
        for sel in (".tennis-results__item._time", ".tennis-results__time", ".results-item__title-date"):
            try:
                txt = _safe_text(match_el.find_element(By.CSS_SELECTOR, sel))
            except Exception:
                continue
            m = time_re.search(txt)
            if m:
                return f"{int(m.group(1)):02d}:{m.group(2)}"

        # Редкий фолбэк — если время попало в статус/примечание.
        try:
            txt = _safe_text(match_el.find_element(By.CSS_SELECTOR, ".tennis-results__status"))
            m = time_re.search(txt)
            if m:
                return f"{int(m.group(1)):02d}:{m.group(2)}"
        except Exception:
            pass

        return "00:00"

    def _extract_player_name(player_el) -> str:
        first = ""
        surname = ""

        for sel in (
            ".tennis-results__player-name._complete",
            ".tennis-results__player-name._initial",
            ".tennis-results__player-name",
        ):
            try:
                first = _safe_text(player_el.find_element(By.CSS_SELECTOR, sel))
            except Exception:
                first = ""
            if first:
                break

        try:
            surname = _safe_text(player_el.find_element(By.CSS_SELECTOR, ".tennis-results__player-surname"))
        except Exception:
            surname = ""

        full = " ".join([p for p in (first, surname) if p]).strip()
        if full:
            return full

        # Последний фолбэк: берём заголовок игрока целиком.
        try:
            return _safe_text(player_el.find_element(By.CSS_SELECTOR, ".tennis-results__player-title"))
        except Exception:
            return ""

    def _extract_team(team_el) -> str:
        # В одиночке: 1 игрок; в паре: 2 игрока.
        players = team_el.find_elements(By.CSS_SELECTOR, ".tennis-results__player")
        names = []
        for p in players:
            name = _extract_player_name(p)
            if name:
                names.append(name)
        if names:
            return " / ".join(names)

        # Фолбэк для редких раскладок (командные соревнования и т.п.)
        return _safe_text(team_el)

    matches = []
    match_elements = driver.find_elements(By.CSS_SELECTOR, ".tennis-results.js-match-item")

    for match in match_elements:
        try:
            status = _safe_text(match.find_element(By.CSS_SELECTOR, ".tennis-results__status")).strip()
            if status.lower() != "не начался":
                continue

            teams = match.find_elements(By.CSS_SELECTOR, ".tennis-results__team")
            if len(teams) < 2:
                continue

            team1 = _extract_team(teams[0])
            team2 = _extract_team(teams[1])
            if not team1 or not team2:
                continue

            match_time = _extract_time(match)
            matches.append((f"{team1} - {team2}", f"{current_date} {match_time}"))
        except Exception as e:
            print(f"⚠️ Ошибка парсинга теннисного матча: {e}")
            continue

    return matches

def save_matches_to_file(sport, matches):
    file_name = FILE_NAMES[sport]
    with open(file_name, "w", encoding="utf-8") as file:
        for match in matches:
            try:
                teams, match_dt = match
                file.write(f"{teams} | {match_dt}\n")
            except:
                file.write(str(match) + "\n")
    print(f"📂 Матчи сохранены в {file_name}")

def update_google_sheets(all_sports):
    # `worksheet.format()` (цвета/оформление) использует Sheets API,
    # поэтому добавляем актуальный scope для таблиц.
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
    client = gspread.authorize(creds)

    sheet = client.open("pars")

    # Код спорта + форматирование отдельной колонки с обозначением.
    # Цвета в формате Sheets API: 0..1
    sport_meta = {
        "football": {
            "code": "f",
            "format": {
                "backgroundColor": {"red": 0.2039, "green": 0.6588, "blue": 0.3255},  # #34A853
                "horizontalAlignment": "CENTER",
                "verticalAlignment": "MIDDLE",
                "textFormat": {
                    "bold": True,
                    "foregroundColor": {"red": 1, "green": 1, "blue": 1},
                },
            },
        },
        "hockey": {
            "code": "h",
            "format": {
                "backgroundColor": {"red": 0.2588, "green": 0.5216, "blue": 0.9569},  # #4285F4
                "horizontalAlignment": "CENTER",
                "verticalAlignment": "MIDDLE",
                "textFormat": {
                    "bold": True,
                    "foregroundColor": {"red": 1, "green": 1, "blue": 1},
                },
            },
        },
        "tennis": {
            "code": "t",
            "format": {
                "backgroundColor": {"red": 1, "green": 0.5961, "blue": 0},  # #FF9800
                "horizontalAlignment": "CENTER",
                "verticalAlignment": "MIDDLE",
                "textFormat": {
                    "bold": True,
                    "foregroundColor": {"red": 1, "green": 1, "blue": 1},
                },
            },
        },
    }

    # 1) Очистка листов + заголовки
    for base_sport, sheet_name in SHEET_NAMES.items():
        worksheet = sheet.worksheet(sheet_name)
        worksheet.clear()
        # Сбрасываем старые заливки/форматы, т.к. `clear()` чистит только значения.
        try:
            if base_sport in sport_meta:
                worksheet.format(
                    "A:C",
                    {
                        "backgroundColor": {"red": 1, "green": 1, "blue": 1},
                        "horizontalAlignment": "LEFT",
                        "verticalAlignment": "MIDDLE",
                        "textFormat": {
                            "bold": False,
                            "foregroundColor": {"red": 0, "green": 0, "blue": 0},
                        },
                    },
                )
            else:
                worksheet.format(
                    "A:B",
                    {
                        "backgroundColor": {"red": 1, "green": 1, "blue": 1},
                        "horizontalAlignment": "LEFT",
                        "verticalAlignment": "MIDDLE",
                        "textFormat": {
                            "bold": False,
                            "foregroundColor": {"red": 0, "green": 0, "blue": 0},
                        },
                    },
                )
        except Exception:
            # Если форматирование не доступно — просто пропускаем сброс.
            pass

        if base_sport in sport_meta:
            # Важно: A1 не должна быть пустой, иначе при append_rows Google Sheets
            # может считать таблицу начинающейся с B1 и все значения сдвинутся вправо.
            worksheet.append_row(["Код", "Матч", "Дата и время"])
        else:
            worksheet.append_row(["Матч", "Дата и время"])
        print(f"✅ Очистили лист {sheet_name} перед парсингом.")

    # 2) Склеиваем дневные + ночные матчи по базовому виду спорта,
    # чтобы аппендить одним батчем и удобно форматировать диапазон.
    combined = {k: [] for k in SHEET_NAMES.keys()}
    for sport_key, matches in all_sports.items():
        base = sport_key.replace("_night", "")
        if base not in combined:
            combined[base] = []
        if matches:
            combined[base].extend(matches)

    # 3) Запись + форматирование
    for base_sport, matches in combined.items():
        sheet_name = SHEET_NAMES.get(base_sport)
        if not sheet_name:
            continue

        worksheet = sheet.worksheet(sheet_name)
        if not matches:
            continue

        if base_sport in sport_meta:
            code = sport_meta[base_sport]["code"]
            worksheet.append_rows([[code, teams, match_dt] for teams, match_dt in matches])

            # Форматируем только заполненные строки в колонке с кодом.
            start_row = 2
            end_row = start_row + len(matches) - 1
            code_range = f"A{start_row}:A{end_row}"
            fmt = sport_meta[base_sport]["format"]

            try:
                worksheet.format(code_range, fmt)
            except Exception as e:
                # Если форматирование не доступно/не хватает прав — не падаем,
                # но оставляем буквы-коды в отдельной колонке.
                print(f"⚠️ Не удалось применить форматирование для {base_sport} ({sheet_name}): {e}")

            print(f"✅ Обновлено {len(matches)} матчей {base_sport} в Google Sheets ({sheet_name})!")
        else:
            worksheet.append_rows([[teams, match_dt] for teams, match_dt in matches])
            print(f"✅ Обновлено {len(matches)} матчей {base_sport} в Google Sheets ({sheet_name})!")

if __name__ == "__main__":
    all_sports = {
        "football": parse_team_sport(URLS["football"]),
        "football_night": parse_team_sport(URLS["football_night"], night_games=True),
        "hockey": parse_team_sport(URLS["hockey"]),
        "hockey_night": parse_team_sport(URLS["hockey_night"], night_games=True),
        "tennis": parse_tennis(),
        "basketball": parse_team_sport(URLS["basketball"]),
        "basketball_night": parse_team_sport(URLS["basketball_night"], night_games=True)
    }

    driver.quit()
    update_google_sheets(all_sports)

    for sport in FILE_NAMES.keys():
        matches = all_sports[sport] + all_sports.get(f"{sport}_night", [])
        save_matches_to_file(sport, matches)
