Array.prototype.move = function (from, to) {
    this.splice(to, 0, this.splice(from, 1)[0]);
};

Array.prototype.replace_data = function (position, replacements) {
    this.map((val, i) => {
        val[position] = replacements[i]
        return val
    })
}

function generateSelectInput(selectId, options, position) {
    const select = document.getElementById(selectId);

    while (select.firstChild) {
        select.removeChild(select.lastChild)
    }

    options.forEach(function (option, i) {
        const optionElement = document.createElement('option');
        optionElement.value = i;
        optionElement.text = option.replace(/"/g, '');
        select.appendChild(optionElement);

        if (i === position) {
            select.selectedIndex = position
        }
    });
}

// CSV parsing function
function parseCSV(csv) {

    var lines = csv.split('\n');
    var data = [];

    for (var i = 1; i < lines.length; i++) { // Start from index 1 to skip header row
        var row = lines[i].split(',');

        // Exclude rows with null or empty values
        if (row.some(cell => cell.trim() !== '')) {
            data.push(row);
        }
    }
    return data;
}

function reorder_columns(table_data, column_id, column_index) {
    document.getElementById(column_id).addEventListener('change', function (e) {
        const arrOfArrays = table_data

        const rearrangedArr = arrOfArrays.map(arr => {
            const secondItem = arr[e.target.value];
            arr.splice(e.target.value, e.target.value); // Remove the second item from the current position
            arr.unshift(secondItem); // Insert the second item at the first position
            return arr;
        });

        hot.updateData(rearrangedArr)
    })
}


const nonEmptyValidator = (value, callback) => {
    if (value === '' || value === null || value === undefined) {
        callback(false)
    } else {
        callback(true)
    }
}