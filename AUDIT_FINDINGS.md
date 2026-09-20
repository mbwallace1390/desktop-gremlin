# Desktop Gremlin audit and repair handoff

> **Historical.** All fifteen findings below were fixed and shipped. Kept for
> the reasoning, not as a to-do list. Superseded by `AUDIT_2026-09-12.md` and
> then by the 2026-09-20 pass, whose one behavioural finding is recorded in
> CLAUDE.md under "A saved score with no decay is a ratchet".

Audit date: 2026-09-05. The initial audit was read-only. The user has now
authorized Codex to implement all findings and the related test improvements.
Codex is handling the fixes in this workspace; this document is a handoff for
Claude to understand the problems and review the resulting changes.

The locations below refer to the source before the fixes. Function names remain
the best references as line numbers change. No actual desktop icons or windows
were moved during the audit: reproductions used isolated in-memory stubs.

## Findings and intended repairs

1. **High: background scans can freeze animation and controls.**
   `Scanner._run` (1508) holds the result lock during the entire desktop scan;
   the frame's `Scanner.take` waits on the same lock. A slow fake scan proved
   the polling call blocks. Scan outside the lock and lock only to exchange
   finished results. Test polling latency while a scan is deliberately blocked.

2. **High: failed icon reads can create a false recovery snapshot.**
   `ShellView.item_pos` (671) ignores write/message/read failure and can return
   `(0, 0)`. `snapshot` then saves those coordinates as valid. Reject failed or
   incomplete snapshots and preserve the last validated recovery layout.

3. **High: a partial restore is marked complete.**
   `restore_layout` (871) clears the dirty flag after any positive restore count.
   Restoring one of two icons reproduced this. Track and verify restore
   completion; retain recovery protection when applicable icons fail to restore.

4. **High: failed writes can destroy the sole icon backup.**
   `_write_backup` (793) truncates the existing file. An injected mid-write
   failure left no readable backup while `BACKUP_OK` stayed true. In addition,
   `mark_layout_dirty` sets its in-memory flag before persistence succeeds and
   never retries. Use atomic replacement and persist protection before allowing
   icon movement; handle failures without claiming that recovery is safe.

5. **Medium: active icon carries ignore disable and restore operations.**
   `carry_tick` (3013) continues moving icons after `move_icons` is turned off.
   Both restore controls leave carry/surf activity running, so the next tick can
   move a restored icon again. Cancel active movement before restoring or when
   disabled, and gate ongoing movement updates.

6. **Medium: damage can strand a carried icon.**
   `hit_fighter` (3768) cleans up rides but not a victim's carry. A nonfatal hit
   changes carry to thrown, then idle, with the carry claim still populated.
   Release the carried icon when damage interrupts the activity, including KO.

7. **Medium: fighters can disappear on uneven or stacked monitors.**
   `update_fighter` (4051) selects the floor using X alone. `physics` (4771)
   only catches a floor crossing from above, and recovery checks only horizontal
   escape. Stacked-monitor and unequal-height transitions reproduced indefinite
   falling below the desktop. Select monitors using both coordinates, resolve
   the floor after horizontal movement, and recover below-screen positions.

8. **Medium: disabling reactions defeats active-window movement protection.**
   `nudge_window` (3498) uses a foreground cache that updates only when
   `react_to_windows` is on. With reactions off and window movement on, the
   window receiving current input can be nudged. Check the real foreground
   window independently of the reaction preference.

9. **Medium: fast projectiles skip opponents at low FPS.**
   `projectiles` (4987) tests only the new point. At default scale and 15 FPS,
   a pellet crossed an opponent's entire hitbox without registering a hit;
   battery mode at 20 FPS can also expose this. Test the traveled segment and
   resolve the first collision, preserving reflection and projectile behavior.

10. **Medium: Explorer restart removes tray controls.**
    `Tray.build` (1134) has no `TaskbarCreated` handler to re-add its icon after
    Explorer recreates the taskbar. Add the handler and an isolated regression.
    Reference: https://learn.microsoft.com/en-us/windows/win32/shell/taskbar#taskbar-creation-notification

