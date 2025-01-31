function formatToLocalTime(utcString) {
    // Parse the UTC date string
    const utcDate = new Date(utcString);

    // Get local date components
    const day = utcDate.getDate();
    const month = utcDate.toLocaleString('en-US', {month: 'short'}); // Get short month name (e.g., "Jan")

    // Format hours and minutes with AM/PM
    let hours = utcDate.getHours();
    const minutes = String(utcDate.getMinutes()).padStart(2, '0');
    const ampm = hours >= 12 ? 'PM' : 'AM';

    hours = hours % 12 || 12; // Convert 24h to 12h format

    // Construct formatted date string
    return `${day} ${month}, ${hours}:${minutes} ${ampm}`;
}

class PanelMonitor {
    constructor({connectionId, panelId, chartContainerId, apiBaseUrl}) {
        this.panelEl = document.getElementById(panelId);

        this.chartContainerId = chartContainerId;

        this.apiBaseUrl = apiBaseUrl;
        this.connectionId = connectionId;

        this.fetchData().then(res => {
            this.renderLatest(res.latest_record)
            this.renderChart(res.data);
        });
    }

    async fetchData() {
        const today = new Date();
        const date = dateFns.format(today, 'yyyy-MM-dd');

        const urlWithDate = `${this.apiBaseUrl}/${this.connectionId}/${date}/`;

        const response = await fetch(urlWithDate);

        return await response.json();
    }


    createCard(label, value) {
        const card = document.createElement('div');
        card.classList.add('m-panel-latest-card');

        const cardLabel = document.createElement('div');
        cardLabel.classList.add('m-panel-latest-card-label');
        cardLabel.innerText = label;

        const cardValue = document.createElement('div');
        cardValue.classList.add('m-panel-latest-card-value');
        cardValue.innerText = value;

        card.appendChild(cardLabel);
        card.appendChild(cardValue);

        return card;
    }


    renderLatest(latestRecord) {
        const container = this.panelEl.querySelector('.m-panel-latest-cards');

        if (container && latestRecord) {
            const info = {
                "date": formatToLocalTime(latestRecord.date_done),
                "processedRecords": latestRecord.result?.saved_records_count,
                "stations": latestRecord.result?.total_stations_count
            }

            const dateCard = this.createCard('Time', info.date);
            container.appendChild(dateCard);

            const stationsCard = this.createCard('Stations Reporting', info.stations);
            container.appendChild(stationsCard);

            const processedRecordsCard = this.createCard('Processed Records', info.processedRecords);
            container.appendChild(processedRecordsCard);
        }
    }

    renderChart(data) {
        this.chart = Highcharts.chart(this.chartContainerId, {
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
            series: [
                {
                    name: 'Processed Records',
                    "type": "spline",
                    data: [],
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
                },
                {
                    name: 'Stations',
                    type: "column",
                    data: [],
                }
            ],
            responsive: {
                rules: [{
                    condition: {
                        maxWidth: 500
                    },
                }]
            }
        });


        const recordsData = data.reduce((acc, record) => {
            acc.push([
                Date.parse(record.date_done),
                record.result?.saved_records_count
            ]);

            return acc;

        }, []);

        this.chart.series[0].setData(recordsData);


        const stationsData = data.reduce((acc, record) => {
            acc.push([
                Date.parse(record.date_done),
                record.result?.total_stations_count
            ]);

            return acc;

        }, []);

        this.chart.series[1].setData(stationsData);


    }
}