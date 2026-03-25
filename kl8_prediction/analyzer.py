"""
多维度分析引擎：针对快乐 8 单码 1–80，结合历史开奖做冷热、遗漏、形态等加权打分。

流程概览：
1. _precompute_statistics：全历史 + 近 10 期计数、当前/平均/最大遗漏；
2. _discover_patterns：近 10 期热区/热尾/热头/012 路倾向、斜连候选；
3. analyze_number：按 config.BASE_DIMENSIONS（或回测得到的最优权重）累加各子项得分。

注意：本模块不依赖邮件或调度，只消费 lottery_data（parse_api_data 产物）。
"""
from collections import Counter
from typing import Dict, List, Set


class MultiDimensionAnalyzer:
    """为每个号码生成多维统计，并输出 analyze_number 综合分（越大越倾向选出）。"""
    
    def __init__(self, lottery_data: Dict, dimension_weights: Dict):
        self.lottery_data = lottery_data
        self.weights = dimension_weights  # 与 BASE_DIMENSIONS 键一致；回测可能替换为最优权重
        self.sorted_issues = lottery_data['sorted_issues'] if lottery_data else []
        self.number_stats = {}  # num -> total_count, current_absence, average_absence, max_absence, recent_10_count
        self.pattern_cache = {}  # 由 _discover_patterns 填充：热区、热尾、斜连集合等
        
        if lottery_data:
            self._precompute_statistics()
            self._discover_patterns()
    
    def _precompute_statistics(self):
        """遍历 sorted_issues 时间序，为 1..80 建 number_stats（冷热与遗漏基准）。"""
        if not self.lottery_data:
            return
        
        total_periods = len(self.sorted_issues)
        
        occurrence_count = [0] * 80  # 下标 j 对应号码 j+1 的全历史出现次数
        current_absence = [0] * 80   # 距「最新一期」最近一次开出间隔了多少期（未开出则很大）
        absence_history = [[] for _ in range(80)]  # 每次开出之间的间隔序列，用于均值/最大遗漏
        
        # 先扫一遍所有期，统计每个号累计出现次数
        for draw in self.lottery_data['historical_draws'].values():
            for num in draw['numbers']:
                if 1 <= num <= 80:
                    occurrence_count[num - 1] += 1
        
        # 当前遗漏：从最后一期往前找该号上次出现位置
        for j in range(80):
            num = j + 1
            current_absence[j] = total_periods  # 从未开出则保持为总期数（表示极大遗漏）
            
            for idx in range(total_periods - 1, -1, -1):
                issue = self.sorted_issues[idx]
                numbers = self.lottery_data['historical_draws'][issue]['numbers']
                if num in numbers:
                    current_absence[j] = (total_periods - 1) - idx
                    break
        
        average_absence = []
        max_absence = []
        
        # 历史遗漏序列：按时间顺序记录相邻两次开出之间的间隔
        for j in range(80):
            num = j + 1
            last_idx = None
            
            for idx in range(total_periods):
                issue = self.sorted_issues[idx]
                numbers = self.lottery_data['historical_draws'][issue]['numbers']
                if num in numbers:
                    if last_idx is not None:
                        gap = idx - last_idx - 1  # 两次开出之间的期数间隔
                        absence_history[j].append(gap)
                    last_idx = idx
            
            # 若最后一期之后到序列末尾仍有「当前这段未闭合遗漏」，补进 history
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
        
        # 近 10 期（时间轴末尾）每个号出现次数，驱动「热号」项
        recent_10_issues = self.sorted_issues[-10:]
        recent_counts = Counter()
        for issue in recent_10_issues:
            draw = self.lottery_data['historical_draws'][issue]
            for num in draw['numbers']:
                recent_counts[num] += 1
        
        for num in range(1, 81):
            self.number_stats[num]['recent_10_count'] = recent_counts.get(num, 0)
    
    def _discover_patterns(self):
        """仅看近 10 期的形态特征，写入 pattern_cache，供 analyze_number 查表。"""
        self.pattern_cache = {
            'hot_zones': self._find_hot_zones(),
            'hot_tails': self._find_hot_tails(),
            'hot_heads': self._find_hot_heads(),
            'modulo_trend': self._find_modulo_trend(),
            'diagonal_sequences': self._find_diagonal_sequences()
        }
    
    def _find_hot_zones(self) -> List[int]:
        """四小区（每区 20 个号）在近 10 期合计出号最多的一区，返回 [1–4]。"""
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
        """个位数 0–9 出现频次最高的前 3 个尾。"""
        tail_counts = Counter()
        
        recent_issues = self.sorted_issues[-10:]
        for issue in recent_issues:
            draw = self.lottery_data['historical_draws'][issue]
            for num in draw['numbers']:
                tail = num % 10
                tail_counts[tail] += 1
        
        return [tail for tail, count in tail_counts.most_common(3)]
    
    def _find_hot_heads(self) -> List[int]:
        """两位号码的「十位」0–7（80 为 8）中出现最多的前 2 个头。"""
        head_counts = Counter()
        
        recent_issues = self.sorted_issues[-10:]
        for issue in recent_issues:
            draw = self.lottery_data['historical_draws'][issue]
            for num in draw['numbers']:
                head = num // 10
                head_counts[head] += 1
        
        return [head for head, count in head_counts.most_common(2)]
    
    def _find_modulo_trend(self) -> int:
        """012 路（num % 3）在近 10 期累计出号最多的那一路 0/1/2。"""
        modulo_counts = {0: 0, 1: 0, 2: 0}
        
        recent_issues = self.sorted_issues[-10:]
        for issue in recent_issues:
            draw = self.lottery_data['historical_draws'][issue]
            for num in draw['numbers']:
                mod = num % 3
                modulo_counts[mod] += 1
        
        return max(modulo_counts.items(), key=lambda x: x[1])[0]
    
    def _find_diagonal_sequences(self) -> Set[int]:
        """
        连续三期是否形成 +1 或 -1 的斜跳：若 t、t+1、t+2 期存在 n、n+1、n+2（或反向），
        则把可能命中的端点号记入集合，用于斜连加分。
        """
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
        """
        取时间轴上倒数第 n 期的开奖号码列表（n=1 为最近一期）。
        用于重号、连号等与「上期」相关的加分。
        """
        if not self.lottery_data or n > len(self.sorted_issues):
            return []
        
        issue = self.sorted_issues[-n]
        return self.lottery_data['historical_draws'][issue]['numbers']
    
    def analyze_number(self, num: int) -> float:
        """
        对单个候选号码累加各维度加权分。权重键须与 self.weights 对齐。

        返回值：浮点分，仅用于池内排序；无统计时返回 0。
        """
        if num not in self.number_stats:
            return 0.0
        
        stats = self.number_stats[num]
        score = 0.0
        
        # 热号：近 10 期出现次数越高，加分越多（分两档阈值）
        recent_count = stats['recent_10_count']
        if recent_count >= 5:
            score += self.weights['hot_number'] * (recent_count / 10) * 1.5
        elif recent_count >= 3:
            score += self.weights['hot_number'] * (recent_count / 10)
        
        # 重号：若在上期开出过，再按近期相邻期平均重号数放大 repeat 权重
        if num in self.get_latest_numbers(1):
            repeat_prob = self._calculate_repeat_probability()
            score += self.weights['repeat'] * (repeat_prob / 2) * 5
            if recent_count >= 4:
                score *= 1.3
        
        # 遗漏：高出自身历史平均遗漏时给 omission；中等遗漏区间给固定斜率
        current_miss = stats['current_absence']
        avg_miss = stats['average_absence']

        if current_miss > avg_miss * 1.5 and avg_miss > 0:
            ratio = current_miss / avg_miss
            score += self.weights['omission'] * (ratio * 5)
        elif current_miss > 5 and current_miss <= 15:
            score += self.weights['omission'] * (current_miss / 2)

        # 冷号：极长未出时按 cold_number 加分（有上限避免暴走）
        if current_miss > 15:
            score += self.weights['cold_number'] * min(current_miss / 5, 12)
        
        # 斜连：落在 pattern_cache 的斜连候选集
        if num in self.pattern_cache.get('diagonal_sequences', set()):
            score += self.weights['diagonal'] * 2
        
        # 连号：与最近一期号码相邻或夹心
        consecutive_bonus = self._check_consecutive_pattern(num)
        score += self.weights['consecutive'] * consecutive_bonus
        
        # 和值趋势：近 10 期平均和偏低时偏好小号区，偏高时偏好大号区
        sum_trend = self._analyze_sum_trend()
        avg_sum = sum_trend.get('average', 810)
        
        if num <= 40 and avg_sum < 800:
            score += self.weights['sum_trend'] * 3
        elif num > 40 and avg_sum > 800:
            score += self.weights['sum_trend'] * 3
        
        # 奇偶：根据近 10 期平均奇数个数的偏离，偏向奇或偶
        odd_even_trend = self._analyze_odd_even_trend()
        target_odd = odd_even_trend.get('target_odd', 10)
        
        if num % 2 == 1:
            if target_odd >= 10:
                score += self.weights['odd_even'] * 3
        else:
            if target_odd <= 10:
                score += self.weights['odd_even'] * 3
        
        # 大小：>40 为大号；根据近期大号偏多/偏少微调
        big_small_trend = self._analyze_big_small_trend()
        
        if num <= 40:
            if big_small_trend == '小数多':
                score += self.weights['big_small'] * 4
        else:
            if big_small_trend == '大数多':
                score += self.weights['big_small'] * 4
        
        # 区域热点：号码所属四区是否为当前热区
        zone_num = ((num - 1) // 20) + 1
        if zone_num in self.pattern_cache.get('hot_zones', []):
            score += self.weights['zone_hot'] * 3
        
        # 尾数、头数形态
        tail = num % 10
        if tail in self.pattern_cache.get('hot_tails', []):
            score += self.weights['tail_pattern'] * 3
        
        head = num // 10
        if head in self.pattern_cache.get('hot_heads', []):
            score += self.weights['head_focus'] * 4
        
        # 012 路与当前主导路一致则加分
        mod = num % 3
        if mod == self.pattern_cache.get('modulo_trend', -1):
            score += self.weights['modulo_3'] * 3
        
        return score
    
    def _check_consecutive_pattern(self, num: int) -> float:
        """与最近一期号码比：单边邻号 +1，双边夹心再 +1.5，封顶 2.0。"""
        bonus = 0.0
        
        latest_nums = set(self.get_latest_numbers(1))
        
        if (num - 1) in latest_nums or (num + 1) in latest_nums:
            bonus += 1.0
        
        if (num - 1) in latest_nums and (num + 1) in latest_nums:
            bonus += 1.5
        
        return min(bonus, 2.0)
    
    def _calculate_repeat_probability(self) -> float:
        """
        粗估「相邻期重号个数」的近期均值，给 repeat 维度当尺度（默认回退 5）。
        取最近至多 10 对相邻期，对每对算 |上期∩当期|，再平均。
        """
        if len(self.sorted_issues) < 2:
            return 5.0
        
        repeat_counts = []
        for i in range(1, min(10, len(self.sorted_issues))):
            prev_nums = set(self.get_latest_numbers(i + 1))
            curr_nums = set(self.get_latest_numbers(i))
            repeat_counts.append(len(prev_nums & curr_nums))
        
        return sum(repeat_counts) / len(repeat_counts) if repeat_counts else 5.0
    
    def _analyze_sum_trend(self) -> Dict:
        """近 10 期每期 20 码和值：返回均值与首尾粗趋势 up/down。"""
        recent_sums = []
        for issue in self.sorted_issues[-10:]:
            draw = self.lottery_data['historical_draws'][issue]
            recent_sums.append(draw['sum'])
        
        return {
            'average': sum(recent_sums) / len(recent_sums),
            'trend': 'up' if recent_sums[-1] > recent_sums[0] else 'down'
        }
    
    def _analyze_odd_even_trend(self) -> Dict:
        """近 10 期每期奇数个数的均值，并拍一个 target_odd 供打分用。"""
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
        """近 10 期每期大号（>40）个数均值，返回中文描述标签。"""
        big_counts = []
        for issue in self.sorted_issues[-10:]:
            draw = self.lottery_data['historical_draws'][issue]
            big_count = sum(1 for n in draw['numbers'] if n > 40)
            big_counts.append(big_count)
        
        avg_big = sum(big_counts) / len(big_counts)
        
        return '大数多' if avg_big > 10 else '小数多' if avg_big < 10 else '平衡'
