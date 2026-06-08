#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
组装+视觉模块
包含Markdown组装和图片生成
"""

import os
import sys
import logging
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logger = logging.getLogger('composer')


class NewsComposer:
    """新闻组装器"""
    
    def __init__(self, settings, sources):
        self.settings = settings
        self.sources = sources
        self.output_config = settings.get('output', {})
        self.project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    def compose_all(self, refined_news, report_date):
        """组装所有报告"""
        reports = {}
        
        # 按国家组装
        for country_key, dims in refined_news.items():
            country_cfg = self.sources.get('countries', {}).get(country_key, {})
            
            # 收集该国所有新闻
            items_by_dim = {}
            total_items = 0
            for dim_key, items in dims.items():
                if items:
                    items_by_dim[dim_key] = items
                    total_items += len(items)
            
            if total_items == 0:
                continue
            
            # 生成Markdown
            markdown = self._build_markdown(country_key, items_by_dim, report_date)
            
            # 生成图片
            image_path = self._generate_image(country_key, items_by_dim, report_date)
            
            reports[country_key] = {
                'markdown': markdown,
                'image_path': image_path,
                'country_config': country_cfg,
                'items': items_by_dim,
                'total_items': total_items
            }
        
        return reports
    
    def _build_markdown(self, country_key, items_by_dim, report_date):
        """构建Markdown内容"""
        country_cfg = self.sources.get('countries', {}).get(country_key, {})
        country_name = country_cfg.get('name', country_key)
        flag = country_cfg.get('flag', '')
        
        lines = []
        
        # 标题
        lines.append(f"## {flag} {country_name} 每日新闻")
        lines.append(f"**日期：{report_date}**")
        lines.append("")
        lines.append("---")
        lines.append("")
        
        # 维度配置
        dim_config = {
            'politics': {'name': '政治动态', 'icon': '🏛️'},
            'economy': {'name': '经济形势', 'icon': '💰'},
            'automotive': {'name': '汽车动态', 'icon': '🚗'},
            'user_voice': {'name': '用户声音', 'icon': '💬'}
        }
        
        # 按顺序输出各维度
        for dim_key in ['politics', 'economy', 'automotive', 'user_voice']:
            items = items_by_dim.get(dim_key, [])
            if not items:
                continue
            
            dim_info = dim_config.get(dim_key, {'name': dim_key, 'icon': ''})
            
            lines.append(f"### {dim_info['icon']} {dim_info['name']}")
            lines.append("")
            
            for i, item in enumerate(items, 1):
                title_zh = item.get('title_zh', item.get('title', ''))
                summary_zh = item.get('summary_zh', item.get('summary', ''))
                impact = item.get('impact', '')
                source_name = item.get('source_name', '')
                url = item.get('url', '')
                
                # 构建新闻条目
                entry = f"{i}、**{title_zh}**"
                lines.append(entry)
                lines.append("")
                lines.append(f"   {summary_zh}")
                lines.append("")
                lines.append(f"   📊 行业影响：{impact}")
                lines.append("")
                lines.append(f"   📰 来源：[{source_name}]({url})")
                lines.append("")
            
            lines.append("---")
            lines.append("")
        
        # 底部提示
        lines.append("💡 部分链接可能需要VPN访问")
        
        return "\n".join(lines)
    
    def _generate_image(self, country_key, items_by_dim, report_date):
        """生成新闻卡片图片"""
        country_cfg = self.sources.get('countries', {}).get(country_key, {})
        country_name = country_cfg.get('name', country_key)
        flag = country_cfg.get('flag', '')
        
        # 图片配置
        width = 800
        height = 1200
        bg_color = (11, 29, 58)  # #0B1D3A
        title_color = (212, 168, 67)  # #D4A843
        text_color = (255, 255, 255)  # #FFFFFF
        accent_color = (100, 149, 237)  # Cornflower Blue
        
        # 创建图片
        img = Image.new('RGB', (width, height), bg_color)
        draw = ImageDraw.Draw(img)
        
        # 尝试加载中文字体
        font_paths = [
            '/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc',
            '/usr/share/fonts/truetype/noto/NotoSansSC-Regular.ttf',
            '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
            '/System/Library/Fonts/PingFang.ttc',
            'C:/Windows/Fonts/simhei.ttf',
            None
        ]
        
        font_large = None
        font_medium = None
        font_small = None
        
        for font_path in font_paths:
            if font_path and os.path.exists(font_path):
                try:
                    font_large = ImageFont.truetype(font_path, 32)
                    font_medium = ImageFont.truetype(font_path, 24)
                    font_small = ImageFont.truetype(font_path, 18)
                    break
                except Exception:
                    continue
        
        if font_large is None:
            font_large = ImageFont.load_default()
            font_medium = ImageFont.load_default()
            font_small = ImageFont.load_default()
        
        y_offset = 40
        
        # 顶部标题区域
        draw.rectangle([(20, 20), (width - 20, 100)], fill=title_color)
        title_text = f"{flag} {country_name} 每日新闻"
        if font_large:
            bbox = draw.textbbox((0, 0), title_text, font=font_large)
            text_width = bbox[2] - bbox[0]
            draw.text(((width - text_width) // 2, 35), title_text, fill=bg_color, font=font_large)
        
        y_offset = 120
        
        # 日期
        date_text = f"📅 {report_date}"
        if font_medium:
            draw.text((40, y_offset), date_text, fill=title_color, font=font_medium)
        y_offset += 50
        
        # 分隔线
        draw.line([(40, y_offset), (width - 40, y_offset)], fill=title_color, width=2)
        y_offset += 30
        
        # 维度图标映射
        dim_icons = {
            'politics': '🏛️',
            'economy': '💰',
            'automotive': '🚗',
            'user_voice': '💬'
        }
        
        dim_names = {
            'politics': '政治动态',
            'economy': '经济形势',
            'automotive': '汽车动态',
            'user_voice': '用户声音'
        }
        
        # 各维度新闻
        for dim_key in ['politics', 'economy', 'automotive', 'user_voice']:
            items = items_by_dim.get(dim_key, [])
            if not items:
                continue
            
            icon = dim_icons.get(dim_key, '📰')
            dim_name = dim_names.get(dim_key, dim_key)
            
            # 维度标题
            if font_medium:
                draw.text((40, y_offset), f"{icon} {dim_name}", fill=accent_color, font=font_medium)
            y_offset += 40
            
            # 该维度的新闻
            for i, item in enumerate(items[:3], 1):
                title_zh = item.get('title_zh', item.get('title', ''))
                summary_zh = item.get('summary_zh', item.get('summary', ''))
                impact = item.get('impact', '')
                
                # 截断过长文本
                if len(title_zh) > 25:
                    title_zh = title_zh[:22] + "..."
                if len(summary_zh) > 60:
                    summary_zh = summary_zh[:57] + "..."
                if len(impact) > 30:
                    impact = impact[:27] + "..."
                
                # 新闻标题
                news_title = f"  {i}. {title_zh}"
                if font_small:
                    draw.text((50, y_offset), news_title, fill=text_color, font=font_small)
                y_offset += 28
                
                # 摘要
                summary_text = f"     {summary_zh}"
                if font_small:
                    draw.text((50, y_offset), summary_text, fill=(180, 180, 180), font=font_small)
                y_offset += 28
                
                # 影响
                impact_text = f"     📊 {impact}"
                if font_small:
                    draw.text((50, y_offset), impact_text, fill=title_color, font=font_small)
                y_offset += 35
                
                # 检查是否超出图片高度
                if y_offset > height - 150:
                    break
            
            y_offset += 20
            
            if y_offset > height - 150:
                break
        
        # 底部标识
        draw.line([(40, height - 60), (width - 40, height - 60)], fill=title_color, width=1)
        footer_text = "长城汽车 | 拉美市场情报监控"
        if font_small:
            bbox = draw.textbbox((0, 0), footer_text, font=font_small)
            text_width = bbox[2] - bbox[0]
            draw.text(((width - text_width) // 2, height - 45), footer_text, fill=(150, 150, 150), font=font_small)
        
        # 保存图片
        image_dir = os.path.join(self.project_root, self.output_config.get('image_dir', 'output/images'))
        os.makedirs(image_dir, exist_ok=True)
        
        filename = f"{country_key}_{datetime.now().strftime('%Y%m%d')}.png"
        image_path = os.path.join(image_dir, filename)
        
        img.save(image_path, 'PNG')
        logger.info(f"生成图片: {image_path}")
        
        return image_path

