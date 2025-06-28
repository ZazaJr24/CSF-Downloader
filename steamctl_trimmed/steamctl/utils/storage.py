"""Storage utilities for the application"""
import os
import json
import errno
import re
import logging
from pathlib import Path
from fnmatch import fnmatch

LOG = logging.getLogger(__name__)

def ensure_dir(filepath):
    """Ensure directory exists for given file path"""
    directory = os.path.dirname(filepath)
    if directory and not os.path.exists(directory):
        try:
            os.makedirs(directory)
        except OSError as exc:
            if exc.errno != errno.EEXIST:
                raise

def sanitizerelpath(path):
    """Sanitize path to ensure it's relative and safe"""
    path = Path(path.replace('\\', '/')).as_posix().lstrip('/')
    return path

class FileWrapper(object):
    """Base wrapper for files in user data/cache directories"""
    def __init__(self, subpath):
        self.subpath = subpath
        self.path = str(Path(self.basepath) / subpath)

    def __repr__(self):
        return "{}({!r})".format(self.__class__.__name__, self.subpath)

    def exists(self):
        """Check if file/directory exists"""
        return os.path.exists(self.path)

    def mkdir(self):
        """Create directory"""
        ensure_dir(self.path + '/')

    def remove(self):
        """Remove file/directory"""
        if os.path.isdir(self.path):
            os.rmdir(self.path)
        else:
            try:
                os.remove(self.path)
            except:
                pass

    def open(self, mode='r', encoding=None):
        """Open file and return file object"""
        ensure_dir(self.path)
        return open(self.path, mode, encoding=encoding)

    def read_text(self, encoding='utf-8'):
        """Read file content as text"""
        if not self.exists():
            return ''
        with self.open('r', encoding=encoding) as fp:
            return fp.read()

    def write_text(self, data, encoding='utf-8'):
        """Write text to file"""
        with self.open('w', encoding=encoding) as fp:
            fp.write(data)
        return len(data)

    def read_json(self):
        """Read file content as JSON"""
        if not self.exists():
            return None
        try:
            with self.open('r', encoding='utf-8') as fp:
                return json.load(fp)
        except json.decoder.JSONDecodeError:
            LOG.warning("JSON decode error for %s", self.path)
            return None
        except:
            LOG.warning("Error reading %s", self.path)
            return None

    def write_json(self, obj):
        """Write object as JSON to file"""
        with self.open('w', encoding='utf-8') as fp:
            json.dump(obj, fp, indent=2)
        return True

class UserDataDirectory(FileWrapper):
    """Wrapper for user data directory"""
    basepath = os.path.join(os.path.expanduser('~'), '.steamctl')

    def __init__(self, subpath=''):
        super(UserDataDirectory, self).__init__(subpath)

    def iter_files(self, pattern='*'):
        """Iterate over files in directory matching the pattern"""
        if not self.exists():
            return

        for entry in os.scandir(self.path):
            if fnmatch(entry.name, pattern):
                yield UserDataFile(os.path.join(self.subpath, entry.name))

class UserDataFile(FileWrapper):
    """Wrapper for user data file"""
    basepath = os.path.join(os.path.expanduser('~'), '.steamctl')

    @property
    def filename(self):
        """Return filename without path"""
        return os.path.basename(self.path)

class UserCacheDirectory(FileWrapper):
    """Wrapper for user cache directory"""
    basepath = os.path.join(os.path.expanduser('~'), '.cache', 'steamctl')

    def __init__(self, subpath=''):
        super(UserCacheDirectory, self).__init__(subpath)

    def iter_files(self, pattern='*'):
        """Iterate over files in directory matching the pattern"""
        if not self.exists():
            return

        for entry in os.scandir(self.path):
            if entry.is_file() and fnmatch(entry.name, pattern):
                yield UserCacheFile(os.path.join(self.subpath, entry.name))

class UserCacheFile(FileWrapper):
    """Wrapper for user cache file"""
    basepath = os.path.join(os.path.expanduser('~'), '.cache', 'steamctl')

    @property
    def filename(self):
        """Return filename without path"""
        return os.path.basename(self.path) 