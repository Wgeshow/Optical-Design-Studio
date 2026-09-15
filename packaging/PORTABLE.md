# Optical Design Studio portable

1. Download the Windows x64 portable ZIP and choose Extract All.
2. Extract into a writable folder, such as Documents or a USB drive.
3. Open the extracted Optical Design Studio folder and run Optical Design Studio.exe.

No installer, Python setup, administrator access, or internet connection is needed
to run the app. Keep the entire folder together; the EXE alone is not sufficient.
The package includes the runtime, libraries, readable source, and license notices.
GPU acceleration needs compatible NVIDIA hardware and its existing driver.

## Data folder

New data is saved to User Data beside Optical Design Studio.exe by default.
In Settings, use Data output folder → Browse → Save data folder, then restart.
The chosen folder stores runs, projects, results, material presets, and settings.
The selection is saved in portable_settings.json beside the program.
Use folder beside the program resets the selection; click Save data folder.

Changing the folder does not move or delete existing data. Select an existing
library folder to reopen it, or export/import via Saved work. Earlier installed
versions normally stored data in %LOCALAPPDATA%/Optical Design Studio/User Data;
select that folder to continue using it. An explicit --library launch argument or
S4_LIBRARY_ROOT environment variable overrides the saved setting.

## Updates

About → Check for updates → Download update downloads a verified portable ZIP.
No GitHub account or key is needed. Close the application and extract the newer
ZIP. Preserve your User Data folder and portable_settings.json. For a separate
new extraction, choose your existing data folder in Settings and restart.
Do not delete the old folder until your saved work is available in the new one.

Version 1.0.3 and earlier recognize installer assets only; download this ZIP once
from the public releases page to switch to portable updates. No auto-install or
auto-extraction occurs. Fresh downloads contain no personal research data.
