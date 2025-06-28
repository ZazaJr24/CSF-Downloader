import sys
import os
import re
import traceback
import asyncio
import aiofiles
import zlib
import struct
import json
import argparse
import logging
import tempfile
import shutil
import signal
from pathlib import Path
from colorama import init, Fore, Style, Back
import time

# Import runtime hook to ensure it runs even when called directly
try:
    import runtime_hook
except ImportError:
    pass  # No runtime_hook available or already imported

# Configure root logger to suppress all logs
logging.basicConfig(level=logging.ERROR)

# Application constants
APP_ID = "1244460"
OUTPUT_FOLDER_NAME = "Jurassic World Evolution 2"

# Flag to track if the program is being canceled
is_canceling = False

# Signal handler for graceful exit
def signal_handler(sig, frame):
    global is_canceling
    
    if not is_canceling:
        is_canceling = True
        
        # Don't display cancellation message yet, just set the flag
        # The message will be shown after the download actually stops
        # Try to access steamctl tasks and cancel them first
        try:
            import steamctl.commands.depot.gcmds as gcmds
            if hasattr(gcmds, 'global_tasks') and gcmds.global_tasks:
                # Cancel tasks without showing message yet
                gcmds.global_tasks.kill(block=False)
        except:
            pass
            
        # Cancel any asyncio tasks
        try:
            for task in asyncio.all_tasks():
                if hasattr(task, '_coro') and task._coro.__name__ == 'depotdownloadermod_add':
                    task.cancel()
                    break
        except:
            pass
            
        return
    else:
        # If pressed twice, force immediate exit
        print(f"\n{Fore.RED}Forcing immediate exit.{Style.RESET_ALL}")
        os._exit(1)

# Register the signal handler for SIGINT (Ctrl+C)
signal.signal(signal.SIGINT, signal_handler)

# Determine if we're running in a PyInstaller bundle
def get_resource_path(relative_path):
    """Get the correct resource path whether running from source or as frozen executable"""
    if getattr(sys, 'frozen', False):  # Running as compiled executable
        # Path to the directory containing the executable
        base_path = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
        
        # Check if it's one of our data files that should be in resource_files
        if relative_path.endswith('.lua') or relative_path.endswith('.manifest') or relative_path.endswith('.st'):
            # First check if it exists directly in base_path (for backward compatibility)
            direct_path = os.path.join(base_path, relative_path)
            if os.path.exists(direct_path):
                return direct_path
                
            # Otherwise look in resource_files subdirectory
            return os.path.join(base_path, 'resource_files', os.path.basename(relative_path))
    else:
        # Path to the directory containing the script
        base_path = os.path.dirname(os.path.abspath(__file__))
    
    return os.path.join(base_path, relative_path)

# Create a temporary working directory that will be cleaned up on exit
temp_dir = None
def get_temp_dir():
    global temp_dir
    if temp_dir is None:
        temp_dir = tempfile.mkdtemp(prefix='reboot_downloader_')
    return temp_dir

# Clean up the temporary directory when the program exits
def cleanup_temp_dir():
    global temp_dir
    if temp_dir and os.path.exists(temp_dir):
        try:
            shutil.rmtree(temp_dir)
        except:
            pass

# Add the steamctl_trimmed directory to the path to find the module instead of steamctl
steamctl_dir = get_resource_path('steamctl_trimmed')
sys.path.append(steamctl_dir)
from steamctl.commands.depot.gcmds import cmd_depot_download

init()

# Initialize logging - only display errors by default
log = logging.getLogger('RebootDownloader')
log.setLevel(logging.ERROR)  # Only show errors
handler = logging.StreamHandler()
log.addHandler(handler)

# Disable other loggers
logging.getLogger('steamctl').setLevel(logging.ERROR)
logging.getLogger('asyncio').setLevel(logging.ERROR)
logging.getLogger('urllib3').setLevel(logging.ERROR)

# Make sure all other loggers inherit the root logger's level
for name in logging.root.manager.loggerDict:
    logging.getLogger(name).setLevel(logging.ERROR)

lock = asyncio.Lock()

def print_welcome_screen():
    """Display a welcome screen with the tool name and information"""
    width = shutil.get_terminal_size().columns
    
    print(Fore.CYAN + "=" * width + Style.RESET_ALL)
    print(Fore.CYAN + Style.BRIGHT + "CSF Downloader".center(width) + Style.RESET_ALL)
    print(Fore.CYAN + f"v1.0".center(width) + Style.RESET_ALL)
    print(Fore.CYAN + "=" * width + Style.RESET_ALL)
    print()
    print(Fore.GREEN + f"Target Application: {Fore.YELLOW}{OUTPUT_FOLDER_NAME} (AppID: {APP_ID})" + Style.RESET_ALL)
    print(Fore.GREEN + f"Output Directory: {Fore.YELLOW}./{OUTPUT_FOLDER_NAME}" + Style.RESET_ALL)
    print()
    print(Fore.CYAN + "=" * width + Style.RESET_ALL)
    print()

