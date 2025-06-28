import gevent
import gevent.monkey
gevent.monkey.patch_socket()
gevent.monkey.patch_select()
gevent.monkey.patch_ssl()

from gevent.pool import Pool as GPool

import re
import os
import sys
import logging
from io import open
from contextlib import contextmanager
from re import search as re_search
from fnmatch import fnmatch
from binascii import unhexlify
import vpk
from steam import webapi
from steam.exceptions import SteamError, ManifestError
from steam.enums import EResult, EDepotFileFlag
from steam.client import EMsg, MsgProto
from steam.client.cdn import decrypt_manifest_gid_2
from steamctl.clients import CachingSteamClient, CTLDepotManifest, CTLDepotFile
from steamctl.utils.web import make_requests_session
from steamctl.utils.format import fmt_size, fmt_datetime
from steamctl.utils.tqdm import tqdm, fake_tqdm
from steamctl.utils.storage import ensure_dir, sanitizerelpath

webapi._make_requests_session = make_requests_session

LOG = logging.getLogger(__name__)

# Global variables for cancellation handling
global_tasks = None
cancel_monitor_reference = None

# overload VPK with a missing method
class c_VPK(vpk.VPK):
    def c_iter_index(self):
        if self.tree:
            index = self.tree.items()
        else:
            index = self.read_index_iter()

        for path, metadata in index:
            yield path, metadata

# find and cache paths to vpk depot files, and set them up to be read directly from CDN
class ManifestFileIndex(object):
    def __init__(self, manifests):
        self.manifests = manifests
        self._path_cache = {}

    def _locate_file_mapping(self, path):
        ref = self._path_cache.get(path, None)

        if ref:
            return ref
        else:
            self._path_cache[path] = None

            for manifest in self.manifests:
                try:
                    foundfile = next(manifest.iter_files(path))
                except StopIteration:
                    continue
                else:
                    self._path_cache[path] = ref = (manifest, foundfile.file_mapping)
        return ref

    def index(self, pattern=None, raw=True):
        for manifest in self.manifests:
            for filematch in manifest.iter_files(pattern):
                filepath = filematch.filename_raw if raw else filematch.filename
                self._path_cache[filepath] = (manifest, filematch.file_mapping)

    def file_exists(self, path):
        return self._locate_file_mapping(path) != None

    def get_file(self, path, *args, **kwargs):
        ref = self._locate_file_mapping(path)
        if ref:
            return CTLDepotFile(*ref)
        raise SteamError("File not found: {}".format(path))

    def get_vpk(self, path):
        return c_VPK(path, fopen=self.get_file)

# vpkfile download task
def vpkfile_download_to(vpk_path, vpkfile, target, no_make_dirs, pbar):
    relpath = sanitizerelpath(vpkfile.filepath)

    if no_make_dirs:
        relpath = os.path.join(target,                     # output directory
                               os.path.basename(relpath))  # filename from vpk
    else:
        relpath = os.path.join(target,         # output directory
                               vpk_path[:-4],  # vpk path with extention (e.g. pak01_dir)
                               relpath)        # vpk relative path

    filepath = os.path.abspath(relpath)
    ensure_dir(filepath)

    LOG.info("Downloading VPK file to {} ({}, crc32:{})".format(relpath,
                                                                fmt_size(vpkfile.file_length),
                                                                vpkfile.crc32,
                                                                ))

    with open(filepath, 'wb') as fp:
        for chunk in iter(lambda: vpkfile.read(16384), b''):
            fp.write(chunk)

            if pbar:
                pbar.update(len(chunk))

@contextmanager
def init_clients(args):
    s = CachingSteamClient()

    if args.cell_id is not None:
        s.cell_id = args.cell_id

    # Get custom depot keys file path if provided
    custom_depot_keys_file = getattr(args, 'depot_keys', None)
    
    # Create CDN client with optional custom depot keys file
    cdn = s.get_cdnclient(custom_depot_keys_file=custom_depot_keys_file)

    # short-curcuit everything, if we pass manifest file(s)
    if getattr(args, 'file', None):
        manifests = []
        for file_list in args.file:
            for fp in file_list:
                manifest = CTLDepotManifest(cdn, args.app or -1, fp.read())
                manifest.name = os.path.basename(fp.name)
                manifests.append(manifest)
        yield None, None, manifests
        return

    # Only including what's necessary for manifest file(s) as that's what reboot_downloader.py uses
    yield s, cdn, []

    # clean and exit
    cdn.save_cache()
    s.disconnect()

