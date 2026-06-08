#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
粗筛+去重+归属模块
包含黑名单过滤、国家归属判定、跨日期去重、优先级评分
"""

import os
import sys
import json
import logging
import glob
import difflib
from datetime import datetime, timedelta
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logger = logging.getLogger('filter')


class NewsFilter:
    """新闻过滤器"""
    
    def __init__(self, settings, keywords, sources):
        self.settings = settings
        self.keywords = keywords
        self.sources = sources
        self.dedup_config = settings.get('dedup', {})
        self.priorities_config = settings.get('priorities', {})
        self.candidate_n = self.priorities_config.get('candidate_n_per_dimension', 5)
        self.similarity_threshold = self.dedup_config.get('similarity_threshold', 0.55)
        self.history_days = self.dedup_config.get('history_days', 3)
    
    def process(self, raw_news, history_dir):
        """处理原始新闻"""
        result = {}
        
        for country_key, items in raw_news.items():
            if country_key not in result:
                result[country_key] = {}
            
            for dim in ['politics', 'economy', 'automotive', 'user_voice']:
                result[country_key][dim] = []
        
        # 步骤1：黑名单过滤
        logger.info("  -> 黑名单过滤")
        filtered_news = self._apply_blacklist(raw_news)
        
        # 步骤2：国家归属判定
        logger.info("  -> 国家归属判定")
        country_assigned = self._assign_countries(filtered_news)
        
        # 步骤3：加载历史数据进行去重
        logger.info("  -> 跨日期去重")
        history_items = self._load_history(history_dir)
        
        # 步骤4：合并所有新闻用于去重
        all_items = []
        for country_key, items in country_assigned.items():
            all_items.extend(items)
        
        # 步骤5：去重
        deduplicated = self._deduplicate(all_items, history_items)
        
        # 步骤6：按国家和维度分组
        grouped = self._group_by_country_dimension(deduplicated)
        
        # 步骤7：计算优先级并选取候选
        for country_key in grouped:
            for dim_key in grouped[country_key]:
                items = grouped[country_key][dim_key]
                scored = self._score_items(items, dim_key)
                sorted_items = sorted(scored, key=lambda x: x['score'], reverse=True)
                result[country_key][dim_key] = sorted_items[:self.candidate_n]
        
        return result
    
    def _apply_blacklist(self, raw_news):
        """应用黑名单过滤"""
        blacklist = self.keywords.get('blacklist', [])
        filtered = {}
        
        for country_key, items in raw_news.items():
            filtered[country_key] = []
            for item in items:
                text = f"{item.title} {item.summary}".lower()
                
                # 检查黑名单
                blocked = False
                for keyword in blacklist:
                    if keyword.lower() in text:
                        blocked = True
                        break
                
                if not blocked:
                    # 转换为dict
                    item_dict = {
                        'title': item.title,
                        'summary': item.summary,
                        'url': item.url,
                        'source_name': item.source_name,
                        'published_date': item.published_date,
                        'thumbnail_url': item.thumbnail_url,
                        'country': item.country,
                        'dimension': item.dimension,
                        'source_type': item.source_type,
                        'language': item.language
                    }
                    filtered[country_key].append(item_dict)
        
        total_filtered = sum(len(v) for v in filtered.values())
        logger.info(f"    黑名单过滤后: {total_filtered}条")
        return filtered
    
    def _assign_countries(self, filtered_news):
        """国家归属判定"""
        country_keywords = self.keywords.get('country_keywords', {})
        result = defaultdict(list)
        
        for country_key, items in filtered_news.items():
            for item in items:
                # 主源直接归属
                if item['source_type'] == 'primary':
                    item['assigned_country'] = country_key
                    result[country_key].append(item)
                else:
                    # 辅源需要关键词匹配
                    text = f"{item['title']} {item['summary']}".lower()
                    assigned = False
                    
                    for c_key, keywords in country_keywords.items():
                        for kw in keywords:
                            if kw.lower() in text:
                                item['assigned_country'] = c_key
                                result[c_key].append(item)
                                assigned = True
                                break
                        if assigned:
                            break
                    
                    # 未匹配到任何国家，标记为unassigned
                    if not assigned:
                        item['assigned_country'] = 'unassigned'
        
        # 处理unassigned的新闻，尝试跨维度匹配
        unassigned = [item for item in result.get('unassigned', [])]
        if unassigned:
            del result['unassigned']
            logger.info(f"    未分配国家的新闻: {len(unassigned)}条")
        
        return result
    
    def _load_history(self, history_dir):
        """加载历史新闻"""
        history_items = []
        
        if not os.path.exists(history_dir):
            return history_items
        
        cutoff = datetime.now() - timedelta(days=self.history_days)
        
        for f in glob.glob(os.path.join(history_dir, 'news_*.json')):
            try:
                date_str = os.path.basename(f).replace('news_', '').replace('.json', '')
                file_date = datetime.strptime(date_str, '%Y-%m-%d')
                
                if file_date >= cutoff:
                    with open(f, 'r', encoding='utf-8') as fp:
                        data = json.load(fp)
                        for country_key, items in data.items():
                            history_items.extend(items)
            except Exception as e:
                logger.warning(f"加载历史失败 {f}: {e}")
        
        logger.info(f"    加载历史新闻: {len(history_items)}条")
        return history_items
    
    def _deduplicate(self, items, history_items):
        """去重处理"""
        seen_urls = set()
        seen_titles = []
        result = []
        
        # 先加入历史记录
        for item in history_items:
            if item.get('url'):
                seen_urls.add(item['url'])
            if item.get('title'):
                seen_titles.append(item['title'].lower())
        
        for item in items:
            url = item.get('url', '')
            title = item.get('title', '')
            title_lower = title.lower()
            
            # URL精确匹配
            if url and url in seen_urls:
                continue
            
            # 标题相似度匹配
            is_duplicate = False
            for seen_title in seen_titles:
                if self._calculate_similarity(title_lower, seen_title) > self.similarity_threshold:
                    is_duplicate = True
                    break
            
            if is_duplicate:
                continue
            
            # 加入结果集
            result.append(item)
            seen_urls.add(url)
            seen_titles.append(title_lower)
        
        logger.info(f"    去重后: {len(result)}条")
        return result
    
    def _calculate_similarity(self, s1, s2):
        """计算标题相似度"""
        return difflib.SequenceMatcher(None, s1, s2).ratio()
    
    def _group_by_country_dimension(self, items):
        """按国家和维度分组"""
        grouped = defaultdict(lambda: defaultdict(list))
        
        for item in items:
            country = item.get('assigned_country', item.get('country', ''))
            dimension = item.get('dimension', 'other')
            
            if country and dimension:
                grouped[country][dimension].append(item)
        
        return grouped
    
    def _score_items(self, items, dimension):
        """对新闻进行优先级评分"""
        if not items:
            return []
        
        boost_config = self.keywords.get('whitelist_boost', {})
        dim_weights = self.priorities_config.get('dimension_weights', {}).get(dimension, {})
        authority_sources = self.priorities_config.get('source_authority', {}).get('sources', [])
        authority_boost = self.priorities_config.get('source_authority', {}).get('authority_boost', 1)
        
        scored_items = []
        
        for item in items:
            score = 0
            text = f"{item.get('title', '')} {item.get('summary', '')}".lower()
            
            # 白名单加分
            for category, config in boost_config.items():
                boost_score = config.get('score', 0)
                keywords = config.get('keywords', [])
                for kw in keywords:
                    if kw.lower() in text:
                        score += boost_score
                        break
            
            # 维度权重加分
            for keyword, weight in dim_weights.items():
                if keyword.lower() in text:
                    score += weight
            
            # 来源权威性加分
            source_name = item.get('source_name', '')
            if source_name in authority_sources:
                score += authority_boost
            
            # 时效性加分
            published = item.get('published_date')
            if published:
                hours_ago = (datetime.now() - published).total_seconds() / 3600
                if hours_ago <= 12:
                    score += self.priorities_config.get('timeliness', {}).get('within_12h', 2)
                elif hours_ago <= 24:
                    score += self.priorities_config.get('timeliness', {}).get('within_24h', 1)
            
            # 保留相关性（后续AI会重新评估）
            item['score'] = score
            scored_items.append(item)
        
        return scored_items

