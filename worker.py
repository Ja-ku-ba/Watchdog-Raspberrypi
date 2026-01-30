import sys
import subprocess
import signal
import os
import cv2
import threading
import time
import requests
import queue
from datetime import datetime
import mediapipe as mp
from dotenv import load_dotenv
from logger import setup_logging, get_logger

load_dotenv()

STREAM_URL = os.getenv("STREAM_URL")
OUTPUT_DIR = os.getenv("OUTPUT_DIR")
PID_FILE = os.getenv("PID_FILE")
MOTION_LOG_FILE = os.getenv("MOTION_LOG_FILE")
REMOTE_SERVER_URL = os.getenv("REMOTE_SERVER_URL")
DEVICE_UID = os.getenv("DEVICE_UID")

MOTION_RATIO_THRESHOLD = float(os.getenv("MOTION_RATIO_THRESHOLD"))
MOTION_SENSITIVITY = int(os.getenv("MOTION_SENSITIVITY"))
RECORDING_AFTER_MOTION = int(os.getenv("RECORDING_AFTER_MOTION"))
MOTION_CHECK_INTERVAL = int(os.getenv("MOTION_CHECK_INTERVAL"))
FACE_SCAN_TIME = int(os.getenv("FACE_SCAN_TIME"))
FRAME_WIDTH = int(os.getenv("FRAME_WIDTH"))
FRAME_HEIGHT = int(os.getenv("FRAME_HEIGHT"))
MOTION_WIDTH = int(os.getenv("MOTION_WIDTH"))
MOTION_HEIGHT = int(os.getenv("MOTION_HEIGHT"))
MEDIAMTX_DIR = os.getenv("MEDIAMTX_DIR")

FACE_OUTPUT_DIR = os.path.join(OUTPUT_DIR, "faces")
os.makedirs(FACE_OUTPUT_DIR, exist_ok=True)

setup_logging()
logger = get_logger("worker")


