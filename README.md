# CSF Clean Steam Files Downloader
**Preset Game: Jurassic world evolution 2**

Manifest,Lua Files Here: https://discord.gg/M7jCcUvMmb / https://discord.gg/KYKFNmaEwp Ping @zazaajr24 for help (thats the owner of the downloader so me)

to make a .exe do open cmd in the folder

**pyinstaller reboot_downloader.spec**

if: 
**pyinstaller reboot_downloader.spec** didnt work try:

**python -m PyInstaller reboot_downloader.spec**

# you want to change 

in reboot_downloader.spec .EXE output name

**Line 40: name='Jurassic World Evolution 2',**

In  reboot_downloader.py Output Folder name and App Id

    #Application constants
     
     APP_ID = "1244460"
     
     OUTPUT_FOLDER_NAME = "Jurassic World Evolution 2"

In reboot_downloader.spec Manifest lua 

    datas=[
     
        # Include files in both root and subdirectory for compatibility
        
        ('2495100.lua', '.'),  # Include in root for compatibility
        
        ('2495101_FILE1.manifest', '.'),  # Include in root for compatibility 
        
        ('2495101_FILE2.manifest', '.'),  # Include in root for compatibility 
        
        ('2495100.lua', 'resource_files'),  # Also in resource_files subdirectory
        
        ('2495101_FILE1.manifest', 'resource_files'),  # Also in resource_files subdirectory
        
        ('2495101_FILE2.manifest', 'resource_files'),  # Also in resource_files subdirectory
        
        ('steamctl_trimmed', 'steamctl_trimmed'),  # Include complete steamctl directory
        
    ],
    
change names with new manifest and lua those up are examples if you need more help: https://discord.gg/M7jCcUvMmb

run **pip install -r requirements. txt**
if you want already working .exe / downloader go to branches on left top
