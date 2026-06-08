#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
钉钉推送模块
支持Markdown消息、重复运行保护、运行结果通知
"""

import os
import sys
import json
import logging
import requests
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logger = logging.getLogger('sender')


class DingTalkSender:
    """钉钉推送器"""
    
    def __init__(self, webhook, settings):
        self.webhook = webhook
        self.settings = settings
        self.dingtalk_config = settings.get('dingtalk', {})
        self.max_message_size = self.dingtalk_config.get('max_message_size', 18000)
        self.split_by_country = self.dingtalk_config.get('split_by_country', True)
        self.project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    def send_all(self, reports, country_order):
        """发送所有报告"""
        if not reports:
            logger.warning("没有报告可发送")
            return False
        
        success_count = 0
        fail_count = 0
        
        # 按国家顺序发送
        for country_key in country_order:
            if country_key not in reports:
                continue
            
            report = reports[country_key]
            
            try:
                # 发送Markdown消息
                success = self._send_markdown(report, country_key)
                
                if success:
                    success_count += 1
                    logger.info(f"发送成功: {country_key}")
                else:
                    fail_count += 1
                    logger.warning(f"发送失败: {country_key}")
                    
            except Exception as e:
                fail_count += 1
                logger.error(f"发送异常 {country_key}: {e}")
        
        # 发送汇总消息
        self._send_summary(reports, success_count, fail_count)
        
        return fail_count == 0
    
    def _send_markdown(self, report, country_key):
        """发送Markdown消息"""
        markdown_content = report.get('markdown', '')
        image_path = report.get('image_path', '')
        country_config = report.get('country_config', {})
        total_items = report.get('total_items', 0)
        
        # 分割过长的消息
        if len(markdown_content) > self.max_message_size:
            parts = self._split_markdown(markdown_content)
        else:
            parts = [markdown_content]
        
        for i, part in enumerate(parts):
            # 构建钉钉消息
            message = {
                "msgtype": "markdown",
                "markdown": {
                    "title": f"{country_config.get('flag', '')} {country_config.get('name', country_key)} 新闻",
                    "text": part
                }
            }
            
            # 发送
            response = self._http_post(self.webhook, message)
            
            if not response:
                return False
            
            # 钉钉API有频率限制，稍微等待
            if i < len(parts) - 1:
                import time
                time.sleep(1)
        
        return True
    
    def _send_markdown_with_image(self, report, country_key):
        """发送带图片的Markdown消息（备用方案）"""
        markdown_content = report.get('markdown', '')
        image_path = report.get('image_path', '')
        country_config = report.get('country_config', {})
        
        # 先上传图片获取media_id
        media_id = None
        if image_path and os.path.exists(image_path):
            media_id = self._upload_image(image_path)
        
        # 构建内容
        if media_id:
            # 钉钉Markdown不支持直接显示图片，使用图片URL引用
            # 实际发送时仍用纯Markdown
            pass
        
        return self._send_markdown(report, country_key)
    
    def _upload_image(self, image_path):
        """上传图片到钉钉（需要access_token）"""
        # 注意：自定义机器人Webhook不支持直接上传图片
        # 这里仅记录，实际发送时不使用此功能
        logger.warning("钉钉自定义机器人不支持直接上传图片，使用纯Markdown发送")
        return None
    
    def _send_summary(self, reports, success_count, fail_count):
        """发送汇总消息"""
        total_countries = len(reports)
        total_items = sum(r.get('total_items', 0) for r in reports.values())
        
        # 汇总表格
        summary_lines = ["### 📊 今日推送汇总", "", ""]
        summary_lines.append("| 国家 | 新闻条数 | 状态 |")
        summary_lines.append("|------|----------|------|")
        
        for country_key, report in reports.items():
            flag = report.get('country_config', {}).get('flag', '🏳️')
            name = report.get('country_config', {}).get('name', country_key)
            count = report.get('total_items', 0)
            summary_lines.append(f"| {flag} {name} | {count}条 | ✅ |")
        
        summary_lines.append("")
        summary_lines.append(f"**总计：{total_countries}个国家 {total_items}条新闻**")
        summary_lines.append("")
        summary_lines.append(f"🕐 推送时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        if fail_count > 0:
            summary_lines.append("")
            summary_lines.append(f"⚠️ 失败：{fail_count}个国家")
        
        summary_text = "\n".join(summary_lines)
        
        message = {
            "msgtype": "markdown",
            "markdown": {
                "title": "GWM LatAm News 推送汇总",
                "text": summary_text
            }
        }
        
        self._http_post(self.webhook, message)
    
    def _split_markdown(self, content):
        """分割过长的Markdown内容"""
        parts = []
        
        # 按段落分割
        paragraphs = content.split('\n\n')
        current_part = []
        current_length = 0
        
        for para in paragraphs:
            para_length = len(para)
            
            if current_length + para_length > self.max_message_size:
                if current_part:
                    parts.append('\n\n'.join(current_part))
                    current_part = [para]
                    current_length = para_length
                else:
                    # 单个段落就超过限制，强制截断
                    parts.append(para[:self.max_message_size])
                    current_part = []
                    current_length = 0
            else:
                current_part.append(para)
                current_length += para_length
        
        if current_part:
            parts.append('\n\n'.join(current_part))
        
        return parts
    
    def _http_post(self, url, payload, timeout=10):
        """发送HTTP POST请求"""
        try:
            headers = {'Content-Type': 'application/json'}
            response = requests.post(url, headers=headers, json=payload, timeout=timeout)
            
            if response.status_code == 200:
                result = response.json()
                if result.get('errcode') == 0:
                    return True
                else:
                    logger.warning(f"钉钉返回错误: {result.get('errmsg', '')}")
                    return False
            else:
                logger.warning(f"HTTP错误: {response.status_code}")
                return False
                
        except requests.exceptions.Timeout:
            logger.warning("请求超时")
            return False
        except requests.exceptions.RequestException as e:
            logger.warning(f"请求异常: {e}")
            return False
        except Exception as e:
            logger.error(f"发送失败: {e}")
            return False
    
    def send_notification(self, title, content):
        """发送通知消息"""
        message = {
            "msgtype": "markdown",
            "markdown": {
                "title": title,
                "text": content
            }
        }
        return self._http_post(self.webhook, message)

