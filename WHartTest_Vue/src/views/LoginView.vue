<template>
  <div class="login-container">
    <!-- 左侧品牌展示区 -->
    <div class="brand-panel">
      <!-- 毛玻璃背景层 -->
      <div class="glass-overlay"></div>
      <div class="brand-content">
        <div class="brand-logo">
          <img src="/WHartTest.png" alt="WHartTest Logo" class="logo-icon" />
        </div>
        <h1 class="brand-title">WHartTest</h1>
        <p class="brand-subtitle">小麦智测自动化平台</p>
        <div class="brand-features">
          <div class="feature-item">
            <div class="feature-icon">
              <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.456 2.456L21.75 6l-1.035.259a3.375 3.375 0 00-2.456 2.456zM16.894 20.567L16.5 21.75l-.394-1.183a2.25 2.25 0 00-1.423-1.423L13.5 18.75l1.183-.394a2.25 2.25 0 001.423-1.423l.394-1.183.394 1.183a2.25 2.25 0 001.423 1.423l1.183.394-1.183.394a2.25 2.25 0 00-1.423 1.423z" />
              </svg>
            </div>
            <span>AI 智能生成</span>
          </div>
          <div class="feature-item">
            <div class="feature-icon">
              <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="M20.25 6.375c0 2.278-3.694 4.125-8.25 4.125S3.75 8.653 3.75 6.375m16.5 0c0-2.278-3.694-4.125-8.25-4.125S3.75 4.097 3.75 6.375m16.5 0v11.25c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125V6.375m16.5 0v3.75m-16.5-3.75v3.75m16.5 0v3.75C20.25 16.153 16.556 18 12 18s-8.25-1.847-8.25-4.125v-3.75m16.5 0c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125" />
              </svg>
            </div>
            <span>RAG 知识库</span>
          </div>
          <div class="feature-item">
            <div class="feature-icon">
              <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="M13.19 8.688a4.5 4.5 0 011.242 7.244l-4.5 4.5a4.5 4.5 0 01-6.364-6.364l1.757-1.757m13.35-.622l1.757-1.757a4.5 4.5 0 00-6.364-6.364l-4.5 4.5a4.5 4.5 0 001.242 7.244" />
              </svg>
            </div>
            <span>MCP 工具调用</span>
          </div>
          <div class="feature-item">
            <div class="feature-icon">
              <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="M14.25 6.087c0-.355.186-.676.401-.959.221-.29.349-.634.349-1.003 0-1.036-1.007-1.875-2.25-1.875s-2.25.84-2.25 1.875c0 .369.128.713.349 1.003.215.283.401.604.401.959v0a.64.64 0 01-.657.643 48.39 48.39 0 01-4.163-.3c.186 1.613.293 3.25.315 4.907a.656.656 0 01-.658.663v0c-.355 0-.676-.186-.959-.401a1.647 1.647 0 00-1.003-.349c-1.036 0-1.875 1.007-1.875 2.25s.84 2.25 1.875 2.25c.369 0 .713-.128 1.003-.349.283-.215.604-.401.959-.401v0c.31 0 .555.26.532.57a48.039 48.039 0 01-.642 5.056c1.518.19 3.058.309 4.616.354a.64.64 0 00.657-.643v0c0-.355-.186-.676-.401-.959a1.647 1.647 0 01-.349-1.003c0-1.035 1.008-1.875 2.25-1.875 1.243 0 2.25.84 2.25 1.875 0 .369-.128.713-.349 1.003-.215.283-.4.604-.4.959v0c0 .333.277.599.61.58a48.1 48.1 0 005.427-.63 48.05 48.05 0 00.582-4.717.532.532 0 00-.533-.57v0c-.355 0-.676.186-.959.401-.29.221-.634.349-1.003.349-1.035 0-1.875-1.007-1.875-2.25s.84-2.25 1.875-2.25c.37 0 .713.128 1.003.349.283.215.604.401.96.401v0a.656.656 0 00.658-.663 48.422 48.422 0 00-.37-5.36c-1.886.342-3.81.574-5.766.689a.578.578 0 01-.61-.58v0z" />
              </svg>
            </div>
            <span>Skills 技能库</span>
          </div>
          <div class="feature-item">
            <div class="feature-icon">
              <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="M5.25 5.653c0-.856.917-1.398 1.667-.986l11.54 6.348a1.125 1.125 0 010 1.971l-11.54 6.347a1.125 1.125 0 01-1.667-.985V5.653z" />
              </svg>
            </div>
            <span>Playwright 自动化</span>
          </div>
          <div class="feature-item">
            <div class="feature-icon">
              <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="M7.5 21L3 16.5m0 0L7.5 12M3 16.5h13.5m0-13.5L21 7.5m0 0L16.5 12M21 7.5H7.5" />
              </svg>
            </div>
            <span>LangGraph</span>
          </div>
        </div>
      </div>
      <!-- 装饰元素 -->
      <div class="brand-decoration">
        <div class="decoration-circle circle-1"></div>
        <div class="decoration-circle circle-2"></div>
        <div class="decoration-circle circle-3"></div>
        <div class="decoration-circle circle-4"></div>
        <div class="decoration-circle circle-5"></div>
      </div>
    </div>

    <!-- 右侧登录表单区 -->
    <div class="form-panel">
      <div class="form-container">
        <div class="form-header">
          <h2 class="form-title">欢迎回来</h2>
          <p class="form-subtitle">请登录您的账户</p>
        </div>

        <!-- 登录表单 -->
        <form @submit.prevent="handleLogin" class="login-form">
          <!-- 用户名输入框 -->
          <div class="input-group">
            <div class="input-wrapper">
              <div class="input-icon">
                <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M15.75 6a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0zM4.501 20.118a7.5 7.5 0 0114.998 0A17.933 17.933 0 0112 21.75c-2.676 0-5.216-.584-7.499-1.632z" />
                </svg>
              </div>
              <input
                type="text"
                id="username"
                v-model="username"
                required
                class="form-input"
                placeholder="请输入用户名"
              />
            </div>
          </div>

          <!-- 密码输入框 -->
          <div class="input-group">
            <div class="input-wrapper">
              <div class="input-icon">
                <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M16.5 10.5V6.75a4.5 4.5 0 10-9 0v3.75m-.75 11.25h10.5a2.25 2.25 0 002.25-2.25v-6.75a2.25 2.25 0 00-2.25-2.25H6.75a2.25 2.25 0 00-2.25 2.25v6.75a2.25 2.25 0 002.25 2.25z" />
                </svg>
              </div>
              <input
                :type="showPassword ? 'text' : 'password'"
                id="password"
                v-model="password"
                required
                class="form-input"
                placeholder="请输入密码"
              />
              <div class="password-toggle" @click="togglePasswordVisibility">
                <svg v-if="!showPassword" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M2.036 12.322a1.012 1.012 0 010-.639C3.423 7.51 7.36 4.5 12 4.5c4.638 0 8.573 3.007 9.963 7.178.07.207.07.431 0 .639C20.577 16.49 16.64 19.5 12 19.5c-4.638 0-8.573-3.007-9.963-7.178z" />
                  <path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                </svg>
                <svg v-else xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M3.98 8.223A10.477 10.477 0 001.934 12C3.226 16.338 7.244 19.5 12 19.5c.993 0 1.953-.138 2.863-.395M6.228 6.228A10.45 10.45 0 0112 4.5c4.756 0 8.773 3.162 10.065 7.498a10.523 10.523 0 01-4.293 5.774M6.228 6.228L3 3m3.228 3.228l3.65 3.65m7.894 7.894L21 21m-3.228-3.228l-3.65-3.65m0 0a3 3 0 10-4.243-4.243m4.242 4.242L9.88 9.88" />
                </svg>
              </div>
            </div>
          </div>

          <!-- 记住我选项 -->
          <div class="form-options">
            <div class="checkbox-group">
              <input
                id="remember-me"
                type="checkbox"
                v-model="rememberMe"
                class="form-checkbox"
              />
              <label for="remember-me" class="checkbox-label">记住我</label>
            </div>
          </div>

          <!-- 登录按钮 -->
          <button
            type="submit"
            class="login-button"
            :class="{'loading': isLoading}"
            :disabled="isLoading"
          >
            <span v-if="!isLoading">登录</span>
            <span v-else class="loading-content">
              <svg class="loading-spinner" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
              </svg>
              登录中...
            </span>
          </button>

          <!-- 错误消息 -->
          <div v-if="errorMessage" class="error-message">
            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="error-icon">
              <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z" />
            </svg>
            {{ errorMessage }}
          </div>

          <!-- 注册链接 -->
          <div class="register-link">
            <p>
              还没有账号?
              <router-link to="/register" class="link">立即注册</router-link>
            </p>
          </div>
        </form>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed } from 'vue';
