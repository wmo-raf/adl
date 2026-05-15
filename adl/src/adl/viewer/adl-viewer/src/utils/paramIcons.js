const ICON_MAP = [
    {keys: ['temperature', 'temp'], icon: '🌡️'},
    {keys: ['humidity', 'rh'], icon: '💧'},
    {keys: ['wind_speed', 'wind speed', 'windspeed'], icon: '💨'},
    {keys: ['wind_dir', 'wind direction', 'wind_direction'], icon: '🧭'},
    {keys: ['precipitation', 'rainfall', 'rain'], icon: '🌧️'},
    {keys: ['pressure', 'qnh', 'qfe'], icon: '🔵'},
    {keys: ['visibility'], icon: '👁️'},
    {keys: ['solar', 'radiation', 'irradiance'], icon: '☀️'},
    {keys: ['dew'], icon: '🌫️'},
    {keys: ['cloud'], icon: '☁️'},
    {keys: ['battery', 'voltage'], icon: '🔋'},
    {keys: ['signal', 'rssi'], icon: '📶'},
]

// Returns an emoji string based on parameter name keyword matching (fallback only)
export function getParamIcon(name) {
    const lower = name.toLowerCase()
    for (const entry of ICON_MAP) {
        if (entry.keys.some(k => lower.includes(k))) return entry.icon
    }
    return '📊'
}

// Returns FA icon HTML if a backend icon is configured, otherwise an emoji string.
// Call sites that render inside v-html or innerHTML can use this directly.
export function renderParamIcon(param) {
    if (param.icon) {
        return `<i class="fa-solid fa-${param.icon}"></i>`
    }
    return getParamIcon(param.name)
}
