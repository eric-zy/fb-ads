export {}

declare global {
  interface FacebookLoginResponse {
    authResponse?: { accessToken: string; userID: string; expiresIn?: number }
    status: string
  }

  interface FacebookSDK {
    init(options: { appId: string; cookie?: boolean; xfbml?: boolean; version: string }): void
    login(callback: (response: FacebookLoginResponse) => void, options?: { scope?: string; auth_type?: 'rerequest' | 'reauthorize'; return_scopes?: boolean }): void
  }

  interface Window { FB?: FacebookSDK }
}
