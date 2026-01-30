import subprocess
import time
import os
from dotenv import load_dotenv
from uniwersal import start_script
from logger import setup_logging, get_logger

load_dotenv()

INTERFACE = os.getenv('INTERFACE')
AP_PASSWORD = os.getenv('AP_PASSWORD')
AP_CONNECTION_NAME = os.getenv('AP_CONNECTION_NAME')
WAIT_TIME = int(os.getenv('WAIT_TIME'))
MAX_RETRIES = int(os.getenv('MAX_RETRIES'))
POSTMAN_SCRIPT = os.getenv('POSTMAN_SCRIPT')
WORKER_SCRIPT = os.getenv('WORKER_SCRIPT')
REMOTE_SERVER_URL = os.getenv('REMOTE_SERVER_URL')
DEVICE_UID = os.getenv('DEVICE_UID')
WORKER_ENV_PATH = os.getenv('WORKER_ENV_PATH')

setup_logging()
logger = get_logger("gate_watcher")
logger.info("gate_watcher")


def run_command(command, check=True):
    try:
        result = subprocess.run(
            command,
            shell=True,
            check=check,
            capture_output=True,
            text=True,
            timeout=30
        )
        return result.returncode == 0, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        logger.error(f"Timeout podczas wykonywania: {command}")
        return False, "", "Timeout"
    except Exception as e:
        logger.error(f"Błąd podczas wykonywania {command}: {e}")
        return False, "", str(e)


def check_networkmanager():
    success, output, _ = run_command("systemctl is-active NetworkManager", check=False)
    if success and "active" in output:
        logger.info("NetworkManager jest aktywny")
        return True
    logger.error("NetworkManager nie jest aktywny!")
    return False


def is_connected_to_wifi():
    """check if Raspberry Pi is conected to wifi"""
    success, output, _ = run_command(
        f"nmcli -t -f DEVICE,STATE,CONNECTION device | grep '^{INTERFACE}:'",
        check=False
    )
    if success and output.strip():
        parts = output.strip().split(':')
        if len(parts) >= 3:
            state = parts[1]
            connection = parts[2]
            
            if state == "connected" and connection != AP_CONNECTION_NAME:
                logger.info(f"Połączono z siecią: {connection}")
                return True
    
    logger.info("Brak połączenia z zapisaną siecią WiFi")
    return False


def get_saved_connections():
    success, output, _ = run_command(
        "nmcli -t -f NAME,TYPE connection show",
        check=False
    )
    
    if success:
        connections = []
        for line in output.strip().split('\n'):
            if line:
                parts = line.split(':')
                if len(parts) >= 2:
                    name, conn_type = parts[0], parts[1]
                    if conn_type == "802-11-wireless" and name != AP_CONNECTION_NAME:
                        connections.append(name)
        return connections
    return []


def hotspot_exists():
    """check if hotspot was set in past"""
    success, output, _ = run_command(
        f"nmcli connection show '{AP_CONNECTION_NAME}'",
        check=False
    )
    return success


def delete_hotspot():
    logger.info("Usuwam stary profil hotspota...")
    success, output, error = run_command(
        f"nmcli connection delete '{AP_CONNECTION_NAME}'",
        check=False
    )
    if success:
        logger.info("Stary profil hotspota usunięty")
    return success


def create_hotspot():
    logger.info("Tworzę profil hotspota...")
    
    # if hotspot exists, then remove it first
    if hotspot_exists():
        logger.info("Profil hotspota już istnieje - usuwam stary...")
        delete_hotspot()
        time.sleep(1)
    
    success, output, error = run_command(
        f"nmcli connection add type wifi ifname {INTERFACE} "
        f"con-name '{AP_CONNECTION_NAME}' autoconnect no ssid '{AP_CONNECTION_NAME}' "
        f"wifi-sec.key-mgmt wpa-psk "
        f"wifi-sec.psk '{AP_PASSWORD}' "
        f"802-11-wireless.mode ap "
        f"802-11-wireless.band bg "
        f"ipv4.method shared "
        f"ipv6.method disabled"
    )
    
    if success:
        logger.info("Profil hotspota utworzony pomyślnie")
        
        success_verify, output_verify, _ = run_command(
            f"nmcli -s -g 802-11-wireless-security.psk connection show '{AP_CONNECTION_NAME}'",
            check=False
        )
        if success_verify and output_verify.strip():
            logger.info(f"Hasło hotspota zweryfikowane: {'*' * len(AP_PASSWORD)}")
        else:
            logger.warning("Nie można zweryfikować hasła hotspota!")
        
        return True
    else:
        logger.error(f"Nie można utworzyć profilu hotspota: {error}")
        logger.error(f"Output: {output}")
        return False


