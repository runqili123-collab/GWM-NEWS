#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI精炼模块
单条新闻单独调用DeepSeek进行翻译和商务摘要
"""

import os
import sys
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logger = logging.getLogger('analyzer')


class AIAnalyzer:
    """AI新闻分析器"""
    
    def __init__(self, api_key, settings, priorities, keywords):
        self.api_key = api_key
        self.settings = settings
        self.ai_config = settings.get('ai', {})
        self.priorities = priorities
        self.keywords = keywords
        self.model = self.ai_config.get('model', 'deepseek-chat')
        self.api_base = self.ai_config.get('api_base', 'https://api.deepseek.com/v1')
        self.temperature = self.ai_config.get('temperature', 0.0)
        self.max_tokens = self.ai_config.get('max_tokens', 800)
        self.max_workers = self.ai_config.get('concurrency', 4)
        self.max_retries = self.ai_config.get('max_retries', 3)
        self.min_relevance = settings.get('priorities', {}).get('min_relevance_score', 2)
    
    def process_all(self, filtered_news):
        """处理所有新闻"""
        result = {}
        
        # 收集所有待处理条目
        all_items = []
        item_mapping = {}  # (country, dim, idx) -> item
        
        for country_key, dims in filtered_news.items():
            for dim_key, items in dims.items():
                for idx, item in enumerate(items):
                    all_items.append({
                        'country': country_key,
                        'dimension': dim_key,
                        'index': idx,
                        'item': item
                    })
                    item_mapping[(country_key, dim_key, idx)] = item
        
        logger.info(f"待AI处理: {len(all_items)}条")
        
        if not all_items:
            return result
        
        # 并发处理
        processed = []
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(self._analyze_single, item_info['item'], 
                               item_info['country'], item_info['dimension']): item_info
                for item_info in all_items
            }
            
            for future in as_completed(futures):
                item_info = futures[future]
                try:
                    result_item = future.result()
                    if result_item:
                        processed.append({
                            'country': item_info['country'],
                            'dimension': item_info['dimension'],
                            'item': result_item
                        })
                except Exception as e:
                    logger.warning(f"AI分析失败: {e}")
        
        # 按国家和维度组织结果
        for country_key in self.settings.get('country_order', []):
            result[country_key] = {
                'politics': [],
                'economy': [],
                'automotive': [],
                'user_voice': []
            }
        
        for entry in processed:
            country = entry['country']
            dim = entry['dimension']
            item = entry['item']
            
            if country not in result:
                result[country] = {
                    'politics': [],
                    'economy': [],
                    'automotive': [],
                    'user_voice': []
                }
            
            if dim in result[country]:
                result[country][dim].append(item)
        
        # 跨维度去重：每条只保留一个维度
        result = self._dedup_across_dimensions(result)
        
        # 每维度取Top N
        top_n = self.settings.get('priorities', {}).get('top_n_per_dimension', 3)
        for country_key in result:
            for dim_key in result[country_key]:
                items = result[country_key][dim_key]
                # 按relevance排序
                sorted_items = sorted(items, key=lambda x: x.get('relevance', 0), reverse=True)
                result[country_key][dim_key] = sorted_items[:top_n]
        
        return result
    
    def _analyze_single(self, item, country, dimension):
        """分析单条新闻"""
        country_names = {
            'colombia': '哥伦比亚',
            'peru': '秘鲁',
            'ecuador': '厄瓜多尔',
            'venezuela': '委内瑞拉',
            'caribbean': '加勒比地区'
        }
        
        dim_names = {
            'politics': '政治',
            'economy': '经济',
            'automotive': '汽车',
            'user_voice': '用户声音'
        }
        
        country_cn = country_names.get(country, country)
        dim_cn = dim_names.get(dimension, dimension)
        
        prompt = self._build_prompt(item, country_cn, dim_cn)
        
        for attempt in range(self.max_retries):
            try:
                response = self._call_deepseek(prompt)
                
                if response:
                    parsed = self._parse_response(response, item)
                    if parsed:
                        # relevance <= 2 丢弃
                        if parsed.get('relevance', 0) <= self.min_relevance:
                            logger.debug(f"Relevance too low: {parsed.get('relevance')} - {item.get('title', '')[:50]}")
                            return None
                        return parsed
                
            except Exception as e:
                logger.warning(f"AI调用失败 (attempt {attempt + 1}): {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(2 ** attempt)  # 指数退避
        
        return None
    
    def _build_prompt(self, item, country, dimension):
        """构建Prompt"""
        prompt = f"""你是一位拉美商业分析师。请将以下{country}{dimension}新闻翻译为中文商务摘要。

