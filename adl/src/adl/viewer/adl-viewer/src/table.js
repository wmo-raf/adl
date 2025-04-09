import {createPinia} from 'pinia'
import {createApp} from 'vue'
import {createI18n} from 'vue-i18n'
import DjangoUtilsPlugin, {convertDatasetToProps} from 'vue-plugin-django-utils'
import PrimeVue from 'primevue/config';
import Aura from '@primeuix/themes/aura';

import {createAxiosInstance} from '@/utils/axios';

import TableView from "@/components/TableView.vue";

import 'primeicons/primeicons.css';

const pinia = createPinia()

const tableViewEl = document.getElementById('table-view')

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
            preset: Aura,
        }
    });

    const axiosInstance = createAxiosInstance(props.apiUrl);

    pinia.use(() => ({axios: axiosInstance}))

    app.use(pinia)
    app.use(i18n)
    app.use(DjangoUtilsPlugin, {rootElement: tableViewEl})
    app.mount(tableViewEl)
}