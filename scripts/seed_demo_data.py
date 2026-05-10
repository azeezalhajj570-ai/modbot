"""Seed realistic demo data for all dashboard features. Idempotent - clears then recreates."""
from sqlalchemy import delete as sa_delete
from datetime import datetime, timedelta
from bot.db.session import SessionLocal
from bot.db.base import Base
from bot.db.models import *

now = datetime.utcnow()

TABLES_TO_CLEAR = [
    PaymentRecord, GroupSubscriber, SubscriptionPlan,
    GroupSubscriptionSettings, ModerationEvent, ModerationLog,
    Warning, GroupMember, GroupSetting, PluginEnabled, ModerationSetting,
    SubscriptionRequest, Lead, Conversation, Message, Contact,
]

async def seed():
    async with SessionLocal() as session:
        for model in TABLES_TO_CLEAR:
            await session.execute(sa_delete(model))
        await session.flush()

        groups = (await session.execute(
            __import__("sqlalchemy").select(Group).where(Group.is_active.is_(True))
        )).scalars().all()

        if not groups:
            print("No active groups found.")
            return

        for g in groups:
            mid = g.id
            session.add_all([
                GroupSetting(group_id=mid, key="language", value={"code": "ar"}),
                GroupSetting(group_id=mid, key="warn_limit", value={"count": 3}),
                GroupSetting(group_id=mid, key="anti_spam", value={"enabled": True, "threshold": 0.7}),
                GroupSetting(group_id=mid, key="summary_time", value={"time": "21:00", "timezone": "Asia/Riyadh"}),
                GroupSetting(group_id=mid, key="welcome_message", value={"text": "اهلاً بك في المجموعة"}),
            ])
            session.add_all([
                PluginEnabled(group_id=mid, plugin_name="anti_links", enabled=True, config={"delete_links": True}),
                PluginEnabled(group_id=mid, plugin_name="semantic_assistant", enabled=True, config={"top_k": 3}),
                PluginEnabled(group_id=mid, plugin_name="faq", enabled=True, config={"safe_mode": True}),
            ])
            session.add(ModerationSetting(
                group_id=mid, enabled=True, safe_mode=False, dry_run=False,
                default_action="delete", review_threshold=0.6,
                auto_delete_threshold=0.85, mute_threshold=0.93, ban_threshold=0.97,
                action_for_arabic_ads="delete", action_for_investment_scam="ban",
                action_for_crypto_scam="ban", action_for_phishing_link="ban",
                action_for_link_spam="delete", action_for_repeated_promo="mute",
                muted_duration_seconds=7200,
            ))
            session.add(GroupSubscriptionSettings(
                group_id=mid, enabled=True, default_currency="SAR",
                auto_approve_manual_payments=False, auto_remove_expired=True,
                expiry_action="remove", grace_period_days=7, reminder_days_before_expiry=3,
                payment_instructions="حول المبلغ عبر التحويل البنكي وأرسل الإيصال للمشرف",
            ))

        await session.flush()

        for g in groups:
            mid = g.id
            plans = []
            for name, desc, amount, days in [
                ("عضوية شهرية", "عضوية شهرية كاملة المزايا", 5000, 30),
                ("عضوية سنوية", "عضوية سنوية بخصم 20٪", 48000, 365),
            ]:
                p = SubscriptionPlan(group_id=mid, name=name, description=desc,
                                     price_amount=amount, currency="SAR", duration_days=days, enabled=True)
                session.add(p)
                plans.append(p)
            await session.flush()

            if g.id == groups[0].id and plans:
                session.add_all([
                    GroupSubscriber(group_id=mid, user_id=6816159624, username="Axyz9",
                        full_name="أحمد محمد", status="active",
                        plan_id=plans[0].id, starts_at=now - timedelta(days=15),
                        expires_at=now + timedelta(days=15)),
                    GroupSubscriber(group_id=mid, user_id=123456789, username="saud_k",
                        full_name="سعود الكناني", status="active",
                        plan_id=plans[1].id, starts_at=now - timedelta(days=60),
                        expires_at=now + timedelta(days=305)),
                    GroupSubscriber(group_id=mid, user_id=987654321, username="fahad_a",
                        full_name="فهد العنزي", status="pending",
                        plan_id=plans[0].id),
                ])
                session.add_all([
                    PaymentRecord(group_id=mid, user_id=6816159624, plan_id=plans[0].id,
                        provider="manual", amount=5000, currency="SAR", status="paid",
                        metadata_json={"note": "تحويل بنكي", "admin_verified": True}),
                    PaymentRecord(group_id=mid, user_id=123456789, plan_id=plans[1].id,
                        provider="manual", amount=48000, currency="SAR", status="paid",
                        metadata_json={"note": "تم الدفع عبر التحويل", "admin_verified": True}),
                    PaymentRecord(group_id=mid, user_id=987654321, plan_id=plans[0].id,
                        provider="manual", amount=5000, currency="SAR", status="pending",
                        metadata_json={"note": "بانتظار تأكيد الدفع"}),
                ])

        g1 = groups[0]
        session.add_all([
            ModerationEvent(group_id=g1.id, message_id=1001, user_id=555111222,
                username="spam_user1",
                text_preview="اشترك في قناتنا المميزة عبر الرابط https://spam.example.com",
                category="arabic_ads", confidence=0.94, reason="إعلان بالعربية",
                matched_signals=["arabic_ads_pattern", "external_link"],
                recommended_action="delete", action_taken="delete", dry_run=False, status="resolved",
                created_at=now - timedelta(hours=2)),
            ModerationEvent(group_id=g1.id, message_id=1002, user_id=555111222,
                username="spam_user1",
                text_preview="استثمر في العملات الرقمية واحصل على أرباح 500% مضمونة",
                category="investment_scam", confidence=0.97, reason="نصب استثماري",
                matched_signals=["get_rich_quick", "guaranteed_returns"],
                recommended_action="ban", action_taken="ban", dry_run=False, status="resolved",
                created_at=now - timedelta(hours=5)),
            ModerationEvent(group_id=g1.id, message_id=1003, user_id=777333444,
                username="link_poster",
                text_preview="https://bit.ly/suspicious-link تفضلوا هنا فيه عروض",
                category="phishing_link", confidence=0.88, reason="رابط مشبوه",
                matched_signals=["shortened_url", "suspicious_domain"],
                recommended_action="delete", action_taken="delete", dry_run=False, status="resolved",
                created_at=now - timedelta(hours=8)),
            ModerationEvent(group_id=g1.id, message_id=1004, user_id=888444555,
                username="promo_user",
                text_preview="عرض خاص اليوم فقط خصم 50% على جميع المنتجات",
                category="repeated_promo", confidence=0.76, reason="ترويج متكرر",
                matched_signals=["repeated_promotion", "discount_claim"],
                recommended_action="warn", action_taken="warn", dry_run=False, status="resolved",
                created_at=now - timedelta(days=1)),
            ModerationEvent(group_id=g1.id, message_id=1005, user_id=6816159624,
                username="Axyz9",
                text_preview="شكراً لكم على المجموعة الرائعة",
                category="safe", confidence=0.12, reason="", matched_signals=[],
                recommended_action="none", action_taken="none", dry_run=False, status="reviewed",
                created_at=now - timedelta(minutes=30)),
        ])
        session.add_all([
            ModerationLog(group_id=g1.id, action="delete_message", target_user_id=555111222,
                admin_user_id=6816159624, reason="إعلان غير مرخص",
                details={"message_id": 1001, "deleted": True},
                created_at=now - timedelta(hours=2)),
            ModerationLog(group_id=g1.id, action="ban_user", target_user_id=555111222,
                admin_user_id=6816159624, reason="نصب استثماري - تكرار المخالفات",
                details={"warnings_count": 3, "permanent": True},
                created_at=now - timedelta(hours=4)),
            ModerationLog(group_id=g1.id, action="warn_user", target_user_id=888444555,
                admin_user_id=6816159624, reason="ترويج متكرر - إنذار أول",
                details={"warning_count": 1},
                created_at=now - timedelta(days=1)),
            ModerationLog(group_id=g1.id, action="approve_join_request", target_user_id=111222333,
                admin_user_id=6816159624, reason="موافقة على طلب الانضمام",
                details={"approved": True},
                created_at=now - timedelta(hours=6)),
            ModerationLog(group_id=g1.id, action="mute_user", target_user_id=777333444,
                admin_user_id=6816159624, reason="إرسال روابط مشبوهة - كتم لمدة ساعتين",
                details={"duration_seconds": 7200},
                created_at=now - timedelta(hours=8)),
        ])
        session.add_all([
            Warning(group_id=g1.id, user_id=555111222, issued_by=6816159624,
                    reason="إعلان غير مرخص", count=3, created_at=now - timedelta(days=2)),
            Warning(group_id=g1.id, user_id=888444555, issued_by=6816159624,
                    reason="ترويج متكرر", count=1, created_at=now - timedelta(days=1)),
            Warning(group_id=g1.id, user_id=777333444, issued_by=6816159624,
                    reason="رابط مشبوه", count=1, created_at=now - timedelta(hours=12)),
        ])
        session.add_all([
            GroupMember(group_id=g1.id, tg_user_id=6816159624, username="Axyz9",
                full_name="أحمد محمد", role="admin", source="direct_add"),
            GroupMember(group_id=g1.id, tg_user_id=123456789, username="saud_k",
                full_name="سعود الكناني", role="member", source="invite_link"),
            GroupMember(group_id=g1.id, tg_user_id=987654321, username="fahad_a",
                full_name="فهد العنزي", role="member", source="join_request"),
            GroupMember(group_id=g1.id, tg_user_id=555111222, username="spam_user1",
                full_name="مستخدم مزعج", role="member", source="direct_add"),
            GroupMember(group_id=g1.id, tg_user_id=888444555, username="promo_user",
                full_name="مستخدم ترويجي", role="member", source="direct_add"),
        ])
        session.add(SubscriptionRequest(
            tg_user_id=222333444, username="new_user", full_name="عمر الجديد",
            language_code="ar", message="أريد الانضمام للمجموعة", status="pending", plan="pro",
        ))

        await session.commit()
        print("Seed complete!")

if __name__ == "__main__":
    import asyncio
    asyncio.run(seed())