要求：
1. 输出严格的JSON格式，不要输出其他任何内容
2. JSON字段：
   - "title_zh": 中文标题（10-20字，精炼概括）
   - "summary_zh": 中文摘要（50-80字，商务风格）
   - "impact": 对汽车行业影响（20-40字）
   - "relevance": 相关性评分1-5（5=直接影响汽车行业，1=几乎无关）
   - "dimension_suggestion": 建议归入维度（politics/economy/automotive/user_voice）
3. 品牌名（Haval、Toyota、BYD等）和机构名（Bloomberg、Scotiabank等）保留原文
4. 数字保留，其余全部中文
5. 商务风格，语言精炼简洁

原文标题：{item.get('title', '')}
原文摘要：{item.get('summary', '')[:500]}
来源：{item.get('source_name', '')}
"""
        return prompt
    
    def _call_deepseek(self, prompt):
        """调用DeepSeek API"""
        import requests
        
        url = f"{self.api_base}/chat/completions"
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self.api_key}'
        }
        
        data = {
            'model': self.model,
            'messages': [
                {'role': 'user', 'content': prompt}
            ],
            'temperature': self.temperature,
            'max_tokens': self.max_tokens
        }
        
        response = requests.post(url, headers=headers, json=data, timeout=60)
        
        if response.status_code == 200:
            result = response.json()
            return result['choices'][0]['message']['content']
        else:
            logger.warning(f"API错误: {response.status_code} - {response.text[:200]}")
            return None
    
    def _parse_response(self, response_text, original_item):
        """解析AI返回的JSON"""
        try:
            # 尝试提取JSON
            text = response_text.strip()
            
            # 处理可能的markdown代码块
            if text.startswith('```'):
                lines = text.split('\n')
                text = '\n'.join(lines[1:-1] if lines[-1] == '```' else lines[1:])
            
            # 尝试解析JSON
            result = json.loads(text)
            
            # 验证必要字段
            required_fields = ['title_zh', 'summary_zh', 'impact', 'relevance', 'dimension_suggestion']
            for field in required_fields:
                if field not in result:
                    logger.warning(f"缺少字段: {field}")
                    return None
            
            # 合并结果
            result['title'] = original_item.get('title', '')
            result['summary'] = original_item.get('summary', '')
            result['url'] = original_item.get('url', '')
            result['source_name'] = original_item.get('source_name', '')
            result['thumbnail_url'] = original_item.get('thumbnail_url', '')
            result['published_date'] = original_item.get('published_date')
            
            # 转换relevance为数字
            try:
                result['relevance'] = int(result['relevance'])
            except (ValueError, TypeError):
                result['relevance'] = 3
            
            return result
            
        except json.JSONDecodeError as e:
            logger.warning(f"JSON解析失败: {e}")
            logger.debug(f"原始响应: {response_text[:200]}")
            return None
    
    def _dedup_across_dimensions(self, result):
        """跨维度去重：每条新闻只保留在一个维度"""
        # 用于跟踪已去重的URL
        seen_urls = set()
        
        # 统计各维度已使用情况
        dim_urls = {
            'politics': set(),
            'economy': set(),
            'automotive': set(),
            'user_voice': set()
        }
        
        for country_key in result:
            for dim_key in result[country_key]:
                filtered = []
                for item in result[country_key][dim_key]:
                    url = item.get('url', '')
                    
                    # 如果这个URL在这个维度已经出现过，跳过
                    if url in dim_urls[dim_key]:
                        continue
                    
                    # 标记
                    dim_urls[dim_key].add(url)
                    filtered.append(item)
                
                result[country_key][dim_key] = filtered
        
        return result

