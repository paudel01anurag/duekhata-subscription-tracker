"""Windows desktop notifications for DueKhata.

Deliberately free of any Tkinter import, so the daily reminder check can run
without building a user interface. Nothing here reaches the network: a toast is
raised by the local Windows notification service and goes no further than this
machine.

The toast is built as XML and handed to WinRT through PowerShell, which avoids
adding a third-party package to a project that has exactly one runtime
dependency. Registering an AppUserModelId under HKCU is what makes the toast say
"DueKhata" rather than "Windows PowerShell"; it is a per-user registry value and
`unregister_app_id` removes it again.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import List

APP_ID = "Anurag.DueKhata"
APP_DISPLAY_NAME = "DueKhata"

# Toast XML is not HTML: an unescaped & or < breaks the whole notification
# rather than showing oddly, so every value is escaped before it goes in.
_XML_ESCAPES = (("&", "&amp;"), ("<", "&lt;"), (">", "&gt;"), ('"', "&quot;"), ("'", "&apos;"))


def _escape(text: str) -> str:
    for character, replacement in _XML_ESCAPES:
        text = text.replace(character, replacement)
    return text


def is_supported() -> bool:
    """Toasts are a Windows facility. Everywhere else this is a no-op."""
    return sys.platform == "win32"


def _run_powershell(script: str, timeout: int = 25) -> tuple:
    """Run a PowerShell snippet, returning (ok, output).

    Never raises: a reminder failing to appear must not take the application
    down with it, and the caller decides whether the failure is worth saying
    anything about.
    """
    try:
        completed = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy", "Bypass",
                "-Command", script,
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError) as error:
        return False, str(error)

    output = (completed.stdout or "") + (completed.stderr or "")
    return completed.returncode == 0, output.strip()


def register_app_id() -> bool:
    """Make toasts carry the DueKhata name. Safe to call repeatedly."""
    if not is_supported():
        return False
    script = (
        "$key = 'HKCU:\\Software\\Classes\\AppUserModelId\\" + APP_ID + "';"
        "if (-not (Test-Path $key)) { New-Item -Path $key -Force | Out-Null };"
        "New-ItemProperty -Path $key -Name 'DisplayName' -Value '" + APP_DISPLAY_NAME + "'"
        " -PropertyType String -Force | Out-Null"
    )
    ok, _output = _run_powershell(script)
    return ok


def unregister_app_id() -> bool:
    """Remove the registry value again, leaving the machine as it was found."""
    if not is_supported():
        return False
    script = (
        "$key = 'HKCU:\\Software\\Classes\\AppUserModelId\\" + APP_ID + "';"
        "if (Test-Path $key) { Remove-Item -Path $key -Recurse -Force }"
    )
    ok, _output = _run_powershell(script)
    return ok


def toast_xml(heading: str, body: str) -> str:
    """The notification document Windows will be given.

    Attributes use double quotes so the whole document contains no single
    quote, which is what lets it sit inside a PowerShell literal string.
    """
    return (
        '<toast><visual><binding template="ToastGeneric">'
        "<text>" + _escape(heading) + "</text>"
        "<text>" + _escape(body) + "</text>"
        "</binding></visual></toast>"
    )


def _toast_script(xml: str) -> str:
    """Wrap the document in PowerShell that shows it.

    The XML goes inside a **single-quoted** PowerShell string. A double-quoted
    one - including the here-string used before - expands variables, so an
    amount like $22.99 arrived as .99: PowerShell read `$22` as a variable,
    found nothing, and substituted emptiness. Single quotes take text literally.

    Any single quote inside is doubled, PowerShell's own escape, although
    `_escape` has already turned quotes into entities by this point.
    """
    literal = xml.replace("'", "''")
    return (
        "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications,"
        " ContentType = WindowsRuntime] > $null;"
        "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom,"
        " ContentType = WindowsRuntime] > $null;"
        "$doc = New-Object Windows.Data.Xml.Dom.XmlDocument;"
        "$doc.LoadXml('" + literal + "');"
        "$toast = New-Object Windows.UI.Notifications.ToastNotification $doc;"
        "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('"
        + APP_ID + "').Show($toast)"
    )


def show_toast(heading: str, body: str) -> bool:
    """Raise one desktop notification. Returns whether Windows accepted it."""
    if not is_supported():
        return False
    ok, _output = _run_powershell(_toast_script(toast_xml(heading, body)))
    return ok


def show_reminders(reminders: List, today) -> int:
    """Announce each reminder. Returns how many Windows accepted.

    One toast per item rather than a single digest: they are separate
    obligations with separate dates, and a digest would bury the one that
    matters behind the ones that do not.
    """
    shown = 0
    for reminder in reminders:
        if show_toast(reminder.headline(), reminder.detail(today)):
            shown += 1
    return shown


# --- the daily check -----------------------------------------------------
#
# DueKhata does not run in the background. Windows Task Scheduler runs it once
# a day, it looks at what is coming, raises any toast that is due, and exits.
# That is the whole mechanism: no service, no server, no network.

TASK_NAME = "DueKhata Daily Reminder"


def check_command() -> str:
    """The command the scheduled task should run.

    Packaged, that is the executable itself. From source it is pythonw rather
    than python, so the daily check never flashes a console window.
    """
    if getattr(sys, "frozen", False):
        return '"' + sys.executable + '" --check-due'

    launcher = Path(sys.executable).with_name("pythonw.exe")
    if not launcher.exists():
        launcher = Path(sys.executable)
    script = Path(__file__).with_name("main.py")
    return '"' + str(launcher) + '" "' + str(script) + '" --check-due'


def _run_schtasks(arguments: list) -> tuple:
    """Call schtasks directly rather than through PowerShell.

    Going via PowerShell meant the command string was quoted twice and stripped
    once, so a path containing spaces — which this project's does — arrived at
    schtasks broken in half.
    """
    try:
        completed = subprocess.run(
            ["schtasks"] + arguments,
            capture_output=True,
            text=True,
            timeout=25,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError) as error:
        return False, str(error)
    output = ((completed.stdout or "") + (completed.stderr or "")).strip()
    return completed.returncode == 0, output


def is_scheduled() -> bool:
    if not is_supported():
        return False
    ok, _output = _run_schtasks(["/Query", "/TN", TASK_NAME])
    return ok


def schedule_daily_check(at_time: str = "09:00") -> tuple:
    """Create or replace the daily task. Returns (ok, message)."""
    if not is_supported():
        return False, "Desktop reminders are a Windows feature."

    ok, output = _run_schtasks(
        ["/Create", "/TN", TASK_NAME, "/TR", check_command(),
         "/SC", "DAILY", "/ST", at_time, "/F"]
    )
    if ok:
        return True, "Windows will check once a day at " + at_time + "."
    return False, output or "Windows would not create the scheduled task."


def remove_scheduled_check() -> tuple:
    if not is_supported():
        return False, "Desktop reminders are a Windows feature."
    ok, output = _run_schtasks(["/Delete", "/TN", TASK_NAME, "/F"])
    if ok:
        return True, "The daily check has been removed."
    return False, output or "Windows would not remove the scheduled task."
