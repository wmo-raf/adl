import {createADLApp} from "@/core.js";

import 'primeicons/primeicons.css';
import 'primeflex/primeflex.css'

import NetworkActivity from "@/components/network-activity/NetworkActivity.vue";

export const createNetworkActivityApp = (elementID) => {
    createADLApp(elementID, NetworkActivity)
}

document.addEventListener("DOMContentLoaded", () => {
    // Find all mount points rendered by Wagtail
    const nodes = document.querySelectorAll("[id^='network-activity-']")

    nodes.forEach(node => {
        const elId = node.id
        // Mount Vue app into each div
        createNetworkActivityApp(elId)
    })
})
