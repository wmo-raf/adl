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
: A currently mapped parameter (per `get_variable_mappings()`) with no record
  in an expected hour that is otherwise present. Shown as a corner marker on
  the month calendar cell and as a missing hour in that parameter's row of the
  day view. Parameters with data but no current mapping never count as gaps.
