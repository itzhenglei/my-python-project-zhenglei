"""
================================================================================
快乐 8 智能预测系统 - 终极严谨版（带定时任务）
基于 kl8_zh1.py 邮件格式 + 多维度分析 + 周期性反推优化
================================================================================

核心理念：
1. 推荐号池（开机号 + 试机号 + 金码 + 关注码 + 对应码）去重后约 50 个左右
2. 高频推荐号：在 5 个推荐源中出现≥2 次的号码
3. 预测选号：从推荐号池中选择多维度评分最高的 10 个
4. 不使用推荐源权重，只用多维度分析评分
5. 周期性分析：自动找出最优回测期数
6. 反推优化：根据历史开奖反推最优维度权重
7. 邮件格式：完全参考 kl8_zh1.py 的详细展示
8. 定时任务：每天 17:30 自动发送邮件

作者：基于您所有代码的终极整合
日期：2026-03-19
"""
# 程序总流程（向下翻看即可）：抓取推荐页+开奖API → 分析“用多少期回测最稳” → 多套权重回测选最优
# → 对最近15期+最新期做预测 → 拼 HTML 邮件并发信/落盘。定时入口 main() → run_scheduler() 常驻轮询。

import requests  # HTTP 请求：拉网页、拉 JSON 接口
from bs4 import BeautifulSoup  # 把 HTML 解析成可查询的标签树
import re  # 正则：从 HTML 片段里抠开奖号码、匹配 data-name
import json  # 解析 API 返回的 JSON 文本
from collections import Counter, defaultdict  # Counter 统计号码出现次数；defaultdict 备用
from datetime import datetime  # 邮件标题、生成时间、JSON 里的时间戳
from typing import Dict, List, Tuple, Set  # 类型注解，方便读代码与工具检查
import random  # 若需随机性（主流程以确定性分析为主）
import zmail  # SMTP 发邮件（HTML）
import schedule  # 按日历时间注册后台任务
import time  # sleep：定时循环里每隔一段时间检查是否到点
import sys  # exit 退出进程


# ==================== 配置部分 ====================

KL8_HTML_URL = 'https://www.17500.cn/tool/kl8-allm.html'  # 17500 快乐8「推荐+试机」等合一的网页
# 以下为快乐8开奖列表 JSON（注意：URL 中无 {limit}，后面 format(limit) 实际不改变地址）
KL8_API_URL = 'https://m.17500.cn/tgj/api/kl8/getTbList?action=zhfb&page=1&limit=100&orderby=asc&start_issue=0&end_issue=0&week=all'

HEADERS = {  # 模拟浏览器访问 HTML 页，降低被拒概率
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
}

