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

## Monitoring

**expected hour**
: An hour in which a station link should have data: every hour from the
  station link's **availability floor** up to now. Hours before the floor and
  hours still to come (today's remaining hours) are not expected, and the
  hour in progress is not expected until it has elapsed. A station link with no
  floor expects nothing.

**availability floor**
: The earliest hour a station link is expected to have data for. It is the
  collection start date (`get_first_collection_date()`) when the plugin sets
  one, otherwise the hour of the link's first saved record. The start date
  wins even when it predates the first record, which is what makes the hours
  between them gaps.

**gap**
: An expected hour with no record for any parameter. An hour is present if at
  least one record exists for any parameter in it, so a gap is a missing
  hour, not a missing value.

**parameter gap**
: An expected hour in which a currently mapped parameter (per
  `get_variable_mappings()`) has no record, whether or not other parameters
  reported in that hour. Shown as a corner marker on
  the month calendar cell and as a missing hour in that parameter's row of the
  day view. Parameters with data but no current mapping never count as gaps.

**connection grid**
: The availability page for a connection with no station link chosen: one row
  per station link, one column per local day, each cell using the month
  calendar's state, count and corner marker, and each row ending in hours
  present out of expected hours. Enabled links are ranked worst-first by
  missing expected hours (or alphabetically); disabled links are listed apart
  and never ranked.

**availability check**
: A read-only question to the source about one **gap** window of a station
  link: does the source have data for it? Distinct from the **source check**,
  which asks whether the source is reachable and offers anything for a
  station at all, whatever the period. The window is exactly a selected run of
  missing hours, at most one local day, and never from an unmapped parameter's
  row. It is answered by the first tier available: the station link's own
  cheap `check_availability()` (a listing), otherwise core fetches and parses
  the window through `get_station_data`, counts records per hour and per
  parameter, and saves nothing. A cheap check that fails, times out or returns
  something malformed is stored and shown as such; it never falls through to
  fetching by itself, only the operator's explicit "Try by fetching data" does,
  and the cheap check is held to one dial per station link per minute. The answer is stored, shown on the hours it
  covers, and says which tier answered. One check or recovery runs per station
  link at a time.
