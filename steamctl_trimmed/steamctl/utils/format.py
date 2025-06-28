from datetime import datetime

def fmt_size(bytes_size, decimal=2):
    """Format file size in human readable form"""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB', 'PB', 'EB', 'ZB']:
        if abs(bytes_size) < 1024.0:
            return f"{bytes_size:.{decimal}f} {unit}"
        bytes_size /= 1024.0
    return f"{bytes_size:.{decimal}f} YB"

def fmt_datetime(timestamp, format=None):
    """Format unix timestamp as datetime string"""
    if not timestamp:
        return 'Never'
    dt = datetime.fromtimestamp(timestamp)
    if format:
        return dt.strftime(format)
    return dt.isoformat(sep=' ', timespec='seconds') 