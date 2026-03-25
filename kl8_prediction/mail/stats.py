"""
邮件展示用统计：推荐池大小、高频推荐列表、以及与开奖结果的交集统计。

与 IntelligentPredictor 无关，仅消费每期 period_data（HTML 解析结构）。
"""
from collections import Counter
from typing import Dict, List


def calculate_recommend_stats(period_data: Dict) -> Dict:
    """
    统计五类推荐合并后的去重个数，及「在多个推荐源重复出现」的号码列表。

    返回键:
        total_recommends — 去重后推荐池大小；
        high_freq_numbers — [(号码, 出现次数), ...]，次数≥2，按次数与号码排序；
        high_freq_count — high_freq_numbers 长度。
    """
    all_kaiji = period_data.get('kaiji', [])
    all_shiji = period_data.get('shiji', [])
    all_jin = period_data.get('jin', [])
    all_guanzhu = period_data.get('guanzhu', [])
    all_duiying = period_data.get('duiying', [])
    
    recommend_pool = set(all_kaiji) | set(all_shiji) | set(all_jin) | set(all_guanzhu) | set(all_duiying)
    total_recommends = len(recommend_pool)
    
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
    
    high_freq_numbers = [(num, count) for num, count in recommend_counter.items() if count >= 2]
    high_freq_numbers.sort(key=lambda x: (x[1], x[0]), reverse=True)
    high_freq_count = len(high_freq_numbers)
    
    return {
        'total_recommends': total_recommends,
        'high_freq_numbers': high_freq_numbers,
        'high_freq_count': high_freq_count
    }


def calculate_hit_statistics(period_data: Dict) -> Dict:
    """
    已开奖时：推荐与开奖 20 码的交集个数、分项命中、命中率。

    未开奖（无 lottery_numbers）时返回 None，邮件侧跳过统计块。

    命中率 hit_rate 定义：total_hits / 20 * 100（与单文件版一致）。
    """
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
