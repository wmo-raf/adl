# 0001 — WIS2BOX Upload channels write CSV for a csv2bufr template from a code registry

- **Status:** Accepted
- **Date:** 2026-10-21
- **Issues:** #319, #321

## Context

A WIS2BOX Upload channel uploads one-row CSV files to wis2box, which converts
them to BUFR with csv2bufr using a mapping template installed for the dataset.
The CSV only converts correctly if its columns match that template exactly.

ADL had always produced CSV for the
[AWS template](https://training.wis2box.wis.wmo.int/csv2bufr-templates/aws-template/),
but nothing in the code, model or admin said so: the header was an unnamed
44-item list. wis2box has other templates (e.g. DAYCLI), and sites may need
them.

## Decision

1. **csv2bufr templates are defined in code, in a registry**
   (`csv2bufr_template_registry`), not as admin-editable records. Each
   template describes every column: name, unit (a pint symbol), data type, and
   source — station metadata, the observation timestamp, or an observation
   (the only columns a parameter mapping can fill). Core registers the AWS
   template; plugins can register more.
2. **A WIS2BOX Upload channel selects its template** with a `template` field.
   **AWS is the default**, and existing channels were migrated to it.
3. **Station and timestamp columns always come from the station and the
   observation time.** A parameter mapping can never overwrite them.

## Consequences

- A template only works when the matching csv2bufr mapping is installed in
  wis2box, so adding one is a deliberate, versioned change rather than
  something configured on the fly. A site that needs a fully custom template
  can still get one later by registering a "custom" template type.
- The template spec is the single source of truth for the CSV shape, and is
  what the parameter matching panel (#324) is built from.
- `thermometer_height`, which the old header listed but never filled, is now
  sent from the station's thermometer height.
