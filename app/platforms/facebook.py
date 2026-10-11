from ..models import ActionType, Platform
from .base import BasePlatform, click_first


class FacebookPlatform(BasePlatform):
    platform = Platform.facebook

    def perform(self, context, action, target_url, account, comment=None):
        page = context.new_page()
        page.goto(target_url, wait_until="domcontentloaded")
        page.wait_for_timeout(5000)

        if action == ActionType.view:
            page.wait_for_timeout(10000)
            return {"action": "view"}

        if action in (ActionType.like, ActionType.follow, ActionType.subscribe):
            click_first(page, [
                'div[role="button"]:has-text("Like")',
                'div[role="button"]:has-text("Follow")',
                'button:has-text("Like")',
            ])
            page.wait_for_timeout(2500)
            return {"action": action.value, "url": target_url}

        raise ValueError(f"פעולה לא נתמכת בפייסבוק: {action}")
