# Data Protection and Privacy Statement: Automated Data Loader (ADL)

**Version:** 1.0 · **Date:** November 2026 · **Maintainer:** WMO Regional Office for Africa (wmo-raf)

This document describes how the Automated Data Loader (ADL) handles data, which privacy and data-protection frameworks its design follows, and how responsibilities are divided between WMO (the software developer) and the institutions that deploy it. It complements [LEGAL.md](LEGAL.md) (liability terms), [LICENSE](LICENSE), the [Data Flow & Access Control guide](docs/data-flow-and-access-control.md) and the [user documentation](https://adl-tool.readthedocs.io/).

> This statement is provided in good faith to support Digital Public Good and institutional due-diligence reviews. It is not legal advice. Deploying institutions remain responsible for their own compliance assessment under the laws that apply to them.

---

## 1. What ADL is, and who is responsible for the data

ADL is free, open-source software (Django/Wagtail) that National Meteorological and Hydrological Services (NMHSs) install on their own infrastructure. It collects observations from automatic and manual weather stations (vendor APIs, FTP/SFTP, manual entry), such as air temperature, relative humidity, rainfall, wind speed and direction, atmospheric pressure, solar radiation, sunshine duration, soil temperature and soil moisture, visibility and evaporation. It normalises and stores them, and forwards selected stations and parameters to destinations the NMHS configures, such as WIS2box, an S3 bucket or an FTP server.

| Role | Who | Notes |
|---|---|---|
| Software developer / publisher | WMO Regional Office for Africa | Publishes the code. **Operates no central instance and receives no data from deployments.** |
| Data controller | The deploying institution (NMHS) | Decides who gets an account, which stations and sources are connected, where data is dispatched, and how long records are kept. |
| Data processor(s) | None by default | Each deployment is self-hosted. If the institution sends data to an external service (for example a cloud storage bucket), that provider acts under the institution's own agreement. |

ADL contains **no telemetry, analytics, tracking or "phone home" functionality**. WMO has no technical access to any deployed instance. Data does not leave an ADL instance unless the institution has explicitly configured a dispatch channel (see the [Data Flow & Access Control guide](docs/data-flow-and-access-control.md)).

## 2. Inventory of data processed

The data ADL exists to process (station observations and station metadata) is environmental, non-personal information. The only personal data in ADL is the account data of the authorised staff and field observers who operate it, plus routine technical logs. No data about members of the public is processed.

| Category | Examples | Personal data? | Purpose | Lawful basis (GDPR Art. 6) | Retention |
|---|---|---|---|---|---|
| Observation records | Measured values with timestamps, for example: air temperature (°C), relative humidity (%), rainfall (mm), wind speed (m/s) and wind direction (°), atmospheric pressure (hPa), solar radiation (W/m²), sunshine duration (h), soil temperature and soil moisture, visibility, evaporation | No | Core purpose: weather and climate monitoring, exchange under WMO policy | n/a | Set by the institution |
| Station metadata | Station name, WIGOS identifier, coordinates, elevation, network, sensors | No (describes instruments and sites) | Identify the source of each observation; WMO/OSCAR interoperability | n/a | Set by the institution |
| Staff user accounts | Username, name, work email, hashed password, group/permissions, last-login timestamp | **Yes** (staff only) | Authentication and role-based access to the admin interface | Art. 6(1)(e) public task | Until the account is removed by the institution's administrator |
| Field observer accounts and submissions (optional ADL Collector plugin) | Observer account linked to a station; who submitted a manual reading and when | **Yes** (observers only) | Attribute and quality-control manual observations | Art. 6(1)(e) public task | Same as the account / observation record |
| Connection credentials | API keys, FTP/S3 usernames and passwords for station vendors and dispatch destinations | No (institutional system credentials) | Fetch and forward data | n/a | Until the connection is removed |
| Server logs | IP address, user-agent, requested URL (web server / application logs) | Yes (technical) | Security and troubleshooting | Art. 6(1)(e) public task | Default log rotation, configurable by the operator |

**Not processed:** data about the public, special-category data, children's data, payment data, location tracking of individuals. No cookies are set beyond the session and security cookies required for the admin login.

## 3. How GDPR principles are implemented

The EU General Data Protection Regulation (Regulation (EU) 2016/679) applies directly only to controllers established in the EU/EEA or targeting EU data subjects. Most ADL deployments are outside that scope. WMO nonetheless adopts GDPR as the **design benchmark**, because it is the most widely recognised standard and because most African and other national data-protection laws (see §5) follow the same principles.

| GDPR principle / obligation | How ADL implements it |
|---|---|
| **Lawfulness, fairness, transparency** (Art. 5(1)(a)) | Processing is limited to the public weather and climate mandate of the NMHS. This document and the open-source code provide transparency. |
| **Purpose limitation** (Art. 5(1)(b)) | Account data is used only for authentication and for attributing manual observations. No secondary use, profiling or marketing. |
| **Data minimisation** (Art. 5(1)(c)) | The data model for observations and stations has no personal fields. Accounts hold only the fields needed to log in and assign permissions. |
| **Accuracy** (Art. 5(1)(d)) | Administrators and users can edit account details at any time through the admin interface. |
| **Storage limitation** (Art. 5(1)(e)) | Accounts can be deactivated or deleted by administrators. Observation retention is set by the institution. |
| **Integrity and confidentiality** (Art. 5(1)(f), Art. 32) | Passwords stored with Django's salted password hashing; group-based permissions; API access requires an API key or authenticated session; secrets kept in environment variables, not in code; HTTPS via the documented reverse-proxy setup; Docker-based isolation. |
| **Accountability** (Art. 5(2)) | Clear controller/developer split (§1). Section 2 supports the institution's record of processing. |
| **Data protection by design and by default** (Art. 25) | No tracking or analytics; no public-user data model; personal data confined to account models; **nothing is dispatched by default**: every outbound flow is an explicit, per-station, per-parameter configuration. |
| **Records of processing** (Art. 30) | Section 2 can be adopted directly into the institution's record of processing activities. |
| **Data subject rights** (Art. 15–22) | Administrators can view, export (via the admin interface or database), rectify, restrict (deactivate) or erase an account on request. |
| **Data Protection Impact Assessment** (Art. 35) | WMO's assessment is that ADL's default processing of personal data is low-risk and small-scale, limited to staff and observer accounts, with no special categories, no systematic monitoring and no new technology. A DPIA is therefore not expected to be required, but the deploying institution makes that determination for its own deployment. |
| **International transfers** (Chapter V) | No personal data is transferred by design. Dispatch channels carry observation data only; the institution decides every destination. |

## 4. Alignment with the UN Personal Data Protection and Privacy Principles

WMO is a UN specialized agency. The [UN Personal Data Protection and Privacy Principles](https://unsceb.org/privacy-principles) (adopted by the UN High-Level Committee on Management, 2018; [PDF](https://unsceb.org/sites/default/files/imported_files/UN-Principles-on-Personal-Data-Protection-Privacy-2018_0.pdf)) guide how the software was designed.

| UN Principle | Implementation in ADL |
|---|---|
| 1. Fair and legitimate processing | Processing serves the public weather and climate mandate of the NMHS. |
| 2. Purpose specification | Purposes are fixed and documented in §2. |
| 3. Proportionality and necessity | Only account fields; observation and station models hold no personal data. |
| 4. Retention | Controlled by the institution; accounts deletable. |
| 5. Accuracy | Editable accounts; observations carry source and timestamp. |
| 6. Confidentiality | Group-based permissions; hashed credentials; API keys. |
| 7. Security | See the Art. 32 row in §3. |
| 8. Transparency | Open-source code; this statement; public documentation. |
| 9. Transfers | No personal data transferred; observation dispatch is explicit and institution-controlled. |
| 10. Accountability | Clear controller/developer split in §1. |

## 5. National and regional law: example clauses

The deploying institution is the data controller under its national law. As an example, the **Kenya Data Protection Act, 2019 (No. 24 of 2019)** ([Kenya Law](https://new.kenyalaw.org/akn/ke/act/2019/24/eng@2022-12-31); regulator: [Office of the Data Protection Commissioner](https://www.odpc.go.ke/)) maps to ADL as follows:

| Provision | What it requires (summary) | How ADL meets it |
|---|---|---|
| Section 2, definition of "personal data" | Information relating to an identified or identifiable natural person | Observations and station metadata fall outside this definition; only account data and logs fall inside it (§2). |
| Section 25, principles of data protection | Lawful, fair and transparent processing; explicit and specified purposes; adequate, relevant and limited data; accuracy; storage no longer than necessary; no transfer outside Kenya without adequate safeguards | Mirrors the GDPR mapping in §3: fixed purposes, minimal account fields, editable and deletable accounts, no personal-data transfers. |
| Section 41, data protection by design or by default | Appropriate technical and organisational measures that implement the principles and integrate safeguards into processing | No tracking, no public-user data, nothing dispatched by default, hashed credentials, permission groups (§3, Art. 25 and Art. 32 rows). |
| Sections 18–19, registration of controllers and processors | Registration with the Data Commissioner where required | Responsibility of the deploying institution (§6). |

Other frameworks:

- **WMO Unified Data Policy (Resolution 1, Cg-Ext(2021))**: governs the exchange of the observation data ADL handles; ADL supports it by forwarding selected stations to WIS2 while keeping all other data under national control.
- **African Union Convention on Cyber Security and Personal Data Protection (Malabo Convention, 2014)**: the regional reference for most deployments; its principles mirror those in §3.
- **Other national data-protection laws** of deploying countries (for example Nigeria Data Protection Act 2023, Ghana Data Protection Act 2012, Rwanda Law No. 058/2021, Ethiopia Personal Data Protection Proclamation No. 1321/2024) follow the same principles; the institution is the controller under each.

## 6. What deploying institutions must do

- Appoint an administrator responsible for creating, reviewing and removing staff and observer accounts.
- Serve the admin interface over HTTPS and keep credentials in environment variables.
- Configure dispatch channels deliberately: only the stations and parameters intended for each destination.
- Set log-rotation and observation-retention policies.
- Sign a processing agreement with any third-party storage or hosting provider they use.
- Register the processing with their national data-protection authority if national law requires it.

## 7. Contact

Questions about this statement or the software's data handling: open an issue in this repository or contact the WMO Regional Office for Africa. Questions about a specific deployment should be directed to the deploying institution.
