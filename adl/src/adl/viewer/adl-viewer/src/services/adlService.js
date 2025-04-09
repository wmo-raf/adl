export const fetchDataParameters = (axios) => {
    return axios.get('/data-parameters/')
}

export const fetchNetworkConnections = (axios) => {
    return axios.get('/network-connection/')
}

export const fetchNetworkConnectionStations = (axios, networkConnectionId) => {
    return axios.get(`/network-connection/${networkConnectionId}/station-links/`)
}

export const fetchStationLinkLatestData = (axios, stationLinkId) => {
    return axios.get(`/data/latest/${stationLinkId}/`)
}