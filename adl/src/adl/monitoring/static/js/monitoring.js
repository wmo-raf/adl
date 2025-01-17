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
            chart: {
                type: 'spline',
            },
            title: {
                text: 'Data Processing',
                align: 'left'
            },
            yAxis: {
                title: {
                    text: 'Count'
                }
            },
            xAxis: {
                type: 'datetime',
                title: {
                    text: 'Date'
                }
            },
            plotOptions: {
                series: {
                    marker: {
                        symbol: 'circle',
                        fillColor: '#FFFFFF',
                        enabled: true,
                        radius: 2.5,
                        lineWidth: 1,
                        lineColor: null
                    }
                }
            },
            tooltip: {
                formatter: function () {
                    // Format the date using Intl.DateTimeFormat
                    const options = {
                        year: 'numeric',
                        month: 'short',
                        day: 'numeric',
                        hour: 'numeric',
                        minute: 'numeric',
                        hour12: true
                    };
                    const date = new Intl.DateTimeFormat('en-US', options).format(this.x);
                    return `<b>${date}</b><br>Number of Records: ${this.y}`;
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