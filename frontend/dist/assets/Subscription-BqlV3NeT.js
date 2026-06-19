import{u as P,r as p,a as m,j as e}from"./index-BqS_xRrQ.js";const z=[{id:"free",name:"Starter",priceUSD:0,priceAnnualUSD:0,tagline:"15-day trial with live market data",cta:"Current plan",highlight:!1,features:[{label:"Live NSE option chain (demo)",value:!0},{label:"AI agent chat",value:!0},{label:"Saved strategies",value:"10 max"},{label:"Backtest runs",value:"50 max"},{label:"Payoff + Greeks charts",value:!0},{label:"Live broker connection",value:!1},{label:"Paper trading",value:!1},{label:"IV smile + skew",value:!1},{label:"RL signals",value:!1},{label:"Webhook alerts",value:!1}]},{id:"pro",name:"Pro",priceUSD:20,priceAnnualUSD:192,tagline:"Full live trading — unlimited everything",cta:"Upgrade to Pro",highlight:!0,features:[{label:"Live NSE option chain",value:!0},{label:"AI agent chat",value:!0},{label:"Saved strategies",value:"Unlimited"},{label:"Backtest runs",value:"Unlimited"},{label:"Payoff + Greeks charts",value:!0},{label:"Live broker connection",value:!0},{label:"Paper trading",value:!0},{label:"IV smile + skew",value:!0},{label:"RL signals",value:!0},{label:"Webhook alerts (Telegram/Discord)",value:!0}]},{id:"algo",name:"Algo",priceUSD:99,priceAnnualUSD:948,tagline:"For systematic traders & desks",cta:"Upgrade to Algo",highlight:!1,features:[{label:"Everything in Pro",value:!0},{label:"Multi-portfolio + kill switch",value:!0},{label:"Scalping scanner",value:!0},{label:"REST + WebSocket API",value:!0},{label:"Custom risk policies",value:!0},{label:"Multiple broker accounts",value:!0},{label:"Backtesting (with real premiums)",value:!0},{label:"White-glove onboarding",value:!0},{label:"Priority 24/7 support",value:!0},{label:"SLA guarantee",value:!0}]}];let f=!1;function R(){return new Promise((i,n)=>{if(f||window.Razorpay){f=!0,i();return}const o=document.createElement("script");o.src="https://checkout.razorpay.com/v1/checkout.js",o.onload=()=>{f=!0,i()},o.onerror=()=>n(new Error("Razorpay SDK failed to load")),document.body.appendChild(o)})}function I(){var w;const{user:i,tier:n,isAuthenticated:o,openGate:A,trialDaysLeft:h,usage:x}=P(),[u,v]=p.useState("month"),[y,c]=p.useState(!1),[l,C]=p.useState(null),[g,j]=p.useState(null),d=(a,t)=>{j({type:a,msg:t}),setTimeout(()=>j(null),4e3)},b=p.useCallback(async()=>{if(o)try{const{data:a}=await m.get("/api/billing/status");C(a)}catch{}},[o]);p.useEffect(()=>{b()},[b]);async function k(a){var t,r,N,S;if(a.id!==n){if(!o){A({mode:"login",message:"Sign in to upgrade your plan.",onSuccess:()=>k(a)});return}if(a.id==="free"){c(!0);try{await m.post("/api/user/tier",{tier:"free"}),d("ok","Switched to Starter."),await b()}catch(s){d("err",((r=(t=s==null?void 0:s.response)==null?void 0:t.data)==null?void 0:r.detail)||"Could not switch plan.")}c(!1);return}c(!0);try{await R();const{data:s}=await m.post("/api/billing/create-subscription",{tier:a.id,cycle:u});new window.Razorpay({key:s.razorpay_key,subscription_id:s.subscription_id,name:"Reyu.ai",description:`${a.name} Plan — ${u==="month"?"Monthly":"Annual"}`,image:"/reyu-icon.png",handler:async()=>{d("ok",`${a.name} plan activated! Welcome to the next level.`),setTimeout(b,2e3),c(!1)},prefill:{name:(i==null?void 0:i.display_name)||"",email:(i==null?void 0:i.email)||""},theme:{color:"#10b981"},modal:{ondismiss:()=>c(!1)},notes:{tier:a.id,cycle:u}}).open()}catch(s){d("err",((S=(N=s==null?void 0:s.response)==null?void 0:N.data)==null?void 0:S.detail)||(s==null?void 0:s.message)||"Checkout failed."),c(!1)}}}async function D(){var a,t;if(confirm("Cancel subscription? You keep access until the end of your billing period.")){c(!0);try{await m.post("/api/billing/cancel"),d("ok","Subscription cancelled. Access continues until period end."),await b()}catch(r){d("err",((t=(a=r==null?void 0:r.response)==null?void 0:a.data)==null?void 0:t.detail)||"Failed to cancel.")}c(!1)}}const U=a=>u==="month"?a.priceUSD:Math.round(a.priceAnnualUSD/12),$=(l==null?void 0:l.subscription_status)==="active";return e.jsxs("div",{className:"sub-page",children:[g&&e.jsxs("div",{className:`sub-toast ${g.type==="ok"?"sub-toast-ok":"sub-toast-err"}`,children:[g.type==="ok"?"✓":"⚠"," ",g.msg]}),e.jsxs("div",{className:"sub-header",children:[e.jsx("h1",{className:"sub-title",children:"Choose your edge"}),e.jsx("p",{className:"sub-subtitle",children:"From learning options to running a systematic algo book — Reyu.ai scales with you."}),e.jsxs("div",{className:"sub-cycle-toggle",children:[e.jsx("button",{className:`sub-cycle-btn ${u==="month"?"sub-cycle-active":""}`,onClick:()=>v("month"),children:"Monthly"}),e.jsxs("button",{className:`sub-cycle-btn ${u==="year"?"sub-cycle-active":""}`,onClick:()=>v("year"),children:["Annual",e.jsx("span",{className:"sub-save-badge",children:"Save ~20%"})]})]})]}),o&&h!==null&&e.jsxs("div",{className:"sub-trial-banner",children:[e.jsx("span",{className:"sub-trial-icon",children:"⏳"}),e.jsxs("div",{children:[e.jsxs("strong",{children:[h," day",h!==1?"s":""," left on your free trial"]}),e.jsx("span",{className:"sub-trial-sub",children:" — upgrade before it ends to keep your data."})]})]}),o&&n==="free"&&e.jsxs("div",{className:"sub-usage-block",children:[e.jsxs("div",{className:"sub-usage-row",children:[e.jsx("span",{children:"Saved strategies"}),e.jsxs("span",{className:"sub-usage-count",children:[x.strategies," / 10"]})]}),e.jsx("div",{className:"sub-usage-bar",children:e.jsx("div",{className:"sub-usage-fill",style:{width:`${Math.min(100,x.strategies/10*100)}%`}})}),e.jsxs("div",{className:"sub-usage-row",style:{marginTop:8},children:[e.jsx("span",{children:"Backtest runs"}),e.jsxs("span",{className:"sub-usage-count",children:[x.backtests," / 50"]})]}),e.jsx("div",{className:"sub-usage-bar",children:e.jsx("div",{className:"sub-usage-fill",style:{width:`${Math.min(100,x.backtests/50*100)}%`}})})]}),$&&n!=="free"&&e.jsxs("div",{className:"sub-active-banner",children:[e.jsxs("div",{className:"sub-active-left",children:[e.jsx("span",{className:"sub-active-dot"}),e.jsxs("div",{children:[e.jsxs("strong",{children:[((w=z.find(a=>a.id===n))==null?void 0:w.name)??n," plan active"]}),(l==null?void 0:l.subscription_ends_at)&&e.jsxs("div",{className:"sub-active-sub",children:["Renews ",new Date(l.subscription_ends_at).toLocaleDateString("en-IN",{year:"numeric",month:"short",day:"numeric"}),l.pending_plan?` · Changing to ${l.pending_plan} at period end`:""]})]})]}),e.jsx("button",{className:"sub-cancel-btn",onClick:D,disabled:y,children:"Cancel"})]}),e.jsx("div",{className:"sub-plans",children:z.map(a=>{const t=a.id===n;return e.jsxs("div",{className:`sub-card ${a.highlight?"sub-card-highlight":""} ${t?"sub-card-current":""}`,children:[a.highlight&&e.jsx("div",{className:"sub-popular-badge",children:"Most popular"}),e.jsxs("div",{className:"sub-card-header",children:[e.jsx("div",{className:"sub-plan-name",children:a.name}),e.jsxs("div",{className:"sub-price-row",children:[e.jsx("span",{className:"sub-price",children:a.priceUSD===0?"Free":`$${U(a)}`}),a.priceUSD>0&&e.jsx("span",{className:"sub-price-unit",children:"/mo"})]}),u==="year"&&a.priceAnnualUSD>0&&e.jsxs("div",{className:"sub-billed-note",children:["billed $",a.priceAnnualUSD,"/year"]}),e.jsx("div",{className:"sub-tagline",children:a.tagline})]}),e.jsx("button",{className:`sub-cta-btn ${a.highlight?"sub-cta-primary":"sub-cta-ghost"}`,disabled:t||y,onClick:()=>k(a),children:t?"✓ Current plan":a.cta}),e.jsx("ul",{className:"sub-features",children:a.features.map(r=>e.jsxs("li",{className:`sub-feature ${r.value?"":"sub-feature-off"}`,children:[e.jsx("span",{className:"sub-feature-icon",children:r.value?"✓":"–"}),e.jsxs("span",{children:[r.label,typeof r.value=="string"&&e.jsxs("span",{className:"sub-feature-val",children:[" (",r.value,")"]})]})]},r.label))})]},a.id)})}),e.jsxs("div",{className:"sub-trust",children:[e.jsxs("div",{className:"sub-trust-items",children:[e.jsx("span",{children:"🔒 Razorpay secured"}),e.jsx("span",{children:"↩ Cancel anytime"}),e.jsx("span",{children:"🇮🇳 UPI mandate supported"}),e.jsx("span",{children:"💳 All major cards"})]}),e.jsx("p",{className:"sub-trust-note",children:"Payments processed via Razorpay. No questions asked cancellation policy. INR billing available — price shown in USD for reference."})]}),e.jsx("style",{children:`
        .sub-page {
          max-width: 1060px;
          margin: 0 auto;
          padding: 32px 20px 60px;
          position: relative;
        }
        .sub-toast {
          position: fixed;
          top: 20px;
          left: 50%;
          transform: translateX(-50%);
          z-index: 9999;
          padding: 10px 20px;
          border-radius: 8px;
          font-size: 14px;
          font-weight: 500;
          animation: toastIn .2s ease;
        }
        .sub-toast-ok { background: var(--color-success); color: #fff; }
        .sub-toast-err { background: var(--color-danger); color: #fff; }
        @keyframes toastIn { from { opacity:0; transform: translateX(-50%) translateY(-8px); } to { opacity:1; transform: translateX(-50%) translateY(0); } }

        .sub-header { text-align: center; margin-bottom: 32px; }
        .sub-title { font-size: 30px; font-weight: 700; margin: 0 0 8px; }
        .sub-subtitle { color: var(--color-text-muted); font-size: 15px; margin: 0 0 20px; }

        .sub-cycle-toggle {
          display: inline-flex;
          background: var(--color-bg-card);
          border: 1px solid var(--color-border);
          border-radius: 999px;
          padding: 4px;
          gap: 2px;
        }
        .sub-cycle-btn {
          background: none;
          border: none;
          padding: 7px 18px;
          border-radius: 999px;
          font-size: 13px;
          cursor: pointer;
          color: var(--color-text-muted);
          transition: all .15s;
          display: flex;
          align-items: center;
          gap: 6px;
        }
        .sub-cycle-active {
          background: var(--color-primary);
          color: #fff;
        }
        .sub-save-badge {
          background: rgba(16,185,129,.18);
          color: var(--color-success);
          font-size: 10px;
          padding: 2px 6px;
          border-radius: 999px;
        }

        .sub-trial-banner {
          display: flex;
          align-items: center;
          gap: 10px;
          background: rgba(245,158,11,.1);
          border: 1px solid rgba(245,158,11,.3);
          border-radius: 10px;
          padding: 12px 16px;
          margin-bottom: 16px;
          font-size: 13px;
        }
        .sub-trial-icon { font-size: 18px; }
        .sub-trial-sub { color: var(--color-text-muted); }

        .sub-usage-block {
          background: var(--color-bg-card);
          border: 1px solid var(--color-border);
          border-radius: 10px;
          padding: 14px 16px;
          margin-bottom: 20px;
          font-size: 13px;
        }
        .sub-usage-row {
          display: flex;
          justify-content: space-between;
          margin-bottom: 4px;
          color: var(--color-text-muted);
        }
        .sub-usage-count { font-weight: 600; color: var(--color-text); }
        .sub-usage-bar {
          height: 5px;
          background: var(--color-border);
          border-radius: 999px;
          overflow: hidden;
        }
        .sub-usage-fill {
          height: 100%;
          background: var(--color-primary);
          border-radius: 999px;
          transition: width .4s ease;
        }

        .sub-active-banner {
          display: flex;
          align-items: center;
          justify-content: space-between;
          background: rgba(16,185,129,.08);
          border: 1px solid rgba(16,185,129,.25);
          border-radius: 10px;
          padding: 12px 16px;
          margin-bottom: 20px;
        }
        .sub-active-left { display: flex; align-items: center; gap: 10px; font-size: 14px; }
        .sub-active-dot {
          width: 8px; height: 8px;
          background: var(--color-success);
          border-radius: 50%;
          flex-shrink: 0;
          box-shadow: 0 0 0 3px rgba(16,185,129,.2);
        }
        .sub-active-sub { font-size: 12px; color: var(--color-text-muted); margin-top: 2px; }
        .sub-cancel-btn {
          font-size: 12px;
          padding: 5px 12px;
          background: none;
          border: 1px solid var(--color-border);
          border-radius: 6px;
          color: var(--color-text-muted);
          cursor: pointer;
          transition: all .15s;
        }
        .sub-cancel-btn:hover { border-color: var(--color-danger); color: var(--color-danger); }

        .sub-plans {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
          gap: 16px;
          margin-bottom: 32px;
        }

        .sub-card {
          background: var(--color-bg-card);
          border: 1px solid var(--color-border);
          border-radius: 14px;
          padding: 24px;
          position: relative;
          transition: box-shadow .2s, transform .2s;
        }
        .sub-card:hover { box-shadow: 0 4px 24px rgba(0,0,0,.12); }
        .sub-card-highlight {
          border-color: var(--color-primary);
          box-shadow: 0 0 0 1px var(--color-primary), 0 8px 32px rgba(16,185,129,.15);
          transform: translateY(-4px);
        }
        .sub-card-current { opacity: .85; }

        .sub-popular-badge {
          position: absolute;
          top: -12px;
          left: 50%;
          transform: translateX(-50%);
          background: var(--color-primary);
          color: #fff;
          font-size: 10px;
          font-weight: 600;
          letter-spacing: .8px;
          text-transform: uppercase;
          padding: 3px 12px;
          border-radius: 999px;
          white-space: nowrap;
        }

        .sub-card-header { margin-bottom: 18px; }
        .sub-plan-name {
          font-size: 12px;
          font-weight: 600;
          letter-spacing: 1px;
          text-transform: uppercase;
          color: var(--color-text-muted);
          margin-bottom: 8px;
        }
        .sub-price-row { display: flex; align-items: baseline; gap: 3px; }
        .sub-price { font-size: 36px; font-weight: 700; }
        .sub-price-unit { font-size: 14px; color: var(--color-text-muted); }
        .sub-billed-note { font-size: 11px; color: var(--color-text-muted); margin-top: 2px; }
        .sub-tagline { font-size: 13px; color: var(--color-text-muted); margin-top: 8px; line-height: 1.4; }

        .sub-cta-btn {
          width: 100%;
          padding: 11px;
          border-radius: 8px;
          font-size: 14px;
          font-weight: 600;
          cursor: pointer;
          border: none;
          margin-bottom: 18px;
          transition: all .15s;
        }
        .sub-cta-btn:disabled { opacity: .55; cursor: default; }
        .sub-cta-primary {
          background: var(--color-primary);
          color: #fff;
          box-shadow: 0 2px 12px rgba(16,185,129,.3);
        }
        .sub-cta-primary:hover:not(:disabled) { filter: brightness(1.08); }
        .sub-cta-ghost {
          background: none;
          border: 1px solid var(--color-border);
          color: var(--color-text);
        }
        .sub-cta-ghost:hover:not(:disabled) { border-color: var(--color-primary); color: var(--color-primary); }

        .sub-features { list-style: none; padding: 0; margin: 0; }
        .sub-feature {
          display: flex;
          gap: 8px;
          font-size: 13px;
          padding: 4px 0;
          color: var(--color-text);
          line-height: 1.5;
        }
        .sub-feature-off { color: var(--color-text-muted); }
        .sub-feature-icon {
          flex-shrink: 0;
          width: 16px;
          color: var(--color-success);
          font-size: 12px;
        }
        .sub-feature-off .sub-feature-icon { color: var(--color-text-muted); }
        .sub-feature-val { color: var(--color-text-muted); }

        .sub-trust {
          text-align: center;
          padding-top: 24px;
          border-top: 1px solid var(--color-border);
        }
        .sub-trust-items {
          display: flex;
          justify-content: center;
          flex-wrap: wrap;
          gap: 20px;
          font-size: 13px;
          font-weight: 500;
          margin-bottom: 10px;
        }
        .sub-trust-note { font-size: 11px; color: var(--color-text-muted); margin: 0; }

        @media (max-width: 640px) {
          .sub-title { font-size: 22px; }
          .sub-plans { grid-template-columns: 1fr; }
          .sub-card-highlight { transform: none; }
        }
      `})]})}export{I as default};
