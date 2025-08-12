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
            time: {
                timezone: Intl.DateTimeFormat().resolvedOptions().timeZone // Detects the user's timezone
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
            tooltip: {
                xDateFormat: '%b %e, %Y %I:%M %p' // Jan 31, 2025 10:10 AM
            },
            series: [
                {
                    name: 'Processed Records',
                    type: "spline",
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

class StationsActivityTimeline {
    constructor({connectionId, timelineElId, apiBaseUrl}) {
        this.timelineEl = document.getElementById(timelineElId);
        this.apiBaseUrl = apiBaseUrl;
        this.connectionId = connectionId;


        this.fetchData().then(data => {
            this.renderTimeline(data);
        });
    }

    async fetchData() {
        const url = `${this.apiBaseUrl}/${this.connectionId}/`;
        this.timelineEl.innerHTML = "<div class='loading'>Loading activity…</div>";
        try {
            const r = await fetch(url, {headers: {"Accept": "application/json"}});
            if (!r.ok) throw new Error(`HTTP ${r.status}`);
            const data = await r.json();
            if (!data || !data.activity_log?.length) {
                this.timelineEl.innerHTML = "<div class='empty'>No activity in the selected period.</div>";
                return {stations: [], activity_log: []};
            }
            this.timelineEl.innerHTML = "";
            return data;
        } catch (e) {
            console.error("Failed to fetch timeline data:", e);
            this.timelineEl.innerHTML = "<div class='error'>Could not load activity. Try again.</div>";
            return {stations: [], activity_log: []};
        }
    }

    renderTimeline(data) {
        const {stations, activity_log} = data;

        if (!Array.isArray(stations) || !Array.isArray(activity_log)) {
            console.error("Bad payload for timeline", data);
            this.timelineEl.innerHTML = "<div class='empty'>No activity found</div>";
            return;
        }

        // Groups: one per station
        const groups = new vis.DataSet(
            stations.map(station => ({id: station, content: station, className: 'station-group'}))
        );

        // Status -> CSS class
        const statusClass = ({success, records_count, message}) => {
            if (success) return (records_count || 0) > 0 ? "success-with-records" : "success-no-records";
            return message ? "error-with-message" : "error-no-message";
        };

        // Make human tooltips
        const fmt = (d) =>
            new Date(d).toLocaleString(undefined, {hour12: false}); // local time; switch to UTC if you prefer

        const dataset = activity_log.map(log => {
            const start = log.start_date;
            let end = log.end_date;

            // Derive end if missing
            if (!end) {
                if (typeof log.duration_ms === "number") {
                    end = new Date(new Date(start).getTime() + log.duration_ms).toISOString();
                } else {
                    // tiny bar so it’s visible
                    end = new Date(new Date(start).getTime() + 60 * 1000).toISOString();
                }
            }

            const cls = statusClass({
                success: !!log.success,
                records_count: log.records_count || 0,
                message: log.message || ""
            });

            const dirLabel = log.direction === "pull" ? "⬇ Pull" : "⬆ Push";
            const recs = log.records_count != null ? ` • ${log.records_count} recs` : "";
            const status = log.success ? "success" : "error";
            const duration =
                typeof log.duration_ms === "number"
                    ? ` • ${Math.round(log.duration_ms / 1000)}s`
                    : "";

            return {
                id: log.id,
                group: log.station,
                content: dirLabel,
                start,
                end,
                className: cls,
                // Native tooltip
                title: `${log.station} • ${dirLabel} • ${status}${recs}${duration}\n${fmt(start)} → ${fmt(end)}${log.message ? `\n${log.message}` : ""}`,
                // Helpful for later interactions
                status: status,
                direction: log.direction,
                task_id: log.task_id || null
            };
        });

        const items = new vis.DataSet(dataset);

        const options = {
            stack: true,
            stackSubgroups: true,
            orientation: "top",
            zoomMin: 60 * 1000,            // 1 minute minimum zoom level
            zoomMax: 30 * 24 * 60 * 60 * 1000, // 30 days maximum zoom level
            zoomKey: "ctrlKey",
            maxHeight: "420px",
            minHeight: "220px",
            selectable: true,
            multiselect: false,
            // keep labels readable when many items overlap
            margin: {item: 6, axis: 6},
            // snap to minutes when dragging (optional)
            snap: (date /* Date */, scale /* string */, step /* number */) => {
                const d = new Date(date);
                d.setSeconds(0, 0);
                return d;
            },
            // order items by start time inside a group
            order: (a, b) => new Date(a.start) - new Date(b.start),
            // keep stations sorted lexicographically
            groupOrder: (a, b) => String(a.id).localeCompare(String(b.id)),
            tooltip: {followMouse: true}
        };

        const timeline = new vis.Timeline(this.timelineEl, items, groups, options);

        // Optional: click to drill down to your log viewer
        timeline.on("itemclick", (props) => {
            const item = items.get(props.item);
            if (item?.task_id) {
                window.open(`/logs/tasks/${item.task_id}`, "_blank");
            }
        });
    }

}