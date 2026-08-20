# ADL Agent — Windows Desktop Technology Landscape

- **Issue:** [#261](https://github.com/wmo-raf/adl/issues/261) (part of wayfinder map #258)
- **Date:** 2026-08-20
- **Question:** Survey the realistic technology options for the ADL Agent — a Windows desktop app installed on NMHS servers (often old, locked-down Windows Server 2012+ machines, sometimes without admin rights, behind restrictive networks with outbound-only internet) that watches local folders of weather-station data files and uploads raw files to a Django-based ADL server over HTTPS. Needs: small config/login UI; reliable background operation with auto-restart (Windows Service or equivalent); update checking / auto-update.
- **Candidates:** .NET (WPF/WinUI + Windows Service), Tauri, Electron, Python (PyInstaller/Briefcase).
- **Method:** All claims traced to primary sources (Microsoft Learn/lifecycle docs, dotnet/core release notes, tauri.app, electronjs.org, electron.build, python.org/PEPs, pyinstaller.org, project GitHub repos, CA/Browser Forum ballots, CA pricing pages). Each claim carries its source link.

---

## 1. Cross-cutting Windows platform facts

These constraints apply to **every** candidate and shape the whole decision.

### 1.1 Windows Server lifecycle — how real is the 2012 target?

| OS | Extended support ended/ends | ESU end |
|---|---|---|
| Windows Server 2012 | Oct 10, 2023 | **Oct 13, 2026** (ESU Year 3) |
| Windows Server 2012 R2 | Oct 10, 2023 | **Oct 13, 2026** |
| Windows Server 2016 | **Jan 12, 2027** | — |
| Windows Server 2019 | **Jan 9, 2029** | — |

Sources: Microsoft lifecycle pages for [2012](https://learn.microsoft.com/en-us/lifecycle/products/windows-server-2012), [2012 R2](https://learn.microsoft.com/en-us/lifecycle/products/windows-server-2012-r2), [2016](https://learn.microsoft.com/en-us/lifecycle/products/windows-server-2016), [2019](https://learn.microsoft.com/en-us/lifecycle/products/windows-server-2019); [ESU FAQ](https://learn.microsoft.com/en-us/lifecycle/faq/extended-security-updates) ("Windows Server 2012/R2 … ESU End Date Year 3: October 13, 2026").

Microsoft frames ESU as "a last resort paid option … a temporary bridge", covering only Critical/Important security updates, priced at 100% of the full license price annually — realistically out of reach for many NMHS budgets ([ESU FAQ](https://learn.microsoft.com/en-us/lifecycle/faq/extended-security-updates)). **By the time the ADL Agent ships, Server 2012/2012 R2 will be past even ESU and fully unpatched.** The design center should be Server 2016+; 2012-era boxes should be treated as best-effort legacy, and the framework choice decides whether "best effort" is even possible.

### 1.2 No-admin installs: what Windows actually allows

What a per-user (non-elevated) install **can** do:

- **Per-user MSI / installer**: MSI's per-user installation context installs without UAC credentials; per-machine (`ALLUSERS=1`) fails without admin ([ALLUSERS doc](https://learn.microsoft.com/en-us/windows/win32/msi/allusers)). NSIS, Inno Setup, electron-builder, Tauri NSIS, and Velopack all offer per-user `%LOCALAPPDATA%` installs (sources in the per-candidate sections).
- **Start at logon**: HKCU `Run` key is writable by the user ([Run keys doc](https://learn.microsoft.com/en-us/windows/win32/setupapi/run-and-runonce-registry-keys)); a standard user can also register a **logon-triggered** scheduled task under their own account ([Task Scheduler security contexts](https://learn.microsoft.com/en-us/windows/win32/taskschd/security-contexts-for-running-tasks)).

What **requires admin**:

- **Installing a Windows Service** — SCM's security descriptor grants `SC_MANAGER_CREATE_SERVICE` only to Administrators ([service security](https://learn.microsoft.com/en-us/windows/win32/services/service-security-and-access-rights)).
- **Boot-triggered scheduled tasks** — "Only a member of the Administrators group can create a task with a boot trigger" ([BootTrigger](https://learn.microsoft.com/en-us/windows/win32/taskschd/boottrigger)); likewise tasks running as SYSTEM/elevated ([schtasks](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/schtasks-create)).
- Per-machine installs / HKLM writes ([ALLUSERS doc](https://learn.microsoft.com/en-us/windows/win32/msi/allusers)).

**Consequence — two install tiers are forced, regardless of framework:**

1. **Admin tier (preferred):** Windows Service with delayed auto-start + SCM failure actions. Survives reboot, runs with nobody logged in.
2. **No-admin tier (degraded):** per-user files + logon-triggered task / HKCU Run key. **Cannot start at boot** — after a reboot the agent is down until someone logs in. This must be documented as a hard limitation on unattended servers; it is a Windows constraint, not a framework one.

### 1.3 Windows Service reliability primitives

- **Recovery/auto-restart**: `SERVICE_FAILURE_ACTIONS` (or `sc.exe failure`) gives SCM-supervised restart-on-crash with escalating delays and no watchdog process ([SERVICE_FAILURE_ACTIONS](https://learn.microsoft.com/en-us/windows/win32/api/winsvc/ns-winsvc-service_failure_actionsa)).
- **Delayed auto-start** is available on every OS in scope ([SERVICE_DELAYED_AUTO_START_INFO](https://learn.microsoft.com/en-us/windows/win32/api/winsvc/ns-winsvc-service_delayed_auto_start_info)).
- **Session 0 isolation**: services cannot show UI. Microsoft's prescribed pattern is exactly a **headless service + separate GUI process communicating over IPC (e.g. named pipes)** ([interactive services doc](https://learn.microsoft.com/en-us/windows/win32/services/interactive-services)). The two-process design is not a choice; it is the only supported design.

### 1.4 Installer formats: MSIX is ruled out

MSIX is supported only on Windows 10 1709+ and **Windows Server 2019 LTSC and later**; Server 2019 lacks App Installer by default and MSIX-packaged services need Server 2022 ([MSIX supported platforms](https://learn.microsoft.com/en-us/windows/msix/supported-platforms)). No support on Server 2012/2012 R2/2016 at all. **Classic MSI or EXE (NSIS/Inno) installers are the only formats spanning the fleet**, and MSIX-based auto-update is off the table.

### 1.5 Code signing: effectively mandatory, and priced

- **SmartScreen**: unsigned installers show "Windows protected your PC", must rebuild reputation with every update, and "Enterprise policy can prevent continuation entirely" — i.e. on locked-down NMHS machines an unsigned installer may be a hard block ([SmartScreen reputation doc](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/smartscreen-reputation)). The same doc states **"EV certificates no longer bypass SmartScreen"** — no reason to pay EV premiums.
- **Hardware-key mandate**: since June 1, 2023 (CA/B Forum ballots [CSC-13](https://cabforum.org/2022/04/06/ballot-csc-13-update-to-subscriber-key-protection-requirements/), [CSC-17](https://cabforum.org/2022/09/27/ballot-csc-17-subscriber-private-key-extension/)), all publicly-trusted code-signing keys must live on FIPS 140-2 L2+ hardware or a cloud HSM — no more downloadable `.pfx` files.
- **Costs** (official pages, 2026): DigiCert OV $696/yr ([pricing](https://www.digicert.com/signing/code-signing-certificates)); Sectigo from ~$536/yr on 5-year terms ([pricing](https://sectigo.com/ssl-certificates-tls/code-signing)); SSL.com OV $129/yr + $379 YubiKey or cloud-HSM fees ([OV](https://www.ssl.com/products/software-integrity/code-signing/ov/)); **Certum "Open Source Code Signing" €69 incl. smartcard** — aimed at open-source projects like ADL ([Certum shop](https://shop.certum.eu/open-source-code-signing.html)).
- **Azure Trusted Signing (renamed Azure Artifact Signing)**: $9.99/mo Basic, signs anything SignTool signs — but Public Trust is limited to organizations in the US/CA/EU/UK/AU/NZ/JP/KR/SG/CH/NO/IL, individuals US/Canada only ([quickstart prerequisites](https://learn.microsoft.com/en-us/azure/artifact-signing/quickstart), [FAQ](https://learn.microsoft.com/en-us/azure/artifact-signing/faq)). **An African NMHS or regional body is not eligible directly**; a partner org in a listed region could sign on the project's behalf.

Budget path for ADL: **Certum's €69 open-source certificate**, or Azure Artifact Signing via an eligible partner organization.

### 1.6 TLS for the HTTPS upload path

TLS 1.2 is enabled by default (client + server) on Windows 8/Server 2012 through Server 2019 ([Schannel protocol table](https://learn.microsoft.com/en-us/windows/win32/secauthn/protocols-in-tls-ssl--schannel-ssp-)). TLS 1.3 exists only on Server 2022+/Windows 11 and "Enabling TLS 1.3 on earlier versions of Windows is not a safe system configuration" (same source). **The ADL server's HTTPS endpoint must keep TLS 1.2 enabled; it must not require TLS 1.3.**

---

## 2. Candidate: .NET (WPF + Worker Service)

### OS support — the standout

- Every current .NET release's official supported-OS matrix lists **Windows Server back to 2012 (x64), incl. Server Core**, with the caveat "supported with Extended Security Updates (ESU)": [.NET 8](https://github.com/dotnet/core/blob/main/release-notes/8.0/supported-os.md), [.NET 9](https://github.com/dotnet/core/blob/main/release-notes/9.0/supported-os.md), [.NET 10](https://github.com/dotnet/core/blob/main/release-notes/10.0/supported-os.md).
- Lifecycle: .NET 8 LTS and .NET 9 STS both end **Nov 10, 2026**; **.NET 10 is the active LTS, supported to Nov 14, 2028** ([support policy](https://dotnet.microsoft.com/en-us/platform/support/policy/dotnet-core)). Target .NET 10.
- .NET Framework 4.8 is installable (not preinstalled) on Server 2012/2012 R2, but installation requires admin ([system requirements](https://learn.microsoft.com/en-us/dotnet/framework/get-started/system-requirements)); it is preinstalled on Server 2019+. A **self-contained modern .NET publish needs no runtime install at all** — the decisive advantage for no-admin environments.
- **WinUI 3 is disqualified**: Windows App SDK requires Windows 10 1809+ **client SKUs**; Windows Server is never listed as supported ([system requirements](https://learn.microsoft.com/en-us/windows/apps/windows-app-sdk/system-requirements), [FAQ](https://learn.microsoft.com/en-us/windows/apps/get-started/windows-developer-faq)), and its default packaging is MSIX (§1.4). **Use WPF**, which Microsoft calls "supported, recommended, and continues to receive feature updates" (same FAQ; [WPF roadmap](https://github.com/dotnet/wpf/blob/main/roadmap.md)).

### Process model

Microsoft documents the exact target shape end-to-end: Worker Service template + `Microsoft.Extensions.Hosting.WindowsServices` + `AddWindowsService()`, published self-contained single-file, registered via `sc.exe create`, with **SCM recovery configured via `sc.exe failure`** and guidance to `Environment.Exit(1)` on fatal errors so recovery actions actually fire ([Windows Service tutorial](https://learn.microsoft.com/en-us/dotnet/core/extensions/windows-service)). Logging to Event Log is built in. Tray/config UI runs as a separate WPF app over named pipes ([named pipes IPC](https://learn.microsoft.com/en-us/dotnet/standard/io/how-to-use-named-pipes-for-network-interprocess-communication)) or gRPC-over-named-pipes ([doc](https://learn.microsoft.com/en-us/aspnet/core/grpc/interprocess-namedpipes)). The identical worker exe runs as a plain per-user process for the no-admin tier (`AddWindowsService` no-ops outside SCM).

### Installer + auto-update

- **Admin tier**: WiX/MSI (works on every OS in scope) installs the service; service self-update via a small custom download-verify-swap-restart step (SCM restarts it).
- **No-admin tier**: **ClickOnce** — Microsoft-supported, "installs are per-user … no administrative rights are required", self-updating from a plain HTTPS URL ([ClickOnce deployment](https://learn.microsoft.com/en-us/visualstudio/deployment/clickonce-security-and-deployment); modern-.NET caveats: [doc](https://learn.microsoft.com/en-us/visualstudio/deployment/clickonce-deployment-dotnet)). Or **Velopack** (MIT, actively developed successor to Squirrel/Clowd.Squirrel with automatic migrations): per-user `%LocalAppData%` install, "does not require elevation", delta updates from any static HTTPS host ([docs](https://docs.velopack.io/packaging/operating-systems/windows), [repo](https://github.com/velopack/velopack)).

### Footprint & offline resilience

Self-contained worker exe ≈ 35–70 MB untrimmed, ~16–25 MB trimmed (Microsoft's own measurements: [app trimming blog](https://devblogs.microsoft.com/dotnet/app-trimming-in-net-5/)). **WPF cannot be trimmed** ([trimming incompatibilities](https://learn.microsoft.com/en-us/dotnet/core/deploying/trimming/incompatibilities)); a self-contained WPF UI is ~150 MB ([dotnet/wpf#7447](https://github.com/dotnet/wpf/issues/7447)) — acceptable as a one-time install artifact, or ship the UI framework-dependent/as .NET Framework 4.8 WPF on Server 2019+. Self-contained publish means runtime security patches ship through the agent's own update channel — no dependence on Windows Update or admin touches ([deployment doc](https://learn.microsoft.com/en-us/dotnet/core/deploying/)).

### Maintainability

C# is a new language for the team but the closest mainstream typed language to modern typed Python (async/await, LINQ, records); the worker model (`ExecuteAsync` loop, DI, `appsettings.json`, `ILogger`) is conceptually close to a Celery worker + settings module. Everything except (optionally) Velopack is first-party Microsoft with an LTS runway to Nov 2028. The main skill risk is WPF/XAML — mitigated by keeping the config UI to a couple of forms.

---

## 3. Candidate: Tauri (v2)

### OS support — fails the old-server target

Tauri documents "Windows 7 and later" ([prerequisites](https://tauri.app/start/prerequisites/)), but the real gate is **WebView2**, whose supported OSes are "the same as those supported by Microsoft Edge" ([WebView2 intro](https://learn.microsoft.com/en-us/microsoft-edge/webview2/)). Microsoft's Edge supported-OS page records: **"01/12/2023 — Microsoft Edge support for Windows 7, Windows 8, Windows 8.1, Windows Server 2008 R2, Windows Server 2012, and Windows Server 2012 R2 ended in Edge version 109"** ([supported operating systems](https://learn.microsoft.com/en-us/deployedge/microsoft-edge-supported-operating-systems)). On Server 2012/2012 R2 a Tauri app can only run on a frozen, unpatched WebView2 109 (Jan 2023) that is increasingly hard to even obtain ([Microsoft Q&A](https://learn.microsoft.com/en-us/answers/questions/1332623/microsoft-webview2-runtime-109-0-1518-115-offline)). Server 2016/2019/2022 are supported, but Server 2016 ships without the runtime — the installer must deploy it.

### Process model — fails the service requirement

- **No Windows Service mode.** Microsoft explicitly blocks it: "We explicitly disallow running the WebView2 processes as SYSTEM for security reasons" ([WebView2Feedback#2434](https://github.com/MicrosoftEdge/WebView2Feedback/issues/2434), closed "not planned"; non-interactive use also flagged in [#1600](https://github.com/MicrosoftEdge/WebView2Feedback/issues/1600)). The UI half of a Tauri app requires an interactive logged-in session.
- Tray + hidden-window support is first-class ([system tray](https://tauri.app/learn/system-tray/)); background work runs in the Rust backend or **sidecar binaries** — the sidecar docs explicitly bless PyInstaller-packaged Python ([sidecar](https://tauri.app/develop/sidecar/)).
- Autostart plugin writes HKCU Run — no admin, but logon-only, and there is no supervisor/auto-restart; a watchdog would be DIY ([autostart plugin](https://github.com/tauri-apps/plugins-workspace/tree/v2/plugins/autostart), [auto-launch crate](https://github.com/zzzgydi/auto-launch)).

### Installer, updater, footprint, signing

- NSIS (`currentUser` default, "no admin required", `%LOCALAPPDATA%`) and WiX/MSI bundlers; WebView2 deployment modes from a 0 MB `downloadBootstrapper` to a **~127 MB `offlineInstaller`** (which restrictive networks likely force) ([Windows installer guide](https://tauri.app/distribute/windows-installer/)). Non-admin per-user WebView2 runtime install is possible ([distribution doc](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/distribution)).
- Official updater plugin: static-JSON-over-HTTPS (the Django server can host it), **mandatory minisign signing that "cannot be disabled"** and is independent of OS code signing; per-user installs update silently without elevation ([updater plugin](https://tauri.app/plugin/updater/)).
- App binary can be tiny ("as little as 600KB", [tauri.app](https://tauri.app/)), but the WebView2 offline installer dominates real installer size. Signing guidance: [Windows signing doc](https://tauri.app/distribute/sign/windows/).

### Maintainability

Frontend is plain web tech (reusable skill); the backend — folder watching, retry queues, credential storage — is **Rust**, a real learning curve for a Python team unless most logic moves into a Python sidecar (at the cost of a second runtime).

### Verdict

Excellent per-user install/update ergonomics, but **fails two hard constraints**: no Server 2012/2012 R2 support (WebView2 ended Jan 2023) and no true service/headless mode (Microsoft explicitly disallows it). Only workable on Server 2016+ with an always-logged-in session.

---

## 4. Candidate: Electron

### OS support

- **Windows 7/8/8.1 (= Server 2012/2012 R2 kernels) were dropped in Electron 23** (Chromium 110); "Electron 22 … will be the last Electron major version to support Windows versions older than 10", with Electron 22 EOL extended only to **October 10, 2023** to match Server 2012's end of updates ([official deprecation notice](https://www.electronjs.org/blog/windows-7-to-8-1-deprecation-notice)). Serving 2012-era boxes means shipping a permanently vulnerable, 3-years-EOL Electron 22.
- Current support: "Windows 10 and up" ([README](https://github.com/electron/electron/blob/main/README.md)); a new major every **8 weeks** with only the latest 3 majors supported — a perpetual ~6-month patch treadmill ([release timelines](https://www.electronjs.org/docs/latest/tutorial/electron-timelines)).

### Process model

Tray apps and hidden windows are supported ([Tray API](https://www.electronjs.org/docs/latest/api/tray)); run-at-login via `app.setLoginItemSettings` (HKCU, no admin) ([app API](https://www.electronjs.org/docs/latest/api/app)). **No Windows Service support at all** in the official API surface, and no watchdog/crash-restart beyond self-initiated `app.relaunch()` — a crashed agent stays dead until next logon.

### Installer + auto-update

- electron-builder NSIS default is one-click, per-user, no elevation ([NSIS docs](https://www.electron.build/docs/nsis/)); an MSI target exists but is "Not supported via electron-updater" ([MSI docs](https://www.electron.build/docs/msi/)).
- Built-in `autoUpdater` = **Squirrel.Windows**, whose repo is begging for maintainers with its last release in **September 2020** ([repo](https://github.com/Squirrel/Squirrel.Windows), [releases](https://github.com/Squirrel/Squirrel.Windows/releases)). The de facto mechanism is **electron-updater** (NSIS only), self-hostable on any static HTTPS server, with Authenticode validation of downloaded installers ([auto-update docs](https://www.electron.build/docs/features/auto-update/)).

### Footprint

The prebuilt runtime zip alone is **150.2 MB compressed** ([electron v43.4.1 release](https://github.com/electron/electron/releases/tag/v43.4.1)); installed size lands in the 250–350 MB range with a full Chromium multi-process stack resident for a UI that is almost never open. Heaviest option by far for old, low-RAM servers.

### Verdict

Good per-user install and self-hosted update story, but: EOL-framework-only on Server 2012/2012 R2; no service story; the heaviest footprint; and an 8-week Chromium rebuild treadmill for a small Python/Django team. Not a fit.

---

## 5. Candidate: Python (PyInstaller / Briefcase)

### OS support

- CPython minimums ([Using Python on Windows](https://docs.python.org/3/using/windows.html), [PEP 11](https://peps.python.org/pep-0011/)): 3.9–3.12 support "Windows 8.1 and newer"; **3.14 requires Windows 10+** and directs 8.1 users to 3.12. Mapping: **Server 2012 (non-R2) → only EOL Python 3.8; Server 2012 R2 → Python 3.12 ceiling** (security fixes to ~Oct 2028, [PEP 693](https://peps.python.org/pep-0693/)); Server 2016+ → any current Python.
- PyInstaller: "runs in Windows 8 and newer", actively maintained ([requirements](https://pyinstaller.org/en/stable/requirements.html), [PyPI](https://pypi.org/project/pyinstaller/)).

### Windows Service

pywin32's `win32serviceutil` explicitly supports frozen executables (`sys.frozen` → the exe itself is the service binary) ([source](https://github.com/mhammond/pywin32/blob/main/win32/Lib/win32serviceutil.py)); alternatively **WinSW** (MIT, active; .NET Framework build runs on 2012-era boxes) or **NSSM** (public domain, dormant since 2017) wrap any exe as a service with restart-on-failure ([WinSW](https://github.com/winsw/winsw), [NSSM](https://nssm.cc/download)). Service install needs admin (§1.2), same as everyone.

### UI, installer, update

- Config UI: Tkinter ships with CPython ([docs](https://docs.python.org/3/library/tkinter.html)); tray via pystray (beta, single-maintainer, LGPLv3, last release 2023 — [PyPI](https://pypi.org/project/pystray/)); or a **local web UI on 127.0.0.1** — plain stdlib, and the team already writes Django templates; pairs naturally with the headless-service + browser-UI split.
- Installer: PyInstaller **one-dir** (one-file re-extracts on every launch and is warned against for elevated use — [operating mode](https://pyinstaller.org/en/stable/operating-mode.html)) + Inno Setup `PrivilegesRequired=lowest` ([doc](https://jrsoftware.org/ishelp/topic_setup_privilegesrequired.htm)) or NSIS `RequestExecutionLevel user` ([doc](https://nsis.sourceforge.io/Reference/RequestExecutionLevel)) for per-user installs. Briefcase produces WiX MSIs with a per-user option but requires Python 3.10+ and is less trodden for old servers ([Briefcase Windows](https://briefcase.beeware.org/en/stable/reference/platforms/windows/index.html)).
- Auto-update: **PyUpdater is dead**; the only maintained purpose-built option is **tufup** (MIT, TUF-based signed metadata, delta patches, serves from any static HTTPS host — [repo](https://github.com/dennisvang/tufup)) — solid design but a small single-maintainer project. Otherwise roll-your-own "version endpoint → download one-dir bundle → swap on restart".

### The big liability: antivirus false positives

PyInstaller officially acknowledges endemic AV false positives as unfixable: malware authors use PyInstaller, so heuristics flag its output; "we have no control over other organisations' broken antivirus software" ([official issue template](https://github.com/pyinstaller/pyinstaller/blob/develop/.github/ISSUE_TEMPLATE/antivirus.md); mass-flagging examples [#8164](https://github.com/pyinstaller/pyinstaller/issues/8164), [#6754](https://github.com/pyinstaller/pyinstaller/issues/6754)). On locked-down NMHS servers where the team may not be able to whitelist, this is an operational risk that code signing only partially mitigates — expect occasional incidents where the agent is quarantined on a machine nobody can easily reach.

### Verdict

Lowest language barrier by far and a workable service story via pywin32/WinSW — but capped at Python 3.12 on 2012 R2 (and EOL 3.8 on 2012), a thin auto-update ecosystem, and officially-acknowledged endemic AV false positives on exactly the class of locked-down machines this agent targets.

---

## 6. Comparison matrix

| Criterion | .NET 10 (WPF + Worker Service) | Tauri v2 | Electron | Python (PyInstaller) |
|---|---|---|---|---|
| Server 2012/2012 R2 | ✅ In current LTS support matrix (ESU-conditioned) | ❌ WebView2 ended Jan 2023 | ❌ Requires EOL Electron 22 | ⚠️ 2012 R2: Py 3.12 ceiling; 2012: EOL Py 3.8 |
| Server 2016/2019 | ✅ | ✅ (must deploy WebView2) | ✅ | ✅ |
| True Windows Service | ✅ First-party (`AddWindowsService`, SCM recovery documented) | ❌ Microsoft disallows WebView2 as SYSTEM | ❌ None official | ✅ pywin32 / WinSW wrapper |
| Headless (nobody logged in) | ✅ | ❌ | ❌ | ✅ |
| Tray/config-UI two-process model | ✅ WPF + named pipes (Microsoft-prescribed pattern) | ✅ tray, but UI needs a session | ✅ tray, but UI needs a session | ✅ Tkinter/pystray or localhost web UI |
| No-admin per-user install | ✅ ClickOnce / Velopack / per-user MSI | ✅ NSIS currentUser | ✅ NSIS one-click | ✅ Inno/NSIS per-user |
| Auto-update (self-hosted HTTPS) | ✅ ClickOnce (first-party) or Velopack (active) | ✅ Official plugin, mandatory-signed | ✅ electron-updater (Squirrel is abandoned) | ⚠️ tufup (small project) or custom |
| Installer size | ~35–70 MB worker; WPF UI up to ~150 MB self-contained | Tiny app + ~127 MB offline WebView2 | ~150 MB runtime; 250–350 MB installed | ~15–40 MB (unofficial estimate) |
| AV / SmartScreen risk | Low (signed) | Low (signed) | Low (signed) | ❌ Endemic PyInstaller false positives (officially acknowledged) |
| Patch treadmill | LTS to Nov 2028; self-contained updates via own channel | Rust/plugin updates; WebView2 evergreen | New Chromium major every 8 weeks | CPython annual; deps manual |
| Team skill fit (Python/Django) | ⚠️ New language (C#), closest typed analogue | ❌ Rust backend | ⚠️ JS/Node toolchain | ✅ Native |

---

## 7. Recommendation

**Build the ADL Agent on .NET 10 LTS: a Worker Service (Windows Service) for the watcher/uploader core plus a small WPF tray/config app, talking over named pipes, published self-contained single-file.**

Rationale:

1. **It is the only candidate whose current, supported runtime still covers the whole stated fleet.** Tauri and Electron are hard-disqualified on Server 2012/2012 R2 (WebView2/Chromium dropped those kernels in Jan 2023), and both also lack a true service/headless mode — fatal on met-service servers where nobody stays logged in. Python caps at 3.12 on 2012 R2 and EOL 3.8 on 2012. .NET 10 LTS lists Server 2012 → 2025 in its official support matrix.
2. **The reliability requirement maps 1:1 onto first-party, tutorial-grade Microsoft machinery**: SCM-supervised restart-on-failure, delayed auto-start, Event Log logging, and the prescribed service + tray-UI IPC split — no third-party wrappers, no DIY watchdogs.
3. **Both install tiers are covered with supported tooling**: WiX/MSI for the admin/service install (self-update via a small download-verify-swap step), and ClickOnce (fully Microsoft-supported, per-user, auto-updating over plain HTTPS) or Velopack (active Squirrel successor, delta updates) for the no-admin tier. All update channels are static-file-over-HTTPS, which the Django server can host behind the existing outbound-only constraint.
4. **Lowest operational risk on locked-down machines**: no WebView2/Chromium runtime to deploy or patch, no 8-week Chromium treadmill, no PyInstaller AV-false-positive lottery; self-contained publish means runtime patches ship through the agent's own update channel with zero admin touches.

The cost is real but bounded: the team learns C# (the closest mainstream typed language to modern typed Python; the worker model resembles a Celery worker) and a minimal amount of WPF (a couple of config forms). **Runner-up:** Python + PyInstaller + WinSW + tufup — lowest language barrier and a viable service story, held back mainly by the endemic AV false positives and the thin update ecosystem; it remains the sensible fallback if the C# adoption cost proves unacceptable.

Accompanying decisions this research forces regardless of framework:

- **Set the official OS floor at Windows Server 2016**, with Server 2012/2012 R2 as documented best-effort legacy (both are past even ESU as of Oct 2026 — fully unpatched).
- **Ship two install tiers** (admin → service; no-admin → logon-triggered per-user agent that cannot start at boot — a documented limitation).
- **Code-sign everything** from day one (SmartScreen enterprise policy can hard-block unsigned installers; EV buys nothing anymore). Budget path: Certum's €69 open-source certificate, or Azure Artifact Signing ($9.99/mo) via a partner organization in an eligible region — African NMHSs/regional bodies are not directly eligible.
- **Keep TLS 1.2 enabled on the ADL server's upload endpoint**; never require TLS 1.3.
