import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ArcoVue from '@arco-design/web-vue'; // 导入 Arco Design Vue 组件库
import ArcoVueIcon from '@arco-design/web-vue/es/icon'; // 导入 Arco Design 图标
import './style.css'
import '@arco-design/web-vue/dist/arco.css';
import './arco-theme-override.css' // 引入 Arco Design 主题覆盖样式
import './assets/wired-elements-custom.css'
import App from './App.vue'
import router from './router' // 新增导入
import 'wired-elements'

// Monaco Editor 配置 - 使用本地资源，无需外网
import * as monaco from 'monaco-editor'
import { loader } from '@guolao/vue-monaco-editor'
loader.config({ monaco })

const app = createApp(App)

app.use(createPinia())
app.use(router) // 新增使用 router
app.use(ArcoVue); // 全局注册 Arco Design 组件
app.use(ArcoVueIcon); // 全局注册 Arco Design 图标
app.mount('#app')
