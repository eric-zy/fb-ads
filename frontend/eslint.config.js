import vue from 'eslint-plugin-vue'
import vueParser from 'vue-eslint-parser'
import tsParser from '@typescript-eslint/parser'

export default [
  { ignores: ['dist/**', 'node_modules/**', 'src/auto-imports.d.ts', 'src/components.d.ts'] },
  ...vue.configs['flat/essential'],
  {
    files: ['**/*.vue'],
    languageOptions: { parser: vueParser, parserOptions: { parser: tsParser, ecmaVersion: 'latest', sourceType: 'module' } },
    // 页面组件与路由同名；保留现有名称，检查模板中的实际错误。
    rules: { 'vue/multi-word-component-names': 'off' },
  },
  { files: ['**/*.ts'], languageOptions: { parser: tsParser } },
]