def cmd_depot_download(args):
    # Initialize variables
    pbar = pbar2 = None
    global global_tasks
    global_tasks = None
    should_cancel = [False]

    def cancel_download():
        """Helper to cleanly cancel the download"""
        should_cancel[0] = True
        
        # Immediately disable and close progress bars
        if pbar2:
            try:
                pbar2.cancel()
            except:
                pass
        if pbar:
            try:
                pbar.cancel()
            except:
                pass
            
        # Kill tasks immediately
        if global_tasks:
            try:
                global_tasks.kill(block=True)
            except:
                pass

    try:
        with init_clients(args) as (_, _, manifests):
            fileindex = ManifestFileIndex(manifests)

            # Calculate total size and files
            total_files = total_size = 0
            LOG.info("Locating and counting files...")

            for manifest in manifests:
                for depotfile in manifest:
                    if not depotfile.is_file:
                        continue

                    filepath = depotfile.filename_raw
                    total_files += 1
                    total_size += depotfile.size

            if not total_files:
                raise SteamError("No files found to download")

            # Initialize progress bars
            if not args.no_progress and sys.stderr.isatty():
                pbar = tqdm(
                    desc='Data      ',
                    total=total_size,
                    unit='B',
                    unit_scale=True,
                    mininterval=0.5,
                    maxinterval=1,
                    miniters=1024**3*10
                )
                pbar2 = tqdm(
                    desc='Files     ',
                    total=total_files,
                    unit=' file',
                    position=1,
                    mininterval=0.5,
                    maxinterval=1,
                    miniters=10
                )
                gevent.spawn(pbar.gevent_refresh_loop)
                gevent.spawn(pbar2.gevent_refresh_loop)

            # Initialize download tasks
            tasks = GPool(6)
            global_tasks = tasks

            # Monitor for cancellation
            def check_cancellation():
                try:
                    while not should_cancel[0]:
                        try:
                            from __main__ import is_canceling
                            if is_canceling:
                                # First disable progress bars before showing any messages
                                if pbar:
                                    pbar.cancel()
                                if pbar2:
                                    pbar2.cancel()
                                    
                                # Now it's safe to show messages
                                from colorama import Fore, Style
                                print(f"\n{Fore.YELLOW}Download cancellation requested. Cleaning up...{Style.RESET_ALL}")
                                
                                # Now call cancel_download to clean up tasks
                                cancel_download()
                                break
                        except ImportError:
                            pass
                        gevent.sleep(0.1)
                except:
                    pass

            cancel_monitor = gevent.spawn(check_cancellation)

            # Process each manifest
            for manifest in manifests:
                if should_cancel[0]:
                    break

                for depotfile in manifest:
                    if should_cancel[0]:
                        break

                    if not depotfile.is_file:
                        continue

                    tasks.spawn(depotfile.download_to,
                              args.output,
                              no_make_dirs=args.no_directories,
                              pbar=pbar,
                              verify=(not args.skip_verify))
                    if pbar2 and not should_cancel[0]:
                        pbar2.update(1)

            # Wait for downloads to finish
            if not should_cancel[0]:
                tasks.join()

    except KeyboardInterrupt:
        cancel_download()
        # Give a small delay for progress bars to clear
        gevent.sleep(0.1)
        return 1
    except SteamError as exp:
        if pbar and not should_cancel[0]:
            pbar.write(str(exp))
        return 1
    finally:
        # Clean up
        if global_tasks:
            try:
                global_tasks.kill(block=False)
            except:
                pass
        if cancel_monitor:
            try:
                cancel_monitor.kill(block=False)
            except:
                pass
        
        # Close progress bars if they weren't already closed
        if pbar2 and not getattr(pbar2, '_cancelled', False):
            pbar2.cancel()
        if pbar and not getattr(pbar, '_cancelled', False):
            pbar.cancel()

    return 0 if not should_cancel[0] else 1 