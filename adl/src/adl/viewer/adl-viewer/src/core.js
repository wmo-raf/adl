import {definePreset} from "@primeuix/themes";
import Aura from "@primeuix/themes/aura";
import {createPinia} from "pinia";
import DjangoUtilsPlugin, {convertDatasetToProps} from "vue-plugin-django-utils";
import {createI18n} from "vue-i18n";
import {createApp} from "vue";
import PrimeVue from "primevue/config";
import {createAxiosInstance} from "@/utils/axios.js";
import HighchartsVue from "highcharts-vue";
import Tooltip from 'primevue/tooltip'

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

export const createViewerApp = (rootElementId, RootComponent) => {
    const pinia = createPinia()

    const el = document.getElementById(rootElementId)

    if (el) {
        const props = convertDatasetToProps({
            dataset: {...el.dataset},
            component: RootComponent
        })

        let defaultLocale = props?.languageCode || 'en'

        const i18n = createI18n({
            legacy: false,
            locale: defaultLocale,
            fallbackLocale: 'en',
        })

        const app = createApp(RootComponent, props)

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

        app.directive('tooltip', Tooltip)

        app.use(pinia)
        app.use(i18n)
        app.use(DjangoUtilsPlugin, {rootElement: el})
        app.use(HighchartsVue);
        app.mount(el)
    } else {
        console.error(`Element with id ${rootElementId} not found`)
    }
}