class MotionRecorder:
    def __init__(self):
        self.recording = False
        self.ffmpeg_proc = None
        
        # W¹tki
        self.capture_thread = None
        self.motion_thread = None
        
        # Flagi zatrzymywania
        self.stop_capture = False
        self.stop_motion = False
        
        # Kolejki i stan
        self.frame_queue = queue.Queue(maxsize=3)
        self.frame_lock = threading.Lock()
        
        # Stan detekcji
        self.last_motion_time = None
        self.motion_detected_recently = False
        
        # Uruchom mediamtx
        self.ensure_mediamtx_running()
        self.ensure_mediapipe_running()

        self.last_face_save = datetime.min

    def ensure_mediapipe_running(self):
        try:
            self.mp_face_detection = mp.solutions.face_detection
            self.face_detection = self.mp_face_detection.FaceDetection(
                model_selection=0,  # 0 = short range (szybszy), 1 = full range
                min_detection_confidence=0.5
            )
            logger.info("MediaPipe Face Detection zainicjalizowany")
        except Exception as e:
            logger.error(f"B³¹d inicjalizacji MediaPipe: {e}")
            self.face_detection = None
        

    def ensure_mediamtx_running(self, max_retries=3, wait_time=2):
        """
        Sprawdza czy mediamtx działa, jeśli nie - uruchamia go.
        
        Args:
            max_retries: Ile razy próbować uruchomić
            wait_time: Ile sekund czekać po uruchomieniu przed sprawdzeniem
        
        Returns:
            True jeśli mediamtx działa
        
        Raises:
            RuntimeError: Jeśli nie udało się uruchomić mediamtx
        """
        
        def is_mediamtx_running():
            try:
                result = subprocess.run(
                    ['pgrep', '-f', 'mediamtx'],
                    capture_output=True,
                    text=True
                )
                return bool(result.stdout.strip())
            except Exception as e:
                logger.error(f"worker ---- Błąd sprawdzania mediamtx: {e}")
                return False
        
        if is_mediamtx_running():
            logger.info("MediaMTX już działa")
            return True
        
        logger.info("MediaMTX nie działa, uruchamiam...")
        
        for attempt in range(1, max_retries + 1):
            try:
                process = subprocess.Popen(
                    ['./mediamtx'],
                    cwd=MEDIAMTX_DIR,
                    # stdout=subprocess.PIPE,
                    # stderr=subprocess.PIPE,
                    start_new_session=True
                )
                
                logger.info(f"MediaMTX uruchomiony (PID: {process.pid}), czekam {wait_time}s...")
                time.sleep(wait_time)
                
                if is_mediamtx_running():
                    logger.info("MediaMTX działa poprawnie")
                    return True
                else:
                    logger.warning(f"MediaMTX nie działa po uruchomieniu (próba {attempt}/{max_retries})")
                    
            except Exception as e:
                logger.error(f"Błąd podczas uruchamiania mediamtx (próba {attempt}/{max_retries}): {e}")
        
        error_msg = f"Nie udało się uruchomić MediaMTX po {max_retries} próbach"
        logger.error(f"{error_msg}")
        raise RuntimeError(error_msg)


    def start_ffmpeg_recording(self):
        if self.recording:
            return
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self.current_output_file = os.path.join(OUTPUT_DIR, f"motion_rec_{ts}.mp4")
        try:
            cmd = [
                "ffmpeg", 
                "-rtsp_transport", "tcp",
                "-i", STREAM_URL,
                "-c:v", "copy",
                "-avoid_negative_ts", "make_zero",
                "-fflags", "+genpts",
                self.current_output_file
            ]
            
            self.ffmpeg_proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                preexec_fn=os.setsid
            )
            with open(PID_FILE, "w") as f:
                f.write(str(self.ffmpeg_proc.pid))
            self.recording = True
            logger.info(f"Nagrywanie rozpoczête: {self.current_output_file}")

            data = {
                'file_path': os.path.basename(cmd[-1]),
                'recorded_at': datetime.now().isoformat(),
                'record_length': 1111
            }

            headers = {
                'X-Device-UID': DEVICE_UID,
                'Content-Type': 'application/json'
            }

            response = requests.post(
                REMOTE_SERVER_URL + 'videos/save-info-about-video/',
                json=data,
                headers=headers,
                timeout=10
            )
            logger.info(f'start {response}')
            response.raise_for_status()
        except Exception as e:
            logger.error(f"B³¹d startu nagrywania, w lini: {sys.exc_info()[2].tb_lineno}, komunikat b³êdu: {str(e)}")

    def stop_ffmpeg_recording(self):
        if not self.recording or not self.ffmpeg_proc:
            return
        try:
            self.ffmpeg_proc.terminate()
            self.ffmpeg_proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            os.killpg(os.getpgid(self.ffmpeg_proc.pid), signal.SIGKILL)
        except Exception as e:
            logger.error(f"B³¹d zatrzymywania nagrywania: {e}")
        
        if os.path.exists(PID_FILE):
            try: 
                os.remove(PID_FILE)
            except: 
                pass
        
        self.recording = False
        logger.info(f"Nagrywanie zatrzymane: {self.current_output_file}")
        self.ffmpeg_proc = None

    def save_face(self, face_img):
        if face_img is None or face_img.size == 0:
            return

        try:
            success, encoded_image = cv2.imencode(".jpg", face_img, [cv2.IMWRITE_JPEG_QUALITY, 85])
            if not success:
                logger.info("Blad enkodowania zdjecia")
                return
            
            image_bytes = encoded_image.tobytes()
            
            files = {
                "file": (f"{datetime.now().isoformat()}.jpg", image_bytes, "image/jpeg")
            }
            
            data = {
                'recorded_at': datetime.now().isoformat()
            }
            
            headers = {
                'X-Device-UID': DEVICE_UID
            }

            response = requests.post(
                REMOTE_SERVER_URL + 'analyze/upload-face-to-analyze/',
                data=data,
                files=files,
                headers=headers,
                timeout=10
            )
            logger.info(f'face: {response}')
            response.raise_for_status()
        except Exception as e:
            logger.error(f"Błd podczas wysy³ki: {e}")

    def capture_frames(self):
        """W¹tek tylko do czytania klatek"""
        cap = cv2.VideoCapture(STREAM_URL, cv2.CAP_FFMPEG)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        cap.set(cv2.CAP_PROP_FPS, 25)
        
        if not cap.isOpened():
            logger.error("B³¹d otwarcia strumienia!")
            return

        logger.info("Start przechwytywania klatek...")
        
        while not self.stop_capture:
            try:
                ret, frame = cap.read()
                if not ret or frame is None:
                    time.sleep(0.1)
                    continue
                
                if frame.shape[0] < 100 or frame.shape[1] < 100:
                    continue
                
                try:
                    self.frame_queue.put(frame, block=False)
                except queue.Full:
                    try:
                        self.frame_queue.get_nowait()
                        self.frame_queue.put(frame, block=False)
                    except queue.Empty:
                        pass
                
            except Exception as e:
                logger.error(f"B³¹d przechwytywania: {e}")
                time.sleep(1)
        
        cap.release()
        logger.info("Przechwytywanie zakoñczone")

    def motion_detection(self):
        """W¹tek detekcji ruchu - dzia³a rzadziej"""
        logger.info("Start detekcji ruchu...")
        
        prev_motion_frame = None
        last_face_check = 0
        
        while not self.stop_motion:
            try:
                try:
                    frame = self.frame_queue.get(timeout=1)
                    while not self.frame_queue.empty():
                        try:
                            frame = self.frame_queue.get_nowait()
                        except queue.Empty:
                            break
                except queue.Empty:
                    continue
                
                current_time = time.time()
                if current_time - last_face_check > FACE_SCAN_TIME:
                    full_frame = cv2.resize(frame, (FRAME_WIDTH, FRAME_HEIGHT))
                    with self.frame_lock:
                        self.preview_frame = full_frame.copy()
                    last_face_check = current_time
                    
                    if self.motion_detected_recently and self.face_detection is not None:
                        self.detect_faces_mediapipe(full_frame)
                
                motion_frame = cv2.resize(frame, (MOTION_WIDTH, MOTION_HEIGHT))
                motion_gray = cv2.cvtColor(motion_frame, cv2.COLOR_BGR2GRAY)
                motion_gray = cv2.GaussianBlur(motion_gray, (5, 5), 0)
                
                if prev_motion_frame is not None:
                    diff = cv2.absdiff(prev_motion_frame, motion_gray)
                    _, thresh = cv2.threshold(diff, MOTION_SENSITIVITY, 255, cv2.THRESH_BINARY)
                    
                    motion_pixels = cv2.countNonZero(thresh)
                    motion_ratio = motion_pixels / (MOTION_WIDTH * MOTION_HEIGHT)
                    motion_detected = motion_ratio > MOTION_RATIO_THRESHOLD
                    
                    now = datetime.now()
                    
                    if motion_detected:
                        if not self.motion_detected_recently:
                            logger.info(f"RUCH: {motion_ratio:.2%}")
                        self.last_motion_time = now
                        self.motion_detected_recently = True
                        if not self.recording:
                            self.start_ffmpeg_recording()
                    else:
                        if self.motion_detected_recently and self.last_motion_time:
                            if (now - self.last_motion_time).total_seconds() > RECORDING_AFTER_MOTION:
                                self.motion_detected_recently = False
                                logger.info("Brak ruchu")
                    
                    if self.recording and self.last_motion_time and not self.motion_detected_recently:
                        if (now - self.last_motion_time).total_seconds() > RECORDING_AFTER_MOTION:
                            self.stop_ffmpeg_recording()
                            self.last_motion_time = None
                
                prev_motion_frame = motion_gray.copy()
                time.sleep(MOTION_CHECK_INTERVAL)
                
            except Exception as e:
                logger.error(f"B³¹d detekcji ruchu: {e}")
                time.sleep(1)
        
        logger.info("Detekcja ruchu zatrzymana")

    def detect_faces_mediapipe(self, frame):
        """Detekcja twarzy z MediaPipe - szybsza i dok³adniejsza ni¿ Haar"""
        if self.face_detection is None:
            return
        
        now = datetime.now()
        if (now - self.last_face_save).total_seconds() < 3:
            return
        
        try:
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = self.face_detection.process(rgb_frame)
            
            if results.detections:
                for detection in results.detections:
                    # MediaPipe: bounding box wzglêdny 01
                    bboxC = detection.location_data.relative_bounding_box

                    # Wymiary ma³ej klatki
                    small_h, small_w = rgb_frame.shape[:2]

                    # Skalowanie z ma³ej klatki do wspó³rzêdnych pikselowych w niej
                    x_small = int(bboxC.xmin * small_w)
                    y_small = int(bboxC.ymin * small_h)
                    w_small = int(bboxC.width * small_w)
                    h_small = int(bboxC.height * small_h)

                    # Wymiary du¿ej klatki
                    h, w = frame.shape[:2]

                    # Skala powiêkszenia
                    scale_x = w / small_w
                    scale_y = h / small_h

                    # Przeskalowanie wspó³rzêdnych do du¿ej klatki
                    x = int(x_small * scale_x)
                    y = int(y_small * scale_y)
                    box_w = int(w_small * scale_x)
                    box_h = int(h_small * scale_y)

                    # Powiêkszenie bounding boxa
                    scale_factor = 2

                    cx = x + box_w // 2
                    cy = y + box_h // 2

                    new_w = int(box_w * scale_factor)
                    new_h = int(box_h * scale_factor)

                    # Wyznaczenie granic wycinka (z zabezpieczeniem przed wyjciem poza kadr)
                    x1 = max(0, cx - new_w // 2)
                    y1 = max(0, cy - new_h // 2)
                    x2 = min(w, cx + new_w // 2)
                    y2 = min(h, cy + new_h // 2)
                    y2 = int(y2 * 1.5)
                    # Wyciêcie twarzy
                    face_img = frame[y1:y2, x1:x2]

                    if face_img.size > 0:
                        self.save_face(face_img)
                        confidence = detection.score[0]
                        logger.info(f"Twarz wykryta MediaPipe (confidence: {confidence:.2f})")
                        break  # Tylko jedna twarz na raz
                
                self.last_face_save = now
                
        except Exception as e:
            logger.error(f"B³¹d detekcji twarzy MediaPipe, w lini: {sys.exc_info()[2].tb_lineno}, komunikat b³êdu: {str(e)}")

    def start_motion_detection(self):
        logger.info("Uruchamianie systemu...")
        
        self.stop_capture = False
        self.stop_motion = False
        
        self.capture_thread = threading.Thread(target=self.capture_frames, daemon=True)
        self.capture_thread.start()
        
        time.sleep(1)
        
        self.motion_thread = threading.Thread(target=self.motion_detection, daemon=True)
        self.motion_thread.start()
        
        logger.info("System uruchomiony")

    def stop_motion_detection(self):
        logger.info("Zatrzymywanie systemu...")
        
        self.stop_capture = True
        self.stop_motion = True  
        
        threads = [self.capture_thread, self.motion_thread]
        for thread in threads:
            if thread and thread.is_alive():
                thread.join(timeout=3)
        
        if self.recording:
            self.stop_ffmpeg_recording()
        
        if self.face_detection:
            self.face_detection.close()
        
        logger.info("System zatrzymany")


def signal_handler(signum, frame):
    recorder.stop_motion_detection()
    exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    logger.info("worker --- start")
    recorder = MotionRecorder()
    recorder.start_motion_detection()

    try:
        while True:
            logger.info("worker --- loop")
            time.sleep(10)
    except KeyboardInterrupt:
        recorder.stop_motion_detection()
    except Exception as e:
        logger.info(f"{str(e)}") 
