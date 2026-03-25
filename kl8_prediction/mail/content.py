"""
邮件正文 HTML 生成。

约束：大段 HTML/CSS 放在 f-string 内时，**字符串里不要写 Python 风格的 `#` 注释**（会破坏语法或进入邮件）。

流程：首段 f-string → 循环拼 10 个球 → 第二段 f-string → 15 期循环拼卡片 → 末段 f-string 收尾。
"""
from datetime import datetime
from typing import Dict, List

from kl8_prediction.mail.grid import generate_grid_html, generate_period_grid
from kl8_prediction.mail.stats import calculate_hit_statistics, calculate_recommend_stats


def generate_email_content(prediction_result: Dict, backtest_stats: Dict, 
                          all_periods_data: List[Dict], optimal_weights: Dict,
                          all_predictions: Dict[str, List[int]],
                          periodicity_info: Dict) -> str:
    """
    拼装完整 HTML。optimal_weights 保留参数以兼容调用方，当前模板未大段展示权重细节。

    prediction_result / backtest_stats / all_predictions / periodicity_info 含义同 app.process_and_send_email 传入值。
    """
    # 首段 f-string：到「预测号码」div 开口为止；10 个球在下方 Python for 中追加
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
    # 注意：prediction_result 里号码已在 app 层按方案 A 处理，此处顺序为升序；dan_codes 为其中分数最高的两枚（显示排序）
    predicted_numbers = prediction_result.get('predicted_numbers', [])
    dan_codes = prediction_result.get('dan_codes', [])
    
    for num in predicted_numbers:
        is_dan = "dan" if num in dan_codes else ""
        html_content += f'                    <div class="number-ball {is_dan}">{num:02d}</div>\n'
    
    # 第二段 f-string：胆码说明文案、回测数字摘要、「最近 15 期」外层 div 开头
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
    
    # 每期一张卡片：宫格 +（已开奖则）命中统计 + 高频推荐块 +（有预测则）10 码对比 + 图例
    for period_idx, period_data in enumerate(all_periods_data[:15]):
        recommend_stats = calculate_recommend_stats(period_data)
        stats = calculate_hit_statistics(period_data)
        
        has_lottery = len(period_data.get('lottery_numbers', [])) > 0
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
        
        prediction_hits = 0
        if period_prediction and period_data.get('lottery_numbers'):
            actual = set(period_data['lottery_numbers'])
            prediction_hits = len(set(period_prediction) & actual)
        
        status_text = "待开奖" if not has_lottery else f"已开奖"
        
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
        
        # 已开奖才展示「推荐/命中」分项；CSS 类 good/excellent 用于阈值着色
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
            # 高频块：嵌套 f-string 内仍是 HTML，不要写 #；命中角标用 hit 类
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
            # 与 stats 类似：字符串内嵌 f 表达式生成标题，勿在 HTML 行内加 # 注释
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
    
    return html_content  # 整页字符串，供写文件与 zmail 使用
