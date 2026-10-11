from ..models import ActionType, Platform
from .base import BasePlatform, click_first, fill_first, try_click


class TikTokPlatform(BasePlatform):
    platform = Platform.tiktok

    def perform(self, context, action, target_url, account, comment=None):
        page = context.new_page()
        page.goto(target_url, wait_until="domcontentloaded")
        page.wait_for_timeout(6000)

        if action == ActionType.view:
            page.wait_for_timeout(20000)
            return {"action": "view"}

        if action == ActionType.like:
            click_first(page, ['[data-e2e="like-icon"]', 'button[data-e2e="like-icon"]'])
            page.wait_for_timeout(2500)
            return {"action": "like", "url": target_url}

        if action in (ActionType.follow, ActionType.subscribe):
            click_first(page, ['[data-e2e="follow-button"]', 'button[data-e2e="follow-button"]'])
            page.wait_for_timeout(2500)
            return {"action": "follow", "url": target_url}

        raise ValueError(f"פעולה לא נתמכת ב-TikTok: {action}")

    def create_account(self, context, account, mailbox):
        from ..mail import wait_for_code
        from ..security import decrypt

        page = context.new_page()
        page.goto("https://www.tiktok.com/signup/phone-or-email/email", wait_until="domcontentloaded")
        page.wait_for_timeout(6000)

        # בחירת "Email"
        try_click(page, ['a:has-text("Email")', 'div:has-text("Email")'], timeout=5000)

        fill_first(page, ['input[name="email"]', 'input[type="email"]'], account.email)
        fill_first(page, ['input[name="password"]', 'input[type="password"]'], decrypt(account.password) or "Sb!123456")
        click_first(page, ['button[type="submit"]', 'button:has-text("Sign up")'])

        page.wait_for_timeout(6000)
        code = wait_for_code(mailbox, timeout=150)
        if code:
            try:
                fill_first(page, ['input[inputmode="numeric"]', 'input[name="code"]'], code)
                try_click(page, ['button[type="submit"]'])
                page.wait_for_timeout(4000)
            except Exception:
                pass

        account.status = "active"
        return {"created": True}
