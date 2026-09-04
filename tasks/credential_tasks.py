"""凭据巡检定时任务（Meta Token 生命周期管理）

==========================================================================
为什么需要定时巡检
==========================================================================
Meta 的 OAuth **没有 refresh_token 机制**：

    - 短期 User Token：1~2 小时
    - 长期 User Token：固定 60 天，到期即失效，**无法自动续期**
    - 唯一免续期方案是 System User Token（需在 BM 后台手工创建）

不做巡检的后果：Token 静默失效 → 某个时间点批量投放整体失败，
且失败原因分散在各子任务的错误里，排查成本高。

因此本任务每天巡检一次：
    1. 已过期但仍为 ACTIVE 的凭据 → 标记 EXPIRED（让调用方快速失败而非带着坏 Token 重试）
    2. 临近过期（默认 7 天内）→ 汇总告警，提醒管理员重新授权

任务跨租户执行（@for_all_tenants），因为要看到所有租户的凭据。
"""
from datetime import datetime, timedelta
from typing import Dict, List

from celery import shared_task
from sqlalchemy import or_

from config.settings import settings
from core.database import SessionLocal
from core.enums import CredentialStatus
from core.logger import logger
from core.tenant import for_all_tenants
from models import Credential, MetaAccount
from services.notifications import NotificationService

# 到期前多少天开始告警
DEFAULT_WARN_DAYS = 7


def _bm_name(db, meta_account_id: str) -> str:
    meta = db.query(MetaAccount).filter(MetaAccount.id == meta_account_id).first()
    return meta.name if meta else meta_account_id


@shared_task(bind=True, name="credentials.check_expiring", max_retries=1)
@for_all_tenants
def check_expiring_credentials(self, warn_days: int = None) -> Dict:
    """巡检凭据有效期：过期标记 EXPIRED，临近过期发告警

    Args:
        warn_days: 提前告警天数，默认 7 天

    Returns:
        {"expired": int, "expiring": int, "details": [...]}
    """
    warn_days = warn_days or getattr(
        settings, "CREDENTIAL_EXPIRY_WARN_DAYS", DEFAULT_WARN_DAYS
    )
    db = SessionLocal()
    now = datetime.utcnow()
    warn_at = now + timedelta(days=warn_days)
    result: Dict = {"expired": 0, "expiring": 0, "details": []}

    try:
        # 1) 已过期但仍标记为 ACTIVE → 置为 EXPIRED
        #    只改状态字段，不动 tenant_id，绕过租户过滤下同样安全
        expired = (
            db.query(Credential)
            .filter(
                Credential.expires_at.isnot(None),
                Credential.expires_at < now,
                Credential.status == CredentialStatus.ACTIVE.value,
            )
            .all()
        )
        for cred in expired:
            cred.status = CredentialStatus.EXPIRED.value
            cred.last_error = "Token 已过期，请重新授权（Meta 长期 Token 有效期 60 天）"
            result["expired"] += 1
            result["details"].append(
                {
                    "credential_id": cred.id,
                    "meta_account_id": cred.meta_account_id,
                    "bm": _bm_name(db, cred.meta_account_id),
                    "expires_at": cred.expires_at.isoformat() if cred.expires_at else None,
                    "level": "EXPIRED",
                }
            )
        if expired:
            db.commit()
            logger.warning(f"[credential-check] 标记 {len(expired)} 条凭据为 EXPIRED")

        # 2) 临近过期 → 收集告警
        expiring = (
            db.query(Credential)
            .filter(
                Credential.expires_at.isnot(None),
                Credential.expires_at >= now,
                Credential.expires_at <= warn_at,
                Credential.status == CredentialStatus.ACTIVE.value,
            )
            .all()
        )
        for cred in expiring:
            remain = (cred.expires_at - now).days
            result["expiring"] += 1
            result["details"].append(
                {
                    "credential_id": cred.id,
                    "meta_account_id": cred.meta_account_id,
                    "bm": _bm_name(db, cred.meta_account_id),
                    "expires_at": cred.expires_at.isoformat(),
                    "remain_days": remain,
                    "level": "WARNING",
                }
            )

        # 3) 汇总通知（只在有情况时发，避免每天噪声）
        if result["expired"] or result["expiring"]:
            lines: List[str] = []
            for d in result["details"]:
                if d["level"] == "EXPIRED":
                    lines.append(f"- [已过期] {d['bm']}（{d['expires_at']}）")
                else:
                    lines.append(
                        f"- [即将过期] {d['bm']} 剩余 {d['remain_days']} 天（{d['expires_at']}）"
                    )
            message = (
                f"Meta 凭据巡检：{result['expired']} 条已过期，"
                f"{result['expiring']} 条将在 {warn_days} 天内过期。\n"
                + "\n".join(lines)
                + "\n\n请到「凭据管理」重新授权（Meta 长期 Token 有效期 60 天，无法自动续期）。"
            )
            try:
                NotificationService().notify_all("Meta 凭据到期提醒", message)
            except Exception as e:  # 通知失败不应让任务失败
                logger.error(f"[credential-check] 发送到期提醒失败: {e}")

        logger.info(
            f"[credential-check] 完成 expired={result['expired']} "
            f"expiring={result['expiring']}"
        )
        return result

    except Exception as exc:
        logger.error(f"[credential-check] 巡检失败: {exc}")
        raise self.retry(exc=exc, countdown=300)
    finally:
        db.close()
