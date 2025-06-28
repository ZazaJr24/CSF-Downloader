import gevent.monkey
gevent.monkey.patch_socket()
gevent.monkey.patch_ssl()

import os
import logging
import json
from time import time
from eventemitter import EventEmitter
from steam.enums import EResult, EPersonaState
from steam.client import SteamClient
from steam.client.cdn import CDNClient, CDNDepotManifest, CDNDepotFile, ContentServer
from steam.exceptions import SteamError
from steam.core.crypto import sha1_hash

from steamctl.utils.format import fmt_size
from steamctl.utils.storage import (UserCacheFile, UserDataFile,
                                    UserCacheDirectory, UserDataDirectory,
                                    ensure_dir, sanitizerelpath
                                    )

cred_dir = UserDataDirectory('client')

# Create a custom SteamClient that properly initializes the EventEmitter
class CachingSteamClient(SteamClient, EventEmitter):
    credential_location = cred_dir.path
    persona_state = EPersonaState.Offline

    def __init__(self, *args, **kwargs):
        if not cred_dir.exists():
            cred_dir.mkdir()
        # Initialize both parent classes properly
        EventEmitter.__init__(self)
        SteamClient.__init__(self, *args, **kwargs)
        self._LOG = logging.getLogger('CachingSteamClient')

    def get_cdnclient(self, custom_depot_keys_file=None):
        return CachingCDNClient(self, custom_depot_keys_file=custom_depot_keys_file)
        
    def disconnect(self):
        """Override disconnect to avoid errors when closing"""
        try:
            super().disconnect()
        except:
            pass


class CTLDepotFile(CDNDepotFile):
    _LOG = logging.getLogger('CTLDepotFile')

    def download_to(self, target, no_make_dirs=False, pbar=None, verify=True):
        relpath = sanitizerelpath(self.filename)

        if no_make_dirs:
            relpath = os.path.basename(relpath)

        relpath = os.path.join(target, relpath)

        filepath = os.path.abspath(relpath)
        ensure_dir(filepath)

        checksum = self.file_mapping.sha_content.hex()

        # don't bother verifying if file doesn't already exist
        if not os.path.exists(filepath):
            verify = False

        with open(filepath, 'r+b' if verify else 'wb') as fp:
            fp.seek(0, 2)

            # pre-allocate space
            if fp.tell() != self.size:
                newsize = fp.truncate(self.size)

                if newsize != self.size:
                    raise SteamError("Failed allocating space for {}".format(filepath))

            fp.seek(0)
            for chunk in self.chunks:
                # verify chunk sha hash
                if verify:
                    cur_data = fp.read(chunk.cb_original)

                    if sha1_hash(cur_data) == chunk.sha:
                        if pbar:
                            pbar.update(chunk.cb_original)
                        continue

                    fp.seek(chunk.offset)  # rewind before write

                # download and write chunk
                data = self.manifest.cdn_client.get_chunk(
                                self.manifest.app_id,
                                self.manifest.depot_id,
                                chunk.sha.hex(),
                                )

                fp.write(data)

                if pbar:
                    pbar.update(chunk.cb_original)

class CTLDepotManifest(CDNDepotManifest):
    DepotFileClass = CTLDepotFile


