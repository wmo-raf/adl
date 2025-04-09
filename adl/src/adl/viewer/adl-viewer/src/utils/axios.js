import axios from 'axios'

export function createAxiosInstance(apiUrl) {
    return axios.create({
        baseURL: apiUrl,
        timeout: 10000,
        headers: {
            'Content-Type': 'application/json',
        }
    });
}