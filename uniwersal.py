import subprocess
import sys
import os
from dotenv import load_dotenv
import time

load_dotenv()

WORKER_SCRIPT_VENV = os.getenv("WORKER_SCRIPT_VENV")


def start_script(script_path, logger, custon_venv=None):
    """
    Runs the indicated script in the background
    """
    try:
        logger.info(f"Uruchamiam {script_path}")
        os.chmod(script_path, 0o755)

        if custon_venv:
            python_path = custon_venv
        else:
            python_path = WORKER_SCRIPT_VENV
        logger.info(f"Aktywacja venv: {python_path}")
        with open(os.devnull, 'w') as devnull:
            process = subprocess.Popen(
                [python_path, '-u', script_path],
                stdout=devnull,
                stderr=devnull,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
                cwd=os.path.dirname(script_path)
            )
            logger.info(f"{script_path} uruchomiony pomyślnie (PID: {process.pid})")
        return True
    except Exception as e:
        logger.error(f"Błąd podczas uruchamiania {script_path}: {e}")
        return False