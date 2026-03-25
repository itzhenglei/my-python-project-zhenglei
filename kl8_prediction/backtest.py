"""
回测优化：在若干已开奖期上，用不同权重向量跑 IntelligentPredictor，选「预测 10 码 ∩ 实际」命中率最高的一组。

步骤：
1. 先从 HTML 侧各期统计「高频推荐」（在 5 源出现≥2 次）相对只出现 1 次的命中差异（打印报告用）；
2. _test_weight_configs 枚举多组权重，在 optimal_periods 长度内反向时间遍历回测，取最优 weights。

注意：回测用的 all_periods_data 通常为「已开奖」子序列，与主流程里传入的 backtest_periods 一致。
"""
from collections import Counter
from typing import Dict, List, Tuple

from kl8_prediction.config import BASE_DIMENSIONS
from kl8_prediction.predictor import IntelligentPredictor


class BacktestOptimizer:
    """在候选权重表上 grid search，返回最优权重及命中率等指标。"""
    
    def __init__(self):
        self.base_weights = BASE_DIMENSIONS.copy()
    
    def optimize_weights_by_reverse_engineering(self, all_periods_data: List[Dict], 
                                                   lottery_data: Dict, 
                                                   optimal_periods: int) -> Tuple[Dict, Dict]:
        """
        反推优化入口。

        返回:
            (optimal_weights, meta) — meta 含 hit_rate、high_freq_hit_rate、low_freq_hit_rate，
            供邮件「回测统计」区块与 JSON 使用。
        """
        print("\n" + "=" * 80)
        print("【开始反推优化权重配置】")
        print("=" * 80)
        
        feature_data = []
        
        for period_data in all_periods_data:
            if not period_data.get('lottery_numbers'):
                continue
            
            actual = set(period_data['lottery_numbers'])
            
            recommend_pool = set()
            recommend_pool.update(period_data.get('kaiji', []))
            recommend_pool.update(period_data.get('shiji', []))
            recommend_pool.update(period_data.get('jin', []))
            recommend_pool.update(period_data.get('guanzhu', []))
            recommend_pool.update(period_data.get('duiying', []))
            
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
            
            for num in recommend_pool:
                is_hit = num in actual
                recommend_count = recommend_counter[num]
                
                feature_data.append({
                    'is_hit': is_hit,
                    'num': num,
                    'recommend_count': recommend_count
                })
        
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
        
        best_config = self._test_weight_configs(all_periods_data, lottery_data, optimal_periods)
        
        return best_config['weights'], {
            'hit_rate': best_config['hit_rate'],
            'high_freq_hit_rate': high_freq_rate,
            'low_freq_hit_rate': low_freq_rate
        }
    
    def _test_weight_configs(self, all_periods_data: List[Dict], lottery_data: Dict, 
                            optimal_periods: int) -> Dict:
        """
        构造多组 {name, weights}，对每组用同一 lottery_data 建 Predictor，
        在 all_periods_data 前 optimal_periods 条（时间反转后）逐期 predict 10 个，累计命中个数/预测个数。
        """
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
            
            # 从较旧到较新遍历时用 reversed，与单文件版一致
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
