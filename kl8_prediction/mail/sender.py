"""
邮件发送：基于 zmail 连 QQ SMTP，向 EMAIL_CONFIG['recipients'] 逐封投递 HTML。

失败时打印异常并返回 False；成功返回 True（主流程据此决定是否写 JSON）。
"""
import zmail

from kl8_prediction.config import EMAIL_CONFIG


def send_email(html_content: str, subject: str):
    """
    使用 config.EMAIL_CONFIG 中的 sender/password 登录 SMTP，发送 multipart（HTML + 纯文本兜底）。

    参数:
        html_content — generate_email_content 的完整文档字符串；
        subject — 邮件主题（含期号、日期等）。
    """
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
