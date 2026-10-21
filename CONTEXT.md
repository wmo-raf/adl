# ADL domain glossary

Terms used across ADL's code, docs and issues. Use these words, with these
meanings.

## Dispatch

**csv2bufr template**
: The column layout wis2box's csv2bufr expects for a dataset — column names,
  order, units and data types — paired with a mapping installed in wis2box
  that turns that CSV into BUFR. A WIS2BOX Upload channel writes CSV for
  exactly one template; AWS is the default. Templates are defined in code
  (see `docs/adr/0001-wis2box-csv2bufr-templates.md`). Not to be confused
  with Django/Wagtail HTML templates.

**observation column**
: A csv2bufr template column whose value comes from an observation (e.g.
  `air_temperature`, `total_precipitation_1_hour`), as opposed to a column
  filled from the station's metadata (`latitude`, `wsi_series`,
  `thermometer_height`) or from the observation time (`year` … `minute`).
  Only observation columns can be the target of a parameter mapping.
