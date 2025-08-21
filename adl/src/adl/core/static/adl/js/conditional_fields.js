$(document).ready(function () {
    const $useConnectionTimeZoneCheckbox = $('#id_use_connection_timezone');

    const $timezoneInfoInput = $('#id_timezone_info');
    const $timezoneInfoInputWrapper = $timezoneInfoInput.closest('.w-panel__wrapper');

    // Initial check to set visibility based on the checkbox state
    showHideTimezoneInfo();

    // Event listener for checkbox change
    $useConnectionTimeZoneCheckbox.on('change', function () {
        showHideTimezoneInfo();
    });

    function showHideTimezoneInfo() {
        if ($useConnectionTimeZoneCheckbox.is(':checked')) {
            $timezoneInfoInputWrapper.hide();
        } else {
            $timezoneInfoInputWrapper.show();
        }
    }

});