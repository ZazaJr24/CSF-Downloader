"""TQDM progress bar utilities"""
import sys
import time
import gevent
from collections import deque

try:
    from tqdm import tqdm as _tqdm

    # Create a wrapper for the real tqdm that adds gevent_refresh_loop
    class ProgressBar(_tqdm):
        def __init__(self, *args, **kwargs):
            # Set better defaults for display
            kwargs['ncols'] = kwargs.get('ncols', 100)
            kwargs['bar_format'] = kwargs.get('bar_format', 
                '{desc}|{bar:30}| {percentage:3.0f}% | {n_fmt}/{total_fmt} [{rate_fmt}]')
            super().__init__(*args, **kwargs)
            self._running = False
            self._cancelled = False
            self._refresh_lock = gevent.lock.Semaphore()
            
        def _clear_line(self):
            """Clear the current line in the terminal"""
            sys.stdout.write('\r\033[K')
            sys.stdout.flush()
            
        def cancel(self):
            """Safely cancel and close the progress bar"""
            with self._refresh_lock:
                if not self._cancelled:
                    self._cancelled = True
                    self._running = False
                    # Clear the current line and move cursor to start
                    self._clear_line()
                    # Ensure no more updates can happen
                    self.disable = True
            
        def gevent_refresh_loop(self):
            """Refresh the progress bar at regular intervals"""
            if self._running or self._cancelled:
                return
                
            self._running = True
            while self._running and not self._cancelled:
                with self._refresh_lock:
                    if not self._cancelled:
                        try:
                            self.refresh()
                        except:
                            pass
                gevent.sleep(0.1)
            
        def update(self, n):
            """Update progress, checking for cancellation"""
            if not self._cancelled and not self.disable:
                with self._refresh_lock:
                    if not self._cancelled and not self.disable:
                        super().update(n)
                
        def write(self, s):
            """Write a message above the progress bar"""
            if not self._cancelled and not self.disable:
                with self._refresh_lock:
                    if not self._cancelled and not self.disable:
                        super().write(s)
                
        def display(self, *args, **kwargs):
            """Override display to prevent updates after cancellation"""
            if not self._cancelled and not self.disable:
                with self._refresh_lock:
                    if not self._cancelled and not self.disable:
                        super().display(*args, **kwargs)
                
        def refresh(self, *args, **kwargs):
            """Override refresh to prevent updates after cancellation"""
            if not self._cancelled and not self.disable:
                with self._refresh_lock:
                    if not self._cancelled and not self.disable:
                        super().refresh(*args, **kwargs)
                
        def close(self):
            """Close the progress bar and stop refresh loop"""
            with self._refresh_lock:
                self._running = False
                if not self._cancelled:
                    self._clear_line()
                    super().close()

    tqdm = ProgressBar

