/*
 * Live behaviour for the parameter matching panel. The server renders the
 * same state on load and re-checks everything on save; this only keeps the
 * page honest while the user edits it:
 *
 * - a parameter chosen in one row is disabled, and labelled with that row,
 *   in every other row
 * - the aggregation select follows the channel's "Send Aggregated Data"
 *   checkbox, carrying its value in a hidden input while disabled
 * - a row whose aggregation differs from the template default says so
 * - switching the template (when the page embeds the specs) rebuilds the rows
 *   from the embedded JSON, without a request: mappings whose column exists in
 *   the new template stay in their rows, the others are parked out of sight
 *   (still submitted, so the server removes them on save) and listed
 */
document.addEventListener('DOMContentLoaded', function () {
    const panel = document.querySelector('[data-parameter-matching]');
    if (!panel) {
        return;
    }

    const table = panel.querySelector('table.parameter-matching__table');
    const parked = panel.querySelector('[data-role=parked]');
    const dropped = panel.querySelector('[data-role=dropped]');
    const droppedList = panel.querySelector('[data-role=dropped-list]');
    const prototype = panel.querySelector('template[data-role=row-prototype]');
    const specsElement = document.getElementById('parameter-matching-specs');
    const specs = specsElement ? JSON.parse(specsElement.textContent) : null;
    // translated on the server, e.g. "%(name)s (used in %(column)s)"
    const usedInLabel = panel.dataset.usedInLabel;
    const aggregateCheckbox = document.getElementById('id_send_aggregated_data');

    function rows() {
        return Array.from(table.querySelectorAll('tr[data-column]'));
    }

    function refreshUsedParameters() {
        const usedIn = new Map();
        rows().forEach(function (row) {
            const value = row.querySelector('select[data-role=parameter]').value;
            if (value) {
                usedIn.set(value, row.dataset.column);
            }
        });

        rows().forEach(function (row) {
            row.querySelectorAll('select[data-role=parameter] option[value]').forEach(function (option) {
                if (!option.value) {
                    return;
                }
                const column = usedIn.get(option.value);
                const taken = column !== undefined && column !== row.dataset.column;
                if (option.selected && !taken) {
                    // the row's own choice keeps its label, including a "does not fit" warning
                    return;
                }
                option.disabled = taken;
                option.textContent = taken
                    ? usedInLabel.replace('%(name)s', option.dataset.name).replace('%(column)s', column)
                    : option.dataset.name;
            });
        });
    }

    function refreshAggregation(row) {
        const select = row.querySelector('select[data-role=aggregation]');
        const hasParameter = Boolean(row.querySelector('select[data-role=parameter]').value);
        const aggregating = aggregateCheckbox ? aggregateCheckbox.checked : !select.disabled;
        let hidden = row.querySelector('input[data-role=aggregation-value]');

        select.disabled = !aggregating;
        if (aggregating) {
            select.name = select.dataset.name;
            if (hidden) {
                hidden.remove();
            }
        } else {
            select.removeAttribute('name');
            if (!hidden) {
                hidden = document.createElement('input');
                hidden.type = 'hidden';
                hidden.name = select.dataset.name;
                hidden.dataset.role = 'aggregation-value';
                select.after(hidden);
            }
            hidden.value = select.value;
        }

        const note = row.querySelector('[data-role=override-note]');
        const overridden = aggregating && hasParameter && select.value !== row.dataset.defaultAggregation;
        note.classList.toggle('parameter-matching__override--hidden', !overridden);
    }

    function bindRow(row) {
        if (row.dataset.bound) {
            return;
        }
        row.dataset.bound = 'true';
        row.querySelector('select[data-role=parameter]').addEventListener('change', function () {
            refreshUsedParameters();
            refreshAggregation(row);
        });
        row.querySelector('select[data-role=aggregation]').addEventListener('change', function () {
            refreshAggregation(row);
        });
    }

    function idOf(row) {
        const id = row.querySelector('input[name$="-id"]');
        return id ? id.value : '';
    }

    function setText(element, text) {
        element.textContent = text;
    }

    // Point a row at a column of the template being switched to.
    function fitRowToColumn(row, column, fits, selectedId) {
        row.dataset.column = column.name;
        row.dataset.defaultAggregation = column.defaultAggregation;
        setText(row.querySelector('code'), column.name);
        setText(row.querySelector('[data-role=unit]'), column.unit || '\u2014');
        row.querySelector('input[name$="-channel_parameter"]').value = column.name;
        row.querySelector('select[data-role=parameter]')
            .setAttribute('aria-label', specs.labels.parameterFor.replace('%(column)s', column.name));
        row.querySelector('select[data-role=aggregation]')
            .setAttribute('aria-label', specs.labels.aggregationFor.replace('%(column)s', column.name));

        let hint = row.querySelector('[data-role=hint]');
        if (column.hint) {
            if (!hint) {
                hint = document.createElement('p');
                hint.className = 'parameter-matching__hint';
                hint.dataset.role = 'hint';
                row.querySelector('code').after(hint);
            }
            setText(hint, column.hint);
        } else if (hint) {
            hint.remove();
        }

        const select = row.querySelector('select[data-role=parameter]');
        const fitting = new Set(fits.map(String));
        select.querySelectorAll('option[value]').forEach(function (option) {
            if (option.value) {
                option.remove();
            }
        });
        Object.keys(specs.parameters).forEach(function (id) {
            const fit = fitting.has(id);
            if (!fit && id !== selectedId) {
                return;
            }
            const name = specs.parameters[id][0];
            const option = document.createElement('option');
            option.value = id;
            option.dataset.name = name;
            option.textContent = fit ? name : specs.labels.doesNotFit
                .replace('%(name)s', name).replace('%(unit)s', specs.parameters[id][1]);
            option.selected = id === selectedId;
            select.append(option);
        });
        select.value = selectedId || '';
    }

    function sectionHeading(column) {
        const body = document.createElement('tbody');
        const row = document.createElement('tr');
        row.className = 'parameter-matching__section-row';
        const heading = document.createElement('th');
        heading.colSpan = 4;
        heading.dataset.role = 'section-heading';
        heading.textContent = column.sectionLabel;
        row.append(heading);
        body.append(row);
        return body;
    }

    function newRow(column) {
        const totalForms = panel.querySelector('input[name$="-TOTAL_FORMS"]');
        const index = totalForms.value;
        totalForms.value = Number(index) + 1;
        const holder = document.createElement('tbody');
        holder.innerHTML = prototype.innerHTML.replace(/__prefix__/g, index);
        const row = holder.querySelector('tr');
        row.querySelector('select[data-role=aggregation]').value = column.defaultAggregation;
        const hidden = row.querySelector('input[data-role=aggregation-value]');
        if (hidden) {
            hidden.value = column.defaultAggregation;
        }
        return row;
    }

    function switchTemplate(key) {
        const template = specs.templates[key];
        if (!template) {
            return;
        }
        const pool = new Map();
        rows().concat(Array.from(parked.querySelectorAll('tr[data-column]'))).forEach(function (row) {
            pool.set(row.dataset.column, row);
        });

        // park every row, remembering what an unsaved row had chosen, then lay out the new template
        pool.forEach(function (row) {
            const select = row.querySelector('select[data-role=parameter]');
            if (!idOf(row) && select.value) {
                row.dataset.parkedParameter = select.value;
                select.value = '';
            }
            parked.append(row);
        });
        table.querySelectorAll('tbody').forEach(function (body) {
            body.remove();
        });

        let body = null;
        let section = null;
        let position = 1;
        const keep = new Set();
        template.columns.forEach(function (column) {
            if (column.section !== section) {
                section = column.section;
                body = sectionHeading(column);
                table.append(body);
            }
            const row = pool.get(column.name) || newRow(column);
            const select = row.querySelector('select[data-role=parameter]');
            const selectedId = select.value || row.dataset.parkedParameter || '';
            delete row.dataset.parkedParameter;
            fitRowToColumn(row, column, specs.fits[key][column.name], selectedId);
            const order = row.querySelector('input[name$="-ORDER"]');
            if (order) {
                order.value = position;
            }
            position += 1;
            bindRow(row);
            body.append(row);
            keep.add(column.name);
            refreshAggregation(row);
        });

        droppedList.replaceChildren();
        parked.querySelectorAll('tr[data-column]').forEach(function (row) {
            if (idOf(row) && !keep.has(row.dataset.column)) {
                const item = document.createElement('li');
                item.textContent = row.dataset.column;
                droppedList.append(item);
            }
        });
        dropped.hidden = !droppedList.children.length;
        refreshUsedParameters();
    }

    rows().forEach(bindRow);

    if (specs) {
        document.getElementById(specs.field).addEventListener('change', function (event) {
            switchTemplate(event.target.value);
        });
    }

    if (aggregateCheckbox) {
        aggregateCheckbox.addEventListener('change', function () {
            rows().forEach(refreshAggregation);
        });
    }
});
