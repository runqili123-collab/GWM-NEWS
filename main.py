#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GWM LatAm News Monitor v2
五阶段流水线：采集 → 粗筛去重 → AI精炼 → 组装视觉 → 推送归档
"""

import os
import sys
import json
import logging
import glob
import yaml
from datetime import datetime, timedelta
from pathlib import Path

# 确保src目录在path中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fetcher import RSSFetcher
from filter_engine import NewsFilter
from analyzer import AIAnalyzer
from composer import NewsComposer
from sender import DingTalkSender


def load_config(name):
    """加载YAML配置文件"""
    config_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'config')
    path = os.path.join(config_dir, name)
    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def setup_logging():
    """配置日志"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%H:%M:%S'
    )
    return logging.getLogger('main')


def main():
    """主流程"""
    logger = setup_logging()
    
    # 加载配置
    sources = load_config('sources.yaml')
    settings = load_config('settings.yaml')
    keywords = load_config('keywords.yaml')
    priorities = load_config('priorities.yaml')
    
    # 环境变量
    api_key = os.environ.get('AI_API_KEY', '')
    webhook = os.environ.get('DINGTALK_WEBHOOK', '')
    
    # 验证必需配置
    if not api_key:
        logger.error("AI_API_KEY未配置，请设置环境变量")
        return
    if not webhook:
        logger.error("DINGTALK_WEBHOOK未配置，请设置环境变量")
        return
    
    # 项目根目录
    project_root = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(project_root)
    
    # 重复运行保护
    history_dir = os.path.join(project_root, 
                               settings.get('dedup', {}).get('history_dir', 'output/history'))
    today = datetime.now().strftime('%Y-%m-%d')
    today_flag = os.path.join(history_dir, f'sent_{today}.flag')
    
    if os.path.exists(today_flag):
        logger.info(f"今日已推送过({today})，跳过本次运行")
        return
    
    # 报告日期
    report_date = datetime.now().strftime('%Y年%m月%d日')
    logger.info(f"=== GWM LatAm News Monitor v2 启动 === {report_date}")
    
    country_order = settings.get('country_order', [])
    
    try:
        # 阶段1：采集
        logger.info("--- 阶段1：RSS采集 ---")
        fetcher = RSSFetcher(settings, sources)
        raw_news = fetcher.fetch_all()
        total_raw = sum(len(v) for v in raw_news.values())
        logger.info(f"采集完成：共{total_raw}条原始新闻")
        
        if total_raw == 0:
            logger.warning("未采集到任何新闻，退出")
            return
        
        # 阶段2：粗筛+去重+归属
        logger.info("--- 阶段2：粗筛+去重+归属 ---")
        news_filter = NewsFilter(settings, keywords, sources)
        filtered = news_filter.process(raw_news, history_dir)
        total_filtered = sum(sum(len(d) for d in c.values()) for c in filtered.values())
        logger.info(f"粗筛完成：{total_filtered}条候选")
        
        if total_filtered == 0:
            logger.warning("粗筛后无候选新闻，退出")
            return
        
        # 阶段3：AI精炼
        logger.info("--- 阶段3：AI精炼 ---")
        analyzer = AIAnalyzer(api_key, settings, priorities, keywords)
        refined = analyzer.process_all(filtered)
        total_refined = sum(sum(len(d) for d in c.values()) for c in refined.values())
        logger.info(f"精炼完成：{total_refined}条输出")
        
        if total_refined == 0:
            logger.warning("AI精炼后无输出，退出")
            return
        
        # 阶段4：组装+视觉
        logger.info("--- 阶段4：组装+视觉 ---")
        composer = NewsComposer(settings, sources)
        reports = composer.compose_all(refined, report_date)
        logger.info("组装完成")
        
        # 阶段5：推送+归档
        logger.info("--- 阶段5：推送+归档 ---")
        sender = DingTalkSender(webhook, settings)
        success = sender.send_all(reports, country_order)
        
        if success:
            # 归档历史数据
            _archive_history(history_dir, refined, today)
            # 写推送标记
            os.makedirs(history_dir, exist_ok=True)
            with open(today_flag, 'w') as f:
                f.write(today)
            # 清理过期历史
            _clean_old_history(history_dir, 7)
            logger.info("归档完成")
        
        # 运行结果汇总
        status_msg = f"✅ {report_date} 拉美新闻已推送（5国共{total_refined}条）"
        logger.info(status_msg)
        
    except Exception as e:
        logger.error(f"运行失败: {str(e)}")
        import traceback
        traceback.print_exc()
        
        # 失败通知
        if webhook:
            try:
                import requests
                requests.post(webhook, json={
                    "msgtype": "markdown",
                    "markdown": {
                        "title": "新闻监控异常",
                        "text": f"❌ {report_date} 拉美新闻推送失败\n\n原因：{str(e)[:200]}"
                    }
                }, timeout=10)
            except Exception as notify_err:
                logger.warning(f"发送失败通知失败: {notify_err}")


def _archive_history(history_dir, refined, today):
    """归档新闻历史"""
    os.makedirs(history_dir, exist_ok=True)
    history_file = os.path.join(history_dir, f'news_{today}.json')
    history_data = {}
    
    for country_key, dims in refined.items():
        history_data[country_key] = []
        for dim_key, items in dims.items():
            for item in items:
                history_data[country_key].append({
                    'title': item.get('title_zh', ''),
                    'title_original': item.get('title', ''),
                    'url': item.get('url', ''),
                    'date': today,
                    'dimension': dim_key,
                    'relevance': item.get('relevance', 0)
                })
    
    with open(history_file, 'w', encoding='utf-8') as f:
        json.dump(history_data, f, ensure_ascii=False, indent=2)


def _clean_old_history(history_dir, keep_days):
    """清理过期历史文件"""
    cutoff = datetime.now() - timedelta(days=keep_days)
    
    # 清理JSON历史文件
    for f in glob.glob(os.path.join(history_dir, 'news_*.json')):
        try:
            date_str = os.path.basename(f).replace('news_', '').replace('.json', '')
            file_date = datetime.strptime(date_str, '%Y-%m-%d')
            if file_date < cutoff:
                os.remove(f)
                print(f"删除过期历史: {f}")
        except Exception:
            pass
    
    # 清理flag文件
    for f in glob.glob(os.path.join(history_dir, 'sent_*.flag')):
        try:
            date_str = os.path.basename(f).replace('sent_', '').replace('.flag', '')
            file_date = datetime.strptime(date_str, '%Y-%m-%d')
            if file_date < cutoff:
                os.remove(f)
        except Exception:
            pass


if __name__ == '__main__':
    main()

