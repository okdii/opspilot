import { createApp } from 'vue'
import { createPinia } from 'pinia'
import 'vuestic-ui/css'
import App from './App.vue'
import { router } from './router'
import { vuestic } from './plugins/vuestic'

const app = createApp(App)

app.use(createPinia())
app.use(router)
app.use(vuestic)

app.mount('#app')
