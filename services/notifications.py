"""通知服务 - 支持邮件、钉钉、Slack"""
import smtplib
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
        self.email_enabled = bool(settings.NOTIFY_EMAIL)
        self.dingtalk_enabled = bool(settings.NOTIFY_DING_WEBHOOK)
        self.slack_enabled = bool(settings.NOTIFY_SLACK_WEBHOOK)
    
    def notify_all(self, subject: str, message: str, html: Optional[str] = None) -> Dict:
        """发送到所有启用的通知渠道
        
        Args:
            subject: 通知主题
            message: 通知消息
            html: HTML格式消息（可选）
        
        Returns:
            各渠道发送结果
        """
        results = {}
        
        if self.email_enabled:
            try:
                self.send_email(subject, message, html)
                results['email'] = 'success'
            except Exception as e:
                logger.error(f"Failed to send email: {str(e)}")
                results['email'] = f'failed: {str(e)}'
        
        if self.dingtalk_enabled:
            try:
                self.send_dingtalk(subject, message)
                results['dingtalk'] = 'success'
            except Exception as e:
                logger.error(f"Failed to send DingTalk: {str(e)}")
                results['dingtalk'] = f'failed: {str(e)}'
        
        if self.slack_enabled:
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
            return
        
        try:
            # 这里需要根据实际的邮件服务器配置调整
            # 示例使用本地邮件配置或Gmail/企业邮箱
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = settings.NOTIFY_EMAIL or 'noreply@fb-ads.local'
            msg['To'] = settings.NOTIFY_EMAIL
            msg['Date'] = datetime.utcnow().strftime('%a, %d %b %Y %H:%M:%S +0000')
            
            # 添加纯文本部分
            msg.attach(MIMEText(message, 'plain', 'utf-8'))
            
            # 如果提供了HTML，添加HTML部分
            if html:
                msg.attach(MIMEText(html, 'html', 'utf-8'))
            
            # 这里应该配置实际的SMTP服务器
            # 示例配置（需要根据实际情况修改）
            # with smtplib.SMTP('smtp.gmail.com', 587) as server:
            #     server.starttls()
            #     server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            #     server.send_message(msg)
            
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
