"""
数据获取层：从 17500 拉取 HTML 推荐页与开奖 API，并解析为内存结构。

输出约定：
- fetch_html_recommend_data：每期 dict 含 issue、date、lottery_numbers、kaiji/shiji/jin/guanzhu/duiying。
- parse_api_data：lottery_data 含 historical_draws、sorted_issues（升序期号），供分析/回测使用。
"""
import json
import re
from typing import Dict, List

import requests
from bs4 import BeautifulSoup

from kl8_prediction.config import API_HEADERS, KL8_API_URL, KL8_HTML_URL, HEADERS


class DataFetcher:
    """数据获取器：负责 HTTP 拉取 + 解析成 Python 数据结构"""
    
    def __init__(self):
        pass  # 无状态，可不初始化成员
    
    def fetch_lottery_api_data(self, limit=100):
        """从 API 获取开奖数据（原始 JSON，需再 parse_api_data 规范化）"""
        try:
            url = KL8_API_URL.format(limit=limit)  # 当前 URL 无占位符，limit 未真正拼进链接
            response = requests.get(url, headers=API_HEADERS, timeout=10)  # GET，10 秒超时
            response.raise_for_status()  # 非 2xx 状态码则抛异常
            data = json.loads(response.text)  # 响应体当 JSON 解析
            
            if 'data' not in data or 'data' not in data['data']:  # 与站点约定结构不符
                raise ValueError("API 返回数据格式不正确")
            
            return data
        except Exception as e:
            print(f"✗ API 数据获取失败：{e}")
            return None
    
    def fetch_html_recommend_data(self, limit=30):
        """从 HTML 页面解析多期：期号、日期、已开奖号、五类推荐号"""
        try:
            response = requests.get(KL8_HTML_URL, headers=HEADERS, timeout=15)
            response.encoding = 'utf-8'  # 显式 UTF-8，避免乱码
            
            soup = BeautifulSoup(response.text, 'html.parser')  # 解析整页
            periods_data = {}  # issue 字符串 → 该期字典
            
            dd_tags = soup.find_all('dd', class_='flex lineb')  # 每期一块 dd
            
            for dd in dd_tags:  # 遍历页面上每一期
                issue_elem = dd.find('p')
                if not issue_elem:
                    continue
                
                issue = issue_elem.get_text(strip=True)  # 期号文本，如「第 xxx 期」依页面而定
                
                if issue not in periods_data:  # 首次见到该期则建空壳
                    periods_data[issue] = {
                        'issue': issue,
                        'lottery_numbers': [],
                        'kaiji': [],
                        'shiji': [],
                        'jin': [],
                        'guanzhu': [],
                        'duiying': [],
                        'date': ''
                    }
                
                date_elem = dd.find('p', class_='fcol9')
                if date_elem:
                    periods_data[issue]['date'] = date_elem.get_text(strip=True)
                
                winnum_elem = dd.find('p', class_='ball', attrs={'data-name': re.compile(r'winnum_')})
                if winnum_elem:  # 已开奖则有 20 个红球
                    numbers = []
                    b_tags = winnum_elem.find_all('b')
                    for b in b_tags:  # 每个 <b> 一个两位号
                        num_text = b.get_text(strip=True)
                        if num_text.isdigit():
                            numbers.append(int(num_text))
                    periods_data[issue]['lottery_numbers'] = sorted(numbers)  # 排序存储便于展示/比对
                
                data_elements = dd.find_all(attrs={'data-name': True, 'data-v': True})  # 带 data-v 的推荐项
                for elem in data_elements:  # 根据 data-name / 标签文字归入五类推荐
                    data_name = elem.get('data-name', '')
                    data_value = elem.get('data-v', '')
                    
                    numbers = [int(n) for n in data_value.split() if n.isdigit()]  # data-v 里空格分隔的号码
                    
                    i_tag = elem.find('i')
                    i_text = i_tag.get_text(strip=True) if i_tag else ''
                    
                    if 'kjh_' in data_name or i_text == '开':
                        periods_data[issue]['kaiji'] = numbers
                    elif 'sjh_' in data_name or i_text == '试':
                        periods_data[issue]['shiji'] = numbers
                    elif 'jinma_' in data_name or i_text == '金':
                        periods_data[issue]['jin'] = numbers
                    elif 'threema_' in data_name or i_text == '关':
                        periods_data[issue]['guanzhu'] = numbers
                    elif 'duiyingma_' in data_name or i_text == '对':
                        periods_data[issue]['duiying'] = numbers
            
            sorted_periods = sorted(periods_data.values(), key=lambda x: x['issue'], reverse=True)  # 期号大的在前（新→旧）
            return sorted_periods[:limit]  # 只保留最近 limit 期
        
        except Exception as e:
            print(f"✗ HTML 推荐数据获取失败：{e}")
            return []
    
    def parse_api_data(self, api_data):
        """
        规范化开奖 API 返回体为「按期号索引」的结构。

        参数 api_data: fetch_lottery_api_data 返回的顶层 dict（需含 data.data 列表）。
        返回 lottery_data:
            current_draw — 目前遍历到的最大期号字符串；
            historical_draws — 期号 -> {numbers, date, sum, span, ...}；
            sorted_issues — 所有有数据的期号升序列表，供 MultiDimensionAnalyzer 按时间扫。
        """
        lottery_data = {
            'current_draw': '',  # 目前已见的最大期号（字符串）
            'historical_draws': {},  # 期号 → {numbers, date, sum, ...}
            'sorted_issues': []  # 升序期号列表，供按时间遍历
        }
        
        pattern = r"<span class='fred'>(\d+)</span>"  # winnum 里是 HTML，用正则取数字
        
        for item in api_data['data']['data']:  # 每条一期开奖
            issue = str(item['issue'])
            numbers_html = item['winnum']
            numbers = [int(m) for m in re.findall(pattern, numbers_html)]
            
            if not numbers or len(numbers) != 20:  # 快乐8 每期 20 个号，不完整则跳过
                continue
            
            zhfb = item.get('zhfb', {})  # 和值、跨度等扩展字段
            
            lottery_data['historical_draws'][issue] = {
                'numbers': sorted(numbers),
                'date': item['kjdate'],
                'sum': zhfb.get('hz', sum(numbers)),
                'span': zhfb.get('kd', max(numbers) - min(numbers)),
                'odd_even_ratio': zhfb.get('jo', ''),
                'big_small_ratio': zhfb.get('dx', ''),
                'zone_ratio': zhfb.get('zh', ''),
                'lye_ratio': zhfb.get('lye', ''),
                'ac_value': zhfb.get('hw', 0),
                'avg': zhfb.get('avg', 0)
            }
            
            if not lottery_data['current_draw'] or int(issue) > int(lottery_data['current_draw']):
                lottery_data['current_draw'] = issue  # 维护「最新期号」
        
        lottery_data['sorted_issues'] = sorted(lottery_data['historical_draws'].keys())  # 字符串期号按字典序排序（通常为数字序）
        
        return lottery_data