11. **Medium: a rejected second launch erases the current diagnostic log.**
    `main` (6167) opens the log with truncation before claiming the instance
    mutex. Claim the instance first and preserve the active run's log.

12. **Medium: settings report success even when persistence fails.**
    `SettingsWindow.apply` (1367) ignores settings/startup failures, and Forget
    reports success even if memory remains on disk. Return failure information
    from persistence operations and display accurate status messages.

13. **Hardening: reject nonfinite settings.**
    `load_settings` accepts NaN for scale, chaos, and idle duration. Scale can
    then break rendering. Validate each numeric setting as finite, retaining
    valid unrelated settings when another value is invalid.

14. **Test isolation and regression coverage.**
    The harness redirects four persisted paths but `Tray.build` still writes
    the real `gremlin.ico`; initial App construction also reads the real shell
    before fake terrain is installed. Sandbox the icon and install shell/OS
    stubs before construction. Cover all failures above, including low FPS,
    monitor topology, polling latency, and persistence fault injection.

15. **Diagnostics: preserve the first frame-error traceback.**
    Normal frame-loop errors print only exception text, then suppress output
    after 20 errors. Preserve the first full traceback without flooding the log.

## Audit validation

All 21 Python files compiled in memory. The scanner, backup failures, carry
interruption/disable, monitor disappearance, low-FPS collision, and settings
failure reporting were reproduced with in-memory stubs. Tray recreation was
checked against Microsoft's documented behavior. The original full suite was
not run during the read-only audit because it creates files and windows.

## Implementation status

All 15 findings above have been addressed in the working tree. The app's
single-file structure is preserved; no commit or push was made.

Final validation on Windows with Python 3.14 and pywin32 312:

```powershell
.\.venv\Scripts\python.exe -B tests\run_all.py
```

**22/22 checks passed in 11 seconds.** The local `.venv` contains the project's
declared dependency so this command is ready for Claude to repeat.

The new regression files are:

- `tests/test_audit_shell.py`: failed/partial Explorer reads, malformed
  snapshots, atomic-save failures, dirty-before-move ordering, retries,
  and final read-back verification after complete and partial restores.
- `tests/test_audit_runtime.py`: 14 checks covering nonblocking polling,
  queued scans, tray recreation, duplicate-launch logging, monitor topology,
  primary-screen selection, recovery, and bounded traceback logging.
- `tests/test_audit_behaviour.py`: 31 checks covering carry cancellation,
  interrupted deliveries, current foreground protection, secondary-window
  movement, swept nearest-hit collision, pan reflection, and monitor seams.
- `tests/test_audit_settings.py`: five tests covering finite validation,
  independent field recovery, atomic persistence failure, accurate UI status,
  retrying Forget, and harness isolation.

Existing regression suites also passed, including poses, gait, joints, weapon
range, muzzle alignment, fights, rides, window play, crowd performance, roaming,
settings, memory, runtime, and documentation. The roaming check now includes
escape below the screen. Selected deliberately reintroduced bugs failed their
new checks, confirming that the tests detect the original mechanisms.

Independent review also caught and resolved integration edge cases: a primary-
only overlay must not pull a secondary window onto the primary screen; a shot
must not collide with a higher monitor floor before reaching its seam; and a
previously fired shot or Summon must not strand its owner's carried icon.

`git diff --check` passed. All 25 Python files also parsed with Python 3.8
syntax rules; this is a syntax check, not a separate Python 3.8 runtime test.
Hash comparisons around the final suite confirmed that all five actual runtime
files (settings, icon backup, memory, log, and tray icon) were unchanged.

Explorer restart and real icon/window movements were simulated through stubs;
the user's desktop was not rearranged. Tk and the existing application code
were exercised by the suite. Restart an already-running Desktop Gremlin process
to load the repaired source.
