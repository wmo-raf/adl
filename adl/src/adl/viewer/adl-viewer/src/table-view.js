import {createPinia} from 'pinia'
import {createApp} from 'vue'
import {createI18n} from 'vue-i18n'
import DjangoUtilsPlugin, {convertDatasetToProps} from 'vue-plugin-django-utils'
import PrimeVue from 'primevue/config';
import Aura from '@primeuix/themes/aura';

import {createAxiosInstance} from '@/utils/axios';

import TableView from "@/components/TableView.vue";

import 'primeicons/primeicons.css';
import {definePreset} from "@primeuix/themes";

const pinia = createPinia()

const tableViewEl = document.getElementById('table-view')

const WagtailThemePreset = definePreset(Aura, {
    semantic: {
        primary: {
            50: '{teal.50}',
            100: '{teal.100}',
            200: '{teal.200}',
            300: '{teal.300}',
            400: '{teal.400}',
            500: '{teal.700}',
            600: '{teal.800}',
            700: '{teal.700}',
            800: '{teal.800}',
            900: '{teal.900}',
            950: '{teal.950}'
        }
    }
});


if (tableViewEl) {
    const props = convertDatasetToProps({
        dataset: {...tableViewEl.dataset},
        component: TableView
    })

    let defaultLocale = props?.languageCode || 'en'

    const i18n = createI18n({
        legacy: false,
        locale: defaultLocale,
        fallbackLocale: 'en',
    })

    const app = createApp(TableView, props)

    app.use(PrimeVue, {
        theme: {
            preset: WagtailThemePreset,
            options: {
                darkModeSelector: '.w-theme-dark',
            }
        }
    });

    const axiosInstance = createAxiosInstance(props.apiUrl);

    pinia.use(() => ({axios: axiosInstance}))

    app.use(pinia)
    app.use(i18n)
    app.use(DjangoUtilsPlugin, {rootElement: tableViewEl})
    app.mount(tableViewEl)
}