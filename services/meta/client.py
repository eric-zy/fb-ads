"""Meta API 客户端（设计文档第 20 节）

关键设计（修正原有实现的根本缺陷）：
    services/fb_client.py 中的 FacebookClient 是**全局单例**，
    在 __init__ 里用 settings.FB_ACCESS_TOKEN 做全局初始化。
    这意味着系统只能用一个 Token 访问所有账户 —— 与"多 BM / 多广告账户"
    的核心场景直接冲突。

本实现为每个账户/BM 构造**独立的 Session 与 Api 实例**，
不使用 FacebookAdsApi.init()（它是全局的，在 Celery 并发 worker 下会串号），
而是把 api 实例显式传给每个 SDK 对象，保证多账户并发安全。
"""
import json
import re
from typing import List, Optional

import requests

from facebook_business.api import FacebookAdsApi, FacebookSession
from facebook_business.adobjects.adaccount import AdAccount as FBAdAccount

from config.settings import settings
from core.logger import logger
from services.meta.errors import MetaApiError, classify, classify_facebook_error
from core.enums import ErrorCategory
from services.targeting_catalog import LANGUAGE_CATALOG, normalize_languages


class MetaClient:
    """面向单个凭据（Token）的 Meta API 客户端

    用法：
        client = MetaClient(access_token=bm_token)
        account = client.account("123456")
    """

    def __init__(
        self,
        access_token: str,
        app_id: Optional[str] = None,
        app_secret: Optional[str] = None,
    ):
        if not access_token:
            raise MetaApiError(
                "access_token 为空，无法初始化 Meta 客户端",
                category=ErrorCategory.AUTH,
            )

        self.access_token = access_token
        self.app_id = app_id or settings.FB_APP_ID
        self.app_secret = app_secret or settings.FB_APP_SECRET
        # Meta 的 adlocale 搜索结果按查询词缓存；不能只缓存一次“全量”
        # 结果，因为当前 Graph API 对 /search?type=adlocale 的无 q 请求
        # 可能返回不完整目录。
        self._ad_locales_cache: dict[str, List[dict]] = {}

        try:
            session = FacebookSession(
                app_id=self.app_id,
                app_secret=self.app_secret,
                access_token=self.access_token,
            )
            # 构造独立 Api 实例，不调用 FacebookAdsApi.init()（避免全局污染）
            self._api = FacebookAdsApi(
                session,
                api_version=settings.FB_API_VERSION,
            )
        except Exception as e:
            logger.error(f"[MetaClient] 初始化失败: {e}")
            raise MetaApiError(f"Meta 客户端初始化失败: {e}", category=ErrorCategory.AUTH)

    @property
    def api(self) -> FacebookAdsApi:
        return self._api

    @staticmethod
    def normalize_account_id(account_id: str) -> str:
        """统一广告账户 ID 前缀：123456 → act_123456"""
        account_id = (account_id or "").strip()
        if not account_id:
            raise MetaApiError("account_id 不能为空", category=ErrorCategory.VALIDATION)
        return account_id if account_id.startswith("act_") else f"act_{account_id}"

    def account(self, account_id: str) -> FBAdAccount:
        """获取绑定本客户端凭据的广告账户对象"""
        act = self.normalize_account_id(account_id)
        return FBAdAccount(act, self._api)

    # ------------------------------------------------------------------
    # Meta 账号管理 V1（设计文档 §22）
    # 所有 Meta API 调用统一从这里经过，便于 Token / 版本 / 重试 / 限流 / 错误映射
    # ------------------------------------------------------------------
    @staticmethod
    def normalize_business_id(business_id: str) -> str:
        """统一 BM ID 前缀：123456 → 123456（Graph API 直接用纯数字）"""
        bid = (business_id or "").strip()
        if not bid:
            raise MetaApiError("business_id 不能为空", category=ErrorCategory.VALIDATION)
        return bid[2:] if bid.startswith("bm") else bid

    def _get(self, path: str, params: dict) -> dict:
        """统一的 GET 调用与错误映射"""
        try:
            request_params = dict(params or {})
            for key, value in list(request_params.items()):
                if isinstance(value, (dict, list)):
                    request_params[key] = json.dumps(value, separators=(",", ":"))
            request_params["access_token"] = self.access_token
            logger.info("[MetaAPI] GET path=%s param_keys=%s", path, sorted(k for k in request_params if k != "access_token"))
            response = requests.get(
                f"https://graph.facebook.com/{settings.FB_API_VERSION}/{path.lstrip('/')}",
                params=request_params,
                timeout=settings.FB_API_TIMEOUT,
            )
            logger.info("[MetaAPI] GET response path=%s status=%s", path, response.status_code)
            payload = response.json()
            error = payload.get("error") if isinstance(payload, dict) else None
            if response.status_code >= 400 or error:
                error = error or {}
                code = error.get("code")
                subcode = error.get("error_subcode")
                raise MetaApiError(
                    error.get("message", f"Graph API HTTP {response.status_code}"),
                    category=classify(code, subcode, response.status_code),
                    code=code,
                    subcode=subcode,
                    http_status=response.status_code,
                    fbtrace_id=error.get("fbtrace_id"),
                )
            logger.info("[MetaAPI] GET success path=%s keys=%s", path, list(payload.keys()) if isinstance(payload, dict) else type(payload).__name__)
            return payload
        except MetaApiError:
            raise
        except (requests.Timeout, requests.ConnectionError) as exc:
            logger.exception("[MetaAPI] GET transport error path=%s", path)
            raise MetaApiError(str(exc), category=ErrorCategory.TEMPORARY)
        except Exception as exc:
            logger.exception("[MetaAPI] GET unexpected error path=%s", path)
            raise classify_facebook_error(exc)

    def _post(
        self,
        path: str,
        params: dict,
        files: Optional[dict] = None,
        *,
        timeout: Optional[int] = None,
        url_override: Optional[str] = None,
    ) -> dict:
        """统一的 Graph API POST 调用与错误映射。

        写入接口使用账户凭证对应的 User Access Token；不使用全局
        FB_ACCESS_TOKEN。列表/字典参数按 Graph API 的表单格式序列化。
        """
        try:
            request_params = dict(params or {})
            for key, value in list(request_params.items()):
                if isinstance(value, (dict, list)):
                    request_params[key] = json.dumps(value, separators=(",", ":"))
            request_params["access_token"] = self.access_token
            log_params = {k: v for k, v in request_params.items() if k != "access_token"}
            logger.info("[MetaAPI] POST path=%s params=%s files=%s", path, log_params, list((files or {}).keys()))
            base_url = (url_override or "https://graph.facebook.com").rstrip("/")
            response = requests.post(
                f"{base_url}/{settings.FB_API_VERSION}/{path.lstrip('/')}",
                data=request_params,
                files=files,
                timeout=timeout or settings.FB_API_TIMEOUT,
            )
            payload = response.json()
            error = payload.get("error") if isinstance(payload, dict) else None
            if response.status_code >= 400 or error:
                error = error or {}
                code = error.get("code")
                subcode = error.get("error_subcode")
                raise MetaApiError(
                    error.get("message", f"Graph API HTTP {response.status_code}"),
                    category=classify(code, subcode, response.status_code),
                    code=code,
                    subcode=subcode,
                    http_status=response.status_code,
                    fbtrace_id=error.get("fbtrace_id"),
                    error_user_title=error.get("error_user_title"),
                    error_user_msg=error.get("error_user_msg"),
                    error_type=error.get("type"),
                )
            logger.info("[MetaAPI] POST success path=%s status=%s keys=%s", path, response.status_code, list(payload.keys()) if isinstance(payload, dict) else type(payload).__name__)
            return payload
        except MetaApiError:
            raise
        except (requests.Timeout, requests.ConnectionError) as exc:
            raise MetaApiError(str(exc), category=ErrorCategory.TEMPORARY)
        except Exception as exc:
            raise classify_facebook_error(exc)

    def _delete(self, path: str) -> dict:
        """删除 Meta 对象（仅用于投放失败补偿，不作为业务删除入口）。"""
        try:
            logger.info("[MetaAPI] DELETE path=%s", path)
            response = requests.delete(
                f"https://graph.facebook.com/{settings.FB_API_VERSION}/{path.lstrip('/')}",
                params={"access_token": self.access_token},
                timeout=settings.FB_API_TIMEOUT,
            )
            logger.info("[MetaAPI] DELETE response path=%s status=%s", path, response.status_code)
            payload = response.json()
            error = payload.get("error") if isinstance(payload, dict) else None
            if response.status_code >= 400 or error:
                error = error or {}
                raise MetaApiError(error.get("message", f"Graph API HTTP {response.status_code}"), category=classify(error.get("code"), error.get("error_subcode"), response.status_code))
            logger.info("[MetaAPI] DELETE success path=%s", path)
            return payload
        except MetaApiError:
            raise
        except (requests.Timeout, requests.ConnectionError) as exc:
            logger.exception("[MetaAPI] DELETE transport error path=%s", path)
            raise MetaApiError(str(exc), category=ErrorCategory.TEMPORARY)
        except Exception as exc:
            logger.exception("[MetaAPI] DELETE unexpected error path=%s", path)
            raise classify_facebook_error(exc)

    def get_business(self, business_id: str) -> dict:
        """拉取 BM 基础信息（文档 §14 添加 BM 时用于校验 Business ID）"""
        bid = self.normalize_business_id(business_id)
        return self._get(
            bid,
            # BM 对象在较新的 Graph API 版本中并不稳定提供 currency、
            # timezone_id、created_time；绑定 BM 只需要确认对象存在、名称
            # 和授权范围，避免可选字段导致整个 OAuth 校验失败。
            params={"fields": "id,name,verification_status"},
        )

    def get_ad_accounts(self, business_id: str, max_pages: int = 20) -> List[dict]:
        """分页拉取 BM 下的广告账户（文档 §23 同步流程的 Meta 侧入口）"""
        bid = self.normalize_business_id(business_id)
        params = {
            "fields": "id,name,account_status,currency,timezone_name,"
                      "spend_cap,amount_spent,balance,disable_reason",
            "limit": 200,
        }

        accounts: List[dict] = []
        seen: set[str] = set()
        for edge in ("owned_ad_accounts", "client_ad_accounts"):
            after = None
            for _ in range(max_pages):
                if after:
                    params["after"] = after
                else:
                    params.pop("after", None)
                try:
                    data = self._get(f"{bid}/{edge}", params)
                except MetaApiError:
                    if edge == "client_ad_accounts" and accounts:
                        break
                    raise
                for account in data.get("data", []):
                    account_id = str(account.get("id") or "")
                    if account_id and account_id not in seen:
                        seen.add(account_id)
                        accounts.append(account)
                paging = data.get("paging", {}) or {}
                after = (paging.get("cursors") or {}).get("after")
                if not after:
                    break
        return accounts

    def get_ad_account(self, account_id: str) -> dict:
        """拉取单个广告账户的 Meta 侧信息（文档 §23 单账户同步）"""
        act = self.normalize_account_id(account_id)
        return self._get(
            f"/{act}",
            params={
                "fields": "id,name,account_status,currency,"
                          "timezone_name,spend_cap,amount_spent,balance,disable_reason",
            },
        )

    def get_custom_audiences(self, account_id: str, max_pages: int = 20) -> List[dict]:
        """拉取广告账户可访问的 Custom Audience 元数据，不读取成员数据。"""
        act = self.normalize_account_id(account_id)
        params = {
            "fields": "id,name,subtype,delivery_status,sharing_status,time_updated",
            "limit": 200,
        }
        audiences: List[dict] = []
        after = None
        for _ in range(max_pages):
            if after:
                params["after"] = after
            else:
                params.pop("after", None)
            payload = self._get(f"/{act}/customaudiences", params)
            audiences.extend(payload.get("data", []) or [])
            after = (payload.get("paging") or {}).get("cursors", {}).get("after")
            if not after:
                break
        return audiences

    def get_tracking_assets(
        self,
        account_id: str,
        business_id: str | None = None,
        max_pages: int = 20,
    ) -> List[dict]:
        """读取广告账户可用于转化优化的 Pixel / Dataset 元数据。

        Pixel 在 Meta API 中仍通过 ``adspixels`` 暴露；较新的 Dataset
        资产则优先从 BM 的 ``datasets`` 边读取，部分账户也支持账户级
        ``datasets``。这里只返回元数据，不读取事件或用户数据。
        """
        assets: list[dict] = []
        seen: set[tuple[str, str]] = set()
        account_object_id = self.normalize_account_id(account_id)
        edges: list[tuple[str, str]] = [(account_object_id, "PIXEL")]
        edges.append((account_object_id, "DATASET"))
        if business_id:
            edges.append((self.normalize_business_id(business_id), "DATASET"))

        for object_id, asset_type in edges:
            path = f"/{object_id}/adspixels" if asset_type == "PIXEL" else f"/{object_id}/datasets"
            params = {
                "fields": "id,name,owner_ad_account,owner_business",
                "limit": 200,
            }
            after = None
            for _ in range(max_pages):
                if after:
                    params["after"] = after
                else:
                    params.pop("after", None)
                try:
                    payload = self._get(path, params)
                except MetaApiError as exc:
                    # Dataset 不是所有 Graph API 版本/授权范围都提供，
                    # 因此其边不可用时继续尝试另一条边；Pixel 失败仍需
                    # 让调用方看到权限问题，避免把授权异常伪装成空列表。
                    if asset_type == "DATASET":
                        break
                    raise exc
                for raw in payload.get("data", []) or []:
                    asset_id = str(raw.get("id") or "").strip()
                    if not asset_id or (asset_type, asset_id) in seen:
                        continue
                    # BM 级 Dataset 列表可能包含该 BM 下其它账户的资产；
                    # 没有明确 owner_ad_account 时宁可不返回，禁止跨账户串用。
                    if asset_type == "DATASET" and object_id != account_object_id:
                        owner = raw.get("owner_ad_account") or {}
                        owner_id = owner.get("id") if isinstance(owner, dict) else owner
                        if not owner_id or self.normalize_account_id(str(owner_id)) != account_object_id:
                            continue
                    seen.add((asset_type, asset_id))
                    assets.append({
                        "id": asset_id,
                        "name": str(raw.get("name") or asset_id),
                        "asset_type": asset_type,
                        "owner_ad_account": raw.get("owner_ad_account"),
                        "owner_business": raw.get("owner_business"),
                        "last_fired_time": raw.get("last_fired_time"),
                    })
                after = (payload.get("paging") or {}).get("cursors", {}).get("after")
                if not after:
                    break
        return assets

    def get_ad_locales(self, max_pages: int = 20, query: str | None = None) -> List[dict]:
        """从 Meta Targeting Search 拉取可用于 targeting.locales 的语言 ID。

        Meta 官方接口返回的是 locale 对象及其 ID；发布时应使用返回的
        numeric ID，而不是 ``en``、``English`` 等产品层别名。带 q 查询
        比无条件请求“全量目录”更可靠，也能适配目录分页/裁剪。
        """
        cache_key = " ".join(str(query or "").split()).casefold()
        if cache_key in self._ad_locales_cache:
            return list(self._ad_locales_cache[cache_key])
        params = {"type": "adlocale", "limit": 2000}
        if cache_key:
            params["q"] = str(query).strip()
        locales: List[dict] = []
        after = None
        pages = 0
        for _ in range(max_pages):
            pages += 1
            if after:
                params["after"] = after
            else:
                params.pop("after", None)
            payload = self._get("/search", params)
            # Targeting Search follows the Graph API/SDK response contract:
            # ``data`` is normally a list, but some API versions return an
            # object keyed by the result ID.  Treating that object as an
            # iterable used to append only its keys (strings), which meant
            # the resolver could never find English even though Meta had
            # returned a valid adlocale result.
            raw_data = payload.get("data", []) if isinstance(payload, dict) else []
            if isinstance(raw_data, dict):
                page_items = [item for item in raw_data.values() if isinstance(item, dict)]
            elif isinstance(raw_data, list):
                page_items = [item for item in raw_data if isinstance(item, dict)]
            else:
                page_items = []
            locales.extend(page_items)
            after = (payload.get("paging") or {}).get("cursors", {}).get("after")
            if not after:
                break
        logger.info(
            "[MetaTargeting] adlocale search query=%s pages=%s results=%s samples=%s",
            query or "",
            pages,
            len(locales),
            [
                {
                    "id": item.get("id"),
                    "labels": {
                        key: item.get(key)
                        for key in (
                            "name",
                            "name_en",
                            "code",
                            "locale",
                            "key",
                            "label",
                            "title",
                            "display_name",
                        )
                        if item.get(key) is not None
                    },
                }
                for item in locales[:5]
            ],
        )
        self._ad_locales_cache[cache_key] = list(locales)
        return locales

    def resolve_targeting_locales(self, targeting: dict | None) -> dict:
        """把产品层 languages 别名解析成 Meta targeting.locales ID。"""
        result = dict(targeting or {})
        raw_languages = result.pop("languages", None)
        if raw_languages is None or not raw_languages:
            return result

        requested = normalize_languages(raw_languages)
        resolved = [str(value) for value in (result.get("locales") or [])]
        catalog = {item["id"]: item for item in LANGUAGE_CATALOG}

        def clean(value: object) -> str:
            # Meta may return labels such as ``English (All)``, ``English-All``
            # or localized text.  Compare a punctuation-insensitive form so
            # the official Targeting Search label is not rejected merely due
            # to display formatting.
            return re.sub(r"[^\w]+", "", str(value or "").casefold())

        for item_id in requested:
            if str(item_id).isdigit():
                if str(item_id) not in resolved:
                    resolved.append(str(item_id))
                continue
            item = catalog.get(item_id)
            if not item:
                raise ValueError(f"语言 {item_id} 不在当前 Meta 语言目录中")
            names = {
                clean(item["name"]),
                clean(item["name_en"]),
                clean(item["code"]),
            }

            def find_candidates(available: list[dict]) -> list[dict]:
                candidates = []
                for remote in available:
                    remote_id = str(remote.get("id") or "").strip()
                    if not remote_id:
                        continue
                    remote_labels = {
                        clean(remote.get(key))
                        for key in (
                            "name",
                            "name_en",
                            "code",
                            "locale",
                            "key",
                            "label",
                            "title",
                            "display_name",
                        )
                        if remote.get(key)
                    }
                    if not remote_labels:
                        continue
                    if any(
                        label in names
                        or any(
                            name and (label.startswith(name) or name.startswith(label))
                            for name in names
                        )
                        for label in remote_labels
                    ):
                        candidates.append(remote)
                return candidates

            # 官方 Targeting Search 支持 q；优先按英文名、代码、中文名
            # 查询，避免依赖无 q 的不完整分页结果。
            candidates: list[dict] = []
            for query in (item["name_en"], item["code"], item["name"]):
                candidates = find_candidates(self.get_ad_locales(query=query))
                if candidates:
                    break
            if not candidates:
                # 保留一次无 q 兼容回退，覆盖旧版 Graph API 的行为。
                candidates = find_candidates(self.get_ad_locales())
            candidates.sort(key=lambda row: ("all" not in clean(row.get("name")), str(row.get("id"))))
            if not candidates:
                raise MetaApiError(
                    f"Meta 当前未返回语言“{item['name']}”的 adlocale ID，请刷新语言目录后重试",
                    category=ErrorCategory.VALIDATION,
                    code=100,
                )
            remote_id = str(candidates[0].get("id"))
            if remote_id not in resolved:
                resolved.append(remote_id)

        result["locales"] = resolved
        return result
