"""项目CLI命令"""
import hashlib
import uuid

import click
from core.database import init_db, close_db, SessionLocal
from core.logger import logger

@click.group()
def cli():
    """Facebook 广告自动化系统CLI"""
    pass

def _hash_password(password: str) -> str:
    """与登录接口一致的 sha256 哈希（见 main.py:_hash_password）"""
    return hashlib.sha256(password.encode("utf-8")).hexdigest()

@cli.command()
@click.option('--email', default='admin@fbads.com', help='管理员邮箱')
@click.option('--password', default='admin123456', help='管理员密码')
@click.option('--username', default='admin', help='管理员用户名')
def create_admin(email, password, username):
    """创建/重置管理员账户（密码使用与登录一致的 sha256 哈希）"""
    from models import User
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        if user:
            user.hashed_password = _hash_password(password)
            user.is_active = True
            user.role = "admin"
            click.echo(f"[OK] 已更新现有用户密码: {email}")
        else:
            user = User(
                id=str(uuid.uuid4()),
                email=email,
                username=username,
                hashed_password=_hash_password(password),
                role="admin",
                is_active=True,
                is_verified=True,
            )
            db.add(user)
            click.echo(f"[OK] 已创建管理员账户: {email}")
        db.commit()
        click.echo(f"  邮箱: {email}")
        click.echo(f"  密码: {password}")
        click.echo(f"  角色: admin")
    except Exception as e:
        db.rollback()
        click.echo(f"[FAIL] 创建失败: {str(e)}", err=True)
    finally:
        db.close()

@cli.command()
def init_database():
    """初始化数据库"""
    click.echo("Initializing database...")
    try:
        init_db()
        click.echo("[OK] Database initialized successfully")
    except Exception as e:
        click.echo(f"[FAIL] Failed to initialize database: {str(e)}", err=True)

@cli.command()
def start_beat():
    """启动 Celery Beat 定时调度器（替代原 APScheduler）

    等价命令：celery -A celery_app beat --loglevel=info
    """
    click.echo("Starting Celery Beat scheduler...")
    try:
        from celery_app import celery_app
        celery_app.start(["beat", "--loglevel=info"])
    except KeyboardInterrupt:
        click.echo("\n[OK] Celery Beat stopped")
    except Exception as e:
        click.echo(f"[FAIL] Failed to start beat: {str(e)}", err=True)

@cli.command()
@click.option('--host', default='0.0.0.0', help='API服务器主机')
@click.option('--port', default=8000, type=int, help='API服务器端口')
@click.option('--workers', default=4, type=int, help='工作进程数')
def run_api(host, port, workers):
    """运行API服务器"""
    click.echo(f"Starting API server on {host}:{port}...")
    try:
        import uvicorn
        uvicorn.run(
            "main:app",
            host=host,
            port=port,
            workers=workers,
            log_level="info"
        )
    except Exception as e:
        click.echo(f"[FAIL] Failed to start API server: {str(e)}", err=True)

@cli.command()
@click.option('--pool', default=None,
              help='Worker 池类型: solo / threads / prefork（默认自动选择: Windows=solo，其他=prefork）')
@click.option('--concurrency', default=4, type=int,
              help='并发数（仅 prefork / threads 池生效）')
def run_worker(pool, concurrency):
    """运行Celery工作进程

    Windows 下 celery 5.x 的 prefork 池会因 billiard 进程间同步
    报 PermissionError [WinError 5]，故自动改用 --pool=solo。
    等价命令: celery -A celery_app worker --loglevel=info --pool=solo
    """
    import platform
    if pool is None:
        pool = "solo" if platform.system() == "Windows" else "prefork"

    args = ['worker', '--loglevel=info', f'--pool={pool}']
    if pool != "solo":
        args.append(f'--concurrency={concurrency}')
    click.echo(f"Starting Celery worker (pool={pool})...")
    try:
        from celery_app import celery_app
        celery_app.worker_main(args)
    except Exception as e:
        click.echo(f"[FAIL] Failed to start worker: {str(e)}", err=True)

@cli.command()
def status():
    """显示系统状态"""
    from config.settings import settings
    from core.database import engine
    from core.redis_client import redis_client
    
    click.echo("\n========== 系统状态 ==========")
    click.echo(f"应用: {settings.APP_NAME} v{settings.APP_VERSION}")
    click.echo(f"环境: {settings.ENVIRONMENT}")
    
    # 检查数据库
    try:
        with engine.connect() as conn:
            click.echo("[OK] 数据库: 已连接")
    except Exception as e:
        click.echo(f"[FAIL] 数据库: 连接失败 ({str(e)})")
    
    # 检查Redis
    try:
        if redis_client.redis_client.ping():
            click.echo("[OK] Redis: 已连接")
    except Exception as e:
        click.echo(f"[FAIL] Redis: 连接失败 ({str(e)})")
    
    # 显示配置
    click.echo("\n========== 风控配置 ==========")
    click.echo(f"启用: {settings.RISK_ENABLE}")
    click.echo(f"日花费限额: ${settings.RISK_DAILY_SPEND_LIMIT}")
    click.echo(f"CTR阈值: {settings.RISK_DAILY_CTR_THRESHOLD}")
    click.echo(f"CPC阈值: ${settings.RISK_DAILY_CPC_THRESHOLD}")
    click.echo(f"欺诈评分阈值: {settings.RISK_FRAUD_SCORE_THRESHOLD}")
    
    click.echo("\n========== 定时任务配置 ==========")
    click.echo(f"拉取洞察: {settings.SCHEDULE_FETCH_INSIGHTS_CRON}")
    click.echo(f"风险检查: {settings.SCHEDULE_RISK_CHECK_CRON}")
    click.echo(f"日报告: {settings.SCHEDULE_REPORT_DAILY_CRON}")
    click.echo(f"周报告: {settings.SCHEDULE_REPORT_WEEKLY_CRON}")
    click.echo()

if __name__ == '__main__':
    cli()
