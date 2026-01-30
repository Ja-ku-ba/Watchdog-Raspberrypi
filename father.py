#!/usr/bin/env python3
"""
Skrypt monitorujący połączenie WiFi.
Jeśli brak połączenia - uruchamia inny cron i usypia się.
"""

import subprocess
import sys
import os
from dotenv import load_dotenv
import time
from uniwersal import start_script
from logger import setup_logging, get_logger


load_dotenv()

CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", 10))
GATE_WATCHER_SCRIPT = os.getenv("GATE_WATCHER_SCRIPT")
WORKER_SCRIPT = os.getenv("WORKER_SCRIPT")

setup_logging()
logger = get_logger("father")
logger.info("")
logger.info("")
logger.info("")
logger.info("")
logger.info("")
logger.info("")
logger.info("father === start")


def check_wifi_connection():
    """check connection by google ping"""
    try:
        result = subprocess.run(
            ["ping", "-c", "1", "-W", "2", "8.8.8.8"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=3
        )
        return result.returncode == 0
    except subprocess.SubprocessError as e:
        logger.error(f"Ping failed: {e}")
        return False
    except Exception as e:
        logger.error(f"Nieoczekiwany błąd przy sprawdzaniu WiFi: {e}")
        return False


def main():
    logger.info("=====================")
    logger.info("=== Start fathera ===")

    try:
        wifi_ok = check_wifi_connection()
        logger.info(f"wifi_ok: {wifi_ok}")

        if wifi_ok:
            logger.info("Połączenie WiFi: OK - uruchamiam skrypt online i kończę")
            script_wifi_ok = start_script(WORKER_SCRIPT, logger)
            if not script_wifi_ok:
                logger.error("Nie udało się uruchomić skryptu online")
        else:
            logger.info("Brak połączenia WiFi - uruchamiam skrypt offline i kończę")
            script_wifi_not_ok = start_script(GATE_WATCHER_SCRIPT, logger)
            if not script_wifi_not_ok:
                logger.error("Nie udało się uruchomić skryptu offline")

    except Exception as e:
        logger.error(f"Błąd KRYTYCZNY: {e}")
    logger.error(f"kończę")

    while True:
        logger.info("father")
        time.sleep(60)


if __name__ == "__main__":
    main()