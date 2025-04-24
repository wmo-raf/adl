export const fetchDataParameters = (axios) => {
    return axios.get('/data-parameters/')
}

export const fetchNetworkConnections = (axios) => {
    return axios.get('/network-connection/')
}

export const fetchNetworkConnectionStations = (axios, networkConnectionId) => {
    return axios.get(`/network-connection/${networkConnectionId}/station-links/`)
}

export const fetchStationLinkDetail = (axios, stationLinkId) => {
    return axios.get(`/station-link/${stationLinkId}/`)
}

export const fetchStationLinkLatestData = (axios, stationLinkId) => {
    return axios.get(`/data/latest/${stationLinkId}/`)
}

export const fetchStationLinkTimeseriesData = (axios, stationLinkId, page = 1, category) => {
    return axios.get(`/data/timeseries/${stationLinkId}/`, {
        params: {
            page: page,
            category: category
        }
    })
}

