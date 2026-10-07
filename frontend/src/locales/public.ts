import { computed } from 'vue'
import { useLocale } from '@/stores/localeStore'

export const CONTACT_EMAIL = 'bhtf2026@ahpcwl.cn'

const copy = {
  zh: {
    company: '安徽品城网络科技有限公司',
    nav: { home: '首页', about: '关于公司', privacy: '隐私政策', terms: '服务条款', deletion: '数据删除', contact: '联系我们', login: '平台登录' },
    companyInfo: '公司信息',
    companyName: '公司名称',
    addressLabel: '办公地址',
    registeredAddressLabel: '注册地址',
    address: '合肥市高新区红枫路19号柏岭大厦办公2120室',
    creditCode: '统一社会信用代码',
    contactEmail: '联系邮箱',
    contactHelp: '如需处理授权、账户接入、隐私或数据删除请求，请通过上述邮箱联系我们。',
    about: {
      intro: 'myAds 由安徽品城网络科技有限公司运营，为企业用户提供 Meta 广告账户接入、广告创建管理、批量投放、投放状态同步和数据报表服务。',
      typeLabel: '企业类型', type: '有限责任公司（自然人投资或控股）',
      foundedLabel: '成立日期', founded: '2017年4月26日',
      serviceTitle: '服务说明', service: '平台仅在用户明确授权的范围内访问 Business Manager、广告账户和 Facebook Page，并用于广告管理、投放监控和报表服务。',
    },
    privacy: {
      updated: '最后更新：2026年9月5日',
      intro: '本政策说明安徽品城网络科技有限公司运营的 myAds 如何处理您通过 Facebook 登录及 Meta API 授权的广告账户信息。',
      sections: [
        { title: '一、收集的信息', text: '经您授权后，系统可能获取 Facebook 用户标识、广告账户标识、名称、状态、币种、时区、投放及花费数据。' },
        { title: '二、信息用途', text: '数据仅用于广告账户接入、广告创建与管理、批量投放、状态同步、花费统计和报表分析，不出售或出租给第三方。' },
        { title: '三、保存与安全', text: '授权凭据经过加密保存，并通过访问控制和安全措施保护。您可以在 Facebook 的应用和网站设置中撤销授权。' },
      ],
      deletionTitle: '四、数据删除', deletionBefore: '如需删除授权信息或相关数据，请访问', deletionLink: '数据删除说明', deletionAfter: '，或联系',
    },
    terms: {
      updated: '最后更新：2026年9月10日', intro: '使用 myAds 即表示您同意遵守本条款及适用法律法规。',
      sections: [
        { title: '服务范围', text: 'myAds 提供广告账户连接、广告创建管理、投放监控和报表服务。所有 Meta 资产操作均以用户授权和平台权限为前提。' },
        { title: '用户责任', text: '用户应确保拥有所连接资产的合法权限，并对广告内容、落地页、预算、付款方式及投放行为负责，不得发布违法、欺诈或违反 Meta 政策的内容。' },
        { title: '服务限制', text: '因 Meta 接口、账户状态、审核、支付或网络原因造成的限制，不视为 myAds 对投放结果的保证。' },
      ],
    },
    deletion: {
      before: '如需删除 myAds 中与 Facebook/Meta 授权相关的数据，请发送邮件至',
      after: '，主题填写“myAds 数据删除申请”，并提供注册邮箱或用户 ID。',
      subject: 'myAds 数据删除申请', process: '处理流程',
      steps: ['核验申请人身份及账户归属。', '撤销对应 Meta 授权并停止后续同步。', '删除授权凭据、账户关联及可删除的业务数据。', '完成处理后通过邮件通知申请人。'],
      note: 'Meta 平台中的数据还需在 Facebook 设置中单独删除或撤销授权。',
    },
  },
  en: {
    company: 'Anhui Pincheng Network Technology Co., Ltd.',
    nav: { home: 'Home', about: 'About us', privacy: 'Privacy Policy', terms: 'Terms of Service', deletion: 'Data Deletion', contact: 'Contact us', login: 'Platform login' },
    companyInfo: 'Company information',
    companyName: 'Company name',
    addressLabel: 'Office address',
    registeredAddressLabel: 'Registered address',
    address: 'Room 2120, Bailing Building, No. 19 Hongfeng Road, High-tech Zone, Hefei, China',
    creditCode: 'Unified Social Credit Code',
    contactEmail: 'Contact email',
    contactHelp: 'For authorization, account access, privacy or data deletion requests, please contact us at the email address above.',
    about: {
      intro: 'myAds is operated by Anhui Pincheng Network Technology Co., Ltd. It provides businesses with Meta ad account access, ad creation and management, batch delivery, delivery status synchronization and reporting services.',
      typeLabel: 'Company type', type: 'Limited liability company (invested in or controlled by natural persons)',
      foundedLabel: 'Established', founded: 'April 26, 2017',
      serviceTitle: 'Our services', service: 'The platform accesses Business Managers, ad accounts and Facebook Pages only within the scope explicitly authorized by users, for ad management, delivery monitoring and reporting.',
    },
    privacy: {
      updated: 'Last updated: September 5, 2026',
      intro: 'This policy explains how myAds, operated by Anhui Pincheng Network Technology Co., Ltd., processes ad account information authorized through Facebook Login and Meta APIs.',
      sections: [
        { title: '1. Information collected', text: 'With your authorization, the system may obtain Facebook user identifiers, ad account identifiers, names, statuses, currencies, time zones, delivery data and spending data.' },
        { title: '2. Use of information', text: 'Data is used only for ad account access, ad creation and management, batch delivery, status synchronization, spending statistics and reporting analysis. We do not sell or rent it to third parties.' },
        { title: '3. Storage and security', text: 'Authorization credentials are stored in encrypted form and protected by access controls and security measures. You can revoke authorization in the Apps and Websites section of your Facebook settings.' },
      ],
      deletionTitle: '4. Data deletion', deletionBefore: 'To delete authorization information or related data, see our', deletionLink: 'data deletion instructions', deletionAfter: 'or contact',
    },
    terms: {
      updated: 'Last updated: September 10, 2026', intro: 'By using myAds, you agree to these terms and applicable laws and regulations.',
      sections: [
        { title: 'Scope of services', text: 'myAds provides ad account connections, ad creation and management, delivery monitoring and reporting. All operations on Meta assets require user authorization and the relevant platform permissions.' },
        { title: 'User responsibilities', text: 'Users must have lawful access to connected assets and are responsible for ad content, landing pages, budgets, payment methods and advertising activities. Users must not publish unlawful or fraudulent content or content that violates Meta policies.' },
        { title: 'Service limitations', text: 'Delivery may be restricted by Meta APIs, account status, reviews, payments or network conditions. myAds does not guarantee advertising outcomes.' },
      ],
    },
    deletion: {
      before: 'To delete data in myAds associated with Facebook or Meta authorization, email',
      after: 'with the subject “myAds data deletion request” and include your registered email address or user ID.',
      subject: 'myAds data deletion request', process: 'Request process',
      steps: ['Verify the requester’s identity and account ownership.', 'Revoke the corresponding Meta authorization and stop further synchronization.', 'Delete authorization credentials, account associations and business data eligible for deletion.', 'Notify the requester by email when processing is complete.'],
      note: 'Data held by Meta must be deleted or authorization revoked separately in your Facebook settings.',
    },
  },
}

export function usePublicCopy() {
  const { locale } = useLocale()
  return computed(() => copy[locale.value])
}
