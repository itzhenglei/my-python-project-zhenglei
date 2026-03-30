"""
应用层：串联「抓取 → 周期分析 → 权重回测 → 多期预测 → 邮件/HTML/JSON」。

与单文件 kl8ycshunew.py 中主流程一致：
- run_scheduler：注册每日 17:30、启动后立即执行一次、随后每分钟 schedule.run_pending；
- main：捕获 Ctrl+C 与异常退出码。

落盘文件（工作目录）：
- kl8_intelligent_prediction_YYYYMMDD_hhmmss.html
- kl8_intelligent_prediction.json（仅发信成功后才写）
"""
import json
import sys
import time
from datetime import datetime

import schedule

from kl8_prediction.backtest import BacktestOptimizer
from kl8_prediction.config import KL8_SQLITE_SYNC
from kl8_prediction.fetcher import DataFetcher
from kl8_prediction.mail.content import generate_email_content
from kl8_prediction.mail.sender import send_email
from kl8_prediction.periodicity import PeriodicityAnalyzer
from kl8_prediction.predictor import IntelligentPredictor


def process_and_send_email():
    """
    单次端到端任务：拉数、分析、预测、保存 HTML、尝试发信、成功则写 JSON。

    返回:
        True  — 邮件发送成功（JSON 已写）；
        False — 任一步失败或发信失败。
    """
    print("\n" + "=" * 80)
    print("快乐 8 智能预测系统 - 执行预测任务")
    print("=" * 80)

    # --- 1. 抓取：推荐页（多期结构化） + 开奖 API（全历史用于分析器）---
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

    # --- 2. 用开奖序列估计最优回测窗口长度 optimal_periods ---
    print("\n【步骤 2: 分析周期性，确定最优回测期数】")
    periodicity_analyzer = PeriodicityAnalyzer(lottery_data)
    periodicity_result = periodicity_analyzer.analyze_optimal_backtest_periods()
    optimal_periods = periodicity_result['optimal_periods']

    # --- 3. 在已开奖且能对应 HTML 的期上回测，得到 optimal_weights ---
    print("\n【步骤 3: 反推优化权重配置】")
    optimizer = BacktestOptimizer()

    backtest_periods = [p for p in all_periods_data if p.get('lottery_numbers')][:optimal_periods]

    if len(backtest_periods) < optimal_periods:
        print(f"⚠️ 已开奖期数不足{optimal_periods}期，使用{len(backtest_periods)}期回测")

    optimal_weights, backtest_result = optimizer.optimize_weights_by_reverse_engineering(
        backtest_periods, lottery_data, optimal_periods
    )

    # --- 4. 最近 15 期（推荐列表顺序）：每期预测 10 个，对外存 sorted 列表 ---
    print("\n【步骤 4: 生成最近 15 期预测结果】")
    all_predictions = {}

    predictor = IntelligentPredictor(optimal_weights)
    predictor.set_lottery_data(lottery_data)

    for period_data in all_periods_data[:15]:
        period_issue = period_data.get('issue', '')
        predicted = predictor.predict_for_period(period_data, count=10)
        all_predictions[period_issue] = sorted(predicted) if predicted else []
        print(f"  第{period_issue}期：预测{len(all_predictions[period_issue])}个号码")

    # --- 5. 最新一期：先按分取胆码 [:2]，再全体 sorted（方案 A）；回写 all_predictions ---
    print("\n【步骤 5: 预测最新一期】")
    latest_period = all_periods_data[0]

    predicted_numbers = predictor.predict_for_period(latest_period, count=10)
    dan_codes = predicted_numbers[:2] if len(predicted_numbers) >= 2 else list(predicted_numbers)
    predicted_numbers = sorted(predicted_numbers)
    dan_codes = sorted(dan_codes)
    all_predictions[latest_period.get('issue', '')] = predicted_numbers

    print(f"\n【预测结果】")
    print(f"期号：第 {latest_period.get('issue', '待更新')} 期")
    print(f"预测号码：{predicted_numbers}")
    print(f"胆码：{dan_codes}")

    # --- 6. 组装邮件里的「回测统计」文案用字典 ---
    backtest_stats = {
        'total_periods': len(backtest_periods),
        'max_hit_rate': backtest_result.get('hit_rate', 0.0),
        'high_freq_hit_rate': backtest_result.get('high_freq_hit_rate', 0.0),
        'low_freq_hit_rate': backtest_result.get('low_freq_hit_rate', 0.0)
    }

    # --- 6b. 写入 KL8 SQLite（与 backend/app.py 读库对齐；失败不阻断发信）---
    if KL8_SQLITE_SYNC:
        try:
            from kl8_prediction.store import sync_pipeline_to_sqlite

            sync_pipeline_to_sqlite(
                all_periods_data=all_periods_data,
                all_predictions=all_predictions,
                optimal_weights=optimal_weights,
                optimal_periods=optimal_periods,
                backtest_stats=backtest_stats,
                lottery_data=lottery_data,
            )
        except Exception as db_err:
            print(f"⚠️ 写入 KL8 数据库失败：{db_err}")

    # --- 7. 渲染 HTML、写本地、发 SMTP ---
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

    filename = f'kl8_intelligent_prediction_{datetime.now().strftime("%Y%m%d_%H%M%S")}.html'
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(html_content)
    print(f"✓ HTML 已保存到：{filename}")

    if send_email(html_content, subject):
        print("✓ 邮件发送成功")

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
    """
    守护式定时器：注册每日任务、立即跑一轮、while True 每分钟检查 schedule。
    """
    print("\n" + "=" * 80)
    print("快乐 8 智能预测定时任务已启动")
    print("每天 17:30 自动发送预测邮件")
    print("=" * 80)

    schedule.every().day.at("17:30").do(process_and_send_email)

    print("\n【定时任务已注册】")
    print("  ⏰ 执行时间：每天 17:30")
    print("  📧 发送内容：快乐 8 智能预测邮件")
    print("  💾 保存文件：HTML + JSON")
    print("\n按 Ctrl+C 退出程序\n")

    print("\n执行首次任务...\n")
    process_and_send_email()

    while True:
        schedule.run_pending()  # 到期则执行已注册的 process_and_send_email
        time.sleep(60)  # 每分钟轮询一次，避免空转占 CPU


def main():
    """进程入口：默认进入定时模式。"""
    try:
        run_scheduler()

    except KeyboardInterrupt:
        print("\n\n程序已退出")
    except Exception as e:
        print(f"\n发生错误：{e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)