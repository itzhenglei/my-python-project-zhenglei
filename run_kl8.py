"""
分层模块运行入口（与 `kl8ycshunew.py` 行为一致）。

运行后：注册每日 17:30 定时任务、**立即执行一次** `process_and_send_email`，
随后进程常驻，每分钟检查 `schedule`（Ctrl+C 退出）。

前置：已安装 `requirements.txt`（requests、bs4、zmail、schedule 等）。

验证稳定后，可将 `kl8ycshunew.py` 改为仅 `from kl8_prediction.app import main` 的薄封装。
"""
from kl8_prediction.app import main

if __name__ == "__main__":
    main()