def enable_access_point():
    """Włącza tryb Access Point przez NetworkManager"""
    logger.info("Włączam tryb Access Point...")
    
    if not hotspot_exists():
        if not create_hotspot():
            return False
    else:
        success, output, _ = run_command(
            f"nmcli -s -g 802-11-wireless-security.psk connection show '{AP_CONNECTION_NAME}'",
            check=False
        )
        if not success or not output.strip():
            logger.warning("Istniejący profil nie ma hasła - tworzę nowy...")
            delete_hotspot()
            time.sleep(1)
            if not create_hotspot():
                return False
    
    # turnn off active connections in that interface
    success, output, _ = run_command(
        f"nmcli device disconnect {INTERFACE}",
        check=False
    )
    time.sleep(2)
    
    success, output, error = run_command(
        f"nmcli connection up '{AP_CONNECTION_NAME}'",
        check=False
    )
    
    if success:
        logger.info(f"Access Point aktywny: SSID='{AP_CONNECTION_NAME}'")
        logger.info(f"Hasło: {AP_PASSWORD}")
        
        # # check connection status
        # time.sleep(2)
        # success_status, output_status, _ = run_command(
        #     f"nmcli connection show '{AP_CONNECTION_NAME}' | grep -E '(802-11-wireless-security|state)'",
        #     check=False
        # )
        # if success_status:
        #     logger.info(f"Status połączenia:\n{output_status}")
        
        return True
    else:
        logger.error(f"Nie można włączyć hotspota: {error}")
        logger.error(f"Output: {output}")
        return False


def disable_access_point():
    logger.info("Wyłączam tryb Access Point...")
    
    # check if hotspot is active
    success, output, _ = run_command(
        f"nmcli -t -f NAME,DEVICE connection show --active | grep '^{AP_CONNECTION_NAME}:'",
        check=False
    )
    
    if success:
        run_command(f"nmcli connection down '{AP_CONNECTION_NAME}'", check=False)
        logger.info("Tryb Access Point wyłączony")
    
    return True



def main():
    logger.info("start gate watcher")
    logger.info("Uruchamiam WiFi Manager (NetworkManager)")
    
    network_manager_status = False
    for attempt in range(10):
        network_manager_status = check_networkmanager()
        if network_manager_status:
            break
        logger.error(f"Czekam na NetworkManager... (próba {attempt + 1}/10)")
        time.sleep(5)

    if not network_manager_status:
        logger.error("NetworkManager nie jest dostępny")
        return 1
    
    logger.info(f"Czekam {WAIT_TIME} sekund na inicjalizację systemu...")
    time.sleep(WAIT_TIME)
    
    connected = False
    for attempt in range(1, MAX_RETRIES + 1):
        logger.error(f"Próba {attempt}/{MAX_RETRIES} sprawdzenia połączenia...")
        
        if is_connected_to_wifi():
            connected = True
            logger.info("Wykryto aktywne połączenie WiFi")
            break
        else:
            logger.error(f"System sam nie aktywował połączenia, próba: {attempt}/{MAX_RETRIES} czekam {attempt * WAIT_TIME}s")
            time.sleep(WAIT_TIME)

    if connected:
        logger.info("Pozostaję w trybie klienta WiFi")
        disable_access_point()

        status_worker = start_script(WORKER_SCRIPT, logger, WORKER_ENV_PATH)
        if status_worker:
            logger.info(f"Załączono wokera: {WORKER_SCRIPT}")
        else:
            logger.error(f"NIE załączono wokera: {WORKER_SCRIPT}")
            return 1
    else:
        logger.warning("Brak połączenia - przełączam na tryb Access Point")
        if enable_access_point():
            logger.info("Tryb Access Point aktywny")
            logger.info(f"SSID: {AP_CONNECTION_NAME}")
            logger.info(f"Hasło: {AP_PASSWORD}")
            
            status_flask = start_script(POSTMAN_SCRIPT, logger)
            
            if status_flask:
                logger.error(f"Załączono serwer Flask: {POSTMAN_SCRIPT}")
            else:
                logger.error(f"NIE załączono serwera Flask: {POSTMAN_SCRIPT}")
                return 1
        else:
            logger.error("Nie udało się włączyć trybu Access Point")
            return 0

    while True:
        logger.info("gate_watcher")
        time.sleep(60)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Przerwano przez użytkownika")
    except Exception as e:
        logger.error(f"Nieoczekiwany błąd: {str(e)}", exc_info=True)
