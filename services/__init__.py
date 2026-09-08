"""Service package.

服务对象必须从其具体模块显式导入。这里不再初始化全局 Facebook SDK，
避免进程启动时绑定全局 Token，并防止 Celery 并发任务发生凭据串用。
"""
