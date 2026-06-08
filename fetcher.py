#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RSS采集模块
支持多线程并发采集、链接验证、Google News重定向解析
"""

import os
import sys
import time
import logging
import requests
import feedparser
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from dateutil import parser as date_parser
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logger = logging.getLogger('fetcher')


class NewsItem:
    """新闻条目数据类"""
    def __init__(self, title, summary, url, source_name, published_date, 
                 thumbnail_url=None, country=None, dimension=None, 
                 source_type='primary', language='es'):
        self.title = title or ''
        self.summary = summary or ''
        self.url = url or ''
        self.source_name = source_name or ''
        self.published_date = published_date
        self.thumbnail_url = thumbnail_url or ''
        self.country = country or ''
        self.dimension = dimension or ''
        self.source_type = source_type
        self.language = language


class RSSFetcher:
    """RSS采集器"""
    
    def __init__(self, settings, sources):
        self.settings = settings
        self.sources = sources
        self.rss_config = settings.get('rss', {})
        self.link_config = settings.get('link_verification', {})
        self.max_items = self.rss_config.get('max_items_per_feed', 15)
        self.timeout = self.rss_config.get('timeout_seconds', 30)
        self.user_agent = self.rss_config.get('user_agent', 'GWM-LatAm-News-Monitor/2.0')
        self.max_workers = self.rss_config.get('max_workers', 4)
        self.verify_links = self.link_config.get('enabled', True)
    
    def fetch_all(self):
        """采集所有RSS源"""
        all_news = {}
        feeds_to_fetch = []
        
        # 收集所有需要采集的feeds
        for country_key, country_config in self.sources.get('countries', {}).items():
            for dim_key in ['politics', 'economy', 'automotive', 'user_voice']:
                dim_config = country_config.get('dimensions', {}).get(dim_key, {})
                
                # 主源
                for source in dim_config.get('primary', []):
                    feeds_to_fetch.append({
                        'country': country_key,
                        'dimension': dim_key,
                        'source': source,
                        'source_type': 'primary'
                    })
                
                # 辅源
                for source in dim_config.get('secondary', []):
                    feeds_to_fetch.append({
                        'country': country_key,
                        'dimension': dim_key,
                        'source': source,
                        'source_type': 'secondary'
                    })
        
        logger.info(f"待采集RSS源: {len(feeds_to_fetch)}个")
        
        # 并发采集
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(self._fetch_single_feed, feed_info): feed_info 
                for feed_info in feeds_to_fetch
            }
            
            for future in as_completed(futures):
                feed_info = futures[future]
                try:
                    items = future.result()
                    if items:
                        country = feed_info['country']
                        if country not in all_news:
                            all_news[country] = []
                        all_news[country].extend(items)
                except Exception as e:
                    logger.warning(f"采集失败 {feed_info['source']['name']}: {e}")
        
        return all_news
    
    def _fetch_single_feed(self, feed_info):
        """采集单个RSS源"""
        source = feed_info['source']
        rss_url = source.get('rss', '')
        source_name = source.get('name', '')
        country = feed_info['country']
        dimension = feed_info['dimension']
        source_type = feed_info['source_type']
        language = source.get('language', 'es')
        
        if not rss_url:
            return []
        
        items = []
        
        try:
            # 设置请求头
            headers = {
                'User-Agent': self.user_agent,
                'Accept': 'application/rss+xml, application/xml, text/xml, */*',
                'Accept-Language': f'{language}, en;q=0.9'
            }
            
            # 发送请求
            response = requests.get(rss_url, headers=headers, timeout=self.timeout)
            response.raise_for_status()
            
            # 解析RSS
            feed = feedparser.parse(response.content)
            
            if feed.bozo and feed.bozo_exception:
                logger.warning(f"RSS解析警告 {source_name}: {feed.bozo_exception}")
            
            entry_count = 0
            for entry in feed.entries:
                if entry_count >= self.max_items:
                    break
                
                # 提取字段
                title = self._clean_text(self._get_entry_text(entry, 'title'))
                summary = self._clean_text(self._get_entry_summary(entry))
                url = self._get_entry_url(entry)
                published = self._parse_date(entry)
                thumbnail = self._get_thumbnail(entry)
                
                # 跳过无效条目
                if not title or not url:
                    continue
                
                # 验证链接
                if self.verify_links and not self._verify_link(url):
                    logger.debug(f"链接验证失败: {url}")
                    continue
                
                item = NewsItem(
                    title=title,
                    summary=summary,
                    url=url,
                    source_name=source_name,
                    published_date=published,
                    thumbnail_url=thumbnail,
                    country=country,
                    dimension=dimension,
                    source_type=source_type,
                    language=language
                )
                items.append(item)
                entry_count += 1
            
            logger.debug(f"采集 {source_name}: {len(items)}条")
            
        except requests.exceptions.Timeout:
            logger.warning(f"请求超时 {source_name}: {rss_url}")
        except requests.exceptions.RequestException as e:
            logger.warning(f"请求失败 {source_name}: {e}")
        except Exception as e:
            logger.warning(f"采集异常 {source_name}: {e}")
        
        return items
    
    def _get_entry_text(self, entry, key):
        """获取entry字段"""
        return getattr(entry, key, '') or ''
    
    def _get_entry_summary(self, entry):
        """获取摘要，处理不同格式"""
        summary = ''
        if hasattr(entry, 'summary'):
            summary = entry.summary
        elif hasattr(entry, 'description'):
            summary = entry.description
        elif hasattr(entry, 'content'):
            if entry.content:
                summary = entry.content[0].value if hasattr(entry.content[0], 'value') else str(entry.content[0])
        
        # 去除HTML标签
        import re
        summary = re.sub(r'<[^>]+>', '', summary)
        return summary
    
    def _get_entry_url(self, entry):
        """获取条目URL，处理Google News重定向"""
        url = ''
        if hasattr(entry, 'link'):
            url = entry.link
        elif hasattr(entry, 'id'):
            url = entry.id
        
        # 处理Google News重定向URL
        if 'news.google.com' in url:
            # 提取实际URL
            import re
            match = re.search(r'url=([^&]+)', url)
            if match:
                from urllib.parse import unquote
                url = unquote(match.group(1))
        
        return url
    
    def _parse_date(self, entry):
        """解析发布日期"""
        published = None
        date_str = ''
        
        if hasattr(entry, 'published'):
            date_str = entry.published
        elif hasattr(entry, 'updated'):
            date_str = entry.updated
        
        if date_str:
            try:
                published = date_parser.parse(date_str)
            except Exception:
                published = datetime.now()
        else:
            published = datetime.now()
        
        return published
    
    def _get_thumbnail(self, entry):
        """获取缩略图URL"""
        thumbnail = ''
        
        # 尝试多种方式获取thumbnail
        if hasattr(entry, 'media_thumbnail') and entry.media_thumbnail:
            thumbnail = entry.media_thumbnail[0].get('url', '')
        elif hasattr(entry, 'media_content') and entry.media_content:
            for mc in entry.media_content:
                if mc.get('type', '').startswith('image'):
                    thumbnail = mc.get('url', '')
                    break
        elif hasattr(entry, 'enclosures'):
            for enc in entry.enclosures:
                if enc.get('type', '').startswith('image'):
                    thumbnail = enc.get('href', '')
                    break
        
        return thumbnail
    
    def _verify_link(self, url):
        """验证链接是否可达"""
        if not url:
            return False
        
        try:
            verify_config = self.link_config
            timeout = verify_config.get('timeout_seconds', 8)
            retries = verify_config.get('retries', 1)
            
            for attempt in range(retries + 1):
                try:
                    # 先尝试HEAD请求
                    response = requests.head(url, timeout=timeout, allow_redirects=True)
                    if response.status_code < 400:
                        return True
                    
                    # 如果HEAD失败，尝试GET（某些服务器不支持HEAD）
                    if response.status_code in [405, 400]:
                        response = requests.get(url, timeout=timeout, stream=True, allow_redirects=True)
                        if response.status_code < 400:
                            return True
                except requests.exceptions.RequestException:
                    if attempt < retries:
                        time.sleep(1)
                        continue
                    return False
        except Exception:
            pass
        
        return False
    
    def _clean_text(self, text):
        """清理文本"""
        if not text:
            return ''
        # 去除多余空白
        import re
        text = re.sub(r'\s+', ' ', text)
        text = text.strip()
        return text