class CachingCDNClient(CDNClient):
    DepotManifestClass = CTLDepotManifest
    _LOG = logging.getLogger('CachingCDNClient')
    _depot_keys = None
    skip_licenses = False

    def __init__(self, *args, custom_depot_keys_file=None, **kwargs):
        CDNClient.__init__(self, *args, **kwargs)
        self.custom_depot_keys_file = custom_depot_keys_file
        if custom_depot_keys_file:
            self._LOG.info(f"Using custom depot keys file: {custom_depot_keys_file}")

    def fetch_content_servers(self, *args, **kwargs):
        cached_cs = UserDataFile('cs_servers.json')

        data = cached_cs.read_json()

        # load from cache, only keep for 5 minutes
        if data and (data['timestamp'] + 300) > time():
            for server in data['servers']:
                entry = ContentServer()
                entry.__dict__.update(server)
                self.servers.append(entry)
            return

        # fetch cs servers
        CDNClient.fetch_content_servers(self, *args, **kwargs)

        # cache cs servers
        data = {
            "timestamp": int(time()),
            "cell_id": self.cell_id,
            "servers": list(map(lambda x: x.__dict__, self.servers)),
        }

        cached_cs.write_json(data)

    @property
    def depot_keys(self):
        if not self._depot_keys:
            self._depot_keys = {}
            self._depot_keys.update(self.get_cached_depot_keys())
        return self._depot_keys

    @depot_keys.setter
    def depot_keys(self, value):
        self._depot_keys = value

    def get_cached_depot_keys(self):
        """
        Get depot keys from either the custom file or default location
        """
        if self.custom_depot_keys_file and os.path.exists(self.custom_depot_keys_file):
            self._LOG.info(f"Loading depot keys from custom file: {self.custom_depot_keys_file}")
            try:
                with open(self.custom_depot_keys_file, 'r') as f:
                    depot_keys = json.load(f)
                return {int(depot_id): bytes.fromhex(key)
                        for depot_id, key in depot_keys.items()}
            except Exception as e:
                self._LOG.error(f"Error loading custom depot keys file: {e}")
                # Fall back to default if custom file fails
        
        # Default behavior
        return {int(depot_id): bytes.fromhex(key)
                for depot_id, key in (UserDataFile('depot_keys.json').read_json() or {}).items()
                }

    def save_cache(self):
        cached_depot_keys = self.get_cached_depot_keys()

        if cached_depot_keys == self.depot_keys:
            return

        self.depot_keys.update(cached_depot_keys)
        out = {str(depot_id): key.hex()
               for depot_id, key in self.depot_keys.items()
               }

        # Don't override custom depot_keys.json file if one was provided
        if not self.custom_depot_keys_file:
            UserDataFile('depot_keys.json').write_json(out)

    def get_cached_manifest(self, app_id, depot_id, manifest_gid):
        key = (app_id, depot_id, manifest_gid)

        if key in self.manifests:
            return self.manifests[key]

        # if we don't have the manifest loaded, check cache
        cached_manifest = UserCacheFile("manifests/{}_{}_{}".format(app_id, depot_id, manifest_gid))

        # we have a cached manifest file, load it
        if cached_manifest.exists():
            with cached_manifest.open('r+b') as fp:
                try:
                    manifest = self.DepotManifestClass(self, app_id, fp.read())
                except Exception as exp:
                    self._LOG.debug("Error parsing cached manifest: %s", exp)
                else:
                    # if its not empty, load it
                    if manifest.gid > 0:
                        self.manifests[key] = manifest

                        # update cached file if we have depot key for it
                        if manifest.filenames_encrypted and manifest.depot_id in self.depot_keys:
                            manifest.decrypt_filenames(self.depot_keys[manifest.depot_id])
                            fp.seek(0)
                            fp.write(manifest.serialize(compress=False))
                            fp.truncate()

                        return manifest

            # empty manifest files shouldn't exist, handle it gracefully by removing the file
            if key not in self.manifests:
                self._LOG.debug("Found cached manifest, but encountered error or file is empty")
                cached_manifest.remove()

    def get_manifest(self, app_id, depot_id, manifest_gid, decrypt=True, manifest_request_code=None):
        key = (app_id, depot_id, manifest_gid)
        cached_manifest = UserCacheFile("manifests/{}_{}_{}".format(*key))

        if decrypt and depot_id not in self.depot_keys:
            self.get_depot_key(app_id, depot_id)

        manifest = self.get_cached_manifest(*key)

        # if manifest not cached, download from CDN
        if not manifest:
            manifest = CDNClient.get_manifest(
                self, app_id, depot_id, manifest_gid, decrypt=decrypt, manifest_request_code=manifest_request_code
            )

            # cache the manifest
            with cached_manifest.open('wb') as fp:
                fp.write(manifest.serialize(compress=False))

        return self.manifests[key] 