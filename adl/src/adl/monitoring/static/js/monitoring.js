class StationsActivityTimeline {
    constructor({connectionId, timelineElId, apiBaseUrl, defaultDirection = "pull"}) {
        this.timelineEl = document.getElementById(timelineElId);
        this.apiBaseUrl = apiBaseUrl.replace(/\/$/, "");
        this.connectionId = connectionId;
        this.direction = defaultDirection;
        this.channelId = "";

        // Data stores
        this.groups = new vis.DataSet([]);
        this.items = new vis.DataSet([], {queue: true}); // queue for batch add
        this.timeline = null;

        // Cache fetched “tiles” by day (YYYY-MM-DD)
        this.dayCache = new Map();  // key -> Promise<void> to dedupe inflight

        // Bounds
        const now = new Date();
        this.max = new Date(now.getTime() + 24 * 3600 * 1000); // +1 day
        this.min = new Date(now.getTime() - 30 * 24 * 3600 * 1000); // 30 days back

        // Today in local time
        const todayStart = new Date();
        todayStart.setHours(0, 0, 0, 0);
        const todayEnd = new Date(todayStart.getTime() + 24 * 3600 * 1000);

        // Initial window shows the whole of today (forward focus),
        // but we'll only fetch data up to "now".
        this.initialStart = todayStart;
        this.initialEnd = todayEnd;
        this._nowAtInit = now; // freeze "now" for the first fetch

        this.bootstrap();
    }

    // ---- Helpers ----
    iso(d) {
        return new Date(d).toISOString();
    }

// LOCAL day key: YYYY-MM-DD from local clock
    dayKeyLocal(d) {
        const y = d.getFullYear();
        const m = String(d.getMonth() + 1).padStart(2, "0");
        const dd = String(d.getDate()).padStart(2, "0");
        return `${y}-${m}-${dd}`;
    }

// Split [start,end) by LOCAL midnights
    daysInRange(start, end) {
        const out = [];
        const d = new Date(start);
        d.setHours(0, 0, 0, 0);
        const last = new Date(end);
        last.setHours(0, 0, 0, 0);
        while (d <= last) {
            out.push(this.dayKeyLocal(d));
            d.setDate(d.getDate() + 1);
        }
        return out;
    }


    // Fetch a concrete [start, end) window. Optionally include stations if first load.
    async fetchRange(start, end, {includeStations = false} = {}) {
        // Clamp to [this.min, this.max] and (on first load) avoid asking past "now"
        const hardEnd = this.timeline ? end : this._nowAtInit || end;
        const s = new Date(Math.max(+start, +this.min));
        const e = new Date(Math.min(+hardEnd, +this.max));

        if (e <= s) return;

        const tiles = this.daysInRange(s, e);
        const jobs = tiles.map(day => {
            if (!this.dayCache.has(day)) {
                const [Y, M, D] = day.split("-").map(Number);
                const dayStart = new Date(Y, M - 1, D, 0, 0, 0, 0);         // local 00:00
                const dayEnd = new Date(dayStart.getTime() + 24 * 3600 * 1000); // +24h
                const p = this._fetchAndIngest(dayStart, dayEnd, includeStations)
                    .catch(err => console.error("Tile fetch failed", day, err));
                this.dayCache.set(day, p);
            }
            return this.dayCache.get(day);
        });

        this.showLoading(true);
        await Promise.all(jobs);
        this.showLoading(false);
    }

    _populateChannels(channels) {
        const sel = this._getChannelSelect();
        if (!sel) return;
        // Preserve current value if possible
        const curr = sel.value;
        sel.innerHTML = `<option value="">All channels</option>` +
            channels.map(c => `<option value="${c.id}">${c.name}</option>`).join("");
        if (Array.from(sel.options).some(o => o.value === curr)) {
            sel.value = curr;
        }
    }

    _getChannelSelect() {
        // find the select next to this timeline
        const panel = this.timelineEl.closest(".station-activity-panel");
        return panel ? panel.querySelector('select[id^="t-channel-"]') : null;
    }

    async _fetchAndIngest(start, end, includeStations) {
        const params = new URLSearchParams({
            start: this.iso(start),
            end: this.iso(end),
            include_stations: includeStations ? "true" : "false",
            direction: this.direction
        });

        // include push-only params
        if (this.direction === "push") {
            if (this.channelId) params.set("dispatch_channel_id", this.channelId);
            // on first time we switch to push, ask for channels list to populate dropdown
            if (includeStations) params.set("include_channels", "true");
        }

        const url = `${this.apiBaseUrl}/${this.connectionId}/?${params.toString()}`;
        const r = await fetch(url, {headers: {"Accept": "application/json"}});
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const data = await r.json();

        // Seed groups once
        if (includeStations && Array.isArray(data.stations)) {
            const groupObjs = data.stations.map(s => ({id: s, content: s, className: "station-group"}));
            this.groups.update(groupObjs);
        }

        // Populate channels dropdown if present
        if (Array.isArray(data.dispatch_channels)) {
            this._populateChannels(data.dispatch_channels);
        }

        const items = (data.activity_log || []).map(this._toVisItem);
        this.items.update(items);
        this.items.flush();
        if (this.view) this.view.refresh();
        if (data.hard_min) this.min = new Date(data.hard_min);
        if (data.hard_max) this.max = new Date(data.hard_max);
    }


    _toVisItem = (log) => {
        const start = log.start_date;
        let end = log.end_date || (typeof log.duration_ms === "number"
            ? new Date(new Date(start).getTime() + log.duration_ms).toISOString()
            : new Date(new Date(start).getTime() + 60 * 1000).toISOString());

        const success = !!log.success;
        const cls = success
            ? ((log.records_count || 0) > 0 ? "success-with-records" : "success-no-records")
            : (log.message ? "error-with-message" : "error-no-message");

        const fmt = (d) => new Date(d).toLocaleString(undefined, {hour12: false});
        const dirLabel = log.direction === "pull" ? "⬇ Pull" : "⬆ Push";
        const recs = log.records_count != null ? ` • ${log.records_count} recs` : "";
        const status = success ? "success" : "error";
        const duration = typeof log.duration_ms === "number" ? ` • ${Math.round(log.duration_ms / 1000)}s` : "";
        const msg = log.message ? `\n${log.message}` : "";

        const channelTag = (log.dispatch_channel && log.dispatch_channel.name)
            ? ` • ch: ${log.dispatch_channel.name}` : "";

        return {
            id: log.id,
            group: log.station,
            content: log.direction === "push" && log.dispatch_channel?.name
                ? `${dirLabel} · ${log.dispatch_channel.name}` : dirLabel,
            start, end,
            className: cls,
            title: `${log.station} • ${dirLabel}${channelTag} • ${status}${recs}${duration}\n${fmt(start)} → ${fmt(end)}${msg}`,
            status,
            direction: log.direction,
            task_id: log.task_id || null,
            dispatch_channel_id: log.dispatch_channel?.id || null
        };
    };

    async setDirection(dir) {
        if (dir !== "pull" && dir !== "push") return;
        if (dir === this.direction) return;
        this.direction = dir;

        // Enable/disable the channel dropdown
        const sel = this._getChannelSelect();
        if (sel) sel.disabled = (dir !== "push");

        // Reset cache + items, keep groups
        this.dayCache.clear();
        this.items.clear();

        // Window to (re)load
        let start = this.initialStart;
        let end = this.initialEnd;
        if (this.timeline) {
            const range = this.timeline.getWindow();
            start = new Date(range.start);
            end = new Date(range.end);
        }
        await this.fetchRange(start, end, {includeStations: true /* also fetch channels on first push */});
    }

    async setChannel(channelId) {
        // Only relevant on push
        this.channelId = channelId || "";
        if (this.direction !== "push") return;

        // Clear only items (keep cache if you prefer; simplest is full clear)
        this.dayCache.clear();
        this.items.clear();

        // Re-fetch current window
        if (this.timeline) {
            const {start, end} = this.timeline.getWindow();
            await this.fetchRange(new Date(start), new Date(end), {includeStations: false});
        }
    }

    showLoading(on) {
        // Find parent panel
        const panel = this.timelineEl.closest(".station-activity-panel") || this.timelineEl;

        if (!this._overlayEl) {
            const overlay = document.createElement("div");
            overlay.className = "timeline-loader-overlay";

            const spinner = document.createElement("div");
            spinner.className = "timeline-loader-spinner";

            const text = document.createElement("div");
            text.textContent = "Loading activity…";

            overlay.appendChild(spinner);
            overlay.appendChild(text);
            panel.appendChild(overlay);

            this._overlayEl = overlay;
        }
        requestAnimationFrame(() => {
            if (on) {
                this._overlayEl.classList.add("visible");
            } else {
                this._overlayEl.classList.remove("visible");
            }
        });
    }

    bootstrap() {
        this.timelineEl.innerHTML = "<div class='loading'>Loading activity…</div>";

        // Fetch only today's data up to "now"
        this.fetchRange(this.initialStart, this._nowAtInit, {includeStations: true})
            .then(() => {
                this.timelineEl.innerHTML = "";
                const options = {
                    stack: true,
                    orientation: "top",
                    zoomMin: 60 * 1000,
                    zoomMax: 30 * 24 * 3600 * 1000,
                    zoomKey: "ctrlKey",
                    maxHeight: "420px",
                    minHeight: "220px",
                    selectable: true,
                    multiselect: false,
                    margin: {item: 6, axis: 6},
                    snap: (date) => {
                        const d = new Date(date);
                        d.setSeconds(0, 0);
                        return d;
                    },
                    order: (a, b) => new Date(a.start) - new Date(b.start),
                    groupOrder: (a, b) => String(a.id).localeCompare(String(b.id)),
                    tooltip: {followMouse: true},
                    // Allow panning back/forward within bounds
                    min: this.min,
                    max: this.max,
                    // Optional: give vis a starting window immediately
                    start: this.initialStart,
                    end: this.initialEnd
                };

                this.timeline = new vis.Timeline(this.timelineEl, this.items, this.groups, options);

                // Ensure the initial window shows all of today (forward focus)
                this.timeline.setWindow(this.initialStart, this.initialEnd, {animation: false});

                // Debounced incremental loading while user pans/zooms
                let loadTimer = null;
                const debouncedLoad = (props) => {
                    clearTimeout(loadTimer);
                    loadTimer = setTimeout(() => this.onRangeChanged(props), 200);
                };
                this.timeline.on("rangechanged", debouncedLoad);
            })
            .catch(err => {
                console.error(err);
                this.timelineEl.innerHTML = "<div class='error'>Could not load activity. Try again.</div>";
            });
    }

    async onRangeChanged(props) {
        const start = new Date(props.start);
        const end = new Date(props.end);

        const neededDays = this.daysInRange(start, end).filter(day => !this.dayCache.has(day));
        if (neededDays.length === 0) return;

        const [Y1, M1, D1] = neededDays[0].split("-").map(Number);
        const [Y2, M2, D2] = neededDays[neededDays.length - 1].split("-").map(Number);
        const rangeStart = new Date(Y1, M1 - 1, D1, 0, 0, 0, 0);
        const rangeEnd = new Date(Y2, M2 - 1, D2, 24, 0, 0, 0);

        await this.fetchRange(rangeStart, rangeEnd, {includeStations: false});
    }
}
