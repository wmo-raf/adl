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
 */
document.addEventListener('DOMContentLoaded', function () {
    const panel = document.querySelector('[data-parameter-matching]');
    if (!panel) {
        return;
    }

    const rows = Array.from(panel.querySelectorAll('tr[data-column]'));
    // translated on the server, e.g. "%(name)s (used in %(column)s)"
    const usedInLabel = panel.dataset.usedInLabel;
    const aggregateCheckbox = document.getElementById('id_send_aggregated_data');

    function refreshUsedParameters() {
        const usedIn = new Map();
        rows.forEach(function (row) {
            const value = row.querySelector('select[data-role=parameter]').value;
            if (value) {
                usedIn.set(value, row.dataset.column);
            }
        });

        rows.forEach(function (row) {
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

    rows.forEach(function (row) {
        row.querySelector('select[data-role=parameter]').addEventListener('change', function () {
            refreshUsedParameters();
            refreshAggregation(row);
        });
        row.querySelector('select[data-role=aggregation]').addEventListener('change', function () {
            refreshAggregation(row);
        });
    });

    if (aggregateCheckbox) {
        aggregateCheckbox.addEventListener('change', function () {
            rows.forEach(refreshAggregation);
        });
    }
});
