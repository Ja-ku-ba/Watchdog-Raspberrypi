import logging
import os
import sys
from concurrent_log_handler import ConcurrentRotatingFileHandler
from dotenv import load_dotenv


_logger_initialized = False


def setup_logging(log_file=None):
    """
    Configure logger with concurrent-log-handler.
    Safe for multiple processes writing to the same file simultaneously.
    
    This function can be called multiple times from different processes - 
    concurrent-log-handler provides safe synchronization.
    """
    global _logger_initialized
    
    if not log_file:
        if '__file__' in globals():
            script_dir = os.path.dirname(os.path.abspath(__file__))
        else:
            script_dir = os.getcwd()
        
        env_path = os.path.join(script_dir, '.env')
        if os.path.exists(env_path):
            load_dotenv(env_path)
        else:
            load_dotenv()
        
        log_file = os.getenv("LOG_FILE")
        
        if not log_file:
            log_file = os.path.join(script_dir, 'watchdog_father.log')
            print(f"[LOGGER] UWAGA: Brak LOG_FILE w .env, używam: {log_file}", file=sys.stderr)
    
    log_file = os.path.abspath(log_file)
    
    log_dir = os.path.dirname(log_file)
    if log_dir and not os.path.exists(log_dir):
        try:
            os.makedirs(log_dir, exist_ok=True)
        except Exception as e:
            print(f"[LOGGER] BŁĄD: Nie można utworzyć katalogu {log_dir}: {e}", file=sys.stderr)
    
    root_logger = logging.getLogger()
    
    if _logger_initialized and os.getpid() != getattr(setup_logging, '_init_pid', None):
        print(f"[LOGGER] Wykryto fork - resetuję handlery dla PID:{os.getpid()}", file=sys.stderr)
        root_logger.handlers.clear()
        _logger_initialized = False
    
    if _logger_initialized:
        return
    
    root_logger.setLevel(logging.INFO)
    
    formatter = logging.Formatter(
        '[%(asctime)s] PID:%(process)d === %(name)s === %(levelname)s === %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    try:
        file_handler = ConcurrentRotatingFileHandler(
            filename=log_file,
            mode='a',
            maxBytes=10*1024*1024,
            backupCount=5,
            encoding='utf-8',
            use_gzip=False,
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(logging.INFO)
        root_logger.addHandler(file_handler)
        print(f"[LOGGER] File handler dodany: {log_file}", file=sys.stderr)
    except Exception as e:
        print(f"[LOGGER] BŁĄD: Nie można utworzyć file handlera: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
    
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.INFO)
    root_logger.addHandler(console_handler)
    
    _logger_initialized = True
    setup_logging._init_pid = os.getpid()
    
    logging.info(f"Logger zainicjalizowany | PID:{os.getpid()} | LOG_FILE:{log_file}")


def get_logger(name):
    """
    Get the logger for the module.
    
    Args:
        name: The name of the logger (usually the name of the module)
        
    Returns:
        logging.Logger: configured logger
    """
    return logging.getLogger(name)
