"""项目CLI命令"""
import click
from core.database import init_db, close_db
from core.logger import logger
from tasks.scheduler import scheduler

@click.group()
def cli():
    """Facebook 广告自动化系统CLI"""
    pass

@cli.command()
def init_database():
    """初始化数据库"""
    click.echo("Initializing database...")
    try:
        init_db()
        click.echo("✓ Database initialized successfully")
    except Exception as e:
        click.echo(f"✗ Failed to initialize database: {str(e)}", err=True)

@cli.command()
def start_scheduler():
    """启动任务调度器"""
    click.echo("Starting task scheduler...")
    try:
        scheduler.start()
        click.echo("✓ Task scheduler started")
        # 保持运行
        import time
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        click.echo("\n✓ Task scheduler stopped")
    except Exception as e:
        click.echo(f"✗ Failed to start scheduler: {str(e)}", err=True)

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
        click.echo(f"✗ Failed to start API server: {str(e)}", err=True)

@cli.command()
def run_worker():
    """运行Celery工作进程"""
    click.echo("Starting Celery worker...")
    try:
        from celery_app import celery_app
        celery_app.worker_main([
            'worker',
            '--loglevel=info',
            '--concurrency=4'
        ])
    except Exception as e:
        click.echo(f"✗ Failed to start worker: {str(e)}", err=True)

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
            click.echo(f"✓ 数据库: 已连接")
    except Exception as e:
        click.echo(f"✗ 数据库: 连接失败 ({str(e)})")
    
    # 检查Redis
    try:
        if redis_client.redis_client.ping():
            click.echo(f"✓ Redis: 已连接")
    except Exception as e:
        click.echo(f"✗ Redis: 连接失败 ({str(e)})")
    
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
