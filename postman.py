import os
import subprocess
import requests
import time
from flask import Flask, jsonify, request
from dotenv import load_dotenv
from urllib.parse import urlparse

from uniwersal import start_script

app = Flask(__name__)
load_dotenv()

REMOTE_SERVER_URL = os.getenv('REMOTE_SERVER_URL')
DEVICE_UID = os.getenv('DEVICE_UID')
WORKER_SCRIPT = os.getenv('WORKER_SCRIPT')
WORKER_ENV_PATH = os.getenv('WORKER_ENV_PATH')
AP_CONNECTION_NAME = os.getenv('AP_CONNECTION_NAME')

from logger import setup_logging, get_logger
setup_logging()
logger = get_logger("postman")


def scan_networks():
    """Skanuje dostępne sieci WiFi"""
    try:
        result = subprocess.run(
            ['nmcli', '-t', '-f', 'SSID,SIGNAL,SECURITY', 'dev', 'wifi', 'list'],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        networks = []
        for line in result.stdout.strip().split('\n'):
            if line:
                parts = line.split(':')
                if len(parts) >= 3 and parts[0]:
                    networks.append({
                        'ssid': parts[0],
                        'signal': parts[1],
                        'security': parts[2]
                    })
        
        unique_networks = {}
        for net in networks:
            if net['ssid'] not in unique_networks:
                unique_networks[net['ssid']] = net
        
        return list(unique_networks.values())
    
    except subprocess.TimeoutExpired:
        return []
    except Exception as e:
        logger.error(f"postman --- Błąd skanowania: {e}")
        return []

def connect_to_wifi(ssid, password=None):
    """Łączy się z siecią WiFi"""
    try:
        subprocess.run(
            ['nmcli', 'connection', 'delete', ssid],
            capture_output=True,
            timeout=5
        )
        subprocess.run(
            ['nmcli', 'device', 'wifi', 'rescan'],
            capture_output=True,
            timeout=5
        )
        available_networks = subprocess.run(
            ['nmcli', 'device', 'wifi', 'list'],
            capture_output=True,
            timeout=5
        )
        time.sleep(5)
        logger.info(f"Dostępne sieci: {available_networks}")
        if password:
            cmd = ['nmcli', 'dev', 'wifi', 'connect', ssid, 'password', password]
        else:
            cmd = ['nmcli', 'dev', 'wifi', 'connect', ssid]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30
        )

        logger.info(f"Wynik połączenia: {result}")
        logger.info(f"Wynik połączenia: {result.returncode}")
        return result.returncode == 0
    
    except Exception as e:
        logger.error(f"logger --- Błąd połączenia: {e}", flush=True)
        return False

def check_internet():
    """Sprawdza dostęp do internetu"""
    try:
        result = subprocess.run(
            ['ping', '-c', '1', '-W', '3', '8.8.8.8'],
            capture_output=True,
            timeout=5
        )
        logger.info(f'status sprawdzenie połączenia: {result}')
        return result.returncode == 0
    except:
        return False

def enable_worker_cron():
    """Zarządza cronami w zależności od dostępu do internetu"""
    try:
        status_worker = start_script(WORKER_SCRIPT, logger, WORKER_ENV_PATH)
        if status_worker:
            logger.info(f"Załączono wokera: {WORKER_SCRIPT}")
        else:
            logger.error(f"NIE załączono wokera: {WORKER_SCRIPT}")
        return True
    except Exception as e:
        logger.error(f"postman --- Błąd zarządzania cronami: {e}", flush=True)
        return False

def triger_self_reconect():
    subprocess.run(
        ['nmcli', 'connection', 'up', str(AP_CONNECTION_NAME)],
        capture_output=True,
        text=True,
        timeout=5
    )

@app.route('/api/networks', methods=['GET'])
def get_networks():
    networks = scan_networks()
    return jsonify({
        'success': True,
        'count': len(networks),
        'networks': networks
    })

@app.route('/api/connect', methods=['POST'])
def connect_network():
    data = request.get_json()
    logger.info(data)
    try:
        ssid = data['ssid']
        password = data.get('password')
        device_name = data['device_name']
        email = data['email']
    except:
        return jsonify({
            'success': False,
            'error': 'Brak SSID w żądaniu'
        }), 400

    connected = connect_to_wifi(ssid, password)
    
    if not connected:
        triger_self_reconect()
        return jsonify({
            'success': False,
            'error': 'Nie udało się połączyć z siecią'
        }), 500

    # wait to stabilise connection
    time.sleep(10)
    
    has_internet = check_internet()

    try:
        if has_internet:
            # Send request to server with information abut activation
            url = f'{REMOTE_SERVER_URL}device/register-device/'
            parsed_url = urlparse(url)
            host_header = parsed_url.netloc
            logger.info(f'Url: {url}, uid: {DEVICE_UID}')
            request_to_authenticate_device = requests.post(
                url,
                headers={
                    'X-Device-UID': DEVICE_UID,
                    'Host': host_header,
                },
                json={
                    "email": email,
                    "device_name": device_name
                }
            )
            request_to_authenticate_device.raise_for_status()
            logger.info("odpowiedź z serwera: {request_to_authenticate_device.status_code}")
            logger.info(f"Status internetu: {has_internet}")

            enable_worker_cron()
        else:
            raise Exception("No internet connection")
    except Exception as e:
        logger.error(f'Treść błędu połączenia: {str(e)}')

        result = subprocess.run(
                ['nmcli', 'connection', 'delete', str(ssid)],
            capture_output=True,
            text=True,
            timeout=5
        )
        logger.info(f'Treść ,,zapomnienia" sieci: {result}')

        triger_self_reconect()
        logger.info(f'Status połączenia z AP: {result}')

    return jsonify({
        'success': True,
        'ssid': ssid,
        'connected': True,
        'has_internet': has_internet,
    })


# @app.route('/api/status', methods=['GET'])
# def get_status():
#     has_internet = check_internet()
    
#     try:
#         result = subprocess.run(
#             ['nmcli', '-t', '-f', 'NAME', 'connection', 'show', '--active'],
#             capture_output=True,
#             text=True,
#             timeout=5
#         )
#         current_ssid = result.stdout.strip().split('\n')[0] if result.stdout else None
#     except:
#         current_ssid = None
    
#     return jsonify({
#         'connected_ssid': current_ssid,
#         'has_internet': has_internet
#     })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
    while True:
        logger.info('postman')
        time.sleep(60)
