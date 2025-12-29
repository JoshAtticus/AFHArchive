import time
from collections import defaultdict, deque
from threading import Lock
import uuid

class BandwidthLimitedFile:
    """File wrapper that limits read speed based on shared bandwidth pool"""
    
    def __init__(self, file_obj, rate_limiter, download_id):
        self.file_obj = file_obj
        self.rate_limiter = rate_limiter
        self.download_id = download_id
        self.start_time = time.time()
        self.bytes_read = 0
        self.last_read_time = time.time()
    
    def read(self, size=-1):
        # Read the requested data
        data = self.file_obj.read(size)
        if not data:
            return data
        
        # Track bytes read
        self.bytes_read += len(data)
        current_time = time.time()
        
        # Get current allocated speed for this download
        allocated_speed = self.rate_limiter.get_allocated_speed(self.download_id)
        
        if allocated_speed > 0:
            # Calculate how long this chunk should take based on allocated speed
            time_since_last = current_time - self.last_read_time
            expected_time = len(data) / allocated_speed
            
            # If we're going too fast, sleep to throttle
            if time_since_last < expected_time:
                sleep_time = expected_time - time_since_last
                time.sleep(sleep_time)
        
        self.last_read_time = time.time()
        return data
    
    def close(self):
        # Remove this download from the active pool when done
        self.rate_limiter.remove_download(self.download_id)
        return self.file_obj.close()
    
    def __getattr__(self, name):
        # Delegate other attributes to the wrapped file object
        return getattr(self.file_obj, name)

    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

class FixedRateLimitedFile:
    """File wrapper that limits read speed to a fixed rate"""
    
    def __init__(self, file_obj, speed_limit_bps):
        self.file_obj = file_obj
        self.speed_limit = speed_limit_bps
        self.last_read_time = time.time()
    
    def read(self, size=-1):
        # Read the requested data
        data = self.file_obj.read(size)
        if not data:
            return data
        
        current_time = time.time()
        
        if self.speed_limit > 0:
            # Calculate how long this chunk should take based on speed limit
            time_since_last = current_time - self.last_read_time
            expected_time = len(data) / self.speed_limit
            
            # If we're going too fast, sleep to throttle
            if time_since_last < expected_time:
                sleep_time = expected_time - time_since_last
                time.sleep(sleep_time)
        
        self.last_read_time = time.time()
        return data
    
    def close(self):
        return self.file_obj.close()
    
    def __getattr__(self, name):
        # Delegate other attributes to the wrapped file object
        return getattr(self.file_obj, name)

    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

class RateLimiter:
    """Shared bandwidth pool rate limiter for download speed control"""
    
    def __init__(self):
        self.active_downloads = {}  # download_id -> start_time
        self.total_bandwidth = 0  # Will be set when downloads start
        self.lock = Lock()
    
    def create_limited_file(self, file_path, total_bandwidth_bps):
        """
        Create a bandwidth-limited file object for download
        Bandwidth is shared among all active downloads
        """
        download_id = str(uuid.uuid4())
        
        with self.lock:
            self.total_bandwidth = total_bandwidth_bps
            self.active_downloads[download_id] = {
                'start_time': time.time(),
                'bytes_downloaded': 0
            }
        
        file_obj = open(file_path, 'rb')
        return BandwidthLimitedFile(file_obj, self, download_id)
    
    def get_allocated_speed(self, download_id):
        """
        Calculate the allocated speed for a specific download
        Total bandwidth is divided equally among all active downloads
        """
        with self.lock:
            active_count = len(self.active_downloads)
            if active_count == 0 or download_id not in self.active_downloads:
                return 0
            
            # Divide total bandwidth equally among active downloads
            allocated_speed = self.total_bandwidth / active_count
            return allocated_speed
    
    def remove_download(self, download_id):
        """Remove a download from the active pool"""
        with self.lock:
            if download_id in self.active_downloads:
                del self.active_downloads[download_id]
    
    def get_active_downloads_info(self):
        """Get information about active downloads for monitoring"""
        with self.lock:
            active_count = len(self.active_downloads)
            speed_per_download = self.total_bandwidth / active_count if active_count > 0 else 0
            return {
                'active_count': active_count,
                'total_bandwidth': self.total_bandwidth,
                'speed_per_download': speed_per_download
            }
    
    def cleanup_old_entries(self):
        """Clean up any stale entries (downloads that didn't close properly)"""
        current_time = time.time()
        with self.lock:
            # Remove downloads older than 1 hour (likely stale)
            to_remove = []
            for download_id, info in self.active_downloads.items():
                if current_time - info['start_time'] > 3600:
                    to_remove.append(download_id)
            
            for download_id in to_remove:
                del self.active_downloads[download_id]
