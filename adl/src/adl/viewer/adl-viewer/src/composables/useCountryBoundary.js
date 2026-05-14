const PROXY_URL = (iso3) => `/display/country-boundary/${iso3}/`

export async function addCountryBoundary(map, iso3) {
    if (!iso3 || !map) return

    try {
        const res = await fetch(PROXY_URL(iso3))
        if (!res.ok) return
        const geojson = await res.json()

        map.addSource('country-boundary', {type: 'geojson', data: geojson})

        map.addLayer({
            id: 'country-fill',
            type: 'fill',
            source: 'country-boundary',
            paint: {
                'fill-color': '#38bdf8',
                'fill-opacity': 0.06,
            },
        })

        map.addLayer({
            id: 'country-border',
            type: 'line',
            source: 'country-boundary',
            paint: {
                'line-color': '#38bdf8',
                'line-opacity': 0.45,
                'line-width': 1.5,
            },
        })
    } catch (e) {
        console.warn('Could not load country boundary:', e)
    }
}
