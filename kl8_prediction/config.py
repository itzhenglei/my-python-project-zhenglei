"""
项目级配置：请求地址、HTTP 头、发信账号、多维度权重基线。

说明：
- 各业务模块从此处读取常量，避免魔法字符串散落。
- 邮箱 password 一般为 SMTP 授权码，请勿泄露或提交到公开仓库；需要时可改为 os.environ。
"""
import os

# --- SQLite 导出（独立工程：不写死对方仓库路径，仅通过环境变量指向同一 db 文件）---
# 建议导出前设置绝对路径，例如与读库服务使用的文件一致：
#   export KL8_SQLITE_PATH=/path/to/kl8.db
# 读库侧若已用 KL8_DATABASE，这里也可沿用同名环境变量。
SQLITE_EXPORT_PATH = os.environ.get("KL8_SQLITE_PATH") or os.environ.get("KL8_DATABASE")

# 设为 0 则关闭导出（即使已配置路径）。
KL8_SQLITE_SYNC = os.environ.get("KL8_SQLITE_SYNC", "1") != "0"

# 17500「快乐 8」推荐合一页：含多期开机/试机/金码/关注/对应等（由 fetcher 解析 HTML）
KL8_HTML_URL = 'https://www.17500.cn/tool/kl8-allm.html'

# 开奖列表 JSON；URL 无 {limit} 占位，format(limit) 实际不改变地址（与历史实现一致）
KL8_API_URL = 'https://m.17500.cn/tgj/api/kl8/getTbList?action=zhfb&page=1&limit=100&orderby=asc&start_issue=0&end_issue=0&week=all'

# 访问 HTML 页时的浏览器指纹，降低被站点拒绝的概率
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
}

# 访问 JSON 接口；Referer 模拟从官方列表页发起请求
API_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/javascript, */*; q=0.01',
    'Referer': 'https://m.17500.cn/tgj/kl8-kjfb.html'
}

# 发件人、授权码、收件人列表（sender.password 对接 QQ 邮箱等 SMTP）
EMAIL_CONFIG = {
    'sender': 'zhenglei1071925251@qq.com',
    'password': 'hcjxwdijbfxpbfha',
    'recipients': [
        'zhenglei1071925251@qq.com',
        '2863179619@qq.com'
    ]
}

# 多维度分析「基线」权重：数值越大，该维度在 analyze_number 总分里影响越大。
# BacktestOptimizer 会在此基础上生成多组候选配置并选命中率较高的一组。
BASE_DIMENSIONS = {
    'hot_number': 30,    # 近 10 期出现多的热号
    'cold_number': 12,   # 长期遗漏的冷号回补
    'omission': 18,      # 当前遗漏相对历史均值的偏离
    'diagonal': 10,      # 三连期斜连形态
    'consecutive': 8,    # 与上期相邻连号关系
    'repeat': 10,        # 与上期重号倾向
    'sum_trend': 5,      # 近 10 期和值偏高/偏低时对大小号的倾斜
    'odd_even': 4,       # 奇偶比趋势
    'big_small': 3,      # 大小号（以 40 为界）占比趋势
    'zone_hot': 8,       # 四区（1–20…61–80）冷热
    'tail_pattern': 6,   # 个位热尾
    'head_focus': 5,     # 十位「头」热号
    'modulo_3': 5,       # 012 路（模 3）偏好
}
