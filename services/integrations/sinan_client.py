from typing import Any, Dict, Optional
import httpx

class SinanClient:
    def __init__(self, base_url: str, app_id: str, access_token: str, refresh_token: str, menu_id: str):
        self.base_url = base_url.rstrip('/'); self.app_id = app_id; self.menu_id = menu_id
        self.cookies = {'access_token': access_token, 'refresh_token': refresh_token}
    async def request(self, method: str, path: str, *, params: Optional[Dict[str, Any]] = None, json: Any = None):
        q = dict(params or {}); q.setdefault('app_id', self.app_id)
        async with httpx.AsyncClient(timeout=25) as client:
            res = await client.request(method, self.base_url + path, params=q, json=json, cookies=self.cookies, headers={'distributor-menu-id': self.menu_id, 'Accept': 'application/json, text/plain, */*'})
        if res.status_code >= 400: raise RuntimeError(f'Sinan HTTP {res.status_code}')
        data = res.json()
        if data.get('code') not in (None, 0): raise RuntimeError(data.get('message') or '司南接口失败')
        return data
    async def content_list(self, content_type, keyword='', page=1, page_size=20):
        key = {'SHORT_VIDEO': '1', 'COMIC': '4'}[content_type]
        return await self.request('POST', '/delivery/drama/list/v1', json={'drama_id': keyword, 'filter_options': [{'filter': 5, 'filter_key_list': [key]}], 'page_info': {'page': page, 'page_size': page_size}})
    async def content_info(self, drama_id): return await self.request('GET', '/delivery/drama/info/v1', params={'drama_id': drama_id})
    async def chapters(self, drama_id): return await self.request('GET', '/delivery/chapter/list/v1', params={'drama_id': drama_id})
    async def promotion_list(self, page=1, page_size=20): return await self.request('POST', '/delivery/promotion/query/v1', json={'page': page, 'page_size': page_size})
    async def promotion_detail(self, promotion_id): return await self.request('GET', '/delivery/promotion/query_by_id/v1', params={'promotion_id': promotion_id})
    async def create_promotion(self, payload): return await self.request('POST', '/delivery/promotion/create/v1', json=payload)
    async def app_tree(self): return await self.request('GET', '/account/org_tree/v1')
    async def filter_options(self): return await self.request('GET', '/delivery/filter_options/v1')
    async def pixels(self, media_channel, real_app_id): return await self.request('GET', '/delivery/promotion/pixel/query/v1', params={'media_channel': media_channel, 'real_app_id': real_app_id})
    async def recharge_templates(self, real_app_id): return await self.request('GET', '/delivery/recharge_template/query/v1', params={'page': 1, 'page_size': 100, 'dis_app_id': real_app_id})
    async def return_rules(self): return await self.request('GET', '/delivery/ad_convt_config/query/v1', params={'page': 1, 'page_size': 200, 'status': 1, 'is_query_self_create': 'true'})
    async def default_price(self, drama_id, real_app_id): return await self.request('GET', '/delivery/promotion/default_price/v1', params={'drama_id': drama_id, 'real_app_id': real_app_id})
    async def update_promotion(self, payload): return await self.request('POST', '/delivery/promotion/update/v1', json=payload)
    def promotion_detail_sync(self, promotion_id):
        q = {'app_id': self.app_id, 'promotion_id': promotion_id}
        with httpx.Client(timeout=25) as client:
            res = client.get(self.base_url + '/delivery/promotion/query_by_id/v1', params=q, cookies=self.cookies, headers={'distributor-menu-id': self.menu_id, 'Accept': 'application/json'})
        if res.status_code >= 400: raise RuntimeError(f'Sinan HTTP {res.status_code}')
        data = res.json()
        if data.get('code') != 0: raise RuntimeError(data.get('message') or '司南推广链查询失败')
        return data.get('data') or {}
