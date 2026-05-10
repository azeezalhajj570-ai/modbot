import React from 'react'
import type { SubscriptionPlan, GroupSubscriber, PaymentRecord } from '@miniapp/shared'

interface SubscriptionsPageProps {
  plans: SubscriptionPlan[]
  subscribers: GroupSubscriber[]
  payments: PaymentRecord[]
  onMarkPaid: (paymentId: number) => void
}

export const SubscriptionsPage: React.FC<SubscriptionsPageProps> = ({ 
  plans, 
  subscribers, 
  payments, 
  onMarkPaid 
}) => {
  return (
    <div className="space-y-stack-lg pb-10">
      <div className="space-y-stack-sm">
        <h2 className="font-headline-lg text-on-surface">Paid Group Access</h2>
        <p className="font-body-md text-on-surface-variant">Manage your subscription plans and paying members.</p>
      </div>

      <section className="space-y-stack-md">
        <h3 className="font-label-md text-primary tracking-widest px-1 uppercase">Subscription Plans</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {plans.map(plan => (
            <div key={plan.id} className="bg-white rounded-xl shadow-[0_4px_20px_rgba(15,23,42,0.05)] p-5 border border-slate-50 space-y-3">
              <div className="flex justify-between items-start">
                <h4 className="font-headline-md">{plan.name}</h4>
                <span className="text-primary font-bold text-lg">${(plan.price_amount / 100).toFixed(2)}</span>
              </div>
              <p className="text-body-md text-on-surface-variant line-clamp-2">{plan.description}</p>
              <div className="flex justify-between items-center pt-2">
                <span className="text-label-sm text-slate-500">{plan.duration_days} Days</span>
                <span className={`px-2 py-0.5 rounded text-[10px] uppercase font-bold ${plan.enabled ? 'bg-green-50 text-green-600' : 'bg-slate-50 text-slate-400'}`}>
                  {plan.enabled ? 'Active' : 'Disabled'}
                </span>
              </div>
            </div>
          ))}
          <button className="bg-slate-50 border-2 border-dashed border-slate-200 rounded-xl p-5 flex flex-col items-center justify-center text-slate-400 hover:bg-slate-100 transition-colors">
            <span className="material-symbols-outlined text-3xl">add_circle</span>
            <span className="font-label-md mt-1">Create New Plan</span>
          </button>
        </div>
      </section>

      <section className="space-y-stack-md">
        <h3 className="font-label-md text-primary tracking-widest px-1 uppercase">Pending Payments</h3>
        <div className="bg-white rounded-xl shadow-[0_4px_20px_rgba(15,23,42,0.05)] overflow-hidden border border-slate-50">
          {payments.filter(p => p.status === 'pending').length === 0 ? (
            <p className="p-10 text-center text-on-secondary-container">No pending payments.</p>
          ) : (
            payments.filter(p => p.status === 'pending').map(payment => (
              <div key={payment.id} className="p-4 flex items-center justify-between hover:bg-slate-50 border-b last:border-0 border-slate-50">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-full bg-amber-50 flex items-center justify-center text-amber-600">
                    <span className="material-symbols-outlined">pending</span>
                  </div>
                  <div>
                    <p className="font-label-md text-on-surface">User ID: {payment.user_id}</p>
                    <p className="text-label-sm text-on-surface-variant">${(payment.amount / 100).toFixed(2)} • {payment.provider}</p>
                  </div>
                </div>
                <button 
                  onClick={() => onMarkPaid(payment.id)}
                  className="bg-primary text-white px-4 py-1.5 rounded-lg font-label-md"
                >
                  Mark Paid
                </button>
              </div>
            ))
          )}
        </div>
      </section>

      <section className="space-y-stack-md">
        <h3 className="font-label-md text-primary tracking-widest px-1 uppercase">Recent Subscribers</h3>
        <div className="bg-white rounded-xl shadow-[0_4px_20px_rgba(15,23,42,0.05)] overflow-hidden border border-slate-50">
          {subscribers.length === 0 ? (
            <p className="p-10 text-center text-on-secondary-container">No subscribers yet.</p>
          ) : (
            subscribers.slice(0, 5).map(sub => (
              <div key={sub.id} className="p-4 flex items-center justify-between hover:bg-slate-50 border-b last:border-0 border-slate-50">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-full bg-blue-50 flex items-center justify-center text-blue-600">
                    <span className="material-symbols-outlined">person</span>
                  </div>
                  <div>
                    <p className="font-label-md text-on-surface">{sub.username || sub.full_name || sub.user_id}</p>
                    <p className="text-label-sm text-on-surface-variant">Status: {sub.status}</p>
                  </div>
                </div>
                <div className="text-left">
                  <p className="font-label-sm text-on-surface-variant">Expires</p>
                  <p className="font-label-md">{sub.expires_at ? new Date(sub.expires_at).toLocaleDateString() : 'N/A'}</p>
                </div>
              </div>
            ))
          )}
        </div>
      </section>
    </div>
  )
}