except ImportError:
    from shutil import get_terminal_size

    # Keep track of all progress bars
    _all_bars = []
    _initialized = False

    class fake_tqdm(object):
        """Simple progressbar for when tqdm is not available"""
        def __init__(self, *args, **kwargs):
            self.n = 0
            self.total = kwargs.get('total', 0)
            self.desc = kwargs.get('desc', '').strip()
            self.unit = kwargs.get('unit', '')
            self.unit_scale = kwargs.get('unit_scale', False)
            self.miniters = kwargs.get('miniters', 1)
            self.mininterval = kwargs.get('mininterval', 0.1)
            self.maxinterval = kwargs.get('maxinterval', 10.0)
            self.last_print_n = 0
            self.last_print_t = 0
            self.start_t = time.time()
            self.position = kwargs.get('position', 0)
            self._is_closed = False
            self._max_len = 0
            self._running = False
            self._cancelled = False
            self.disable = kwargs.get('disable', False)
            
            # Speed calculation
            self._time_samples = deque(maxlen=20)  # Store last 20 samples
            self._size_samples = deque(maxlen=20)  # Store last 20 samples
            
            # Only add to bars list if it has a valid descriptor and not disabled
            if self.desc and not self.disable:
                # Add to global list of progress bars only once
                if self not in _all_bars:
                    _all_bars.append(self)
            
            # Set up initial newlines if this is the first initialization
            global _initialized
            if not _initialized and _all_bars:
                # Reserve space for the progress bars
                sys.stdout.write('\n' * len(_all_bars))
                sys.stdout.flush()
                _initialized = True

        def _clear_line(self):
            """Clear the current line in the terminal"""
            sys.stdout.write('\r\033[K')
            sys.stdout.flush()

        def cancel(self):
            """Safely cancel and close the progress bar"""
            if not self._cancelled:
                self._cancelled = True
                self._running = False
                self.disable = True
                self._is_closed = True
                
                # Remove from global list
                if self in _all_bars:
                    _all_bars.remove(self)
                    
                # Clear the line
                self._clear_line()

        def _format_size(self, num):
            """Format size with appropriate units"""
            if not self.unit_scale:
                return f"{num} {self.unit}"
                
            for unit in ['', 'K', 'M', 'G', 'T', 'P', 'E', 'Z']:
                if abs(num) < 1024.0:
                    return f"{num:.2f} {unit}{self.unit}"
                num /= 1024.0
            return f"{num:.2f} Y{self.unit}"
            
        def _format_speed(self):
            """Calculate and format the speed"""
            if not self._time_samples or not self._size_samples:
                return "? B/s"
                
            # Calculate speed
            total_time = self._time_samples[-1] - self._time_samples[0]
            if total_time <= 0:
                return "? B/s"
                
            total_size = sum(self._size_samples)
            speed = total_size / total_time
            
            # Format with units
            for unit in ['', 'K', 'M', 'G', 'T']:
                if abs(speed) < 1024.0:
                    return f"{speed:.2f} {unit}B/s"
                speed /= 1024.0
            return f"{speed:.2f} PB/s"

        def _get_progress_bar(self, width=30):
            """Create a progress bar string"""
            if self.total == 0:
                percent = 0
            else:
                percent = min(1.0, self.n / self.total)
            
            filled_len = int(width * percent)
            bar = '█' * filled_len + '░' * (width - filled_len)
            percent_str = f"{percent*100:.1f}%"
            
            if self.total:
                progress_str = f"{self._format_size(self.n)}/{self._format_size(self.total)}"
            else:
                progress_str = f"{self._format_size(self.n)}"
                
            # Create the progress bar string based on unit type
            if self.unit == 'B' and self.unit_scale:
                speed_str = self._format_speed()
                bar_str = f"{self.desc} |{bar}| {percent_str} {progress_str} [{speed_str}]"
            else:
                bar_str = f"{self.desc} |{bar}| {percent_str} {progress_str}"
                
            return bar_str

        def _print_status(self):
            """Print the current status bar"""
            if self._is_closed or self.disable or self._cancelled:
                return
            
            # Only redraw if we have bars
            if _all_bars:
                _redraw_all_bars()
            
        def _direct_print(self):
            """Print this bar directly without moving the cursor"""
            if self._is_closed or self.disable or self._cancelled:
                return
                
            bar = self._get_progress_bar(width=50)
            sys.stdout.write('\r' + bar)
            
            self._max_len = len(bar)
            self.last_print_n = self.n
            self.last_print_t = time.time()

        def update(self, n):
            """Update progress by n units"""
            if self.disable or self._cancelled:
                return

            now = time.time()
            
            # Record time and size for speed calculation if this is a data bar
            if self.unit == 'B' and n > 0:
                self._time_samples.append(now)
                self._size_samples.append(n)
            
            self.n += n
            
            # Only update display if enough progress was made
            if (self.n - self.last_print_n >= self.miniters or 
                now - self.last_print_t >= self.mininterval):
                self._print_status()

        def write(self, s):
            """Write a message above the progress bar"""
            if self._cancelled or self.disable:
                return
                
            if not _all_bars:
                print(s)
                return
                
            # Move cursor to the first bar
            lines_up = len(_all_bars) - 1
            if lines_up > 0:
                sys.stdout.write(f"\033[{lines_up}A")
                
            # Write the message
            sys.stdout.write("\r\033[K" + str(s) + "\n")
            
            # Redraw all bars
            _redraw_all_bars()

        def close(self):
            """Close the progress bar"""
            if not self._is_closed:
                self._is_closed = True
                self._running = False
                
                # Remove from global list
                if self in _all_bars:
                    _all_bars.remove(self)
                    
                # Clear the line
                self._clear_line()

        def gevent_refresh_loop(self):
            """Refresh the progress bar at regular intervals"""
            if self._running or self._cancelled:
                return
                
            self._running = True
            while self._running and not self._cancelled:
                if not self._cancelled and not self.disable:
                    self._print_status()
                gevent.sleep(self.mininterval)
    
    def _redraw_all_bars():
        """Redraw all progress bars from top to bottom"""
        if not _all_bars:
            return
            
        # Only sort if there are multiple bars
        sorted_bars = sorted(_all_bars, key=lambda x: x.position) if len(_all_bars) > 1 else _all_bars
            
        # Move cursor to the first bar position (jump up by number of bars - 1)
        if len(sorted_bars) > 1:
            sys.stdout.write(f"\033[{len(sorted_bars)-1}A\r")
        else:
            sys.stdout.write("\r")
        
        # Draw each bar
        for i, bar in enumerate(sorted_bars):
            # Clear the entire line
            sys.stdout.write("\033[K")
            
            # Draw the bar
            bar._direct_print()
            
            # Move to next line if not the last bar
            if i < len(sorted_bars) - 1:
                sys.stdout.write("\n")
                
        # Ensure all output is displayed
        sys.stdout.flush()
            
    tqdm = fake_tqdm
    
    # Export both tqdm and fake_tqdm to make them available for import
    __all__ = ['tqdm', 'fake_tqdm']
else:
    # Create a wrapper for the real tqdm that adds gevent_refresh_loop
    class fake_tqdm(_tqdm):
        def __init__(self, *args, **kwargs):
            # Set better defaults for display
            kwargs['ncols'] = kwargs.get('ncols', 100)  # Fixed width for consistent display
            kwargs['bar_format'] = kwargs.get('bar_format', 
                '{desc:<10}: {percentage:3.0f}%|{bar:30}| {n_fmt}/{total_fmt} [{rate_fmt}]')
            # Store the disable parameter to control the refresh loop
            self.disable = kwargs.get('disable', False)
            super().__init__(*args, **kwargs)
            self._running = False
            self._cancelled = False
            
        def cancel(self):
            """Safely cancel and close the progress bar"""
            self._cancelled = True
            self._running = False
            self.disable = True
            self.close()
            
        def gevent_refresh_loop(self):
            """Compatibility method for when real tqdm is used"""
            # Don't start refresh loop if disabled
            if self.disable or self._cancelled:
                return
                
            self._running = True
            while self._running and not self._cancelled:
                self.refresh()
                gevent.sleep(0.1)
                
        def close(self):
            """Override to handle _running flag"""
            self._running = False
            super().close()
    
    # Replace the original tqdm with our wrapper
    tqdm = fake_tqdm 