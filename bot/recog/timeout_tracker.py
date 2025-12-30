import threading
import time
import bot.base.log as logger

log = logger.get_logger(__name__)

class RecognitionTimeoutTracker:
    def __init__(self, timeout_seconds=10):
        self.timeout_seconds = timeout_seconds
        self.last_activity_time = time.time()
        self.timeout_triggered = False
        self.lock = threading.Lock()
        self.active = True
        self.monitor_thread = None
        
    def start(self):
        if self.monitor_thread is None or not self.monitor_thread.is_alive():
            self.active = True
            self.timeout_triggered = False
            self.last_activity_time = time.time()
            self.monitor_thread = threading.Thread(target=self.monitor, daemon=True)
            self.monitor_thread.start()
    
    def stop(self):
        self.active = False
        
    def reset(self):
        with self.lock:
            self.last_activity_time = time.time()
            if self.timeout_triggered:
                self.timeout_triggered = False
                log.info("Recognition timeout cleared - activity resumed")
    
    def check_and_reset_timeout(self):
        with self.lock:
            if self.timeout_triggered:
                self.timeout_triggered = False
                self.last_activity_time = time.time()
                return True
            return False
    
    def monitor(self):
        while self.active:
            try:
                time.sleep(1)
                with self.lock:
                    elapsed = time.time() - self.last_activity_time
                    if elapsed >= self.timeout_seconds and not self.timeout_triggered:
                        self.timeout_triggered = True
                        log.warning(f"Recognition timeout triggered - no activity for {self.timeout_seconds} seconds")
            except Exception as e:
                log.error(f"Timeout monitor error: {e}")

tracker = RecognitionTimeoutTracker(timeout_seconds=10)
# tracker.start()  <-- Removed auto-start to prevent import side-effects

def reset_timeout():
    tracker.reset()

def check_and_reset_timeout():
    return tracker.check_and_reset_timeout()

def stop_tracker():
    tracker.stop()