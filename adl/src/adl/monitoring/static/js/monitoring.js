class PanelMonitor {
    constructor({connectionId, panelId, chartContainerId, apiBaseUrl}) {
        this.panelEl = document.getElementById(panelId);

        this.chartContainerId = chartContainerId;

        this.apiBaseUrl = apiBaseUrl;
        this.connectionId = connectionId;

        this.fetchData().then(data => {
            this.data = data;
            this.renderChart();
        });
    }


    async fetchData() {
        const today = new Date();
        const date = dateFns.format(today, 'yyyy-MM-dd');
        
        const urlWithDate = `${this.apiBaseUrl}/${this.connectionId}/${date}/`;

        const response = await fetch(urlWithDate);

        return await response.json();
    }

    renderChart() {
        this.chart = Highcharts.chart(this.chartContainerId, {
            title: {
                text: 'Number of processed records',
                align: 'left'
            },
            yAxis: {
                title: {
                    text: 'Count'
                }
            },
            xAxis: {
                type: 'datetime',
            },
            plotOptions: {
                series: {
                    label: {
                        connectorAllowed: false
                    },
                }
            },
            series: [{
                name: 'Processed Records',
                data: []
            }],
            responsive: {
                rules: [{
                    condition: {
                        maxWidth: 500
                    },
                }]
            }
        });


        const data = this.data.reduce((acc, record) => {
            acc.push([
                Date.parse(record.date_done),
                record.result?.saved_records_count
            ]);

            return acc;

        }, []);


        this.chart.series[0].setData(data);
    }
}