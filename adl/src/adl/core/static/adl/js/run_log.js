/*
 * Rendering and following per-run logs (adl.core.run_log).
 *
 * Lines are the stored shape: {t, level, logger, msg}, or {omitted: n} for
 * the gap between the first and last lines kept. Text goes in through
 * textContent only — log lines carry whatever a plugin or a remote server
 * put in them.
 */
window.adlRunLog = (function () {
    const timeFormat = new Intl.DateTimeFormat(undefined, {
        hour: "2-digit", minute: "2-digit", second: "2-digit",
    });

    function span(className, text) {
        const el = document.createElement("span");
        el.className = className;
        el.textContent = text;
        return el;
    }

    function lineElement(line) {
        if (line.omitted !== undefined) {
            const gap = document.createElement("div");
            gap.className = "run-log__omitted";
            gap.textContent = `… ${line.omitted} line(s) omitted …`;
            return gap;
        }
        const level = (line.level || "INFO").toLowerCase();
        const row = document.createElement("div");
        row.className = `run-log__line run-log__line--${level}`;
        const time = line.t ? timeFormat.format(new Date(line.t)) : "";
        row.title = line.logger || "";
        row.append(
            span("run-log__time", time),
            span("run-log__level", line.level || ""),
            span("run-log__msg", line.msg || ""),
        );
        return row;
    }

    function render(container, lines) {
        container.replaceChildren(...lines.map(lineElement));
    }

    /*
     * Append lines pushed live on `channel` until the run's "end" event.
     * Returns the EventSource so the caller can close it.
     */
    function follow(container, eventsUrl, channel, onEnd) {
        if (!window.EventSource || !eventsUrl || !channel) {
            return null;
        }
        const source = new EventSource(`${eventsUrl}?channel=${encodeURIComponent(channel)}`);
        source.addEventListener("log", function (event) {
            const atBottom = container.scrollHeight - container.scrollTop - container.clientHeight < 8;
            container.append(lineElement(JSON.parse(event.data)));
            if (atBottom) {
                container.scrollTop = container.scrollHeight;
            }
        });
        source.addEventListener("end", function () {
            source.close();
            if (onEnd) {
                onEnd();
            }
        });
        return source;
    }

    return {render, follow, lineElement};
})();
