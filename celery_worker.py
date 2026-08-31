import os
import sys

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(__file__))

from celery_app import celery_app

__all__ = ['celery_app']