import { useRouter } from 'vue-router';
import { useAuthStore } from '@/store/authStore';
import { Message } from '@arco-design/web-vue';

// 基本表单数据
const username = ref('');
const password = ref('');
const rememberMe = ref(false);
const showPassword = ref(false);

const router = useRouter();
const authStore = useAuthStore();

// 从 store 获取加载状态和错误信息
const isLoading = computed(() => authStore.getIsLoading);
const errorMessage = computed(() => authStore.getLoginError);

// 切换密码可见性
const togglePasswordVisibility = () => {
  showPassword.value = !showPassword.value;
};

// 处理登录逻辑
const handleLogin = async () => {
  if (!username.value || !password.value) {
    Message.warning('请输入用户名和密码');
    return;
  }

  const success = await authStore.login(username.value, password.value);

  if (success) {
    Message.success('登录成功！');
    if (rememberMe.value) {
      localStorage.setItem('rememberedUsername', username.value);
    } else {
      localStorage.removeItem('rememberedUsername');
    }
    
    // 使用 nextTick 确保状态更新后再跳转
    await router.push({ name: 'Dashboard' });
  }
};

onMounted(() => {
  // 检查用户是否已登录
  authStore.checkAuthStatus();
  if (authStore.isLoggedIn) {
    router.push({ name: 'Dashboard' });
  }

  // 检查是否有记住的用户名
  const rememberedUsername = localStorage.getItem('rememberedUsername');
  if (rememberedUsername) {
    username.value = rememberedUsername;
    rememberMe.value = true;
  }
});
</script>

