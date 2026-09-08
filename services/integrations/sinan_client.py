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
