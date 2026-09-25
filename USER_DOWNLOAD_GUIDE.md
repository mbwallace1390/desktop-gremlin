Desktop Gremlin for Windows
==========================

1. Open [Desktop Gremlin releases](https://github.com/mbwallace1390/desktop-gremlin/releases).
2. Under Assets, download DesktopGremlin-3.3.1-Windows-x64.zip.
3. Right-click the ZIP and choose Extract All.
4. Open the extracted DesktopGremlin folder and double-click DesktopGremlin.exe.

Python and other packages are already included. Keep the _internal folder beside
DesktopGremlin.exe. The GitHub "Source code" downloads are for developers.

The gremlins appear on your desktop. Open the system tray arrow near the clock
and right-click the Desktop Gremlin icon for Settings, Pause and Quit. You can
also quit with Ctrl+Alt+Shift+Q. Normal use has no command window.

Version 3.3.1 keeps crowded speech readable near the top of the screen and makes
Settings fit small screens and large fonts. Its controls scroll while Apply
and Close stay visible. In Mischief mode with group scenes enabled, short breaks
between fights give shared activities a chance to start. Battle mode keeps its
existing pace. Your saved settings and memory are reused.

Version 3.3.0 fixes things that were drawn wrong and tidies the look. Hovering a
gremlin now shows one name instead of two printed over each other. The bow is
held by its grip instead of drawn as a ring round the fist. Speech bubbles are
rounded, point at whoever is talking, and no longer cover each other. Large
gremlins can be grabbed by the head and feet, toys no longer print captions,
sleepers snore, and Settings is dark throughout. The tray icon is drawn at
exactly your display's scaling, and the program icon carries sizes up to 256
pixels.

Version 3.2.2 fixes grudges that never wore off. Relationship scores only ever
fell, so within about ten minutes every pair reached the minimum and stayed
there, locking out rescues, alliances and the quiet group scenes for good. A
fight now deepens a grudge once every few seconds instead of once per blow,
fighting alone can no longer pass a fixed rivalry bound, and scores fade back
toward neutral as a run goes on. Grudges saved by an earlier version thaw on
their own over the first few minutes; nothing needs deleting. Group scenes are
still uncommon -- they need the cast idle -- but they are no longer locked out.

Version 3.2.1 reduces repeated physics and collision calculations, limits waits
for busy Windows Explorer, and improves the Performance panel's measurements.
Your existing settings and physics choices are preserved.

Version 3.2 adds more responsive throws, hits, bounces, loose limbs and moving
crates. In Settings, choose Physics: normal, moon, bouncy or heavy. Surface feel
offers standard, ice, rubber or sticky. Choose Apply to save; normal and
standard restore the default feel. Playground toys still need their setting
enabled. Windows uses the Tk renderer; native presentation remains disabled.

Windows 10 or Windows 11, 64-bit, is required. This ZIP does not install a
service and does not require administrator rights. The executable is currently
unsigned, so Windows may show an unknown-publisher prompt. Only run a download
from the project release you intended to use.

Settings, counters and the icon-layout backup are stored in
%LOCALAPPDATA%\DesktopGremlin. New versions reuse that folder. To update, quit the
old copy, extract the new ZIP into a fresh folder and run the new executable.
If Start with Windows is enabled, open Settings in the new copy and choose
Apply before deleting the old folder. This updates Windows to the new EXE path.

To remove the app, turn off Start with Windows in Settings if you enabled it,
use Restore my icon layout if you moved icons, and choose Quit. Then delete
the extracted application folder. Delete %LOCALAPPDATA%\DesktopGremlin only if
you also want to remove saved preferences, memory and the recovery backup.

Moving from the older Python version
-----------------------------------

In the old running copy, use Restore my icon layout, then choose Quit. Keep the
old folder until you have checked the new version. To retain your preferences
and counters, create %LOCALAPPDATA%\DesktopGremlin and copy gremlin_settings.json
and gremlin_memory.json from the old folder into it before the first EXE launch.
Skip either file if it does not exist. Do not replace newer settings from a
packaged copy that you have already used.

If the old copy reports an incomplete icon restore and your icons are still
moved, preserve its gremlin_icon_backup.json. Copy that original backup into
%LOCALAPPDATA%\DesktopGremlin before starting the EXE so recovery protection stays
with the moved layout. Keep the old folder and backup until restoration succeeds.

If the app will not start, confirm that the ZIP was extracted completely and
_internal is still beside the EXE. The log, when available, is
%LOCALAPPDATA%\DesktopGremlin\gremlin_log.txt.