def stack_error(exception: Exception) -> str:
    """ Process error stack """
    stack_trace = traceback.format_exception(
        type(exception), exception, exception.__traceback__)
    return ''.join(stack_trace)

async def get_data_local(app_id: str) -> list:
    collected_depots = []
    
    # Use temporary directory for working files instead of current directory
    work_dir = Path(get_temp_dir())
    resource_path = Path(get_resource_path('.'))
    
    # Also check the resource_files subdirectory
    resource_files_path = Path(get_resource_path('resource_files'))
    
    depot_keys = {}  # Dictionary to store depot IDs and their keys
    try:
        # Check in all possible locations
        lua_file_paths = [
            work_dir / f"{app_id}.lua",
            resource_path / f"{app_id}.lua",
            resource_files_path / f"{app_id}.lua"
        ]
        st_file_paths = [
            work_dir / f"{app_id}.st", 
            resource_path / f"{app_id}.st",
            resource_files_path / f"{app_id}.st"
        ]
        
        # Try to find lua file first
        lua_file_path = None
        for path in lua_file_paths:
            if path.exists():
                lua_file_path = path
                break
        
        # Then try st file if no lua file found
        st_file_path = None
        if not lua_file_path:
            for path in st_file_paths:
                if path.exists():
                    st_file_path = path
                    break
        
        # If lua file found, copy to temp dir
        if lua_file_path:
            shutil.copy2(lua_file_path, work_dir.joinpath(f"{app_id}.lua"))
            lua_file_path = work_dir / f"{app_id}.lua"
        # If st file found, copy to temp dir
        elif st_file_path:
            shutil.copy2(st_file_path, work_dir.joinpath(f"{app_id}.st"))
            st_file_path = work_dir / f"{app_id}.st"
        else:
            print(f'Error: Required files not found. Need either {app_id}.lua or {app_id}.st')
            print(f'Searched in: {work_dir}, {resource_path}, {resource_files_path}')
            raise FileNotFoundError
        
        # Read the file that was found
        if lua_file_path and lua_file_path.exists():
            luafile = await aiofiles.open(lua_file_path, 'r', encoding="utf-8")
            content = await luafile.read()
            await luafile.close()
        elif st_file_path and st_file_path.exists():
            stfile = await aiofiles.open(st_file_path, 'rb')
            content = await stfile.read()
            await stfile.close()
            # Parse header
            header = content[:12]
            xorkey, size, xorkeyverify = struct.unpack('III', header)
            xorkey ^= 0xFFFEA4C8
            xorkey &= 0xFF
            # Parse data
            data = bytearray(content[12:12+size])
            for i in range(len(data)):
                data[i] = data[i] ^ xorkey
            # Read data
            decompressed_data = zlib.decompress(data)
            content = decompressed_data[512:].decode('utf-8')
        else:
            print(f'Error: Required files found but could not be opened')
            raise FileNotFoundError

        # Parse addappid and setManifestid
        addappid_pattern = re.compile(r'addappid\(\s*(\d+)\s*(?:,\s*\d+\s*,\s*"([0-9a-f]+)"\s*)?\)')
        setmanifestid_pattern = re.compile(r'setManifestid\(\s*(\d+)\s*,\s*"(\d+)"\s*(?:,\s*\d+\s*)?\)')

        for match in addappid_pattern.finditer(content):
            depot_id = match.group(1)
            decrypt_key = match.group(2) if match.group(2) else None
            if decrypt_key:
                depot_keys[depot_id] = decrypt_key

        # Write depot keys to JSON file in temp directory
        depot_keys_path = work_dir / 'depot_keys.json'
        async with aiofiles.open(depot_keys_path, 'w', encoding="utf-8") as json_file:
            await json_file.write(json.dumps(depot_keys, indent=4))

        for match in setmanifestid_pattern.finditer(content):
            depot_id = match.group(1)
            manifest_id = match.group(2)
            filename = f"{depot_id}_{manifest_id}.manifest"
            
            # Check for the manifest file in all possible locations
            manifest_paths = [
                work_dir / filename,
                resource_path / filename,
                resource_files_path / filename
            ]
            
            manifest_found = False
            for manifest_path in manifest_paths:
                if manifest_path.exists():
                    # If the manifest file is not in work_dir, copy it
                    if manifest_path != work_dir / filename and not (work_dir / filename).exists():
                        shutil.copy2(manifest_path, work_dir / filename)
                    collected_depots.append(work_dir / filename)
                    manifest_found = True
                    break
        
    except KeyboardInterrupt:
        print("Program exited")
    except Exception as e:
        log.error(f'Processing failed: {stack_error(e)}')
        raise
    return collected_depots

