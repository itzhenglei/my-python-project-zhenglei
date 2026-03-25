"""
周期性分析：在多种「连续期数」下做滑动窗口，衡量相邻期重号数的波动，选出最稳的 backtest 窗口长度。

直觉：波动越小（标准差相对均值越小），用该长度做回测时权重优化更可靠。
"""
from typing import Dict


class PeriodicityAnalyzer:
    """基于历史开奖序列，估计「用多少期参与回测」更合适。"""
    
    def __init__(self, lottery_data: Dict):
        # lottery_data 须为 parse_api_data 的结果结构
        self.lottery_data = lottery_data
        self.sorted_issues = lottery_data['sorted_issues'] if lottery_data else []  # 时间升序期号
    
    def analyze_optimal_backtest_periods(self) -> Dict:
        """
        对 test_ranges 中每个窗口长度，在多段历史上滑动，计算稳定性指标，取最优。

        返回:
            optimal_periods: 整数，推荐回测期数；
            all_results: 各候选长度的 {avg_hit_rate, std_dev, stability}，便于调试打印。
        """
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
        
        # stability 越大：窗口内相邻期「重号个数」波动越小；results 为空时此处会异常（与旧版一致）
        best_period = max(results.items(), key=lambda x: x[1]['stability'])
        
        print(f"\n各期数范围稳定性分析:")
        for period, stats in sorted(results.items()):
            stability_flag = "✓" if period == best_period[0] else " "
            print(f"  {stability_flag} {period:2d} 期：平均命中={stats['avg_hit_rate']:.2f}, 标准差={stats['std_dev']:.2f}, 稳定性={stats['stability']*100:.1f}%")
        
        print(f"\n✓ 推荐最优回测期数：{best_period[0]}期 (稳定性：{best_period[1]['stability']*100:.1f}%)")
        
        return {
            'optimal_periods': best_period[0],
            'all_results': results
        }
