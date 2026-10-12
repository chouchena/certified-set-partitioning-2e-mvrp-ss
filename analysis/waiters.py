"""List every armed waiter and running job on this host: bash/sh scripts (queues, waiters) and
python processes with their command lines and parents. Run BEFORE arming any queue or waiter
(d385: two queues fired at once because the second was written without listing the first).

    python analysis/waiters.py
Exit code 0; prints a table. Windows-only (WMI via PowerShell).
"""
import json
import subprocess
import sys

PS = r"""
$all = Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^(python|bash|sh)(\.exe)?$' }
$all | Select-Object ProcessId, ParentProcessId, Name, CommandLine | ConvertTo-Json -Compress
"""


def main():
    out = subprocess.run(["powershell", "-NoProfile", "-Command", PS], capture_output=True, text=True)
    try:
        rows = json.loads(out.stdout or "[]")
    except Exception:
        print(out.stdout[:2000]); print(out.stderr[:2000]); return 1
    if isinstance(rows, dict):
        rows = [rows]
    keep = []
    for r in rows:
        cmd = (r.get("CommandLine") or "")
        if "shell-snapshots" in cmd and "source" in cmd and len(cmd) < 400:
            continue                                   # the harness's own wrapper shells
        keep.append(r)
    print("%-7s %-7s %-10s %s" % ("pid", "parent", "name", "command (queues, waiters, jobs)"))
    for r in keep:
        cmd = (r.get("CommandLine") or "").replace("\n", " ")
        if "shell-snapshots" in cmd:
            i = cmd.find("&&")
            cmd = "[harness shell] " + (cmd[i + 2:] if i >= 0 else cmd[-160:])
        print("%-7s %-7s %-10s %s" % (r.get("ProcessId"), r.get("ParentProcessId"), r.get("Name"), cmd[:220]))
    print("\n%d processes. Arm nothing that a listed waiter already covers." % len(keep))
    return 0


if __name__ == "__main__":
    sys.exit(main())
