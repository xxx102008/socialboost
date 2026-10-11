from ..models import ActionType, Platform
from .base import BasePlatform, click_first, fill_first, try_click


class InstagramPlatform(BasePlatform):
    platform = Platform.instagram

    def perform(self, context, action, target_url, account, comment=None):
        page = context.new_page()
        page.goto(target_url, wait_until="domcontentloaded")
        page.wait_for_timeout(5000)

        if action == ActionType.view:
            page.wait_for_timeout(15000)
            return {"action": "view"}

        if action == ActionType.like:
            click_first(page, ['svg[aria-label="Like"]', 'button[aria-label="Like"]'])
            page.wait_for_timeout(2500)
            return {"action": "like", "url": target_url}

        if action in (ActionType.follow, ActionType.subscribe):
            click_first(page, ['button:has-text("Follow")', 'div[role="button"]:has-text("Follow")'])
            page.wait_for_timeout(2500)
            return {"action": "follow", "url": target_url}

        raise ValueError(f"פעולה לא נתמכת באינסטגרם: {action}")

    def create_account(self, context, account, mailbox):
        from ..mail import wait_for_code

        page = context.new_page()
        page.goto("https://www.instagram.com/accounts/emailsignup/", wait_until="domcontentloaded")
        page.wait_for_timeout(5000)

        fill_first(page, ['input[name="email"]'], account.email)
        fill_first(page, ['input[name="fullName"]'], "Social Boost")
        fill_first(page, ['input[name="username"]'], account.email.split("@")[0])
        from ..security import decrypt

        fill_first(page, ['input[name="password"]'], decrypt(account.password) or "Sb!123456")
        click_first(page, ['button[type="submit"]'])

        page.wait_for_timeout(6000)
        # בקשת קוד אימות
        code = wait_for_code(mailbox, timeout=150)
        if code:
            try:
                fill_first(page, ['input[name="email_confirmation_code"]', 'input[inputmode="numeric"]'], code)
                try_click(page, ['button:has-text("Next")', 'button:has-text("Confirm")'])
                page.wait_for_timeout(4000)
            except Exception:
                pass

        account.status = "active"
        return {"created": True}
