# Desktop input lockout — 2.1.1 recovery

## Observed impact

After starting the 2.1 upgrade, the user could interact with the gremlins but
could not click or move other desktop objects/windows. They needed the Windows
key and arrow keys to restart the PC. This is a critical regression introduced
by enabling native graphics automatically.

## Cause and test failure

The native visual HWND used extended style `0x082000A8`: topmost,
NOREDIRECTIONBITMAP, TRANSPARENT, TOOLWINDOW and NOACTIVATE, without LAYERED.
It covered the virtual desktop. Its DirectComposition pixels were transparent,
but the non-layered HWND retained a rectangular input surface. Returning
`HTTRANSPARENT` does not establish passthrough to unrelated application threads.
Microsoft's [WM_NCHITTEST documentation](https://learn.microsoft.com/en-us/windows/win32/inputdev/wm-nchittest)
limits that forwarding to windows belonging to the same thread. The
[window-features documentation](https://learn.microsoft.com/en-us/windows/win32/winmsg/window-features)
separately describes layered-window input transparency.

The previous probe called WindowFromPoint from the renderer's own thread, which
honored its hit-test response. Placing the backing window in a different process
did not make the query independent, and no mouse-delivery event was measured.
Microsoft's [explanation of window lookup](https://devblogs.microsoft.com/oldnewthing/20101230-00/?p=11873)
describes this thread-dependent difference. The 26 passing suites and native
pixel captures were insufficient evidence for safe desktop input.

The suite had an additional blind spot: production defaulted to `auto`, while
the harness forced `tk`. Most tests bypassed the renderer enabled for the user.

The style/dispatch mechanism matches the reported failure; the unsafe native
overlay has not been relaunched to reproduce the user's lockout.

## Changes made

1. Set the production default to Tk and reject saved native/auto selections.
2. Force the exact original Tk canvas in App configuration, even if raw settings
   are modified in memory. Settings offers only Tk.
3. Disable native renderer and visual-window construction before loading DLLs
   or creating windows. Old native test/preview entry points refuse to run.
4. Explicitly select Tk in this checkout's saved settings, preserving other
   preferences. Keep the animation, visibility, physics and navigation upgrades.
5. Add Ctrl+Alt+Shift+Q as a Windows global exit shortcut. Queue quit outside
   Win32 callbacks, unregister on shutdown, and report registration failure.
6. Hide the overlay before shutdown work; individual cleanup failures cannot
   prevent root-window destruction.
7. Make the harness use the production renderer default and add recovery
   regressions with a tripwire against importing or initializing native code.

## Verification and future work

`tests/test_input_recovery.py` covers startup/settings quarantine, native guards,
keyboard-exit dispatch, unavailable tray/shortcut cases, pause/fullscreen states,
and cleanup failures. The full runner includes 27 suites. Physical mouse input
is not injected into the user's desktop by these checks.

Native presentation remains disabled. A future implementation must prove actual
click, right-click, wheel and drag event receipt in a separate backing process,
using small owned windows and an independent watchdog. A broken implementation
must fail that test. Neither an image nor a same-thread WindowFromPoint result
is a substitute. Do not re-enable a fullscreen native overlay to investigate.
