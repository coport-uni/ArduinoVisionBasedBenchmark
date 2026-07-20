# Arduino Uno Q — ADB Access and Wi-Fi Setup (Windows Host)

Reproducible procedure for bringing an Arduino Uno Q onto the network from a
Windows host over ADB. Every step is a command you can re-run; the observed
values from the first run are recorded in [Appendix A](#appendix-a--reference-values)
for comparison, not as inputs to copy blindly.

The Uno Q runs Debian 13 (trixie) on aarch64, so networking is configured with
NetworkManager (`nmcli`), not with Android tooling — ADB is only the transport.

---

## 1. Prerequisites

| Requirement | Notes |
|---|---|
| Uno Q connected by USB | Use the USB-C port that enumerates ADB, not a charge-only cable |
| Windows 10/11 with `winget` | Ships with App Installer |
| PowerShell | `cmd` works equally well; see [§6](#6-troubleshooting) on PATH |

No USB driver install is needed. Windows binds the Uno Q's ADB interface to its
in-box driver automatically.

---

## 2. Confirm the board enumerates

Run before installing anything — if the board is not visible here, no amount of
ADB setup will help.

```powershell
Get-PnpDevice -PresentOnly |
    Where-Object { $_.InstanceId -like "USB\VID_2341*" } |
    Select-Object Status, Class, FriendlyName, InstanceId |
    Format-Table -AutoSize
```

`VID_2341` is Arduino's USB vendor ID. Expect two interfaces from one composite
device:

- `MI_00` — class `USBDevice`, name **ADB Interface**
- `MI_01` — class `Ports`, a **USB serial device** on some `COMn`

If `Status` is not `OK`, or only the serial interface appears, the problem is
cabling or the board's boot state — resolve that before continuing.

---

## 3. Install ADB

```powershell
winget install --id Google.PlatformTools -e `
    --accept-source-agreements --accept-package-agreements
```

winget installs the package and registers `adb` / `fastboot` aliases under
`%LOCALAPPDATA%\Microsoft\WinGet\Links`, which is already on the user PATH.

**The PATH change does not reach already-open terminals.** A running process
inherits its environment at launch, so `adb` stays unresolved in the window you
installed from — including `cmd`. Pick one:

```powershell
# a) Open a new terminal (in VS Code: new terminal, or reload the window)

# b) Refresh PATH in the current session
$env:Path = [Environment]::GetEnvironmentVariable("Path","Machine") + ";" +
            [Environment]::GetEnvironmentVariable("Path","User")

# c) Call the full path once
& "$env:LOCALAPPDATA\Microsoft\WinGet\Links\adb.exe" devices
```

Verify:

```powershell
adb version
adb devices -l
```

The board should appear as `<serial>  device`. State `unauthorized` or
`offline` means the daemon reached the board but the session is not usable —
see [§6](#6-troubleshooting).

Confirm you are on the intended target:

```powershell
adb shell "whoami; uname -a; cat /etc/os-release | head -3"
```

---

## 4. Connect to Wi-Fi

### 4.1 Check the radio and interface

```powershell
adb shell "nmcli radio wifi; nmcli dev status"
```

`wlan0` must be listed as type `wifi` and not `unmanaged`. If the radio is off:
`adb shell nmcli radio wifi on`.

### 4.2 Scan

```powershell
adb shell "nmcli dev wifi rescan; sleep 5; nmcli -f SSID,SIGNAL,SECURITY,FREQ dev wifi list"
```

The `sleep` matters — `rescan` returns immediately while results are still
arriving, so listing without a delay yields a stale or short list.

Choosing a band: prefer 5 GHz when the signal is strong and the board is
stationary (more bandwidth, less congestion — relevant for camera streaming).
Prefer 2.4 GHz if the board moves or sits behind walls.

### 4.3 Associate

Run this **in your own terminal**, not through an automation tool:

```powershell
adb shell -t "nmcli --ask dev wifi connect '<SSID>'"
```

`-t` forces a TTY so `nmcli --ask` prompts for the passphrase with echo
disabled. This keeps the secret out of shell history, process listings, and any
transcript. Do not use the `password <secret>` form on the command line.

NetworkManager stores the profile itself; the passphrase is never needed again
and is deliberately not recorded in this repository.

---

## 5. Verify

Link state alone is not proof of connectivity. Check each layer — a failure
tells you where the problem is.

```powershell
# L2/L3 — association, address, default route
adb shell "nmcli -f DEVICE,STATE,CONNECTION dev status | grep wlan0; ip -4 addr show wlan0 | grep inet; ip route | grep default"

# Reachability — local subnet, then internet, then name resolution
adb shell "ping -c 2 -W 3 <gateway>; ping -c 2 -W 3 8.8.8.8; getent hosts deb.debian.org"
```

| Symptom | Interpretation |
|---|---|
| No IP on `wlan0` | Associated but DHCP failed |
| Gateway ok, 8.8.8.8 fails | Router or upstream problem, not the board |
| 8.8.8.8 ok, `getent` fails | DNS misconfiguration; `apt` will fail |

Confirm the profile survives a reboot:

```powershell
adb shell "nmcli -f connection.id,connection.autoconnect con show '<SSID>'"
```

`connection.autoconnect: yes` is required for unattended use.

---

## 6. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `adb` not recognized | Terminal predates the PATH change | [§3](#3-install-adb), options (a)–(c). Switching to `cmd` does **not** help |
| `adb devices` empty | Daemon started before the board enumerated | `adb kill-server`, then `adb devices` |
| `unauthorized` | Host key not accepted on the board | Reconnect USB; check the board's ADB authorization setting |
| Scan returns few networks | Listed before the scan completed | Keep the `sleep 5` in [§4.2](#42-scan) |
| Connects, no internet | Captive portal, or wrong band/SSID | Re-check with the layered tests in [§5](#5-verify) |

---

## 7. After setup

With Wi-Fi up, the board is reachable without USB:

```powershell
ssh arduino@<board-ip>
```

The address comes from DHCP and can change. For a stable target, reserve it by
MAC on the router or assign a static address on the board. Get the MAC with:

```powershell
adb shell "cat /sys/class/net/wlan0/address"
```

---

## Appendix A — Reference values

Recorded from the first successful run, 2026-07-20. Treat these as a
comparison baseline; your own values will differ.

| Item | Value |
|---|---|
| Host OS | Windows 11 Education, 10.0.26200 |
| platform-tools | 37.0.1 (`adb` 1.0.41) |
| Board USB ID | `VID_2341&PID_0078` (ADB on `MI_00`, serial on `MI_01`) |
| Board OS | Debian GNU/Linux 13 (trixie), kernel 6.16.7, aarch64 |
| Board user / hostname | `arduino` / `SungwooQ` |
| SSID | `XiaomiDorm55` (5 GHz, WPA2-PSK) |
| Address / gateway | 192.168.31.84/24 (DHCP) via 192.168.31.1 |
| Negotiated rate | 540 Mbit/s at signal 100 |
| Latency | 18 ms to gateway, 76 ms to 8.8.8.8 |

The 18 ms gateway RTT is high for a strong 5 GHz link and is consistent with
Wi-Fi power saving on the board. It was left enabled — it is harmless for
interactive shell use. If latency-sensitive work (camera streaming) shows
stutter, disabling power save is the first thing to try:

```powershell
adb shell "iw dev wlan0 get power_save"
```
