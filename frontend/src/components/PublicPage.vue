<template>
  <main class="public-page"><article class="public-card">
    <header><div class="brand">myAds</div><nav><RouterLink to="/">首页</RouterLink><RouterLink to="/privacy-policy">隐私政策</RouterLink><RouterLink to="/terms">服务条款</RouterLink><RouterLink to="/data-deletion">数据删除</RouterLink><RouterLink to="/contact">联系我们</RouterLink></nav></header>
    <slot /><footer>安徽品城网络科技有限公司 · <a href="mailto:yz6837053@gmail.com">yz6837053@gmail.com</a></footer>
  </article></main>
</template>
<style scoped>
.public-page{min-height:100vh;padding:36px 20px;background:#f5f7fb;color:#1f2937}.public-card{max-width:900px;margin:0 auto;padding:34px 46px;background:#fff;border-radius:12px;box-shadow:0 8px 30px rgba(15,23,42,.08);line-height:1.8}header{display:flex;align-items:center;justify-content:space-between;gap:20px;padding-bottom:24px;border-bottom:1px solid #e5e7eb}.brand{color:#1877f2;font-size:22px;font-weight:700}nav{display:flex;flex-wrap:wrap;gap:14px}nav a{color:#52606d;text-decoration:none;font-size:14px}nav a.router-link-active{color:#1877f2}h1{margin:30px 0 6px;font-size:30px}h2{margin:26px 0 6px;font-size:19px}p{margin:8px 0}ul,ol{padding-left:22px}a{color:#1877f2}footer{margin-top:32px;padding-top:18px;border-top:1px solid #e5e7eb;color:#829ab1;font-size:13px}@media(max-width:640px){.public-card{padding:24px 20px}header{align-items:flex-start;flex-direction:column}}
</style>
