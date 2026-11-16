# 📤 Sending Data to Other Systems

ADL sends the observations it collects to other systems through *dispatch
channels*. Each channel sends data to one destination on its own schedule (see
[Available Dispatch Channel Types](user_guide/manage_dispatch_channels.md)).
The pages below cover the systems NMHSs most often send data to.

```{toctree}
---
maxdepth: 1
---
wis2box_integration
climsoft_integration
```

## Your system isn't listed?

You can still send data to it, by any of these routes:

- **It imports files from an FTP or SFTP server:** use the Standard FTP/SFTP
  Upload channel from the [FTP plugin](plugins/adl-ftp-plugin/guide.md). Climsoft
  uses this route too.
- **It reads from S3 or MinIO object storage:** use the S3 or MinIO Upload
  channel from the [S3 plugin](plugins/adl-s3-plugin/guide.md).
- **It can fetch data itself:** have it pull observations from ADL's
  [REST API](api.md).
