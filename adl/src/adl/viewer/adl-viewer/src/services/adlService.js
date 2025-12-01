export const fetchDataParameters = (axios) => {
    return axios.get('/data-parameters/')
}

export const fetchNetworkConnections = (axios) => {
    return axios.get('/network-connection/')
}

export const fetchNetworkConnectionStations = (axios, networkConnectionId) => {
    return axios.get(`/network-connection/${networkConnectionId}/station-links/`)
}

export const fetchNetworkConnectionDataParameters = (axios, networkConnectionId) => {
    return axios.get(`/network-connection/${networkConnectionId}/data-parameters/`)
}

export const fetchStationLinkDetail = (axios, stationLinkId) => {
    return axios.get(`/station-link/${stationLinkId}/`)
}

export const fetchStationLinkLatestData = (axios, stationLinkId) => {
    return axios.get(`/data/latest/${stationLinkId}/`)
}

export const fetchStationLinkTimeseriesData = (axios, stationLinkId, {
    page = 1, category, startDate, endDate, paginate = 'true'
}) => {
    const params = {
        category: category,
        start_date: startDate,
        end_date: endDate,
        paginate: paginate
    }

    if (paginate === 'true') {
        params.page = page
    }

    return axios.get(`/data/timeseries/${stationLinkId}/`, {
        params
    })
}

export const fetchQCSummary = (axios, month, year) => {
    return axios.get('/qc/summary/', {
        params: {month, year}
    })
}

export const fetchInspectionData = (axios, stationId, month, year) => {
    return axios.get(`/qc/inspection/${stationId}/`, {
        params: {month, year}
    })
}

export const fetchAvailabilitySummary = (axios, connectionId) => {
    return axios.get('/data-availability/summary/', {
        params: {connection_id: connectionId}
    })
}

