import {fileURLToPath, URL} from 'node:url'
import {resolve} from 'path'

import {defineConfig} from 'vite'
import vue from '@vitejs/plugin-vue'
import vueDevTools from 'vite-plugin-vue-devtools'
import cssInjectedByJsPlugin from "vite-plugin-css-injected-by-js";

// https://vite.dev/config/
export default defineConfig({
    base: '/static/vue/',
    plugins: [
        vue(),
        vueDevTools(),
        cssInjectedByJsPlugin({
            jsAssetsFilterFunction: () => true,
        },),
    ],
    resolve: {
        alias: {
            '@': fileURLToPath(new URL('./src', import.meta.url))
        },
    },
    build: {
        rollupOptions: {
            input: {
                "table-view": resolve('./src/table-view.js'),
                "chart-view": resolve('./src/chart-view.js'),
                "map-view": resolve('./src/map-view.js'),
                "qc-status": resolve('./src/qc-status.js'),
                "qc-inspect": resolve('./src/qc-inspect.js'),
            },
            output: {
                dir: '../static/vue/',
                entryFileNames: '[name].js',
            },
        },
    },
})