<style scoped>
/* 主容器 - 左右分栏布局 */
.login-container {
  min-height: 100vh;
  display: flex;
  box-sizing: border-box;
}

/* 左侧品牌展示区 */
.brand-panel {
  flex: 1;
  background: linear-gradient(145deg, #1E88E5 0%, #1565C0 50%, #0D47A1 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
  overflow: hidden;
  padding: 40px;
}

/* 玻璃质感背景层 */
.glass-overlay {
  position: absolute;
  inset: 0;
  /* 玻璃光泽效果 - 顶部高光和边缘反射 */
  background: 
    linear-gradient(135deg, rgba(255, 255, 255, 0.15) 0%, transparent 40%),
    linear-gradient(225deg, rgba(255, 255, 255, 0.08) 0%, transparent 30%),
    linear-gradient(to bottom, rgba(255, 255, 255, 0.1) 0%, transparent 15%);
  z-index: 1;
}

.brand-content {
  position: relative;
  z-index: 2;
  text-align: center;
  max-width: 480px;
}

.brand-logo {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 100px;
  height: 100px;
  background: rgba(255, 255, 255, 0.15);
  border-radius: 24px;
  margin-bottom: 28px;
  backdrop-filter: blur(10px);
  transition: all 0.3s ease;
}

.brand-logo:hover {
  transform: translateY(-5px) scale(1.05);
  background: rgba(255, 255, 255, 0.2);
}

.logo-icon {
  width: 64px;
  height: 64px;
}

.brand-title {
  font-size: 42px;
  font-weight: 700;
  color: #ffffff;
  margin: 0 0 12px 0;
  letter-spacing: -0.5px;
  text-shadow: 0 2px 10px rgba(0, 0, 0, 0.15);
}

.brand-subtitle {
  font-size: 18px;
  color: rgba(255, 255, 255, 0.9);
  margin: 0 0 48px 0;
  font-weight: 500;
}

/* 品牌特性列表 - 两列网格 */
.brand-features {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 20px 32px;
  text-align: left;
  max-width: 560px;
}

.feature-item {
  display: flex;
  align-items: center;
  gap: 14px;
  color: rgba(255, 255, 255, 0.95);
  font-size: 16px;
  font-weight: 500;
  background: rgba(255, 255, 255, 0.1);
  backdrop-filter: blur(10px);
  padding: 16px 18px;
  border-radius: 12px;
  border: 1px solid rgba(255, 255, 255, 0.15);
  transition: all 0.3s ease;
}

.feature-item:hover {
  background: rgba(255, 255, 255, 0.18);
  transform: translateY(-2px);
}

.feature-icon {
  width: 40px;
  height: 40px;
  background: rgba(255, 255, 255, 0.15);
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.feature-icon svg {
  width: 20px;
  height: 20px;
  color: #ffffff;
}

/* 品牌装饰元素 */
.brand-decoration {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  pointer-events: none;
  overflow: hidden;
}

.decoration-circle {
  position: absolute;
  border-radius: 50%;
  animation: float3d 12s ease-in-out infinite;
}

/* 大球 - 右上角 - 玻璃球效果 */
.circle-1 {
  width: 300px;
  height: 300px;
  top: -70px;
  right: -50px;
  background: 
    /* 主高光 - 左上角柔和光 */
    radial-gradient(ellipse 45% 35% at 28% 25%, rgba(255, 255, 255, 0.35) 0%, transparent 100%),
    /* 次高光 - 边缘反光 */
    radial-gradient(ellipse 28% 18% at 70% 80%, rgba(255, 255, 255, 0.12) 0%, transparent 100%),
    /* 底部阴影渐变 */
    radial-gradient(ellipse 60% 50% at 50% 100%, rgba(0, 50, 100, 0.18) 0%, transparent 80%),
    /* 球体基础色 */
    radial-gradient(circle at 50% 50%, rgba(100, 180, 255, 0.1) 0%, rgba(50, 120, 200, 0.05) 100%);
  box-shadow: 
    inset 0 -40px 70px rgba(0, 30, 80, 0.12),
    inset 0 40px 50px rgba(255, 255, 255, 0.08),
    0 30px 60px -20px rgba(0, 30, 80, 0.15),
    0 0 80px rgba(100, 180, 255, 0.06);
  animation-delay: 0s;
}

/* 中球 - 左下角 */
.circle-2 {
  width: 240px;
  height: 240px;
  bottom: -50px;
  left: -30px;
  background: 
    radial-gradient(ellipse 40% 32% at 30% 28%, rgba(255, 255, 255, 0.32) 0%, transparent 100%),
    radial-gradient(ellipse 25% 15% at 68% 78%, rgba(255, 255, 255, 0.1) 0%, transparent 100%),
    radial-gradient(ellipse 55% 45% at 50% 100%, rgba(0, 40, 80, 0.15) 0%, transparent 75%),
    radial-gradient(circle at 50% 50%, rgba(80, 160, 240, 0.08) 0%, rgba(40, 100, 180, 0.04) 100%);
  box-shadow: 
    inset 0 -35px 60px rgba(0, 25, 70, 0.1),
    inset 0 35px 45px rgba(255, 255, 255, 0.06),
    0 25px 50px -15px rgba(0, 25, 70, 0.14),
    0 0 60px rgba(80, 160, 240, 0.05);
  animation-delay: 3s;
  animation-duration: 14s;
}

/* 中小球 - 右下角 */
.circle-3 {
  width: 130px;
  height: 130px;
  bottom: 20%;
  right: 14%;
  background: 
    radial-gradient(ellipse 42% 36% at 32% 28%, rgba(255, 255, 255, 0.38) 0%, transparent 100%),
    radial-gradient(ellipse 22% 12% at 65% 75%, rgba(255, 255, 255, 0.12) 0%, transparent 100%),
    radial-gradient(ellipse 50% 40% at 50% 100%, rgba(0, 50, 100, 0.14) 0%, transparent 70%),
    radial-gradient(circle at 50% 50%, rgba(120, 200, 255, 0.1) 0%, rgba(60, 140, 220, 0.05) 100%);
  box-shadow: 
    inset 0 -20px 40px rgba(0, 30, 80, 0.08),
    inset 0 20px 30px rgba(255, 255, 255, 0.08),
    0 15px 35px -10px rgba(0, 30, 80, 0.12),
    0 0 40px rgba(120, 200, 255, 0.06);
  animation-delay: 1.5s;
  animation-duration: 10s;
}

/* 小球 - 左上角 */
.circle-4 {
  width: 85px;
  height: 85px;
  top: 24%;
  left: 12%;
  background: 
    radial-gradient(ellipse 45% 38% at 30% 25%, rgba(255, 255, 255, 0.42) 0%, transparent 100%),
    radial-gradient(ellipse 20% 10% at 62% 72%, rgba(255, 255, 255, 0.14) 0%, transparent 100%),
    radial-gradient(ellipse 45% 35% at 50% 100%, rgba(0, 60, 120, 0.12) 0%, transparent 65%),
    radial-gradient(circle at 50% 50%, rgba(140, 210, 255, 0.12) 0%, rgba(80, 160, 230, 0.06) 100%);
  box-shadow: 
    inset 0 -12px 25px rgba(0, 35, 90, 0.07),
    inset 0 12px 20px rgba(255, 255, 255, 0.1),
    0 10px 25px -8px rgba(0, 35, 90, 0.1);
  animation-delay: 4s;
  animation-duration: 11s;
}

/* 微小球 - 中间偏右 */
.circle-5 {
  width: 50px;
  height: 50px;
  top: 50%;
  right: 24%;
  background: 
    radial-gradient(ellipse 48% 42% at 28% 22%, rgba(255, 255, 255, 0.45) 0%, transparent 100%),
    radial-gradient(ellipse 18% 8% at 60% 70%, rgba(255, 255, 255, 0.15) 0%, transparent 100%),
    radial-gradient(ellipse 40% 30% at 50% 100%, rgba(0, 70, 140, 0.1) 0%, transparent 60%),
    radial-gradient(circle at 50% 50%, rgba(160, 220, 255, 0.15) 0%, rgba(100, 180, 240, 0.08) 100%);
  box-shadow: 
    inset 0 -8px 18px rgba(0, 40, 100, 0.06),
    inset 0 8px 12px rgba(255, 255, 255, 0.12),
    0 6px 18px -5px rgba(0, 40, 100, 0.08);
  animation-delay: 5s;
  animation-duration: 9s;
}

@keyframes float3d {
  0%, 100% {
    transform: translateY(0) translateX(0) scale(1);
  }
  25% {
    transform: translateY(-30px) translateX(15px) scale(1.03);
  }
  50% {
    transform: translateY(-50px) translateX(0) scale(1.05);
  }
  75% {
    transform: translateY(-25px) translateX(-15px) scale(1.02);
  }
}

/* 右侧表单区 */
.form-panel {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f1f5f9;
  padding: 40px;
}

.form-container {
  width: 100%;
  max-width: 420px;
  background: #ffffff;
  border-radius: 20px;
  padding: 40px;
  box-shadow:
    0 4px 24px rgba(0, 0, 0, 0.06),
    0 12px 48px rgba(0, 0, 0, 0.04);
  transition: all 0.35s cubic-bezier(0.4, 0, 0.2, 1);
}

.form-container:hover {
  transform: translateY(-4px);
  box-shadow:
    0 8px 32px rgba(0, 0, 0, 0.08),
    0 16px 56px rgba(0, 0, 0, 0.06);
}

.form-header {
  margin-bottom: 32px;
  text-align: center;
}

.form-title {
  font-size: 28px;
  font-weight: 700;
  color: #1e293b;
  margin: 0 0 8px 0;
}

.form-subtitle {
  font-size: 15px;
  color: #64748b;
  margin: 0;
}

/* 登录表单 */
.login-form {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

/* 输入组 */
.input-group {
  display: flex;
  flex-direction: column;
  gap: 0;
}

.input-wrapper {
  position: relative;
  display: flex;
  align-items: center;
}

.input-icon {
  position: absolute;
  left: 16px;
  z-index: 1;
  color: #9ca3af;
  transition: color 0.3s ease;
}

.input-icon svg {
  width: 20px;
  height: 20px;
}

.form-input {
  width: 100%;
  padding: 14px 18px 14px 50px;
  border: 1.5px solid #e2e8f0;
  border-radius: 12px;
  font-size: 15px;
  color: #1e293b;
  background: #ffffff;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  box-sizing: border-box;
  min-height: 50px;
}

.form-input:focus {
  outline: none;
  border-color: #00a0e9;
  background: #ffffff;
  box-shadow: 0 0 0 4px rgba(0, 160, 233, 0.08);
  transform: translateY(-1px);
}

.form-input:focus + .input-icon,
.input-wrapper:focus-within .input-icon {
  color: #00a0e9;
}

.password-toggle {
  position: absolute;
  right: 16px;
  cursor: pointer;
  color: #9ca3af;
  transition: color 0.3s ease;
  z-index: 1;
}

.password-toggle:hover {
  color: #00a0e9;
}

.password-toggle svg {
  width: 20px;
  height: 20px;
}

/* 表单选项 */
.form-options {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.checkbox-group {
  display: flex;
  align-items: center;
  gap: 12px;
}

.form-checkbox {
  width: 20px;
  height: 20px;
  border: 2px solid #d1d5db;
  border-radius: 4px;
  background: #ffffff;
  cursor: pointer;
  transition: all 0.2s ease;
}

.form-checkbox:checked {
  background: #00a0e9;
  border-color: #00a0e9;
}

.checkbox-label {
  font-size: 15px;
  color: #6b7280;
  cursor: pointer;
  user-select: none;
}

.forgot-password .link {
  font-size: 15px;
  color: #00a0e9;
  text-decoration: none;
  font-weight: 500;
  transition: color 0.2s ease;
}

.forgot-password .link:hover {
  color: #0090d1;
  text-decoration: underline;
}

/* 登录按钮 */
.login-button {
  width: 100%;
  padding: 12px 24px;
  background: #00a0e9;
  border: none;
  border-radius: 14px;
  color: #ffffff;
  font-size: 16px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  box-shadow: 0 6px 16px rgba(0, 160, 233, 0.25);
  position: relative;
  overflow: hidden;
  min-height: 48px;
  letter-spacing: 0.2px;
}

.login-button:hover:not(:disabled) {
  transform: translateY(-2px);
  box-shadow: 0 10px 25px rgba(26, 170, 235, 0.35);
  background: #1aaaeb;
}

.login-button:active:not(:disabled) {
  transform: translateY(1px) scale(0.98);
  transition: all 0.1s ease;
  background: #0090d1;
}

.login-button:disabled {
  opacity: 0.7;
  cursor: not-allowed;
  transform: none;
}

.loading-content {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
}

.loading-spinner {
  width: 20px;
  height: 20px;
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

/* 错误消息 */
.error-message {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px 20px;
  background: #fef2f2;
  border: 1px solid #fecaca;
  border-radius: 8px;
  color: #dc2626;
  font-size: 15px;
  margin-top: 8px;
}

.error-icon {
  width: 22px;
  height: 22px;
  flex-shrink: 0;
}

/* 注册链接 */
.register-link {
  text-align: center;
  margin-top: 16px;
}

.register-link p {
  font-size: 15px;
  color: #64748b;
  margin: 0;
}

.register-link .link {
  color: #00a0e9;
  text-decoration: none;
  font-weight: 600;
  transition: color 0.2s ease;
}

.register-link .link:hover {
  color: #0090d1;
  text-decoration: underline;
}

/* 响应式设计 - 小屏幕改为上下布局 */
@media (max-width: 1024px) {
  .login-container {
    flex-direction: column;
  }

  .brand-panel {
    flex: none;
    padding: 40px 24px;
    min-height: auto;
  }

  .brand-content {
    max-width: 100%;
  }

  .brand-title {
    font-size: 32px;
  }

  .brand-subtitle {
    font-size: 16px;
    margin-bottom: 32px;
  }

  .brand-features {
    grid-template-columns: repeat(3, auto);
    gap: 12px;
    justify-content: center;
  }

  .feature-item {
    font-size: 14px;
    gap: 10px;
  }

  .feature-icon {
    width: 36px;
    height: 36px;
  }

  .feature-icon svg {
    width: 18px;
    height: 18px;
  }

  .decoration-circle {
    display: none;
  }

  .form-panel {
    flex: 1;
    padding: 32px 24px;
  }

  .form-container {
    padding: 32px 28px;
  }

  .form-header {
    margin-bottom: 28px;
  }

  .form-title {
    font-size: 24px;
  }
}

@media (max-width: 640px) {
  .brand-panel {
    padding: 32px 20px;
  }

  .brand-logo {
    width: 72px;
    height: 72px;
    border-radius: 18px;
    margin-bottom: 20px;
  }

  .logo-icon {
    width: 48px;
    height: 48px;
  }

  .brand-title {
    font-size: 28px;
  }

  .brand-subtitle {
    font-size: 15px;
    margin-bottom: 24px;
  }

  .brand-features {
    gap: 12px;
  }

  .feature-item span {
    display: none;
  }

  .form-panel {
    padding: 28px 20px;
  }

  .form-container {
    max-width: 100%;
    padding: 28px 24px;
  }

  .form-title {
    font-size: 22px;
  }

  .form-subtitle {
    font-size: 14px;
  }

  .login-form {
    gap: 20px;
  }

  .form-input {
    padding: 12px 14px 12px 44px;
    min-height: 46px;
    font-size: 15px;
  }

  .input-icon {
    left: 14px;
  }

  .password-toggle {
    right: 14px;
  }

  .login-button {
    padding: 12px 20px;
    min-height: 46px;
  }
}

/* 动画效果 */
.brand-panel {
  animation: slideInLeft 0.6s ease-out;
}

.form-panel {
  animation: slideInRight 0.6s ease-out;
}

@keyframes slideInLeft {
  from {
    opacity: 0;
    transform: translateX(-30px);
  }
  to {
    opacity: 1;
    transform: translateX(0);
  }
}

@keyframes slideInRight {
  from {
    opacity: 0;
    transform: translateX(30px);
  }
  to {
    opacity: 1;
    transform: translateX(0);
  }
}

/* 输入框聚焦动画 */
.form-input:focus {
  animation: inputFocus 0.3s ease-out;
}

@keyframes inputFocus {
  0% {
    box-shadow: 0 0 0 0 rgba(0, 160, 233, 0.3);
  }
  100% {
    box-shadow: 0 0 0 4px rgba(0, 160, 233, 0.1);
  }
}

/* 按钮光效 */
.login-button:not(:disabled) {
  position: relative;
  overflow: hidden;
}

.login-button:not(:disabled)::before {
  content: '';
  position: absolute;
  top: 0;
  left: -100%;
  width: 100%;
  height: 100%;
  background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.2), transparent);
  transition: left 0.5s ease;
}

.login-button:hover:not(:disabled)::before {
  left: 100%;
}
</style>