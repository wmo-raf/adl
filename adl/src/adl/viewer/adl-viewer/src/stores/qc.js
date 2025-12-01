import {defineStore} from 'pinia'

import {fetchInspectionData, fetchQCSummary} from '@/services/adlService'

export const useQCStore = defineStore('qc', {
    state: () => ({
        stationSummaries: [],
        loadingSummary: false,
        loadingRecords: false,
        records: [],
        qcMessages: [],
        error: null,
        // Default to current month/year
        selectedDate: new Date(),
        apiMonth: null, // Actual month returned from API
        apiYear: null   // Actual year returned from API
    }),

    actions: {
        async loadQCSummary() {
            this.loadingSummary = true
            this.error = null

            try {
                // Extract month (1-12) and year from the selected Date object
                const month = this.selectedDate.getMonth() + 1
                const year = this.selectedDate.getFullYear()

                // Call the Django Endpoint
                const response = await fetchQCSummary(this.axios, month, year)

                console.log(response.data.data)

                // Update state
                this.stationSummaries = response.data.data
                this.apiMonth = response.data.month
                this.apiYear = response.data.year

            } catch (err) {
                console.error('QC Summary Fetch Error:', err)
                this.error = err.message || 'Failed to load QC summary'
                this.stationSummaries = []
            } finally {
                this.loadingSummary = false
            }
        },
        async loadInspectionData(stationId, month, year) {
            this.loadingRecords = true
            this.error = null
            try {
                const res = await fetchInspectionData(this.axios, stationId, month, year)
                this.records = res.data.records
                this.qcMessages = res.data.flags
            } catch (err) {
                this.error = err.message
            } finally {
                this.loadingRecords = false
            }
        },

        setSelectedDate(newDate) {
            if (newDate) {
                this.selectedDate = newDate
                this.loadQCSummary()
            }
        }
    }
})