import {createADLApp} from "@/core.js";

import 'primeicons/primeicons.css';
import 'primeflex/primeflex.css'

import NetworkActivity from "@/components/activity-monitor/NetworkActivity.vue";
import DispatchChannelActivity from "@/components/activity-monitor/DispatchChannelActivity.vue";

export const createActivityApp = (elementID, type = "network") => {
    if (type === "dispatch") {
        createADLApp(elementID, DispatchChannelActivity)
    } else {
        createADLApp(elementID, NetworkActivity)
    }
}

document.addEventListener("DOMContentLoaded", () => {
    // Find all mount points rendered by Wagtail
    const NetworkConnectionnodes = document.querySelectorAll("[id^='network-activity-']")

    NetworkConnectionnodes.forEach(node => {
        const elId = node.id
        // Mount Vue app into each div
        createActivityApp(elId)
    })

    const DispatchChannelNodes = document.querySelectorAll("[id^='dispatch-activity-']")

    DispatchChannelNodes.forEach(node => {

        console.log(node.id)
        const elId = node.id
        // Mount Vue app into each div
        createActivityApp(elId, "dispatch")
    })
})
