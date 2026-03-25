"""
智能预测：在某一期的「五类推荐」并集构成的号池内，用 MultiDimensionAnalyzer 打分，取 Top N。

重要语义：
- predict_for_period 返回的列表顺序为**得分从高到低**，不是号码升序；
- 对外展示/邮件/JSON 的号序由 app.process_and_send_email 中「先胆后 sorted」统一处理（方案 A）。
"""
from typing import Dict, List

from kl8_prediction.analyzer import MultiDimensionAnalyzer


class IntelligentPredictor:
    """绑定一套维度权重 + 历史 lottery_data，对任意一期 period_data 做池内选号。"""
    
    def __init__(self, dimension_weights: Dict):
        self.weights = dimension_weights
        self.analyzer = None  # 须在 set_lottery_data 之后才有分析器实例
    
    def set_lottery_data(self, lottery_data: Dict):
        """注入 parse_api_data 的结果；会新建 MultiDimensionAnalyzer 并预计算统计。"""
        self.analyzer = MultiDimensionAnalyzer(lottery_data, self.weights)
    
    def predict_for_period(self, period_data: Dict, count=10) -> List[int]:
        """
        合并 kaiji/shiji/jin/guanzhu/duiying 为候选池，对池内每号 analyze_number，取前 count 个。

        参数 period_data: 单期推荐页解析结果（须含五类列表之一非空才有预测）。
        返回: 长度至多 count 的号码列表，**按分数降序**排列。
        """
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
        
        scores = {}
        for num in recommend_pool:
            score = self.analyzer.analyze_number(num)
            scores[num] = score
        
        sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        predicted = [item[0] for item in sorted_scores[:count]]
        
        print(f"  TOP5 高分号码:")
        for idx, (num, score) in enumerate(sorted_scores[:5], 1):
            print(f"    {idx}. 号码{num:02d}: {score:.2f}分")
        
        return predicted