API_HEADERS = {  # 访问 JSON 接口用的头；Referer 模拟从列表页发起请求
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/javascript, */*; q=0.01',
    'Referer': 'https://m.17500.cn/tgj/kl8-kjfb.html'
}

EMAIL_CONFIG = {  # 发件箱与收件人（password 一般为邮箱 SMTP 授权码，勿泄露）
    'sender': 'zhenglei1071925251@qq.com',
    'password': 'hcjxwdijbfxpbfha',
    'recipients': [
        'zhenglei1071925251@qq.com',
        '2863179619@qq.com'
    ]
}

# 基础维度权重：各分析项在「给号码打分」时的相对重要性（后续回测会在此基础上微调）
BASE_DIMENSIONS = {
    'hot_number': 30,
    'cold_number': 12,
    'omission': 18,
    'diagonal': 10,
    'consecutive': 8,
    'repeat': 10,
    'sum_trend': 5,
    'odd_even': 4,
    'big_small': 3,
    'zone_hot': 8,
    'tail_pattern': 6,
    'head_focus': 5,
    'modulo_3': 5,
}


# ==================== 第一部分：数据获取 ====================

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
        """把开奖 API 的每条记录转成 historical_draws[期号]，并排序期号列表"""
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


# ==================== 第二部分：周期性分析器 ====================

class PeriodicityAnalyzer:
    """周期性分析器：用「相邻期号码重复个数」的波动，选出回测窗口长度（几期更稳）"""
    
    def __init__(self, lottery_data: Dict):
        self.lottery_data = lottery_data  # 含 historical_draws、sorted_issues
        self.sorted_issues = lottery_data['sorted_issues'] if lottery_data else []  # 升序期号
    
    def analyze_optimal_backtest_periods(self) -> Dict:
        """枚举多种回测长度，算稳定性 stability，返回最优期数 optimal_periods"""
        print("\n" + "=" * 80)
        print("【开始分析开奖数据周期性】")
        print("=" * 80)
        
        test_ranges = [5, 7, 10, 12, 15, 20, 25, 30]  # 候选「连续期数」
        results = {}  # period_count → {avg_hit_rate, std_dev, stability}
        
        for period_count in test_ranges:
            if len(self.sorted_issues) < period_count:  # 数据不够长则跳过该候选
                continue
            
            hit_rates = []  # 每个滑动窗口得到一个「平均相邻重复数」
            
            for start_idx in range(len(self.sorted_issues) - period_count):  # 滑动窗口
                end_idx = start_idx + period_count
                test_issues = self.sorted_issues[start_idx:end_idx]
                
                repeat_counts = []
                for i in range(1, len(test_issues)):  # 窗口内相邻两期
                    prev_nums = set(self.lottery_data['historical_draws'][test_issues[i-1]]['numbers'])
                    curr_nums = set(self.lottery_data['historical_draws'][test_issues[i]]['numbers'])
                    repeat_counts.append(len(prev_nums & curr_nums))  # 两期交集个数（重号数）
                
                if repeat_counts:
                    avg_repeat = sum(repeat_counts) / len(repeat_counts)
                    hit_rates.append(avg_repeat)
            
            if hit_rates:
                avg_hit_rate = sum(hit_rates) / len(hit_rates)
                std_dev = (sum((x - avg_hit_rate) ** 2 for x in hit_rates) / len(hit_rates)) ** 0.5
                stability = 1 - (std_dev / avg_hit_rate if avg_hit_rate > 0 else 1)  # 相对波动越小越「稳」
                results[period_count] = {
                    'avg_hit_rate': avg_hit_rate,
                    'std_dev': std_dev,
                    'stability': stability
                }
        
        best_period = max(results.items(), key=lambda x: x[1]['stability'])  # 挑 stability 最大的窗口长度
        
        print(f"\n各期数范围稳定性分析:")
        for period, stats in sorted(results.items()):
            stability_flag = "✓" if period == best_period[0] else " "
            print(f"  {stability_flag} {period:2d} 期：平均命中={stats['avg_hit_rate']:.2f}, 标准差={stats['std_dev']:.2f}, 稳定性={stats['stability']*100:.1f}%")
        
        print(f"\n✓ 推荐最优回测期数：{best_period[0]}期 (稳定性：{best_period[1]['stability']*100:.1f}%)")
        
        return {
            'optimal_periods': best_period[0],
            'all_results': results
        }


# ==================== 第三部分：多维度分析引擎 ====================

class MultiDimensionAnalyzer:
    """多维度分析器：为 1～80 每个号预计算冷热遗漏等，再按权重合成「综合分」"""
    
    def __init__(self, lottery_data: Dict, dimension_weights: Dict):
        self.lottery_data = lottery_data
        self.weights = dimension_weights  # 各维度乘到分项得分上
        self.sorted_issues = lottery_data['sorted_issues'] if lottery_data else []
        self.number_stats = {}  # 号码 → 出现次数、遗漏、近10期次数等
        self.pattern_cache = {}  # 热区、热尾、斜连趋势等
        
        if lottery_data:
            self._precompute_statistics()  # 先算统计量
            self._discover_patterns()  # 再算形态特征
    
    def _precompute_statistics(self):
        """预计算统计数据"""
        if not self.lottery_data:
            return
        
        total_periods = len(self.sorted_issues)
        
        occurrence_count = [0] * 80  # 下标 0 对应号码 1
        current_absence = [0] * 80  # 当前遗漏（距最近一次开出的间隔期数）
        absence_history = [[] for _ in range(80)]  # 历史上相邻两次开出之间的间隔序列
        
        for draw in self.lottery_data['historical_draws'].values():
            for num in draw['numbers']:
                if 1 <= num <= 80:
                    occurrence_count[num - 1] += 1  # 全历史出现次数
        
        for j in range(80):  # 算每个号「当前遗漏」：从最近一期往前扫
            num = j + 1
            current_absence[j] = total_periods  # 默认若从未开出
            
            for idx in range(total_periods - 1, -1, -1):  # 从新到旧
                issue = self.sorted_issues[idx]
                numbers = self.lottery_data['historical_draws'][issue]['numbers']
                if num in numbers:
                    current_absence[j] = (total_periods - 1) - idx
                    break
        
        average_absence = []
        max_absence = []
        
        for j in range(80):
            num = j + 1
            last_idx = None
            
            for idx in range(total_periods):
                issue = self.sorted_issues[idx]
                numbers = self.lottery_data['historical_draws'][issue]['numbers']
                if num in numbers:
                    if last_idx is not None:
                        gap = idx - last_idx - 1
                        absence_history[j].append(gap)
                    last_idx = idx
            
            if last_idx is not None and last_idx < total_periods - 1:
                current_gap = (total_periods - 1) - last_idx
                absence_history[j].append(current_gap)
            
            avg_val = sum(absence_history[j]) / len(absence_history[j]) if absence_history[j] else float(total_periods)
            max_val = max(absence_history[j]) if absence_history[j] else total_periods
            
            average_absence.append(avg_val)
            max_absence.append(max_val)
        
        for num in range(1, 81):
            idx = num - 1
            self.number_stats[num] = {
                'total_count': occurrence_count[idx],
                'current_absence': current_absence[idx],
                'average_absence': average_absence[idx],
                'max_absence': max_absence[idx]
            }
        
        recent_10_issues = self.sorted_issues[-10:]
        recent_counts = Counter()
        for issue in recent_10_issues:
            draw = self.lottery_data['historical_draws'][issue]
            for num in draw['numbers']:
                recent_counts[num] += 1
        
        for num in range(1, 81):
            self.number_stats[num]['recent_10_count'] = recent_counts.get(num, 0)
    
    def _discover_patterns(self):
        """自动发现出号规律"""
        self.pattern_cache = {
            'hot_zones': self._find_hot_zones(),
            'hot_tails': self._find_hot_tails(),
            'hot_heads': self._find_hot_heads(),
            'modulo_trend': self._find_modulo_trend(),
            'diagonal_sequences': self._find_diagonal_sequences()
        }
    
    def _find_hot_zones(self) -> List[int]:
        zones = [(1, 20), (21, 40), (41, 60), (61, 80)]
        zone_counts = [0, 0, 0, 0]
        
        recent_issues = self.sorted_issues[-10:]
        for issue in recent_issues:
            draw = self.lottery_data['historical_draws'][issue]
            for num in draw['numbers']:
                for idx, (start, end) in enumerate(zones):
                    if start <= num <= end:
                        zone_counts[idx] += 1
        
        hot_zone_idx = zone_counts.index(max(zone_counts))
        return [hot_zone_idx + 1]
    
    def _find_hot_tails(self) -> List[int]:
        tail_counts = Counter()
        
        recent_issues = self.sorted_issues[-10:]
        for issue in recent_issues:
            draw = self.lottery_data['historical_draws'][issue]
            for num in draw['numbers']:
                tail = num % 10
                tail_counts[tail] += 1
        
        return [tail for tail, count in tail_counts.most_common(3)]
    
    def _find_hot_heads(self) -> List[int]:
        head_counts = Counter()
        
        recent_issues = self.sorted_issues[-10:]
        for issue in recent_issues:
            draw = self.lottery_data['historical_draws'][issue]
            for num in draw['numbers']:
                head = num // 10
                head_counts[head] += 1
        
        return [head for head, count in head_counts.most_common(2)]
    
    def _find_modulo_trend(self) -> int:
        modulo_counts = {0: 0, 1: 0, 2: 0}
        
        recent_issues = self.sorted_issues[-10:]
        for issue in recent_issues:
            draw = self.lottery_data['historical_draws'][issue]
            for num in draw['numbers']:
                mod = num % 3
                modulo_counts[mod] += 1
        
        return max(modulo_counts.items(), key=lambda x: x[1])[0]
    
    def _find_diagonal_sequences(self) -> Set[int]:
        diagonals = set()
        
        if len(self.sorted_issues) < 3:
            return diagonals
        
        for i in range(len(self.sorted_issues) - 2):
            curr_nums = set(self.lottery_data['historical_draws'][self.sorted_issues[i]]['numbers'])
            next_nums = set(self.lottery_data['historical_draws'][self.sorted_issues[i + 1]]['numbers'])
            next_next_nums = set(self.lottery_data['historical_draws'][self.sorted_issues[i + 2]]['numbers'])
            
            for num in curr_nums:
                if (num + 1) in next_nums and (num + 2) in next_next_nums:
                    diagonals.add(num + 2)
                if (num - 1) in next_nums and (num - 2) in next_next_nums:
                    diagonals.add(num - 2)
        
        return diagonals
    
    def get_latest_numbers(self, n=1):
        if not self.lottery_data or n > len(self.sorted_issues):
            return []
        
        issue = self.sorted_issues[-n]
        return self.lottery_data['historical_draws'][issue]['numbers']
    
    def analyze_number(self, num: int) -> float:
        """分析单个号码的综合评分"""
        if num not in self.number_stats:
            return 0.0
        
        stats = self.number_stats[num]
        score = 0.0
        
        # 热号
        recent_count = stats['recent_10_count']
        if recent_count >= 5:
            score += self.weights['hot_number'] * (recent_count / 10) * 1.5
        elif recent_count >= 3:
            score += self.weights['hot_number'] * (recent_count / 10)
        
        # 重号
        if num in self.get_latest_numbers(1):
            repeat_prob = self._calculate_repeat_probability()
            score += self.weights['repeat'] * (repeat_prob / 2) * 5
            if recent_count >= 4:
                score *= 1.3
        
        # 遗漏值
        current_miss = stats['current_absence']
        avg_miss = stats['average_absence']

        if current_miss > avg_miss * 1.5 and avg_miss > 0:
            ratio = current_miss / avg_miss
            score += self.weights['omission'] * (ratio * 5)
        elif current_miss > 5 and current_miss <= 15:
            score += self.weights['omission'] * (current_miss / 2)

        # 冷号
        if current_miss > 15:
            score += self.weights['cold_number'] * min(current_miss / 5, 12)
        
        # 斜连
        if num in self.pattern_cache.get('diagonal_sequences', set()):
            score += self.weights['diagonal'] * 2
        
        # 连号
        consecutive_bonus = self._check_consecutive_pattern(num)
        score += self.weights['consecutive'] * consecutive_bonus
        
        # 和值
        sum_trend = self._analyze_sum_trend()
        avg_sum = sum_trend.get('average', 810)
        
        if num <= 40 and avg_sum < 800:
            score += self.weights['sum_trend'] * 3
        elif num > 40 and avg_sum > 800:
            score += self.weights['sum_trend'] * 3
        
        # 奇偶
        odd_even_trend = self._analyze_odd_even_trend()
        target_odd = odd_even_trend.get('target_odd', 10)
        
        if num % 2 == 1:
            if target_odd >= 10:
                score += self.weights['odd_even'] * 3
        else:
            if target_odd <= 10:
                score += self.weights['odd_even'] * 3
        
        # 大小
        big_small_trend = self._analyze_big_small_trend()
        
        if num <= 40:
            if big_small_trend == '小数多':
                score += self.weights['big_small'] * 4
        else:
            if big_small_trend == '大数多':
                score += self.weights['big_small'] * 4
        
        # 区域
        zone_num = ((num - 1) // 20) + 1
        if zone_num in self.pattern_cache.get('hot_zones', []):
            score += self.weights['zone_hot'] * 3
        
        # 尾数
        tail = num % 10
        if tail in self.pattern_cache.get('hot_tails', []):
            score += self.weights['tail_pattern'] * 3
        
        # 头数
        head = num // 10
        if head in self.pattern_cache.get('hot_heads', []):
            score += self.weights['head_focus'] * 4
        
        # 012 路
        mod = num % 3
        if mod == self.pattern_cache.get('modulo_trend', -1):
            score += self.weights['modulo_3'] * 3
        
        return score
    
    def _check_consecutive_pattern(self, num: int) -> float:
        bonus = 0.0
        
        latest_nums = set(self.get_latest_numbers(1))
        
        if (num - 1) in latest_nums or (num + 1) in latest_nums:
            bonus += 1.0
        
        if (num - 1) in latest_nums and (num + 1) in latest_nums:
            bonus += 1.5
        
        return min(bonus, 2.0)
    
    def _calculate_repeat_probability(self) -> float:
        if len(self.sorted_issues) < 2:
            return 5.0
        
        repeat_counts = []
        for i in range(1, min(10, len(self.sorted_issues))):
            prev_nums = set(self.get_latest_numbers(i + 1))
            curr_nums = set(self.get_latest_numbers(i))
            repeat_counts.append(len(prev_nums & curr_nums))
        
        return sum(repeat_counts) / len(repeat_counts) if repeat_counts else 5.0
    
    def _analyze_sum_trend(self) -> Dict:
        recent_sums = []
        for issue in self.sorted_issues[-10:]:
            draw = self.lottery_data['historical_draws'][issue]
            recent_sums.append(draw['sum'])
        
        return {
            'average': sum(recent_sums) / len(recent_sums),
            'trend': 'up' if recent_sums[-1] > recent_sums[0] else 'down'
        }
    
    def _analyze_odd_even_trend(self) -> Dict:
        odd_counts = []
        for issue in self.sorted_issues[-10:]:
            draw = self.lottery_data['historical_draws'][issue]
            odd_count = sum(1 for n in draw['numbers'] if n % 2 == 1)
            odd_counts.append(odd_count)
        
        avg_odd = sum(odd_counts) / len(odd_counts)
        
        return {
            'average': avg_odd,
            'target_odd': 12 if avg_odd > 10 else 8 if avg_odd < 10 else 10
        }
    
    def _analyze_big_small_trend(self) -> str:
        big_counts = []
        for issue in self.sorted_issues[-10:]:
            draw = self.lottery_data['historical_draws'][issue]
            big_count = sum(1 for n in draw['numbers'] if n > 40)
            big_counts.append(big_count)
        
        avg_big = sum(big_counts) / len(big_counts)
        
        return '大数多' if avg_big > 10 else '小数多' if avg_big < 10 else '平衡'


# ==================== 第四部分：智能预测器 ====================

class IntelligentPredictor:
    """智能预测器：某期只从「五类推荐合并池」里按多维得分取前 count 个（顺序为分数降序，非号序）"""
    
    def __init__(self, dimension_weights: Dict):
        self.weights = dimension_weights
        self.analyzer = None  # 等 set_lottery_data 后再实例化分析器
    
    def set_lottery_data(self, lottery_data: Dict):
        self.analyzer = MultiDimensionAnalyzer(lottery_data, self.weights)  # 绑定历史开奖
    
    def predict_for_period(self, period_data: Dict, count=10) -> List[int]:
        """预测单期号码：返回长度为 count 的列表（最高分在前）"""
        # 构建推荐号池
        recommend_pool = set()
        recommend_pool.update(period_data.get('kaiji', []))
        recommend_pool.update(period_data.get('shiji', []))
        recommend_pool.update(period_data.get('jin', []))
        recommend_pool.update(period_data.get('guanzhu', []))
        recommend_pool.update(period_data.get('duiying', []))
        
        if not recommend_pool:
            print(f"⚠️ 期号{period_data.get('issue', '')}没有推荐号码")
            return []
        
        print(f"  推荐号池：{len(recommend_pool)}个号码")
        print(f"    开机号:{len(period_data.get('kaiji', []))} 试机号:{len(period_data.get('shiji', []))} 金码:{len(period_data.get('jin', []))} 关注码:{len(period_data.get('guanzhu', []))} 对应码:{len(period_data.get('duiying', []))}")
        
        # 为每个推荐号评分
        scores = {}
        for num in recommend_pool:
            score = self.analyzer.analyze_number(num)
            scores[num] = score
        
        # 按评分排序，选择前 count 个（item[0] 是号码，item[1] 是得分）
        sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        predicted = [item[0] for item in sorted_scores[:count]]  # 展示/邮件里若要号序需再 sorted()
        
        # 输出高分号码详情
        print(f"  TOP5 高分号码:")
        for idx, (num, score) in enumerate(sorted_scores[:5], 1):
            print(f"    {idx}. 号码{num:02d}: {score:.2f}分")
        
        return predicted


# ==================== 第五部分：回测优化器 ====================

class BacktestOptimizer:
    """回测优化器"""
    
    def __init__(self):
        self.base_weights = BASE_DIMENSIONS.copy()
    
    def optimize_weights_by_reverse_engineering(self, all_periods_data: List[Dict], 
                                                   lottery_data: Dict, 
                                                   optimal_periods: int) -> Tuple[Dict, Dict]:
        """反推优化法"""
        print("\n" + "=" * 80)
        print("【开始反推优化权重配置】")
        print("=" * 80)
        
        # 收集所有特征数据
        feature_data = []
        
        for period_data in all_periods_data:
            if not period_data.get('lottery_numbers'):
                continue
            
            actual = set(period_data['lottery_numbers'])
            
            # 构建推荐号池
            recommend_pool = set()
            recommend_pool.update(period_data.get('kaiji', []))
            recommend_pool.update(period_data.get('shiji', []))
            recommend_pool.update(period_data.get('jin', []))
            recommend_pool.update(period_data.get('guanzhu', []))
            recommend_pool.update(period_data.get('duiying', []))
            
            # 统计每个号码在 5 个推荐源中的出现次数
            recommend_counter = Counter()
            for num in period_data.get('kaiji', []):
                recommend_counter[num] += 1
            for num in period_data.get('shiji', []):
                recommend_counter[num] += 1
            for num in period_data.get('jin', []):
                recommend_counter[num] += 1
            for num in period_data.get('guanzhu', []):
                recommend_counter[num] += 1
            for num in period_data.get('duiying', []):
                recommend_counter[num] += 1
            
            # 为每个推荐号记录特征
            for num in recommend_pool:
                is_hit = num in actual
                recommend_count = recommend_counter[num]
                
                feature_data.append({
                    'is_hit': is_hit,
                    'num': num,
                    'recommend_count': recommend_count
                })
        
        # 分析高频推荐号的命中率
        high_freq_hits = 0
        high_freq_total = 0
        low_freq_hits = 0
        low_freq_total = 0
        
        for feature in feature_data:
            if feature['recommend_count'] >= 2:
                high_freq_total += 1
                if feature['is_hit']:
                    high_freq_hits += 1
            else:
                low_freq_total += 1
                if feature['is_hit']:
                    low_freq_hits += 1
        
        high_freq_rate = (high_freq_hits / high_freq_total * 100) if high_freq_total > 0 else 0
        low_freq_rate = (low_freq_hits / low_freq_total * 100) if low_freq_total > 0 else 0
        
        print(f"\n高频推荐号（≥2 次）命中率：{high_freq_rate:.1f}% ({high_freq_hits}/{high_freq_total})")
        print(f"低频推荐号（1 次）命中率：{low_freq_rate:.1f}% ({low_freq_hits}/{low_freq_total})")
        
        # 测试不同权重组合
        best_config = self._test_weight_configs(all_periods_data, lottery_data, optimal_periods)
        
        return best_config['weights'], {
            'hit_rate': best_config['hit_rate'],
            'high_freq_hit_rate': high_freq_rate,
            'low_freq_hit_rate': low_freq_rate
        }
    
    def _test_weight_configs(self, all_periods_data: List[Dict], lottery_data: Dict, 
                            optimal_periods: int) -> Dict:
        """测试多种权重配置"""
        configs = []
        
        configs.append({'name': '基础配置', 'weights': self.base_weights.copy()})
        
        for hot_w in [35, 40]:
            config = self.base_weights.copy()
            config['hot_number'] = hot_w
            config['repeat'] = 12
            configs.append({'name': f'热号强化 (hot={hot_w})', 'weights': config})
        
        for repeat_w in [12, 15]:
            config = self.base_weights.copy()
            config['repeat'] = repeat_w
            config['hot_number'] = 35
            configs.append({'name': f'重号强化 (repeat={repeat_w})', 'weights': config})
        
        for omission_w in [20, 25]:
            config = self.base_weights.copy()
            config['omission'] = omission_w
            configs.append({'name': f'遗漏优化 (omission={omission_w})', 'weights': config})
        
        config = self.base_weights.copy()
        config['hot_number'] = 35
        config['repeat'] = 12
        config['omission'] = 20
        config['diagonal'] = 12
        configs.append({'name': '综合优化', 'weights': config})
        
        best_config = None
        best_hit_rate = 0
        
        for config in configs:
            predictor = IntelligentPredictor(config['weights'])
            predictor.set_lottery_data(lottery_data)
            
            total_hits = 0
            total_predictions = 0
            
            reversed_periods = list(reversed(all_periods_data[:optimal_periods]))
            
            for period_data in reversed_periods:
                if not period_data.get('lottery_numbers'):
                    continue
                
                predicted = predictor.predict_for_period(period_data, count=10)
                
                if not predicted:
                    continue
                
                actual = set(period_data['lottery_numbers'])
                hits = len(set(predicted) & actual)
                total_hits += hits
                total_predictions += len(predicted)
            
            hit_rate = (total_hits / total_predictions * 100) if total_predictions > 0 else 0
            print(f"{config['name']}: 命中率={hit_rate:.2f}%")
            
            if hit_rate > best_hit_rate:
                best_hit_rate = hit_rate
                best_config = config
        
        print(f"\n✓ 最优配置：{best_config['name']}, 命中率={best_hit_rate:.2f}%")
        
        return {'weights': best_config['weights'], 'hit_rate': best_hit_rate}


# ==================== 第六部分：邮件生成（参考 kl8_zh1.py） ====================

def calculate_recommend_stats(period_data: Dict) -> Dict:
    """计算推荐号统计信息"""
    # 合并所有推荐号
    all_kaiji = period_data.get('kaiji', [])
    all_shiji = period_data.get('shiji', [])
    all_jin = period_data.get('jin', [])
    all_guanzhu = period_data.get('guanzhu', [])
    all_duiying = period_data.get('duiying', [])
    
    # 去重后的推荐号池
    recommend_pool = set(all_kaiji) | set(all_shiji) | set(all_jin) | set(all_guanzhu) | set(all_duiying)
    total_recommends = len(recommend_pool)
    
    # 统计每个号码在 5 个推荐源中的出现次数
    recommend_counter = Counter()
    for num in all_kaiji:
        recommend_counter[num] += 1
    for num in all_shiji:
        recommend_counter[num] += 1
    for num in all_jin:
        recommend_counter[num] += 1
    for num in all_guanzhu:
        recommend_counter[num] += 1
    for num in all_duiying:
        recommend_counter[num] += 1
    
    # 高频推荐号（在 5 个推荐源中出现≥2 次）
    high_freq_numbers = [(num, count) for num, count in recommend_counter.items() if count >= 2]
    high_freq_numbers.sort(key=lambda x: (x[1], x[0]), reverse=True)
    high_freq_count = len(high_freq_numbers)
    
    return {
        'total_recommends': total_recommends,
        'high_freq_numbers': high_freq_numbers,
        'high_freq_count': high_freq_count
    }


def generate_period_grid(period_data: Dict) -> List[List[Dict]]:
    """生成单期 9 宫格数据"""
    grid = []
    
    lottery_numbers = set(period_data.get('lottery_numbers', []))
    kaiji = set(period_data.get('kaiji', []))
    shiji = set(period_data.get('shiji', []))
    jin = set(period_data.get('jin', []))
    guanzhu = set(period_data.get('guanzhu', []))
    duiying = set(period_data.get('duiying', []))
    
    has_lottery = len(lottery_numbers) > 0
    
    for row in range(8):
        grid_row = []
        for col in range(10):
            num = row * 10 + col + 1
            
            is_lottery = num in lottery_numbers
            is_kaiji = num in kaiji
            is_shiji = num in shiji
            is_jin = num in jin
            is_guanzhu = num in guanzhu
            is_duiying = num in duiying
            
            is_recommend = is_kaiji or is_shiji or is_jin or is_guanzhu or is_duiying
            is_hit = is_lottery and is_recommend
            
            type_labels = []
            if is_kaiji:
                type_labels.append('开')
            if is_shiji:
                type_labels.append('试')
            if is_jin:
                type_labels.append('金')
            if is_guanzhu:
                type_labels.append('关')
            if is_duiying:
                type_labels.append('对')
            
            grid_row.append({
                'number': num,
                'is_lottery': is_lottery,
                'is_recommend': is_recommend,
                'is_hit': is_hit,
                'type_labels': type_labels
            })
        
        grid.append(grid_row)
    
    return grid


def calculate_hit_statistics(period_data: Dict) -> Dict:
    """计算命中统计"""
    lottery_numbers = set(period_data.get('lottery_numbers', []))
    kaiji = set(period_data.get('kaiji', []))
    shiji = set(period_data.get('shiji', []))
    jin = set(period_data.get('jin', []))
    guanzhu = set(period_data.get('guanzhu', []))
    duiying = set(period_data.get('duiying', []))
    
    if not lottery_numbers:
        return None
    
    all_recommends = set(kaiji | shiji | jin | guanzhu | duiying)
    total_hits = len(all_recommends & lottery_numbers)
    hit_rate = (total_hits / 20 * 100) if len(lottery_numbers) > 0 else 0
    
    return {
        'total_hits': total_hits,
        'hit_rate': hit_rate,
        'kaiji_hits': len(kaiji & lottery_numbers),
        'shiji_hits': len(shiji & lottery_numbers),
        'jin_hits': len(jin & lottery_numbers),
        'guanzhu_hits': len(guanzhu & lottery_numbers),
        'duiying_hits': len(duiying & lottery_numbers),
        'total_recommends': len(all_recommends)
    }


def generate_grid_html(grid: List[List[Dict]], has_lottery: bool = True) -> str:
    """生成 9 宫格 HTML"""
    grid_html = ""
    
    for row_idx, row in enumerate(grid):
        grid_html += f'<div class="grid-row">\n'
        for cell in row:
            num = cell['number']
            
            class_name = "grid-cell"
            
            if cell['is_hit']:
                class_name += " hit"
            elif cell['is_lottery'] and has_lottery:
                class_name += " lottery"
            elif cell['is_recommend']:
                if len(cell['type_labels']) >= 3:
                    class_name += " multi-recommend"
                elif len(cell['type_labels']) >= 2:
                    class_name += " double-recommend"
                else:
                    class_name += " recommend"
            
            data_attrs = ""
            if cell['type_labels']:
                data_attrs = f' data-types="{",".join(cell["type_labels"])}"'
            
            grid_html += f'<div class="{class_name}"{data_attrs}>{num:02d}</div>\n'
        
        grid_html += '</div>\n'
    
    return grid_html


def generate_email_content(prediction_result: Dict, backtest_stats: Dict, 
                          all_periods_data: List[Dict], optimal_weights: Dict,
                          all_predictions: Dict[str, List[int]],
                          periodicity_info: Dict) -> str:
    """生成完整邮件 HTML（参考 kl8_zh1.py 格式优化版）"""
    # ---------- 下面整段是 f-string：内含 HTML + CSS，勿在字符串里写 # 注释 ----------
    # 结构：head 里 style 定义邮件里各区块样式；body 里 header → 本期10球(见后续循环) → 回测 → 15期卡片
    html_content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>快乐 8 智能预测 - {datetime.now().strftime('%Y-%m-%d')}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ 
            font-family: 'Microsoft YaHei', Arial, sans-serif; 
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            padding: 20px;
        }}
        .container {{ 
            max-width: 1400px; 
            margin: 0 auto; 
            background: white;
            border-radius: 20px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.3);
            overflow: hidden;
        }}
        .header {{ 
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white; 
            padding: 25px; 
            text-align: center;
        }}
        .header h1 {{ font-size: 28px; margin-bottom: 10px; }}
        .header p {{ font-size: 14px; opacity: 0.9; }}
        
        .content {{ padding: 30px; }}
        
        .section {{
            margin-bottom: 30px;
            padding: 20px;
            background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%);
            border-radius: 12px;
            border-left: 5px solid #667eea;
        }}
        
        .section-title {{
            font-size: 20px;
            font-weight: bold;
            color: #333;
            margin-bottom: 15px;
        }}
        
        .prediction-numbers {{
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
            justify-content: center;
            margin-top: 15px;
        }}
        
        .number-ball {{
            width: 50px;
            height: 50px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 20px;
            font-weight: bold;
            color: white;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            box-shadow: 0 4px 15px rgba(102, 126, 234, 0.4);
        }}
        
        .number-ball.dan {{
            background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
            animation: pulse 2s infinite;
        }}
        
        @keyframes pulse {{
            0%, 100% {{ transform: scale(1); }}
            50% {{ transform: scale(1.05); }}
        }}
        
        .periods-container {{
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 20px;
            margin-top: 20px;
        }}
        
        .period-card {{
            background: white;
            border-radius: 12px;
            box-shadow: 0 4px 15px rgba(0,0,0,0.1);
            overflow: hidden;
            border: 2px solid #e9ecef;
        }}
        
        .period-header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 15px;
            text-align: center;
            border-radius: 12px 12px 0 0;
        }}
        .period-header h3 {{
            font-size: 18px;
            margin-bottom: 8px;
        }}
        .period-info {{
            font-size: 13px;
            opacity: 0.95;
            margin-bottom: 5px;
        }}
        
        .grid-row {{
            display: flex;
            gap: 2px;
            margin-bottom: 2px;
            justify-content: center;
            padding: 2px 5px;
        }}
        
        .grid-cell {{
            width: 28px;
            height: 28px;
            display: flex;
            align-items: center;
            justify-content: center;
            background: white;
            border: 1px solid #e9ecef;
            border-radius: 50%;
            font-size: 11px;
            font-weight: bold;
            position: relative;
        }}
        
        .grid-cell.lottery {{
            background: linear-gradient(135deg, #ff6b6b 0%, #ee5a6f 100%);
            color: white;
            border-color: #ff6b6b;
        }}
        
        .grid-cell.recommend {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border-color: #667eea;
        }}
        
        .grid-cell.double-recommend {{
            background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
            color: white;
            border-color: #f093fb;
            font-weight: 900;
        }}
        
        .grid-cell.multi-recommend {{
            background: linear-gradient(135deg, #10b981 0%, #059669 100%);
            color: white;
            border-color: #10b981;
            font-weight: 900;
            box-shadow: 0 2px 8px rgba(16, 185, 129, 0.5);
        }}
        
        .grid-cell.hit {{
            background: linear-gradient(135deg, #ffd700 0%, #ffed4e 100%);
            color: #333;
            border-color: #ffd700;
            box-shadow: 0 2px 8px rgba(255, 215, 0, 0.5);
            font-weight: 900;
        }}
        
        .grid-cell[data-types]::after {{
            content: attr(data-types);
            position: absolute;
            top: -5px;
            right: -5px;
            background: rgba(0,0,0,0.7);
            color: white;
            font-size: 8px;
            padding: 1px 3px;
            border-radius: 3px;
        }}
        
        .stats-summary {{
            padding: 10px;
            background: #f8f9fa;
            border-top: 1px solid #e9ecef;
            font-size: 12px;
        }}
        
        .stat-row {{
            display: flex;
            justify-content: space-between;
            padding: 4px 10px;
            font-size: 12px;
            border-bottom: 1px solid #f5f5f5;
        }}
        .stat-row:last-child {{
            border-bottom: none;
        }}
        .stat-label {{
            color: #666;
        }}
        .stat-value {{
            font-weight: bold;
            color: #333;
        }}
        .stat-value.good {{
            color: #10b981;
        }}
        .stat-value.excellent {{
            color: #f59e0b;
        }}
        
        .high-freq-section {{
            margin-top: 12px;
            padding: 10px;
            background: linear-gradient(135deg, #fff5f5 0%, #ffe5e5 100%);
            border-radius: 8px;
            border: 2px solid #fc8181;
        }}
        
        .high-freq-title {{
            font-size: 13px;
            font-weight: bold;
            color: #c53030;
            margin-bottom: 8px;
            text-align: center;
        }}
        
        .high-freq-numbers {{
            display: flex;
            flex-wrap: wrap;
            gap: 6px;
            justify-content: center;
        }}
        
        .high-freq-number {{
            background: linear-gradient(135deg, #f56565 0%, #c53030 100%);
            color: white;
            padding: 4px 10px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: bold;
            box-shadow: 0 2px 6px rgba(245, 101, 101, 0.4);
        }}
        
        .high-freq-number.hit {{
            background: linear-gradient(135deg, #d53f8c 0%, #805ad5 100%);
            color: white;
            padding: 4px 10px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: bold;
            box-shadow: 0 2px 6px rgba(212, 53, 149, 0.5);
            animation: pulse 2s infinite;
        }}
        
        .hit-count-badge {{
            display: inline-block;
            background: rgba(255, 255, 255, 0.3);
            padding: 2px 6px;
            border-radius: 8px;
            font-size: 10px;
            margin-left: 4px;
            font-weight: bold;
        }}
        
        .prediction-info {{
            padding: 10px;
            background: linear-gradient(135deg, #e3f2fd 0%, #bbdefb 100%);
            border-top: 1px solid #e9ecef;
            font-size: 12px;
        }}
        
        .prediction-title {{
            font-weight: bold;
            color: #1976d2;
            margin-bottom: 8px;
        }}
        
        .prediction-number-list {{
            display: flex;
            flex-wrap: wrap;
            gap: 5px;
            justify-content: center;
        }}
        
        .prediction-number {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            width: 24px;
            height: 24px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 11px;
            font-weight: bold;
        }}
        
        .prediction-number.hit {{
            background: linear-gradient(135deg, #ffd700 0%, #ffed4e 100%);
            color: #333;
            animation: pulse 2s infinite;
        }}
        
        .legend {{
            display: flex;
            justify-content: center;
            gap: 10px;
            font-size: 10px;
            color: #666;
            flex-wrap: wrap;
            margin-top: 10px;
        }}
        
        .legend-item {{
            display: flex;
            align-items: center;
        }}
        
        .dot {{
            display: inline-block;
            width: 10px;
            height: 10px;
            border-radius: 50%;
            margin-right: 4px;
        }}
        
        .lottery-dot {{ background: #ff6b6b; }}
        .recommend-dot {{ background: #667eea; }}
        .double-recommend-dot {{ background: #f093fb; }}
        .multi-recommend-dot {{ background: #10b981; }}
        .hit-dot {{ background: #ffd700; }}
        
        .footer {{
            text-align: center;
            padding: 20px;
            color: #999;
            font-size: 11px;
            background: #f8f9fa;
            border-top: 2px solid #e9ecef;
            margin-top: 30px;
        }}
        
        .warning {{
            margin-top: 20px;
            padding: 15px;
            background: linear-gradient(135deg, #fff3cd 0%, #ffe69c 100%);
            border-left: 5px solid #ffc107;
            border-radius: 8px;
            color: #856404;
        }}
        
        @media (max-width: 1200px) {{
            .periods-container {{ grid-template-columns: repeat(2, 1fr); }}
        }}
        
        @media (max-width: 768px) {{
            .periods-container {{ grid-template-columns: 1fr; }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🎲 快乐 8 智能预测</h1>
            <p>生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        </div>
        
        <div class="content">
            <div class="section">
                <div class="section-title">🎯 最新一期智能预测（10 个）</div>
                <div class="prediction-numbers">
"""
    # f-string 第一段到此结束：下面用循环补 10 个预测球，再接第二段 HTML
    predicted_numbers = prediction_result.get('predicted_numbers', [])  # 最新期10个（分数降序）
    dan_codes = prediction_result.get('dan_codes', [])  # 胆码，用于 CSS 类 dan
    
    for num in predicted_numbers:
        is_dan = "dan" if num in dan_codes else ""  # 在胆码里则多一个 CSS 类名
        html_content += f'                    <div class="number-ball {is_dan}">{num:02d}</div>\n'
    
    # 第二段 f-string：胆码说明、回测统计区、15 期卡片容器开头
    html_content += f"""
                </div>
                <div style="text-align: center; margin-top: 10px; color: #666; font-size: 13px;">
                    <span class="legend-item"><span class="dot" style="background: #f093fb;"></span>红色球为胆码（重点推荐）</span>
                </div>
            </div>
            
            <div class="section">
                <div class="section-title">📊 回测统计</div>
                <div style="padding: 15px; background: white; border-radius: 8px;">
                    <p style="font-size: 14px; color: #666;">
                        最优回测期数：<strong>{periodicity_info.get('optimal_periods', 15)}期</strong><br>
                        回测期数：<strong>{backtest_stats.get('total_periods', 0)}期</strong><br>
                        最优命中率：<strong style="color: #10b981;">{backtest_stats.get('max_hit_rate', 0):.1f}%</strong><br>
                        高频推荐命中率：<strong style="color: #f59e0b;">{backtest_stats.get('high_freq_hit_rate', 0):.1f}%</strong>
                    </p>
                </div>
            </div>
            
            <div class="section">
                <div class="section-title">📈 最近 15 期详细分析（含预测对比）</div>
                <div class="periods-container">
"""
    
    for period_idx, period_data in enumerate(all_periods_data[:15]):  # 最多 15 张卡片
        recommend_stats = calculate_recommend_stats(period_data)  # 推荐池、高频列表
        stats = calculate_hit_statistics(period_data)  # 若未开奖则为 None
        
        has_lottery = len(period_data.get('lottery_numbers', [])) > 0  # 是否已有开奖号
        grid = generate_period_grid(period_data)
        grid_html = generate_grid_html(grid, has_lottery)
        
        high_freq_numbers = recommend_stats['high_freq_numbers']
        high_freq_count = recommend_stats['high_freq_count']
        
        high_freq_hits = 0
        if high_freq_numbers and period_data.get('lottery_numbers'):
            actual = set(period_data['lottery_numbers'])
            high_freq_nums = set([num for num, count in high_freq_numbers])
            high_freq_hits = len(high_freq_nums & actual)
        high_freq_hit_rate = (high_freq_hits / high_freq_count * 100) if high_freq_count > 0 else 0
        
        period_issue = period_data.get('issue', '')
        period_prediction = all_predictions.get(period_issue, [])
        
        prediction_hits = 0  # 该期预测10个与真实开奖交集个数
        if period_prediction and period_data.get('lottery_numbers'):
            actual = set(period_data['lottery_numbers'])
            prediction_hits = len(set(period_prediction) & actual)  # 集合交，与顺序无关
        
        status_text = "待开奖" if not has_lottery else f"已开奖"  # 卡片标题旁状态
        
        html_content += f"""
            <div class="period-card">
                <div class="period-header">
                    <h3>第 {period_data['issue']} 期</h3>
                    <div class="period-info">📅 {period_data.get('date', '')}</div>
                    <div class="period-info">{status_text}</div>
                </div>
                <div style="padding: 10px; background: #f8f9fa;">
                    <div class="grid">
                        {grid_html}
                    </div>
                </div>
"""
        
        if stats and has_lottery:
            hit_class = "good" if stats['hit_rate'] >= 30 else ""
            hit_class = "excellent" if stats['hit_rate'] >= 50 else hit_class
            
            html_content += f"""
                <div class="stats-summary">
                    <div class="stat-row">
                        <span class="stat-label">📊 推荐号码：</span>
                        <span class="stat-value">{recommend_stats['total_recommends']} 个（去重后）</span>
                    </div>
                    <div class="stat-row">
                        <span class="stat-label">🎯 命中号码：</span>
                        <span class="stat-value {hit_class}">{stats['total_hits']} 个</span>
                    </div>
                    <div class="stat-row">
                        <span class="stat-label">📈 命中率：</span>
                        <span class="stat-value {hit_class}">{stats['hit_rate']:.1f}%</span>
                    </div>
                    <div class="stat-row">
                        <span class="stat-label">🔔 开机号命中：</span>
                        <span class="stat-value {hit_class}">{stats['kaiji_hits']} 个</span>
                    </div>
                    <div class="stat-row">
                        <span class="stat-label">🧪 试机号命中：</span>
                        <span class="stat-value {hit_class}">{stats['shiji_hits']} 个</span>
                    </div>
                    <div class="stat-row">
                        <span class="stat-label">🏆 金码命中：</span>
                        <span class="stat-value {hit_class}">{stats['jin_hits']} 个</span>
                    </div>
                    <div class="stat-row">
                        <span class="stat-label">👁️ 关注码命中：</span>
                        <span class="stat-value {hit_class}">{stats['guanzhu_hits']} 个</span>
                    </div>
                    <div class="stat-row">
                        <span class="stat-label">🎯 对应码命中：</span>
                        <span class="stat-value {hit_class}">{stats['duiying_hits']} 个</span>
                    </div>
                </div>
"""
        
        if high_freq_numbers:
            high_freq_html = f"""
                <div class="high-freq-section">
                    <div class="high-freq-title">🔥 高频推荐（出现≥2 次）共{high_freq_count}个 
                       {f'(命中{high_freq_hits}个，命中率{high_freq_hit_rate:.1f}%)' if has_lottery and high_freq_hits > 0 else ''}</div>
                    <div class="high-freq-numbers">
"""
            for num, count in high_freq_numbers[:15]:
                is_hit = num in (set(period_data['lottery_numbers']) if period_data.get('lottery_numbers') else set())
                hit_class = "hit" if is_hit else ""
                high_freq_html += f'                        <span class="high-freq-number {hit_class}">{num:02d}<span class="hit-count-badge">{count}次</span></span>\n'
            
            high_freq_html += """
                    </div>
                </div>
"""
            html_content += high_freq_html
        
        if period_prediction:
            prediction_html = f"""
                <div class="prediction-info">
                    <div class="prediction-title">🔮 预测号码（10 个）{f'(命中{prediction_hits}个)' if has_lottery and prediction_hits > 0 else ''}</div>
                    <div class="prediction-number-list">
"""
            for pred_num in period_prediction:
                is_hit = pred_num in (set(period_data['lottery_numbers']) if period_data.get('lottery_numbers') else set())
                hit_class = "hit" if is_hit else ""
                prediction_html += f'                        <div class="prediction-number {hit_class}">{pred_num:02d}</div>\n'
            
            prediction_html += """
                    </div>
                </div>
"""
            html_content += prediction_html
        
        html_content += """
                <div class="legend">
                    <span class="legend-item"><span class="dot lottery-dot"></span>开奖</span>
                    <span class="legend-item"><span class="dot recommend-dot"></span>推荐</span>
                    <span class="legend-item"><span class="dot double-recommend-dot"></span>双荐</span>
                    <span class="legend-item"><span class="dot multi-recommend-dot"></span>多荐</span>
                    <span class="legend-item"><span class="dot hit-dot"></span>命中</span>
                </div>
            </div>
"""
    
    html_content += f"""
                </div>
            </div>
            
            <div class="warning">
                <strong>⚠️ 温馨提示：</strong><br>
                彩票有风险，购买需谨慎。<br>
                本预测仅供参考，不保证中奖。
            </div>
        </div>
        
        <div class="footer">
            <p>© 2026 快乐 8 智能预测系统 - 每天 17:30 自动发送</p>
            <p>图例说明：红色 - 开奖号码 | 紫色 - 单荐 | 粉紫 - 双荐 | 绿色 - 多荐 | 黄色 - 命中</p>
        </div>
    </div>
</body>
</html>"""
    
    return html_content


def send_email(html_content: str, subject: str):
    """发送邮件"""
    try:
        mail_data = {
            'subject': subject,
            'content_html': html_content,
            'content_text': f'快乐 8 智能预测已生成，请查看 HTML 邮件。'
        }
        
        server = zmail.server(EMAIL_CONFIG['sender'], EMAIL_CONFIG['password'])
        
        for recipient in EMAIL_CONFIG['recipients']:
            server.send_mail(recipient, mail_data)
            print(f"✓ 邮件已发送至：{recipient}")
        
        return True
    except Exception as e:
        print(f"❌ 邮件发送失败：{e}")
        return False


# ==================== 第七部分：主程序 ====================
def process_and_send_email():
    """主业务：拉数→分析→预测→写 HTML/JSON→发邮件；供定时任务与手动运行共用"""
    print("\n" + "=" * 80)
    print("快乐 8 智能预测系统 - 执行预测任务")
    print("=" * 80)

    # 1. 获取数据
    print("\n【步骤 1: 获取数据】")
    fetcher = DataFetcher()

    print("正在获取推荐数据...")
    all_periods_data = fetcher.fetch_html_recommend_data(limit=30)

    if not all_periods_data:
        print("✗ 推荐数据获取失败")
        return False

    print(f"✓ 成功获取 {len(all_periods_data)} 期推荐数据")

    print("\n正在获取开奖数据...")
    api_data = fetcher.fetch_lottery_api_data(limit=100)

    if not api_data:
        print("✗ 开奖数据获取失败")
        return False

    lottery_data = fetcher.parse_api_data(api_data)
    print(f"✓ 成功获取 {len(lottery_data['sorted_issues'])} 期开奖数据")

    # 2. 周期性分析
    print("\n【步骤 2: 分析周期性，确定最优回测期数】")
    periodicity_analyzer = PeriodicityAnalyzer(lottery_data)
    periodicity_result = periodicity_analyzer.analyze_optimal_backtest_periods()
    optimal_periods = periodicity_result['optimal_periods']

    # 3. 反推优化权重
    print("\n【步骤 3: 反推优化权重配置】")
    optimizer = BacktestOptimizer()

    backtest_periods = [p for p in all_periods_data if p.get('lottery_numbers')][:optimal_periods]

    if len(backtest_periods) < optimal_periods:
        print(f"⚠️ 已开奖期数不足{optimal_periods}期，使用{len(backtest_periods)}期回测")

    optimal_weights, backtest_result = optimizer.optimize_weights_by_reverse_engineering(
        backtest_periods, lottery_data, optimal_periods
    )

    # 4. 对最近 15 期进行预测
    print("\n【步骤 4: 生成最近 15 期预测结果】")
    all_predictions = {}

    predictor = IntelligentPredictor(optimal_weights)
    predictor.set_lottery_data(lottery_data)

    for period_data in all_periods_data[:15]:
        period_issue = period_data.get('issue', '')
        predicted = predictor.predict_for_period(period_data, count=10)
        # 对外统一用号码升序；命中计算等为集合运算，与顺序无关
        all_predictions[period_issue] = sorted(predicted) if predicted else []
        print(f"  第{period_issue}期：预测{len(all_predictions[period_issue])}个号码")

    # 5. 预测最新一期
    print("\n【步骤 5: 预测最新一期】")
    latest_period = all_periods_data[0]  # HTML 推荐列表已按新→旧排序，故 [0] 为最新一期

    predicted_numbers = predictor.predict_for_period(latest_period, count=10)  # 分数降序；先定胆码再排序
    dan_codes = predicted_numbers[:2] if len(predicted_numbers) >= 2 else list(predicted_numbers)
    predicted_numbers = sorted(predicted_numbers)  # 邮件/JSON/打印均用号码升序
    dan_codes = sorted(dan_codes)  # 仍为分数最高的两枚，仅显示顺序按号序
    all_predictions[latest_period.get('issue', '')] = predicted_numbers  # 与步骤4可能重复算一期，此处以本次为准

    print(f"\n【预测结果】")
    print(f"期号：第 {latest_period.get('issue', '待更新')} 期")
    print(f"预测号码：{predicted_numbers}")
    print(f"胆码：{dan_codes}")

    # 6. 统计
    backtest_stats = {
        'total_periods': len(backtest_periods),
        'max_hit_rate': backtest_result.get('hit_rate', 0.0),
        'high_freq_hit_rate': backtest_result.get('high_freq_hit_rate', 0.0),
        'low_freq_hit_rate': backtest_result.get('low_freq_hit_rate', 0.0)
    }

    # 7. 生成邮件
    print("\n【步骤 6: 发送邮件】")

    prediction_result = {
        'predicted_numbers': predicted_numbers,
        'dan_codes': dan_codes
    }

    html_content = generate_email_content(
        prediction_result,
        backtest_stats,
        all_periods_data[:15],
        optimal_weights,
        all_predictions,
        periodicity_result
    )

    subject = f'🎲 快乐 8 智能预测 - 第{latest_period.get("issue", "")}期 - {datetime.now().strftime("%Y-%m-%d")}'

    # 8. 保存 HTML 文件
    filename = f'kl8_intelligent_prediction_{datetime.now().strftime("%Y%m%d_%H%M%S")}.html'
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(html_content)
    print(f"✓ HTML 已保存到：{filename}")

    if send_email(html_content, subject):
        print("✓ 邮件发送成功")

        # 9. 保存结果
        result = {
            'period': latest_period.get('issue', ''),
            'generated_at': datetime.now().isoformat(),
            'optimal_weights': optimal_weights,
            'optimal_periods': optimal_periods,
            'prediction': {
                'numbers': predicted_numbers,
                'dan_codes': dan_codes
            },
            'backtest_stats': backtest_stats,
            'all_predictions': all_predictions
        }

        with open('kl8_intelligent_prediction.json', 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        print(f"✓ 预测结果已保存到 kl8_intelligent_prediction.json")

        print("\n" + "=" * 80)
        print("分析完成！祝您好运！")
        print("=" * 80)

        return True

    return False


def run_scheduler():
    """注册每天 17:30 任务并立即跑一轮，然后永不退出地 sleep+检查 schedule"""
    print("\n" + "=" * 80)
    print("快乐 8 智能预测定时任务已启动")
    print("每天 17:30 自动发送预测邮件")
    print("=" * 80)

    # 注册定时任务 - 每天 17:30 执行
    schedule.every().day.at("17:30").do(process_and_send_email)

    print("\n【定时任务已注册】")
    print("  ⏰ 执行时间：每天 17:30")
    print("  📧 发送内容：快乐 8 智能预测邮件")
    print("  💾 保存文件：HTML + JSON")
    print("\n按 Ctrl+C 退出程序\n")

    # 立即执行一次
    print("\n执行首次任务...\n")
    process_and_send_email()

    # 循环检查定时任务
    while True:  # 常驻：每分钟醒来检查是否到点执行已注册任务
        schedule.run_pending()  # 执行所有已到期的任务
        time.sleep(60)


def main():
    """主程序入口"""
    try:
        # 启动定时任务
        run_scheduler()

    except KeyboardInterrupt:
        print("\n\n程序已退出")
    except Exception as e:
        print(f"\n发生错误：{e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
if __name__ == '__main__':  # 直接运行本脚本时进入定时模式（非被 import 时）
    main()

   