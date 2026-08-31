#!/usr/bin/env python3
"""一次性迁移：把 meta_accounts 中的明文 Token 加密迁入 credentials 表。

背景（设计文档第 9 节）：
    Access Token 必须加密存储，不应直接存放在 BM / 广告账户表中。
    历史实现把 access_token、app_secret 明文存在 meta_accounts，
    一旦数据库泄露或日志回显即造成凭据外泄。

用法：
    # 1) 先预览，确认影响范围（不写库）
    python scripts/migrate_tokens_to_credentials.py --dry-run

    # 2) 执行迁移（默认保留明文字段，稳妥）
    python scripts/migrate_tokens_to_credentials.py

    # 3) 确认业务正常后，再清空明文字段
    python scripts/migrate_tokens_to_credentials.py --purge

重要前提：
    加解密密钥由 settings.SECRET_KEY 派生（见 core/security.py）。
    迁移前请确保 .env 中 SECRET_KEY 已设置为稳定值并妥善备份；
    一旦 SECRET_KEY 变更，已加密的凭据将无法解密。

幂等：已存在 ACTIVE 凭据的 BM 自动跳过；--force 可强制再新增一条。
"""
from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy.orm import Session

from core.database import SessionLocal
from core.enums import CredentialStatus
from core.logger import logger
from core.security import mask_token
from models import Credential, MetaAccount


def migrate(db: Session, *, dry_run: bool, purge: bool, force: bool) -> dict:
    stats = {"total": 0, "migrated": 0, "skipped": 0, "purged": 0, "failed": 0}

    metas = db.query(MetaAccount).all()
    stats["total"] = len(metas)

    for meta in metas:
        if not meta.access_token:
            print(f"  [skip]   BM {meta.id} ({meta.name}) 无 access_token")
            stats["skipped"] += 1
            continue

        existing = (
            db.query(Credential)
            .filter(
                Credential.meta_account_id == meta.id,
                Credential.status == CredentialStatus.ACTIVE.value,
            )
            .first()
        )

        if existing and not force:
            print(f"  [skip]   BM {meta.id} 已存在凭据 {existing.id}")
            stats["skipped"] += 1
        elif dry_run:
            print(
                f"  [dry-run] 将创建凭据: BM={meta.id} "
                f"token={mask_token(meta.access_token)}"
            )
            stats["migrated"] += 1
        else:
            try:
                cred = Credential(
                    id=uuid.uuid4().hex,
                    meta_account_id=meta.id,
                    token_type="USER",
                    status=CredentialStatus.ACTIVE.value,
                )
                # set_access_token 内部完成 Fernet 加密，明文不落盘
                cred.set_access_token(meta.access_token)
                db.add(cred)
                db.flush()
                print(
                    f"  [ok]     BM {meta.id} -> 凭据 {cred.id} "
                    f"token={mask_token(meta.access_token)}"
                )
                stats["migrated"] += 1
            except Exception as e:
                logger.error(f"迁移失败 BM={meta.id}: {e}")
                print(f"  [fail]   BM {meta.id}: {e}")
                stats["failed"] += 1
                continue

        # 清空明文字段（仅 access_token；app_secret 建议改为环境变量注入）
        if purge and not dry_run:
            meta.access_token = ""
            if meta.app_secret:
                print(
                    f"  [warn]   BM {meta.id} 仍有明文 app_secret，"
                    f"建议改为环境变量 FB_APP_SECRET 注入后清空该列"
                )
            stats["purged"] += 1
            print(f"  [purge]  BM {meta.id} 明文 access_token 已清空")

    if not dry_run:
        db.commit()

    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="迁移明文 Token 到加密凭据表")
    parser.add_argument("--dry-run", action="store_true", help="只预览，不写入数据库")
    parser.add_argument(
        "--purge", action="store_true", help="迁移后清空 meta_accounts 的明文 access_token"
    )
    parser.add_argument("--force", action="store_true", help="即使已存在凭据也新增一条")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        mode = "DRY RUN" if args.dry_run else "LIVE"
        if args.purge:
            mode += " + PURGE"
        print("=== 明文 Token -> 加密凭据表 迁移 ===")
        print(f"模式: {mode}\n")

        stats = migrate(db, dry_run=args.dry_run, purge=args.purge, force=args.force)

        print("\n---- 结果 ----")
        print(f"BM 总数    : {stats['total']}")
        print(f"已迁移     : {stats['migrated']}")
        print(f"跳过       : {stats['skipped']}")
        print(f"清空明文   : {stats['purged']}")
        print(f"失败       : {stats['failed']}")
        if args.dry_run:
            print("\n(DRY RUN：未写入任何数据)")
        elif stats["purged"] == 0:
            print("\n提示：明文字段仍保留。确认业务正常后，用 --purge 再次执行以清空。")
    finally:
        db.close()


if __name__ == "__main__":
    main()
