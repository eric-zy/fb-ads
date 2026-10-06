"""通知服务 - 支持邮件、钉钉、Slack"""
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional, List, Dict
import requests
from datetime import datetime

from config.settings import settings
from core.logger import logger

class NotificationService:
    """多渠道通知服务"""
    
    def __init__(self):
        self.email_enabled = bool(settings.NOTIFY_EMAIL and settings.SMTP_HOST)
        self.dingtalk_enabled = bool(settings.NOTIFY_DING_WEBHOOK)
        self.slack_enabled = bool(settings.NOTIFY_SLACK_WEBHOOK)
    
    def notify_all(
        self,
        subject: str,
        message: str,
        html: Optional[str] = None,
        channels: Optional[List[str]] = None,
    ) -> Dict:
        """发送到所有启用的通知渠道
        
        Args:
            subject: 通知主题
            message: 通知消息
            html: HTML格式消息（可选）
        
        Returns:
            各渠道发送结果
        """
        results = {}
        selected = set(channels) if channels is not None else {"email", "dingtalk", "slack"}
        if "email" in selected and not self.email_enabled:
            results["email"] = "disabled"

        if self.email_enabled and "email" in selected:
            try:
                self.send_email(subject, message, html)
                results['email'] = 'success'
            except Exception as e:
                logger.error(f"Failed to send email: {str(e)}")
                results['email'] = f'failed: {str(e)}'
        
        if self.dingtalk_enabled and "dingtalk" in selected:
            try:
                self.send_dingtalk(subject, message)
                results['dingtalk'] = 'success'
            except Exception as e:
                logger.error(f"Failed to send DingTalk: {str(e)}")
                results['dingtalk'] = f'failed: {str(e)}'
        
        if self.slack_enabled and "slack" in selected:
            try:
                self.send_slack(subject, message)
                results['slack'] = 'success'
            except Exception as e:
                logger.error(f"Failed to send Slack: {str(e)}")
                results['slack'] = f'failed: {str(e)}'
        
        return results
    
    def send_email(self, subject: str, message: str, html: Optional[str] = None):
        """发送邮件通知
        
        Args:
            subject: 邮件主题
            message: 邮件内容（纯文本）
            html: HTML格式内容（可选）
        """
        if not self.email_enabled:
            raise RuntimeError("邮件渠道未配置")
        
        try:
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = settings.SMTP_FROM or settings.SMTP_USER or settings.NOTIFY_EMAIL
            msg['To'] = settings.NOTIFY_EMAIL
            msg['Date'] = datetime.utcnow().strftime('%a, %d %b %Y %H:%M:%S +0000')
            
            # 添加纯文本部分
            msg.attach(MIMEText(message, 'plain', 'utf-8'))
            
            # 如果提供了HTML，添加HTML部分
            if html:
                msg.attach(MIMEText(html, 'html', 'utf-8'))
            
            context = ssl.create_default_context()
            smtp_class = smtplib.SMTP_SSL if settings.SMTP_SSL else smtplib.SMTP
            kwargs = {"timeout": settings.SMTP_TIMEOUT}
            if settings.SMTP_SSL:
                kwargs["context"] = context
            with smtp_class(settings.SMTP_HOST, settings.SMTP_PORT, **kwargs) as server:
                if not settings.SMTP_SSL and settings.SMTP_STARTTLS:
                    server.starttls(context=context)
                if settings.SMTP_USER:
                    server.login(settings.SMTP_USER, settings.SMTP_PASSWORD or "")
                refused = server.send_message(msg)
                if refused:
                    raise smtplib.SMTPRecipientsRefused(refused)
            
            logger.info(f"Email notification sent to {settings.NOTIFY_EMAIL}")
        except Exception as e:
            logger.error(f"Failed to send email: {str(e)}")
            raise
    
    def send_dingtalk(self, subject: str, message: str):
        """发送钉钉通知
        
        Args:
            subject: 通知主题
            message: 通知消息
        """
        if not self.dingtalk_enabled:
            return
        
        try:
            data = {
                "msgtype": "text",
                "text": {
                    "content": f"{subject}\n{message}"
                },
                "at": {
                    "isAtAll": False
                }
            }
            
            response = requests.post(
                settings.NOTIFY_DING_WEBHOOK,
                json=data,
                timeout=10
            )
            
            if response.status_code != 200:
                raise Exception(f"DingTalk API returned {response.status_code}")
            
            logger.info("DingTalk notification sent successfully")
        except Exception as e:
            logger.error(f"Failed to send DingTalk notification: {str(e)}")
            raise
    
    def send_slack(self, subject: str, message: str):
        """发送Slack通知
        
        Args:
            subject: 通知主题
            message: 通知消息
        """
        if not self.slack_enabled:
            return
        
        try:
            data = {
                "text": subject,
                "blocks": [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*{subject}*\n{message}"
                        }
                    }
                ]
            }
            
            response = requests.post(
                settings.NOTIFY_SLACK_WEBHOOK,
                json=data,
                timeout=10
            )
            
            if response.status_code != 200:
                raise Exception(f"Slack API returned {response.status_code}")
            
            logger.info("Slack notification sent successfully")
        except Exception as e:
            logger.error(f"Failed to send Slack notification: {str(e)}")
            raise