def run_steamctl_download(manifest_file, output_dir, depot_keys_file=None):
    """
    Run the steamctl depot download command directly using the local module
    """
    global is_canceling
    
    try:
        # Check if cancellation was requested
        if is_canceling:
            return False
            
        # Disable all loggers before running steamctl
        for name in logging.root.manager.loggerDict:
            logging.getLogger(name).setLevel(logging.ERROR)
        
        # Create argument namespace similar to what the steamctl command line would generate
        args = argparse.Namespace()
        args.file = [[open(manifest_file, 'rb')]]
        args.output = output_dir
        args.no_directories = False
        args.no_progress = False
        args.app = None
        args.depot = None
        args.manifest = None
        args.branch = 'public'
        args.password = None
        args.skip_depot = None
        args.skip_login = True
        args.skip_licenses = True
        args.vpk = False
        args.skip_verify = False
        args.name = None
        args.regex = None
        args.cell_id = None
        args.os = 'any'
        args.depot_keys = depot_keys_file
        
        # Call the steamctl download command
        if not is_canceling:  # Double check is_canceling flag before printing anything
            print(f"\n{Fore.CYAN}Downloading content...{Style.RESET_ALL}")
        result = cmd_depot_download(args)
        
        # Check if download was cancelled
        if result == 1:
            is_canceling = True
            return False
            
        return True
    except KeyboardInterrupt:
        is_canceling = True
        return False
    except Exception as e:
        if not is_canceling:  # Only print error if we're not canceling
            print(f'{Fore.RED}Error running steamctl download: {e}{Style.RESET_ALL}')
        return False
    finally:
        # Close the file handle
        if hasattr(args, 'file') and args.file and args.file[0] and args.file[0][0]:
            args.file[0][0].close()

async def depotdownloadermod_add(app_id: str, manifests: list) -> bool:
    global is_canceling  # Declare global at the start of the function
    async with lock:
        try:
            success = True
            
            # Create the output directory relative to current directory, not temp directory
            # This is the only directory we want to be visible to the user
            output_dir = f"./{OUTPUT_FOLDER_NAME}"
            os.makedirs(output_dir, exist_ok=True)
            
            # Use the depot_keys.json in the temp directory
            temp_dir = get_temp_dir()
            depot_keys_file = os.path.join(temp_dir, "depot_keys.json")
            
            # Process each manifest
            for manifest in manifests:
                # Check if cancellation was requested
                if is_canceling:
                    return False
                    
                # Call the steamctl download command with our parameters
                if not run_steamctl_download(str(manifest), output_dir, depot_keys_file):
                    success = False
                    
                # Check cancellation again after each manifest
                if is_canceling:
                    return False
                    
            return success
        except asyncio.CancelledError:
            # If we're cancelled through asyncio, mark as canceling and return
            is_canceling = True
            return False
        except Exception as e:
            print(f'{Fore.RED}Error occurred: {e}{Style.RESET_ALL}')
            return False

async def main():
    try:
        print_welcome_screen()
        
        # Use the global APP_ID constant instead of hardcoding it
        app_id = APP_ID
        app_id_list = list(filter(str.isdecimal, app_id.strip().split('-')))
        
        if not app_id_list:
            print(f'{Fore.RED}Invalid App ID{Style.RESET_ALL}')
            return False
        
        app_id = app_id_list[0]
        
        try:
            manifests = await get_data_local(app_id)
            
            # Check if cancellation was requested during manifest preparation
            if is_canceling:
                print(f"{Fore.YELLOW}Download canceled during manifest preparation.{Style.RESET_ALL}")
                return False
                
            if manifests:
                print(f"{Fore.GREEN}Starting download process, please wait (for large games, preparing files may take a while at the beginning)...{Style.RESET_ALL}")
                print(f"{Fore.CYAN}Press Ctrl+C once to cancel the download safely.{Style.RESET_ALL}")
                success = await depotdownloadermod_add(app_id, manifests)
                
                # Check if cancellation was requested during download
                if is_canceling:
                    # Now it's safe to show the cancellation message after depotdownloadermod_add returned
                    print(f"{Fore.YELLOW}Download canceled by user.{Style.RESET_ALL}")
                    print(f"{Fore.YELLOW}Partial files may have been downloaded to: ./{OUTPUT_FOLDER_NAME}{Style.RESET_ALL}")
                    return False
                    
                if not success:
                    print(f'{Fore.RED}Failed to process manifests for AppID: {app_id}{Style.RESET_ALL}')
                else:
                    print(f'{Fore.GREEN}Download completed successfully!{Style.RESET_ALL}')
                    print(f'{Fore.GREEN}Files downloaded to: ./{OUTPUT_FOLDER_NAME}{Style.RESET_ALL}')
            else:
                print(f'{Fore.RED}No manifest files found for AppID: {app_id}{Style.RESET_ALL}')
                
        except Exception as e:
            if is_canceling:
                print(f"{Fore.YELLOW}Download canceled during processing.{Style.RESET_ALL}")
            else:
                print(f'{Fore.RED}Processing failed: {e}{Style.RESET_ALL}')
            
    except KeyboardInterrupt:
        # This should no longer trigger due to our signal handler, but kept as a fallback
        print(f"{Fore.YELLOW}Program exited by user{Style.RESET_ALL}")
    except SystemExit:
        sys.exit()
    finally:
        # Always clean up temporary files, even when canceled
        cleanup_temp_dir()
        
        # If we were canceling, show final message
        if is_canceling:
            print(f"{Fore.GREEN}Cleanup completed. Program exited safely.{Style.RESET_ALL}")

if __name__ == '__main__':
    asyncio.run(main())
