(operations)=

# 🛠 Operations Runbook

Procedures for the people who keep an ADL deployment running: what to back
up and how to restore it, how to upgrade the core and plugins safely, and the
routine checks, restarts and housekeeping of a production stack.

These pages assume the Docker Compose deployment described in
[Installation](../installation.md), run from the checked-out `adl` folder
with the root `Makefile`.

```{toctree}
---
maxdepth: 1
---
backup_restore
upgrading
routine_operations
```

| I need to… | Page |
|---|---|
| Take a backup before doing anything risky | [Backup and restore](backup_restore.md) |
| Rebuild a server from a backup | {ref}`Backup and restore <restoring>` |
| Move to a newer ADL release | [Upgrading](upgrading.md) |
| Move a plugin to a newer release tag | {ref}`Upgrading <upgrading-a-plugin>` |
| Know which container does what | {ref}`Routine operations <service-map>` |
| Restart something a diagnostic told me to restart | {ref}`Routine operations <restarting-services>` |
| Free disk space | {ref}`Routine operations <disk-and-housekeeping>` |
